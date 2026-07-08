from conquisterco.enrich import enrich_deposits
from conquisterco.ingest import add_deposit

from .conftest import dep, mkuser


def test_dedup_stesso_pin_stesso_minuto(conn):
    u = mkuser(conn, "A")
    id1 = dep(conn, u, 1012, "2026-02-01 10:00:00")
    # stesso utente, stesso pin, stesso minuto → scartato
    id2 = dep(conn, u, 1012, "2026-02-01 10:00:30")
    assert id1 is not None
    assert id2 is None
    n = conn.execute("SELECT COUNT(*) FROM deposits").fetchone()[0]
    assert n == 1


def test_minuto_diverso_non_dedup(conn):
    u = mkuser(conn, "A")
    assert dep(conn, u, 1012, "2026-02-01 10:00:00") is not None
    assert dep(conn, u, 1012, "2026-02-01 10:01:00") is not None
    assert conn.execute("SELECT COUNT(*) FROM deposits").fetchone()[0] == 2


def test_source_non_valida(conn):
    u = mkuser(conn, "A")
    try:
        add_deposit(conn, user_id=u, ts="2026-02-01 10:00:00",
                    lat=41.9, lon=12.5, source="carta_igienica")
        assert False, "doveva sollevare ValueError"
    except ValueError:
        pass


def test_enrich_assegna_comune_e_quota(conn, geo):
    u = mkuser(conn, "A")
    dep(conn, u, 1050, "2026-02-01 10:00:00")  # Breuil-Cervinia, 2050 m
    enrich_deposits(conn, geo)
    r = conn.execute("SELECT territory_osm_id, altitude, alt_source FROM deposits").fetchone()
    assert r["territory_osm_id"] == 1050
    assert r["altitude"] == 2050
    assert r["alt_source"] == "dem"


def test_enrich_idempotente(conn, geo):
    u = mkuser(conn, "A")
    dep(conn, u, 1012, "2026-02-01 10:00:00")
    assert enrich_deposits(conn, geo) == 1
    assert enrich_deposits(conn, geo) == 0  # già arricchito, niente da fare
