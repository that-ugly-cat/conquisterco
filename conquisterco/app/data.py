"""Query di lettura per la dashboard (ritornano dict serializzabili)."""

from __future__ import annotations

import sqlite3

from ..leaderboards import main_leaderboard, records


def _names(conn):
    return {r["id"]: r for r in conn.execute("SELECT * FROM users")}


def territories_geo(conn: sqlite3.Connection) -> list[dict]:
    """Comuni toccati, con centroide (media dei depositi), owner e stato.
    Il centroide evita di dover storare la geometria: buono per i marker."""
    centroids = {
        r["t"]: (r["clat"], r["clon"], r["n"])
        for r in conn.execute(
            """SELECT territory_osm_id AS t, AVG(lat) AS clat, AVG(lon) AS clon, COUNT(*) AS n
               FROM deposits WHERE territory_osm_id IS NOT NULL
               GROUP BY territory_osm_id"""
        )
    }
    users = _names(conn)
    out = []
    for r in conn.execute(
        """SELECT o.territory_osm_id AS t, o.owner_user_id AS uid, o.is_contested AS c,
                  o.top_count AS tc, t.name AS name, t.country AS country,
                  t.region AS region, t.area_km2 AS area
           FROM territory_ownership o JOIN territories t ON t.osm_id=o.territory_osm_id"""
    ):
        cen = centroids.get(r["t"])
        if not cen:
            continue
        owner = users.get(r["uid"]) if r["uid"] else None
        out.append({
            "osm_id": r["t"], "name": r["name"], "country": r["country"],
            "region": r["region"], "area_km2": r["area"],
            "lat": round(cen[0], 5), "lon": round(cen[1], 5), "deposits": cen[2],
            "top_count": r["tc"], "is_contested": bool(r["c"]),
            "owner_id": r["uid"],
            "owner_name": owner["display_name"] if owner else None,
            "owner_color": owner["color"] if owner else None,
        })
    return out


def dumps_geo(conn: sqlite3.Connection) -> list[dict]:
    """Singoli depositi (GATED: solo utenti loggati)."""
    users = _names(conn)
    out = []
    for r in conn.execute(
        """SELECT id, user_id, ts, lat, lon, altitude, photo_ref, territory_osm_id
           FROM deposits ORDER BY ts"""
    ):
        u = users.get(r["user_id"])
        out.append({
            "id": r["id"], "user_name": u["display_name"] if u else "?",
            "color": u["color"] if u else "#888",
            "ts": r["ts"], "lat": r["lat"], "lon": r["lon"],
            "altitude": r["altitude"],
            "has_photo": r["photo_ref"] is not None,  # False → placeholder coniglio
        })
    return out


def leaderboard(conn: sqlite3.Connection) -> dict:
    return {"main": main_leaderboard(conn), "records": records(conn)}


def feed(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    names = {r["id"]: r["display_name"] for r in conn.execute("SELECT id, display_name FROM users")}
    out = []
    for f in conn.execute(
        """SELECT f.ts, f.prev_owner_user_id AS p, f.new_owner_user_id AS nw, t.name AS tn
           FROM flips f JOIN territories t ON t.osm_id=f.territory_osm_id
           ORDER BY f.ts DESC, f.id DESC LIMIT ?""", (limit,)
    ):
        nw = names.get(f["nw"]) if f["nw"] else None
        p = names.get(f["p"]) if f["p"] else None
        if nw is None:
            text = f"{f['tn']} è diventato conteso"
            kind = "contested"
        elif p is None:
            text = f"{nw} ha conquistato {f['tn']}"
            kind = "conquer"
        else:
            text = f"{nw} ha strappato {f['tn']} a {p}"
            kind = "steal"
        out.append({"ts": f["ts"], "text": text, "kind": kind})
    return out


def territory_detail(conn: sqlite3.Connection, osm_id: int) -> dict:
    names = {r["id"]: r["display_name"] for r in conn.execute("SELECT id, display_name FROM users")}
    t = conn.execute("SELECT * FROM territories WHERE osm_id=?", (osm_id,)).fetchone()
    standings = [
        {"user": names.get(r["user_id"], "?"), "count": r["deposit_count"]}
        for r in conn.execute(
            "SELECT user_id, deposit_count FROM standings WHERE territory_osm_id=? ORDER BY deposit_count DESC",
            (osm_id,),
        )
    ]
    history = [
        {"ts": r["ts"],
         "prev": names.get(r["prev_owner_user_id"]) if r["prev_owner_user_id"] else None,
         "new": names.get(r["new_owner_user_id"]) if r["new_owner_user_id"] else None}
        for r in conn.execute(
            "SELECT * FROM flips WHERE territory_osm_id=? ORDER BY ts, id", (osm_id,)
        )
    ]
    return {
        "name": t["name"] if t else str(osm_id),
        "country": t["country"] if t else None,
        "area_km2": t["area_km2"] if t else None,
        "standings": standings, "history": history,
    }


def profile(conn: sqlite3.Connection, user_id: int) -> dict | None:
    u = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if u is None:
        return None
    owned = conn.execute(
        """SELECT t.name AS name, t.country AS country, t.area_km2 AS area
           FROM territory_ownership o JOIN territories t ON t.osm_id=o.territory_osm_id
           WHERE o.owner_user_id=? ORDER BY t.name""", (user_id,)
    ).fetchall()
    badges = conn.execute(
        """SELECT a.name AS name, a.icon_ref AS icon, COUNT(*) AS c
           FROM awards w JOIN achievements a ON a.id=w.achievement_id
           WHERE w.user_id=? GROUP BY a.id ORDER BY a.name""", (user_id,)
    ).fetchall()
    return {
        "id": u["id"], "name": u["display_name"], "color": u["color"],
        "comuni": len(owned),
        "km2": round(sum(o["area"] or 0 for o in owned), 1),
        "territories": [{"name": o["name"], "country": o["country"]} for o in owned],
        "badges": [{"name": b["name"], "icon": b["icon"], "count": b["c"]} for b in badges],
    }
