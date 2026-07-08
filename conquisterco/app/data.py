"""Query di lettura per la dashboard (ritornano dict serializzabili)."""

from __future__ import annotations

import json
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


def areas(conn: sqlite3.Connection, level: str) -> list[dict]:
    """Aree con geometria per un livello del LOD: 'comune' (da territories +
    territory_ownership) o 'province'/'region'/'country' (da admin_units +
    aggregate_ownership). Ritorna Feature-like con geometria GeoJSON."""
    users = _names(conn)
    if level == "comune":
        rows = conn.execute(
            """SELECT t.osm_id, t.name, t.centroid_lat clat, t.centroid_lon clon,
                      t.geometry_geojson geo, o.owner_user_id uid, o.is_contested c,
                      o.top_count cnt
               FROM territories t
               LEFT JOIN territory_ownership o ON o.territory_osm_id = t.osm_id
               WHERE t.geometry_geojson IS NOT NULL"""
        )
    else:
        rows = conn.execute(
            """SELECT a.osm_id, a.name, a.centroid_lat clat, a.centroid_lon clon,
                      a.geometry_geojson geo, g.owner_user_id uid, g.is_contested c,
                      g.comuni_owned cnt
               FROM admin_units a
               LEFT JOIN aggregate_ownership g ON g.unit_osm_id = a.osm_id
               WHERE a.kind = ? AND a.geometry_geojson IS NOT NULL""",
            (level,),
        )
    out = []
    for r in rows:
        owner = users.get(r["uid"]) if r["uid"] else None
        out.append({
            "osm_id": r["osm_id"], "name": r["name"], "level": level,
            "centroid": [r["clat"], r["clon"]] if r["clat"] is not None else None,
            "geometry": json.loads(r["geo"]),
            "owner_id": r["uid"],
            "owner_name": owner["display_name"] if owner else None,
            "owner_color": owner["color"] if owner else None,
            "is_contested": bool(r["c"]),
            "count": r["cnt"] or 0,
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


def list_users(conn: sqlite3.Connection) -> list[dict]:
    """Anagrafica per il pannello admin: chi ha già una password impostata."""
    return [
        {"id": r["id"], "name": r["display_name"], "role": r["role"],
         "has_password": bool(r["password_hash"]),
         "deposits": r["n"]}
        for r in conn.execute(
            """SELECT u.id, u.display_name, u.role, u.password_hash,
                      (SELECT COUNT(*) FROM deposits d WHERE d.user_id=u.id) AS n
               FROM users u ORDER BY n DESC, u.display_name"""
        )
    ]


def achievements(conn: sqlite3.Connection) -> list[dict]:
    """Legenda dei badge: nome, descrizione, icona + quanti li hanno presi."""
    return [
        {"code": r["code"], "name": r["name"], "description": r["description"],
         "icon": r["icon_ref"], "type": r["type"], "holders": r["holders"]}
        for r in conn.execute(
            """SELECT a.code, a.name, a.description, a.icon_ref, a.type,
                      COUNT(DISTINCT w.user_id) AS holders
               FROM achievements a
               LEFT JOIN awards w ON w.achievement_id = a.id
               WHERE a.active = 1
               GROUP BY a.id ORDER BY a.name"""
        )
    ]


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
