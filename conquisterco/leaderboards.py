"""Leaderboard: principale (comuni + km²) e secondarie (record superlativi)."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from . import config
from .ownership import replay_flips
from .util import parse_ts


def _names(conn: sqlite3.Connection) -> dict[int, str]:
    # nome PUBBLICO (fallback allo username)
    return {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, COALESCE(public_name, display_name) AS name FROM users")}


def _decayed(points: float, decay: float, n: int) -> float:
    """Valore di n prese dello stesso badge.

    La presa n-esima vale `points·decay^(n-1)`, **ma non scende mai sotto la
    meta' dei punti base**: ripetere rende sempre qualcosa. Con decay=0.5 il
    pavimento si tocca subito e la curva e' 10, 5, 5, 5…; con un decay piu' alto
    la discesa dal pieno alla meta' e' graduale (con 0.8: 10, 8, 6.4, 5.12, 5…).
    Il `decay` governa quindi la discesa, non il valore finale.

    Niente tetto, di conseguenza: un ripetibile cresce all'infinito di meta'
    punto-badge per volta. E' il prezzo di «i badge danno sempre punti».

    Forma chiusa invece del ciclo perche' questa funzione gira dentro ogni
    istantanea di punteggio, e le istantanee sono due per settimana su
    quattrocento settimane.
    """
    if n <= 0:
        return 0.0
    if decay >= 1.0:
        return points * n            # nessun calo: lineare (es. Gnnn!)
    floor = points / 2.0
    if decay <= 0.0:
        return points + (n - 1) * floor
    # quante prese stanno ancora sopra il pavimento: decay^i >= 1/2
    import math
    k = min(n, int(math.log(0.5) / math.log(decay)) + 1)
    return points * (1.0 - decay ** k) / (1.0 - decay) + (n - k) * floor


def badge_points(conn: sqlite3.Connection, until: str | None = None) -> dict[int, float]:
    """Punti da badge per utente. **Ogni presa conta**, anche dei ripetibili, ma
    con peso calante per badge (§config, deroga per badge nel registry). I
    segreti valgono ×SECRET_MULT. `until`: solo i badge presi fino a quel ts."""
    out: dict[int, float] = defaultdict(float)
    where = "WHERE w.ts_earned <= ?" if until else ""
    args = (until,) if until else ()
    for r in conn.execute(
        f"""SELECT w.user_id AS uid, a.secret AS secret,
                   a.points AS points, a.decay AS decay, COUNT(*) AS n
            FROM awards w JOIN achievements a ON a.id = w.achievement_id
            {where}
            GROUP BY w.user_id, a.id""", args
    ):
        val = _decayed(r["points"], r["decay"], r["n"])
        out[r["uid"]] += val * (config.SCORE_SECRET_MULT if r["secret"] else 1)
    return dict(out)


def _score(comuni: int, km2: float, badge_pts: float) -> float:
    return (config.SCORE_PT_COMUNE * comuni
            + config.SCORE_PT_KM2 * km2
            + badge_pts)


def main_leaderboard(conn: sqlite3.Connection) -> list[dict]:
    """Per utente: comuni, km² e PUNTEGGIO (somma pesata, §config). Ordinata per
    punteggio, poi comuni, poi km²."""
    names = _names(conn)
    comuni: dict[int, int] = defaultdict(int)
    km2: dict[int, float] = defaultdict(float)
    for r in conn.execute(
        """SELECT o.owner_user_id AS uid, COALESCE(t.area_km2, 0) AS area
           FROM territory_ownership o
           JOIN territories t ON t.osm_id = o.territory_osm_id
           WHERE o.owner_user_id IS NOT NULL"""
    ):
        comuni[r["uid"]] += 1
        km2[r["uid"]] += r["area"]
    badges = badge_points(conn)
    depositors = {r["uid"] for r in conn.execute("SELECT DISTINCT user_id AS uid FROM deposits")}
    rows = []
    # chiunque abbia giocato compare: ha cagato almeno una volta, possiede un
    # comune, o ha un badge (i gatti col badge del Sistema inclusi).
    for u in set(comuni) | set(badges) | depositors:
        rows.append({
            "user_id": u, "name": names.get(u, str(u)),
            "comuni": comuni[u], "km2": round(km2[u], 1),
            "score": round(_score(comuni[u], km2[u], badges.get(u, 0.0))),
        })
    rows.sort(key=lambda x: (x["score"], x["comuni"], x["km2"]), reverse=True)
    return rows


def _extreme(conn: sqlite3.Connection, expr: str, order: str) -> dict | None:
    r = conn.execute(
        f"""SELECT d.user_id AS uid, {expr} AS val, t.name AS tname
            FROM deposits d LEFT JOIN territories t ON t.osm_id = d.territory_osm_id
            WHERE {expr} IS NOT NULL
            ORDER BY val {order} LIMIT 1"""
    ).fetchone()
    if r is None:
        return None
    names = _names(conn)
    return {"user_id": r["uid"], "name": names.get(r["uid"], str(r["uid"])),
            "value": r["val"], "where": r["tname"]}


def _streaks(conn: sqlite3.Connection) -> dict[int, int]:
    """Streak massima (giorni consecutivi con >=1 deposito) per utente."""
    by_user: dict[int, set] = defaultdict(set)
    for r in conn.execute("SELECT user_id, ts FROM deposits"):
        by_user[r["user_id"]].add(parse_ts(r["ts"]).date())
    out: dict[int, int] = {}
    for uid, days in by_user.items():
        best = cur = 0
        prev = None
        for day in sorted(days):
            if prev is not None and (day - prev).days == 1:
                cur += 1
            else:
                cur = 1
            best = max(best, cur)
            prev = day
        out[uid] = best
    return out


def _latifondista(conn: sqlite3.Connection) -> dict | None:
    flips = [
        {"territory": r["territory_osm_id"], "ts": r["ts"],
         "prev_owner": r["prev_owner_user_id"], "new_owner": r["new_owner_user_id"]}
        for r in conn.execute("SELECT * FROM flips ORDER BY ts, id")
    ]
    tc = {r["osm_id"]: r["country"] for r in conn.execute("SELECT osm_id, country FROM territories")}
    res = replay_flips(flips, tc)
    if not res.max_owned:
        return None
    uid = max(res.max_owned, key=res.max_owned.get)
    names = _names(conn)
    return {"user_id": uid, "name": names.get(uid, str(uid)), "value": res.max_owned[uid]}


def records(conn: sqlite3.Connection) -> dict:
    """Tutte le leaderboard secondarie in un colpo."""
    names = _names(conn)
    streaks = _streaks(conn)
    streak_holder = None
    if streaks:
        uid = max(streaks, key=streaks.get)
        streak_holder = {"user_id": uid, "name": names.get(uid, str(uid)), "value": streaks[uid]}

    # esploratore / volume / cosmopolita
    explorer = defaultdict(set)
    volume = defaultdict(int)
    nations = defaultdict(set)
    for r in conn.execute(
        """SELECT d.user_id AS uid, d.territory_osm_id AS t, t.country AS c
           FROM deposits d LEFT JOIN territories t ON t.osm_id = d.territory_osm_id"""
    ):
        volume[r["uid"]] += 1
        if r["t"] is not None:
            explorer[r["uid"]].add(r["t"])
        if r["c"]:
            nations[r["uid"]].add(r["c"])

    def _top(d, transform=len):
        if not d:
            return None
        uid = max(d, key=lambda u: transform(d[u]))
        return {"user_id": uid, "name": names.get(uid, str(uid)), "value": transform(d[uid])}

    return {
        "nord": _extreme(conn, "d.lat", "DESC"),
        "sud": _extreme(conn, "d.lat", "ASC"),
        "est": _extreme(conn, "d.lon", "DESC"),
        "ovest": _extreme(conn, "d.lon", "ASC"),
        "piu_in_alto": _extreme(conn, "d.altitude", "DESC"),
        "piu_in_basso": _extreme(conn, "d.altitude", "ASC"),
        "esploratore": _top(explorer),
        "volume": _top(volume, transform=lambda x: x),
        "cosmopolita": _top(nations),
        "streak": streak_holder,
        "latifondista": _latifondista(conn),
    }
