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
    assert len(s["activity"]) == 12          # istogramma 12 mesi
    assert s["weight_kg"] == round(2 * 128 / 1000.0, 1)  # 2 depositi × ~128 g


def test_merge_users():
    from conquisterco.ingest import add_user
    conn = fresh_db(":memory:")
    real = add_user(conn, "Hannes_S")
    prov = add_user(conn, "tg_hannes")
    conn.execute("UPDATE users SET telegram_user_id=999, provisional=1 WHERE id=?", (prov,))
    conn.commit()
    dep(conn, real, 1012, "2024-01-01 10:00:00")   # Roma
    dep(conn, prov, 1003, "2024-01-02 10:00:00")   # Milano
    run_all(conn, FakeGeocoder())

    assert data.merge_users(conn, prov, real) is True
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id=?", (prov,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM deposits WHERE user_id=?", (real,)).fetchone()[0] == 2
    assert conn.execute("SELECT telegram_user_id FROM users WHERE id=?", (real,)).fetchone()[0] == 999
    # ora Hannes_S possiede sia Roma sia Milano
    assert conn.execute("SELECT COUNT(*) FROM territory_ownership WHERE owner_user_id=?",
                        (real,)).fetchone()[0] == 2


def test_delete_solo_selfie(tmp_path):
    from conquisterco.db import fresh_db
    from conquisterco.ingest import add_deposit, add_user
    conn = fresh_db(":memory:")
    a = add_user(conn, "A")
    add_deposit(conn, user_id=a, ts="2024-01-01 10:00:00", lat=1, lon=1,
                source="telegram", photo_ref="whatsapp/x/a.jpg")
    add_deposit(conn, user_id=a, ts="2024-01-02 10:00:00", lat=2, lon=2, source="telegram")
    (tmp_path / "whatsapp/x").mkdir(parents=True)
    (tmp_path / "whatsapp/x/a.jpg").write_bytes(b"x")

    assert data.delete_user_selfies(conn, a, tmp_path) == 1
    assert conn.execute("SELECT COUNT(*) FROM deposits WHERE photo_ref IS NOT NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM deposits WHERE user_id=?", (a,)).fetchone()[0] == 2  # depositi restano
    assert not (tmp_path / "whatsapp/x/a.jpg").exists()


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
