from conquisterco.app import data
from conquisterco.db import fresh_db
from conquisterco.geo import FakeGeocoder
from conquisterco.pipeline import run_all

from .conftest import dep, mkuser


def _world():
    conn = fresh_db(":memory:")
    a = mkuser(conn, "A")
    b = mkuser(conn, "B")
    dep(conn, a, 1012, "2024-01-01 10:00:00")  # Roma
    dep(conn, a, 1003, "2024-01-02 10:00:00")  # Milano (A owner)
    dep(conn, b, 1019, "2024-01-03 10:00:00")  # Palermo (B owner)
    run_all(conn, FakeGeocoder())
    return conn, a, b


def test_my_stats():
    conn, a, b = _world()
    s = data.my_stats(conn, a)
    assert s["name"] == "A"
    assert s["deposits"] == 2
    assert s["comuni_visitati"] == 2
    assert s["rank"] in (1, 2)
    assert isinstance(s["badges"], list)


def test_delete_user_cancella_tutto(tmp_path):
    conn, a, b = _world()
    data.delete_user(conn, a, tmp_path)
    # utente e depositi spariti
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id=?", (a,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM deposits WHERE user_id=?", (a,)).fetchone()[0] == 0
    # B intatto
    assert conn.execute("SELECT COUNT(*) FROM deposits WHERE user_id=?", (b,)).fetchone()[0] == 1
    # stato derivato rigenerato senza A (Milano torna libero)
    assert conn.execute("SELECT COUNT(*) FROM territory_ownership WHERE owner_user_id=?",
                        (a,)).fetchone()[0] == 0
    # B possiede ancora Palermo
    assert conn.execute("SELECT COUNT(*) FROM territory_ownership WHERE owner_user_id=?",
                        (b,)).fetchone()[0] == 1
