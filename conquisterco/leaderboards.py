"""Leaderboard: principale (comuni + km²) e secondarie (record superlativi)."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from .ownership import replay_flips
from .util import haversine_km, parse_ts


def _names(conn: sqlite3.Connection) -> dict[int, str]:
    # nome PUBBLICO (fallback allo username)
    return {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, COALESCE(public_name, display_name) AS name FROM users")}


def main_leaderboard(conn: sqlite3.Connection) -> list[dict]:
    """Per utente: comuni posseduti e km² controllati. Ordinata per comuni, poi km²."""
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
    rows = [
        {"user_id": u, "name": names.get(u, str(u)), "comuni": comuni[u], "km2": round(km2[u], 1)}
        for u in comuni
    ]
    rows.sort(key=lambda x: (x["comuni"], x["km2"]), reverse=True)
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


def _trasferta(conn: sqlite3.Connection) -> dict | None:
    """Deposito più lontano dalla home base del suo autore."""
    homes = {r["id"]: (r["home_lat"], r["home_lon"])
             for r in conn.execute("SELECT id, home_lat, home_lon FROM users")}
    best = None
    for r in conn.execute("SELECT user_id, lat, lon FROM deposits"):
        h = homes.get(r["user_id"])
        if not h or h[0] is None:
            continue
        km = haversine_km(h[0], h[1], r["lat"], r["lon"])
        if best is None or km > best[1]:
            best = (r["user_id"], km)
    if best is None:
        return None
    names = _names(conn)
    return {"user_id": best[0], "name": names.get(best[0], str(best[0])), "value": round(best[1], 1)}


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

    # esploratore / volume / passaporto
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
        "trasferta": _trasferta(conn),
        "esploratore": _top(explorer),
        "volume": _top(volume, transform=lambda x: x),
        "passaporto": _top(nations),
        "streak": streak_holder,
        "latifondista": _latifondista(conn),
    }
