"""Geo-enrich: assegna a ogni deposito il comune (osm_id) e la quota stimata.

Campi derivati: si possono azzerare e ricalcolare. Idempotente — rielabora solo
i depositi non ancora arricchiti (salvo `force=True`).
"""

from __future__ import annotations

import sqlite3

from .geo import Geocoder


def _upsert_territory(conn: sqlite3.Connection, t) -> None:
    conn.execute(
        """INSERT INTO territories (osm_id, name, admin_level, country, region, area_km2)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(osm_id) DO UPDATE SET
             name=excluded.name, admin_level=excluded.admin_level,
             country=excluded.country, region=excluded.region,
             area_km2=excluded.area_km2""",
        (t.osm_id, t.name, t.admin_level, t.country, t.region, t.area_km2),
    )


def enrich_deposits(conn: sqlite3.Connection, geocoder: Geocoder,
                    *, force: bool = False) -> int:
    """Arricchisce i depositi. Ritorna quanti ne ha (ri)elaborati."""
    where = "" if force else "WHERE territory_osm_id IS NULL"
    rows = conn.execute(
        f"SELECT id, lat, lon, altitude FROM deposits {where}"
    ).fetchall()

    n = 0
    for r in rows:
        terr = geocoder.locate(r["lat"], r["lon"])
        territory_id = None
        if terr is not None:
            _upsert_territory(conn, terr)
            territory_id = terr.osm_id

        # quota: solo se assente (il pin di norma non la porta)
        altitude = r["altitude"]
        alt_source = None
        if altitude is None:
            est = geocoder.elevation(r["lat"], r["lon"])
            if est is not None:
                altitude, alt_source = est, "dem"

        conn.execute(
            "UPDATE deposits SET territory_osm_id=?, altitude=?, alt_source=COALESCE(?, alt_source) WHERE id=?",
            (territory_id, altitude, alt_source, r["id"]),
        )
        n += 1

    conn.commit()
    return n
