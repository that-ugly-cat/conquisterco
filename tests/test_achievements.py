from conquisterco.achievements import evaluate
from conquisterco.geo import FakeGeocoder
from conquisterco.pipeline import run_all

from .conftest import dep, mkuser


def _codes(conn, geo):
    """Esegue la pipeline e ritorna dict user_id -> set(codici award)."""
    run_all(conn, geo)
    out: dict[int, set] = {}
    for a in evaluate(conn):
        out.setdefault(a.user_id, set()).add(a.code)
    return out


def test_colonizzatore_primo_del_gruppo(conn, geo):
    a = mkuser(conn, "A")
    b = mkuser(conn, "B")
    dep(conn, a, 1012, "2026-04-01 10:00:00")   # A primo a Roma
    dep(conn, b, 1012, "2026-04-02 10:00:00")   # B secondo → niente
    codes = _codes(conn, geo)
    assert "colonizzatore" in codes[a]
    assert "colonizzatore" not in codes.get(b, set())


def test_conquistador_e_regicidio(conn, geo):
    a = mkuser(conn, "A")
    b = mkuser(conn, "B")
    # A diventa leader possedendo due comuni
    dep(conn, a, 1001, "2026-04-01 09:00:00")
    dep(conn, a, 1012, "2026-04-01 10:00:00")
    # B ruba Roma ad A (leader) → Conquistador + Regicidio
    dep(conn, b, 1012, "2026-04-02 10:00:00")   # 1-1 conteso
    dep(conn, b, 1012, "2026-04-03 10:00:00")   # 2-1 furto
    codes = _codes(conn, geo)
    assert "conquistador" in codes[b]
    assert "regicidio" in codes[b]


def test_guardiano(conn, geo):
    a = mkuser(conn, "A")
    b = mkuser(conn, "B")
    dep(conn, a, 1012, "2026-04-01 10:00:00")   # A 1
    dep(conn, a, 1012, "2026-04-01 11:00:00")   # A 2 (owner con margine)
    dep(conn, b, 1012, "2026-04-02 10:00:00")   # B 1
    dep(conn, b, 1012, "2026-04-02 11:00:00")   # 2-2 → conteso (A perde)
    dep(conn, a, 1012, "2026-04-03 10:00:00")   # A 3 → riprende → Guardiano
    codes = _codes(conn, geo)
    assert "guardiano" in codes[a]


def test_blitz_tre_comuni_in_24h(conn, geo):
    a = mkuser(conn, "A")
    dep(conn, a, 1001, "2026-04-01 09:00:00")
    dep(conn, a, 1002, "2026-04-01 12:00:00")
    dep(conn, a, 1003, "2026-04-01 15:00:00")
    codes = _codes(conn, geo)
    assert "blitz" in codes[a]


def test_blitz_non_scatta_oltre_finestra(conn, geo):
    a = mkuser(conn, "A")
    dep(conn, a, 1001, "2026-04-01 09:00:00")
    dep(conn, a, 1002, "2026-04-02 12:00:00")
    dep(conn, a, 1003, "2026-04-04 15:00:00")   # spalmati su >24h
    codes = _codes(conn, geo)
    assert "blitz" not in codes.get(a, set())


def test_passaporto_cinque_nazioni(conn, geo):
    a = mkuser(conn, "A")
    for i, osm in enumerate([1012, 2001, 3001, 4001, 4002]):  # IT, FR, PL, ES, DE
        dep(conn, a, osm, f"2026-04-0{i+1} 10:00:00")
    codes = _codes(conn, geo)
    assert "passaporto" in codes[a]


def test_waterloo_tre_comuni_francesi(conn, geo):
    a = mkuser(conn, "A")
    for i, osm in enumerate([2001, 2002, 2003]):
        dep(conn, a, osm, f"2026-04-0{i+1} 10:00:00")
    codes = _codes(conn, geo)
    assert "waterloo" in codes[a]


def test_spartizione_polonia(conn, geo):
    a = mkuser(conn, "A")
    for i, osm in enumerate([3001, 3002, 3003]):
        dep(conn, a, osm, f"2026-04-0{i+1} 10:00:00")
    codes = _codes(conn, geo)
    assert "spartizione_polonia" in codes[a]


def test_scalatore_e_batisfera(conn, geo):
    a = mkuser(conn, "A")
    dep(conn, a, 1050, "2026-04-01 10:00:00")   # 2050 m
    dep(conn, a, 4004, "2026-04-02 10:00:00")   # Rotterdam -2 m
    codes = _codes(conn, geo)
    assert "scalatore" in codes[a]
    assert "batisfera" in codes[a]
