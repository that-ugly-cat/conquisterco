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
    assert len(s["cal"]["cols"]) == 53       # calendario: 53 settimane
    assert all(len(c) == 7 for c in s["cal"]["cols"])
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


def test_calendario_attivita():
    """La griglia stile GitHub: quadratini giusti nei giorni giusti.

    La data di oggi si passa da fuori, altrimenti il test dice cose diverse a
    seconda del giorno in cui gira — difetto gia' pagato con le settimane.
    """
    from datetime import date

    conn = fresh_db(":memory:")
    a = mkuser(conn, "A")
    dep(conn, a, 1012, "2026-09-16 08:00:00")   # mercoledi'
    dep(conn, a, 1003, "2026-09-16 19:00:00")   # stesso giorno: due
    dep(conn, a, 1019, "2026-09-20 09:00:00")   # domenica
    run_all(conn, FakeGeocoder())

    cal = data.activity_calendar(conn, a, today=date(2026, 9, 24))  # un giovedi'
    celle = {c["d"]: c for col in cal["cols"] for c in col if c}

    assert celle["2026-09-16"]["n"] == 2 and celle["2026-09-16"]["lvl"] == 2
    assert celle["2026-09-20"]["n"] == 1 and celle["2026-09-20"]["lvl"] == 1
    assert celle["2026-09-17"]["n"] == 0 and celle["2026-09-17"]["lvl"] == 0
    assert cal["totale"] == 3 and cal["giorni"] == 2

    # l'ultima colonna e' la settimana in corso, e il futuro resta vuoto
    ultima = cal["cols"][-1]
    assert ultima[0]["d"] == "2026-09-21"       # lunedi' in alto
    assert ultima[3]["d"] == "2026-09-24"       # oggi
    assert ultima[4] is None and ultima[6] is None

    # il primo giorno e' il lunedi' di 53 settimane prima: un anno pieno
    assert cal["dal"] == "2025-09-22" and cal["al"] == "2026-09-24"


def test_le_soglie_del_calendario_sono_fisse():
    """Quattro livelli, non relativi al massimo del giocatore: due calendari
    affiancati devono dire la stessa cosa."""
    assert [data._livello_cal(n) for n in (0, 1, 2, 3, 4, 12)] == [0, 1, 2, 3, 4, 4]
