import json

from conquisterco.db import fresh_db
from conquisterco.elevation import enrich_altitude, fetch_elevations
from conquisterco.ingest import add_deposit

from .conftest import mkuser


def _fake_fetch(url):
    # conta quante coordinate ci sono e ritorna quote finte allineate
    lats = url.split("latitude=")[1].split("&")[0].split(",")
    return json.dumps({"elevation": [100.0 + i for i in range(len(lats))]}).encode()


def test_fetch_elevations_batch():
    pts = [(45.0, 11.0)] * 250  # > batch da 100 → 3 richieste
    els = fetch_elevations(pts, fetch=_fake_fetch, batch=100)
    assert len(els) == 250
    assert els[0] == 100.0


def test_enrich_altitude_riempie_e_marca_dem():
    conn = fresh_db(":memory:")
    a = mkuser(conn, "A")
    add_deposit(conn, user_id=a, ts="2024-01-01 10:00:00", lat=46.0, lon=11.0, source="telegram")
    add_deposit(conn, user_id=a, ts="2024-01-02 10:00:00", lat=46.1, lon=11.1, source="telegram")

    stats = enrich_altitude(conn, fetcher=lambda pts: [1200.0, -5.0])
    assert stats == {"pending": 2, "updated": 2}
    rows = conn.execute("SELECT altitude, alt_source FROM deposits ORDER BY id").fetchall()
    assert rows[0]["altitude"] == 1200.0 and rows[0]["alt_source"] == "dem"
    assert rows[1]["altitude"] == -5.0

    # idempotente: già valorizzate → niente da fare
    assert enrich_altitude(conn, fetcher=lambda pts: [])["pending"] == 0
