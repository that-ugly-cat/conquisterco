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


def _record(conn: sqlite3.Connection, start_ts: str, end_ts: str, now: str) -> dict:
    g = gains(conn, start_ts, end_ts)
    win, contested = _winner(g)
    cur = conn.execute(
        """INSERT INTO weeks (start_ts, end_ts, closed_at, winner_user_id, contested)
           VALUES (?,?,?,?,?)""",
        (start_ts, end_ts, now, win, int(contested)))
    return {"id": cur.lastrowid, "start_ts": start_ts, "end_ts": end_ts,
            "winner_user_id": win, "contested": contested, "gains": g}


def close_due_weeks(conn: sqlite3.Connection, *, closing_now: bool = False,
                    now: datetime | None = None) -> list[dict]:
    """Chiude tutte le settimane chiudibili e ritorna quelle appena chiuse, in
    ordine. Idempotente: una settimana già in tabella non si tocca.

    - le settimane **scadute** (griglia dei lunedì, ormai vecchie di oltre un
      giorno) si chiudono retroattivamente: è così che entra tutto lo storico;
    - con `closing_now` (lo passa il recap) si chiude anche la settimana in
      corso, che finisce nell'istante del recap. Sotto MIN_WEEK_DAYS non si
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
        closed.append(_record(conn, start, end, now_s))
        start = end
    # 2. la settimana in corso, se è il recap a chiedercelo
    if closing_now and (now - parse_ts(start)) >= timedelta(days=config.MIN_WEEK_DAYS):
        closed.append(_record(conn, start, now_s, now_s))
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

def weeks_leaderboard(conn: sqlite3.Connection) -> list[dict]:
    """Settimane vinte su settimane giocate. «Giocata» = settimana chiusa in cui
    hai depositato almeno una volta: chi non c'era non viene punito per le
    settimane in cui non c'era, ma chi c'era e ha perso sì.

    Ordinata per rateo, poi per settimane vinte: con pochi dati il rateo è
    rumoroso, quindi la colonna `played` va mostrata sempre accanto."""
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
    for u in set(played) | set(won):
        p, v = played.get(u, 0), won.get(u, 0)
        rows.append({
            "user_id": u, "name": names.get(u, str(u)),
            "won": v, "played": p,
            "ratio": round(v / p, 3) if p else 0.0,
        })
    rows.sort(key=lambda x: (x["ratio"], x["won"], x["played"]), reverse=True)
    return rows


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
