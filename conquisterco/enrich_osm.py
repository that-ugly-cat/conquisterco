"""Geo-enrich reale: coordinate → comuni + catena amministrativa, via OSMResolver.

Passa dalla `geocode_cache`: ogni coordinata si risolve una volta sola (egress
verso OSM una tantum). Commit per punto → il backfill è ripartibile: se si
interrompe, riprende dai depositi ancora senza comune saltando quelli in cache.

Le geometrie vivono una volta per unità (territories per i comuni, admin_units
per provincia/regione/stato); la cache tiene solo la mappatura coordinata→comune.
"""

from __future__ import annotations

import json
import sqlite3

from .geo_osm import OSMResolver, Resolution, Unit
from .geoarea import geojson_area_km2


def _upsert_admin_unit(conn: sqlite3.Connection, u: Unit, parent_osm_id: int | None) -> None:
    conn.execute(
        """INSERT INTO admin_units (osm_id, kind, name, parent_osm_id, centroid_lat, centroid_lon, geometry_geojson)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(osm_id) DO UPDATE SET
             kind=excluded.kind, name=excluded.name,
             parent_osm_id=COALESCE(excluded.parent_osm_id, admin_units.parent_osm_id),
             centroid_lat=excluded.centroid_lat, centroid_lon=excluded.centroid_lon,
             geometry_geojson=COALESCE(excluded.geometry_geojson, admin_units.geometry_geojson)""",
        (u.osm_id, u.kind, u.name, parent_osm_id, u.lat, u.lon, u.geometry),
    )


def _persist(conn: sqlite3.Connection, res: Resolution) -> None:
    # aggregati prima (per i FK logici) — province→regione→stato
    if res.country:
        _upsert_admin_unit(conn, res.country, None)
    if res.region:
        _upsert_admin_unit(conn, res.region, res.country.osm_id if res.country else None)
    if res.province:
        _upsert_admin_unit(conn, res.province, res.region.osm_id if res.region else None)

    c = res.comune
    if c is None:
        return
    area = geojson_area_km2(json.loads(c.geometry)) if c.geometry else None
    conn.execute(
        """INSERT INTO territories
             (osm_id, name, admin_level, country, region, province,
              province_osm_id, region_osm_id, country_osm_id,
              area_km2, centroid_lat, centroid_lon, geometry_geojson)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(osm_id) DO UPDATE SET
             name=excluded.name, country=excluded.country, region=excluded.region,
             province=excluded.province, province_osm_id=excluded.province_osm_id,
             region_osm_id=excluded.region_osm_id, country_osm_id=excluded.country_osm_id,
             area_km2=excluded.area_km2,
             centroid_lat=excluded.centroid_lat, centroid_lon=excluded.centroid_lon,
             geometry_geojson=COALESCE(excluded.geometry_geojson, territories.geometry_geojson)""",
        (c.osm_id, c.name, 8, c.country, c.region, c.province,
         res.province.osm_id if res.province else None,
         res.region.osm_id if res.region else None,
         res.country.osm_id if res.country else None,
         area, c.lat, c.lon, c.geometry),
    )


def drop_fallback_territories(conn: sqlite3.Connection) -> int:
    """Rimuove i 'comuni' che sono in realtà unità aggregate (osm_id presente in
    admin_units): sono fallback del geocoding (es. un punto in mare finito
    sull'intero Paese). I loro depositi tornano non risolti (territory=NULL), la
    cache viene azzerata per non ri-assegnarli. Ritorna quanti ne ha tolti.
    Ricordarsi di richiamare pipeline.finalize dopo."""
    bad = [r["osm_id"] for r in conn.execute(
        "SELECT osm_id FROM territories WHERE osm_id IN (SELECT osm_id FROM admin_units)")]
    if not bad:
        return 0
    ph = ",".join("?" * len(bad))
    conn.execute(f"UPDATE deposits SET territory_osm_id=NULL WHERE territory_osm_id IN ({ph})", bad)
    conn.execute(f"UPDATE geocode_cache SET comune_osm_id=NULL WHERE comune_osm_id IN ({ph})", bad)
    # svuota le derivate che referenziano i territori (finalize le ricostruisce)
    for tbl in ("flips", "aggregate_ownership", "territory_ownership", "standings"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.execute(f"DELETE FROM territories WHERE osm_id IN ({ph})", bad)
    conn.commit()
    return len(bad)


def enrich_deposits_osm(conn: sqlite3.Connection, resolver: OSMResolver,
                        *, progress=None) -> dict:
    """Arricchisce i depositi senza comune. Ritorna un riepilogo."""
    rows = conn.execute(
        "SELECT id, lat, lon FROM deposits WHERE territory_osm_id IS NULL ORDER BY id"
    ).fetchall()
    stats = {"total": len(rows), "geocoded": 0, "cache_hits": 0, "sea": 0}

    for i, r in enumerate(rows, 1):
        lat, lon = round(r["lat"], 6), round(r["lon"], 6)
        cached = conn.execute(
            "SELECT comune_osm_id FROM geocode_cache WHERE lat=? AND lon=?", (lat, lon)
        ).fetchone()

        if cached is not None:
            comune_id = cached["comune_osm_id"]
            stats["cache_hits"] += 1
        else:
            res = resolver.resolve(lat, lon)
            _persist(conn, res)
            comune_id = res.comune.osm_id if res.comune else None
            payload = {u.kind: u.osm_id for u in res.units()}
            conn.execute(
                "INSERT OR REPLACE INTO geocode_cache (lat, lon, comune_osm_id, payload_json) VALUES (?,?,?,?)",
                (lat, lon, comune_id, json.dumps(payload)),
            )
            stats["geocoded"] += 1

        if comune_id is None:
            stats["sea"] += 1
        conn.execute("UPDATE deposits SET territory_osm_id=? WHERE id=?", (comune_id, r["id"]))
        conn.commit()  # ripartibile
        if progress:
            progress(i, stats["total"])
    return stats
