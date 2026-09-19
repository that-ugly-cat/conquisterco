"""Le settimane del cacasto: chi ne guadagna di più, e chi le vince.

Il punteggio di un giocatore è una funzione dello stato (comuni, km², badge),
quindi «punti della settimana» non è un dato: è un **delta** fra due istantanee.
Qui si ricostruiscono le istantanee (l'ownership si rilegge dai flip, i badge
dagli award datati) e si differenziano.

Una settimana **la chiude il recap**: quando il bot manda il riepilogo, la
settimana finisce lì e il verdetto viene scritto in `weeks`. Da quel momento non
si ricalcola più — quello che il bot ha annunciato al gruppo resta il verdetto,
anche se lo storico viene ri-arricchito dopo. È lo stesso patto di
`manual_awards`: dato grezzo, non derivato, immune al `finalize`.

Le settimane passate senza recap (tutto lo storico importato da WhatsApp, e
un'eventuale domenica in cui il cron non è partito) si chiudono
retroattivamente sulla griglia dei lunedì, una volta sola.

Vincitore = chi guadagna **strettamente** più punti. Parità = settimana
**contesa**, non la vince nessuno: la stessa regola dei comuni (SPEC §2).
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from . import config
from .leaderboards import _score, badge_points
from .util import fmt_ts, parse_ts


# ---------------------------------------------------------------------------
# Istantanee del punteggio
# ---------------------------------------------------------------------------

def _owned_at(conn: sqlite3.Connection, until: str | None = None
              ) -> tuple[dict[int, int], dict[int, float]]:
    """Comuni e km² posseduti da ciascuno a `until` (None = adesso), ricostruiti
    dai flip: l'owner di un comune è quello dell'ultimo flip entro quel ts."""
    areas = {r["osm_id"]: (r["area_km2"] or 0.0)
             for r in conn.execute("SELECT osm_id, area_km2 FROM territories")}
    owner: dict[int, int | None] = {}
    q = "SELECT territory_osm_id AS t, new_owner_user_id AS o FROM flips"
    if until:
        q += " WHERE ts <= ?"
    q += " ORDER BY ts, id"
    for r in conn.execute(q, (until,) if until else ()):
        owner[r["t"]] = r["o"]
    comuni: dict[int, int] = defaultdict(int)
    km2: dict[int, float] = defaultdict(float)
    for t, o in owner.items():
        if o is not None:
            comuni[o] += 1
            km2[o] += areas.get(t, 0.0)
    return dict(comuni), dict(km2)


def score_snapshot(conn: sqlite3.Connection, until: str | None = None) -> dict[int, float]:
    """Punteggio di ogni giocatore com'era a `until` (None = adesso)."""
    comuni, km2 = _owned_at(conn, until)
    badges = badge_points(conn, until)
    return {u: _score(comuni.get(u, 0), km2.get(u, 0.0), badges.get(u, 0.0))
            for u in set(comuni) | set(badges)}


def gains(conn: sqlite3.Connection, start_ts: str, end_ts: str | None) -> dict[int, float]:
    """Punti guadagnati da ciascuno nell'intervallo [start_ts, end_ts). Solo i
    guadagni: chi resta fermo non compare, e un delta negativo (ti hanno rubato
    un comune) non fa punti ma non toglie la settimana a nessuno."""
    before = score_snapshot(conn, start_ts)
    after = score_snapshot(conn, end_ts)
    out = {}
    for u in set(before) | set(after):
        d = after.get(u, 0.0) - before.get(u, 0.0)
        if d > 0:
            out[u] = d
    return out


def _winner(g: dict[int, float]) -> tuple[int | None, bool]:
    """(vincitore, contesa). Massimo STRETTO, altrimenti contesa (SPEC §2).
    Nessun guadagno = nessun vincitore e nessuna contesa: settimana vuota."""
    if not g:
        return (None, False)
    top = max(g.values())
    leaders = [u for u, v in g.items() if abs(v - top) < 1e-9]
    if len(leaders) == 1:
        return (leaders[0], False)
    return (None, True)


# ---------------------------------------------------------------------------
# Chiusura delle settimane
# ---------------------------------------------------------------------------

def _monday(dt: datetime) -> datetime:
    return (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)


def _last_end(conn: sqlite3.Connection) -> str | None:
    r = conn.execute("SELECT end_ts FROM weeks ORDER BY end_ts DESC LIMIT 1").fetchone()
    return r["end_ts"] if r else None


def _first_deposit_ts(conn: sqlite3.Connection) -> str | None:
    r = conn.execute("SELECT MIN(ts) AS t FROM deposits").fetchone()
    return r["t"] if r and r["t"] else None


def _record(conn: sqlite3.Connection, start_ts: str, end_ts: str, now: str,
            *, apre_voto: bool) -> dict:
    """Scrive il verdetto di una settimana.

    `apre_voto` decide se la faccia di merda si puo' votare. Solo il recap lo
    passa vero, perche' e' il recap a mandare il link al gruppo: una settimana
    chiusa retroattivamente nasce **gia' votata e chiusa**, altrimenti il
    backfill dello storico aprirebbe in silenzio un voto su selfie di cui
    nessuno sa niente — e' successo davvero il 19 set 2026, 67 selfie in gara
    su una settimana mai annunciata."""
    g = gains(conn, start_ts, end_ts)
    win, contested = _winner(g)
    cur = conn.execute(
        """INSERT INTO weeks (start_ts, end_ts, closed_at, winner_user_id, contested,
                              face_closed_at)
           VALUES (?,?,?,?,?,?)""",
        (start_ts, end_ts, now, win, int(contested), None if apre_voto else now))
    return {"id": cur.lastrowid, "start_ts": start_ts, "end_ts": end_ts,
            "winner_user_id": win, "contested": contested, "gains": g}


def close_due_weeks(conn: sqlite3.Connection, *, closing_now: bool = False,
                    now: datetime | None = None) -> list[dict]:
    """Chiude tutte le settimane chiudibili e ritorna quelle appena chiuse, in
    ordine. Idempotente: una settimana già in tabella non si tocca.

    - le settimane **scadute** (griglia dei lunedì, ormai vecchie di oltre un
      giorno) si chiudono retroattivamente: è così che entra tutto lo storico;
    - con `closing_now` (lo passa il recap) si chiude anche la settimana in
      corso, che finisce nell'istante del recap ed e' **l'unica** ad aprire il
      voto per la faccia di merda. Sotto MIN_WEEK_DAYS non si
      chiude: due `conquisterco-recap` nello stesso giorno non devono
      fabbricare una settimana di due ore.
    """
    now = now or datetime.now()
    now_s = fmt_ts(now)
    start = _last_end(conn)
    if start is None:
        first = _first_deposit_ts(conn)
        if first is None:
            return []
        start = fmt_ts(_monday(parse_ts(first)))

    closed: list[dict] = []
    # 1. settimane passate senza recap → chiuse sulla griglia dei lunedì
    while True:
        nxt = _monday(parse_ts(start) + timedelta(days=7))
        if nxt > now - timedelta(days=1):
            break
        end = fmt_ts(nxt)
        closed.append(_record(conn, start, end, now_s, apre_voto=False))
        start = end
    # 2. la settimana in corso, se è il recap a chiedercelo
    if closing_now and (now - parse_ts(start)) >= timedelta(days=config.MIN_WEEK_DAYS):
        closed.append(_record(conn, start, now_s, now_s, apre_voto=True))
    conn.commit()
    return closed


def current_week_start(conn: sqlite3.Connection) -> str:
    """Inizio della settimana in corso: dove è finita l'ultima chiusa, oppure
    lunedì di questa settimana se non ne è mai stata chiusa nessuna. NON il
    primo deposito della storia: quello è il punto da cui parte il backfill
    (`close_due_weeks`), e confonderli farebbe della settimana in corso tutto
    lo storico del gioco."""
    return _last_end(conn) or fmt_ts(_monday(datetime.now()))


def running_gains(conn: sqlite3.Connection) -> dict[int, float]:
    """Punti guadagnati nella settimana ancora aperta."""
    return gains(conn, current_week_start(conn), None)


# ---------------------------------------------------------------------------
# Classifica per settimane vinte
# ---------------------------------------------------------------------------

def weeks_leaderboard(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    """Settimane vinte su settimane giocate. «Giocata» = settimana chiusa in cui
    hai depositato almeno una volta: chi non c'era non viene punito per le
    settimane in cui non c'era, ma chi c'era e ha perso sì.

    Per stare **in graduatoria** (`ranked`) servono due cose insieme:

    - almeno `WEEKS_MIN_PLAYED` settimane giocate — un rateo su una settimana
      sola non è un rateo, 1/1 fa 1.00 e resterebbe in testa per sempre;
    - almeno `WEEKS_ACTIVE_DUMPS` cacate nelle ultime `WEEKS_ACTIVE_WINDOW`
      settimane — la storia non basta, bisogna esserci adesso.

    La seconda condizione rende questa classifica **dipendente dall'istante in
    cui la si guarda**: è l'unica cosa qui dentro che cambia senza che cambi un
    dato, e un giocatore ne esce da solo smettendo di cagare. Da qui il
    parametro `now`, che i test fissano.

    Fuori graduatoria non vuol dire fuori dalla lista: si compare in coda con
    i numeri veri, ordinati per quanto manca a rientrarci. Ordinata per rateo,
    poi vinte, poi giocate; `played` e `recent` vanno mostrate sempre accanto
    al rateo, perché le soglie riducono il rumore ma non lo azzerano."""
    now = now or datetime.now()
    da = fmt_ts(now - timedelta(weeks=config.WEEKS_ACTIVE_WINDOW))
    recenti = {r["u"]: r["n"] for r in conn.execute(
        "SELECT user_id AS u, COUNT(*) AS n FROM deposits WHERE ts >= ? GROUP BY user_id", (da,))}
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, COALESCE(public_name, display_name) AS name FROM users")}
    weeks = conn.execute(
        "SELECT id, start_ts, end_ts, winner_user_id FROM weeks ORDER BY start_ts").fetchall()
    won: dict[int, int] = defaultdict(int)
    played: dict[int, int] = defaultdict(int)
    for w in weeks:
        for r in conn.execute(
            "SELECT DISTINCT user_id AS u FROM deposits WHERE ts >= ? AND ts < ?",
            (w["start_ts"], w["end_ts"]),
        ):
            played[r["u"]] += 1
        if w["winner_user_id"] is not None:
            won[w["winner_user_id"]] += 1
            played.setdefault(w["winner_user_id"], 0)
    rows = []
    for u in set(played) | set(won) | set(recenti):
        p, v, rec = played.get(u, 0), won.get(u, 0), recenti.get(u, 0)
        rows.append({
            "user_id": u, "name": names.get(u, str(u)),
            "won": v, "played": p, "recent": rec,
            "ratio": round(v / p, 3) if p else 0.0,
            "ranked": p >= config.WEEKS_MIN_PLAYED and rec >= config.WEEKS_ACTIVE_DUMPS,
        })
    rows.sort(key=lambda x: (x["ranked"], x["ratio"], x["won"], x["played"]), reverse=True)
    # in coda chi è fuori: prima chi è più vicino a rientrarci
    coda = [r for r in rows if not r["ranked"]]
    coda.sort(key=lambda x: (x["played"], x["recent"], x["won"]), reverse=True)
    return [r for r in rows if r["ranked"]] + coda


def week_history(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Le ultime settimane chiuse, con vincitore ed eventuale faccia di merda."""
    return [dict(r) for r in conn.execute(
        """SELECT w.id, w.start_ts, w.end_ts, w.contested,
                  COALESCE(u.public_name, u.display_name) AS winner,
                  w.face_deposit_id,
                  COALESCE(f.public_name, f.display_name) AS face
           FROM weeks w
           LEFT JOIN users u ON u.id = w.winner_user_id
           LEFT JOIN deposits d ON d.id = w.face_deposit_id
           LEFT JOIN users f ON f.id = d.user_id
           ORDER BY w.start_ts DESC LIMIT ?""", (limit,))]
