from conquisterco.enrich import enrich_deposits
from conquisterco.recompute import owner_of, recompute

from .conftest import dep, mkuser


def _prep(conn, geo):
    enrich_deposits(conn, geo)
    recompute(conn)


def _owner(conn, osm_id):
    r = conn.execute(
        "SELECT owner_user_id, is_contested, top_count FROM territory_ownership WHERE territory_osm_id=?",
        (osm_id,),
    ).fetchone()
    return r


def test_owner_of_regola():
    assert owner_of({}) == (None, 0, False)
    assert owner_of({1: 3}) == (1, 3, False)
    assert owner_of({1: 3, 2: 2}) == (1, 3, False)
    assert owner_of({1: 3, 2: 3}) == (None, 3, True)  # parità → conteso


def test_prima_mossa_e_conteso(conn, geo):
    a = mkuser(conn, "A")
    b = mkuser(conn, "B")
    dep(conn, a, 1012, "2026-03-01 10:00:00")   # A 1 → owner A
    dep(conn, b, 1012, "2026-03-02 10:00:00")   # 1-1 → conteso
    _prep(conn, geo)
    r = _owner(conn, 1012)
    assert r["owner_user_id"] is None
    assert r["is_contested"] == 1


def test_rubare_richiede_superare(conn, geo):
    a = mkuser(conn, "A")
    b = mkuser(conn, "B")
    dep(conn, a, 1012, "2026-03-01 10:00:00")   # A 1
    dep(conn, b, 1012, "2026-03-02 10:00:00")   # 1-1 conteso
    dep(conn, b, 1012, "2026-03-03 10:00:00")   # B 2 > A 1 → owner B
    _prep(conn, geo)
    r = _owner(conn, 1012)
    assert r["owner_user_id"] == b
    assert r["top_count"] == 2


def test_flip_sequenza(conn, geo):
    a = mkuser(conn, "A")
    b = mkuser(conn, "B")
    dep(conn, a, 1012, "2026-03-01 10:00:00")   # → owner A          flip None→A
    dep(conn, b, 1012, "2026-03-02 10:00:00")   # → conteso          flip A→None
    dep(conn, b, 1012, "2026-03-03 10:00:00")   # → owner B          flip None→B
    _prep(conn, geo)
    flips = conn.execute(
        "SELECT prev_owner_user_id, new_owner_user_id FROM flips ORDER BY ts, id"
    ).fetchall()
    seq = [(f["prev_owner_user_id"], f["new_owner_user_id"]) for f in flips]
    assert seq == [(None, a), (a, None), (None, b)]


def test_standings_conteggi(conn, geo):
    a = mkuser(conn, "A")
    dep(conn, a, 1012, "2026-03-01 10:00:00")
    dep(conn, a, 1012, "2026-03-01 10:05:00")
    _prep(conn, geo)
    c = conn.execute(
        "SELECT deposit_count FROM standings WHERE territory_osm_id=1012 AND user_id=?",
        (a,),
    ).fetchone()["deposit_count"]
    assert c == 2
