"""Test dei badge temporali / assiduità / selfie + occultamento dei segreti.
Usano il catalogo fittizio di base (fixture conftest)."""

from datetime import datetime, timedelta

from conquisterco.achievements import evaluate
from conquisterco.app import data
from conquisterco.pipeline import run_all

from .conftest import dep


def _codes(conn, geo):
    run_all(conn, geo)
    out: dict[int, set] = {}
    for a in evaluate(conn):
        out.setdefault(a.user_id, set()).add(a.code)
    return out


def test_turno_notte_e_alba(conn, geo):
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    dep(conn, a, 1012, "2026-05-01 03:30:00")   # notte
    dep(conn, a, 1012, "2026-05-02 06:15:00")   # alba
    c = _codes(conn, geo)[a]
    assert "turno_notte" in c
    assert "alba_regno" in c


def test_natale_e_bisesto(conn, geo):
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    dep(conn, a, 1012, "2024-02-29 10:00:00")   # anno bisestile
    dep(conn, a, 1012, "2026-12-25 10:00:00")   # Natale
    c = _codes(conn, geo)[a]
    assert "anno_bisesto" in c
    assert "natale_fecale" in c


def test_capodanno_e_ultima_chiamata(conn, geo):
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    dep(conn, a, 1012, "2025-03-01 10:00:00")   # prima del 2025
    dep(conn, a, 1012, "2025-11-30 10:00:00")   # ultima del 2025
    dep(conn, a, 1012, "2026-01-15 10:00:00")   # prima del 2026
    c = _codes(conn, geo)[a]
    assert "capodanno" in c
    assert "ultima_chiamata" in c


def test_streak_e_selfie(conn, geo):
    """50 depositi con foto in 50 giorni consecutivi → orologio(7), metronomo(30),
    pilastro(50 giorni), gallerista(50 selfie)."""
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    start = datetime(2026, 1, 1, 10, 0, 0)
    for i in range(50):
        ts = (start + timedelta(days=i)).strftime("%Y-%m-%d %H:%M:%S")
        dep(conn, a, 1012, ts, photo=True)
    c = _codes(conn, geo)[a]
    assert {"orologio", "metronomo", "pilastro", "gallerista"} <= c
    assert "archivista" not in c   # servono 100 selfie


def test_badge_holders_e_descrizione_profilo(conn, geo):
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    b = add_user(conn, "B")
    dep(conn, a, 1012, "2026-04-01 10:00:00")   # A colonizza Roma
    dep(conn, b, 1001, "2026-04-01 10:00:00")   # B colonizza Aosta
    run_all(conn, geo)

    holders = {h["name"] for h in data.badge_holders(conn, "colonizzatore")}
    assert {"A", "B"} <= holders

    # profilo: ogni badge porta code + descrizione (tradotta col dict fornito)
    prof = data.profile(conn, a, {"ach_colonizzatore_d": "testo come-si-prende"})
    byc = {x["code"]: x for x in prof["badges"]}
    assert "colonizzatore" in byc
    assert byc["colonizzatore"]["description"] == "testo come-si-prende"


def test_segreti_nascosti_dalla_legenda_ma_assegnati(conn, geo):
    """Un badge segreto scatta e finisce negli award, ma NON compare nella
    legenda pubblica del modale."""
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    # Venezia (1005) = Serenissima Deposizione (segreto)
    dep(conn, a, 1005, "2026-05-01 10:00:00")
    run_all(conn, geo)

    legend_codes = {b["code"] for b in data.achievements(conn)}
    assert "serenissima" not in legend_codes            # nascosto dalla legenda
    awarded = {r["code"] for r in conn.execute(
        "SELECT a.code FROM awards w JOIN achievements a ON a.id=w.achievement_id")}
    assert "serenissima" in awarded                     # ma assegnato davvero
