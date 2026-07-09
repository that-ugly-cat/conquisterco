"""Test dei nuovi badge (fase "espansione achievement").

Molti richiedono nazioni/luoghi assenti dal catalogo fittizio di base, quindi qui
si usa un catalogo custom (nazioni in nome NATIVO, come il geocoder reale) per
verificare anche il layer di canonicalizzazione `geonames`.
"""

from conquisterco.achievements import evaluate
from conquisterco.geo import FakeGeocoder, _Cell
from conquisterco.ingest import add_deposit, add_user
from conquisterco.pipeline import run_all

from .conftest import dep as dep_default

# --- catalogo custom: nomi nazione nativi + luoghi speciali, bbox disgiunti ---
WORLD = [
    _Cell(9101, "Roma", "Italia", "Lazio", 41.70, 12.30, 21, 1287.0, half=0.05),
    _Cell(9102, "Venezia", "Italia", "Veneto", 45.44, 12.33, 1, 415.0, half=0.05),
    _Cell(9103, "Paris", "France", "Île-de-France", 48.85, 2.35, 35, 105.0, half=0.05),
    _Cell(9104, "Avignon", "France", "Provence-Alpes-Côte d'Azur", 43.95, 4.80, 23, 64.0, half=0.05),
    _Cell(9105, "Caen", "France", "Normandie", 49.18, -0.37, 10, 25.0, half=0.05),
    _Cell(9106, "Berlin", "Deutschland", "Berlin", 52.52, 13.40, 34, 891.0, half=0.05),
    _Cell(9107, "Wien", "Österreich", "Wien", 48.20, 16.37, 151, 414.0, half=0.05),
    _Cell(9108, "Zürich", "Schweiz/Suisse/Svizzera/Svizra", "Zürich", 47.37, 8.54, 408, 87.0, half=0.05),
    _Cell(9109, "Praha 5", "Česko", None, 50.08, 14.42, 200, 496.0, half=0.05),
    _Cell(9110, "Moskva", "Россия", None, 55.75, 37.61, 156, 2561.0, half=0.05),
    _Cell(9111, "London", "United Kingdom", "England", 51.50, -0.12, 11, 1572.0, half=0.05),
    _Cell(9112, "Città del Vaticano", "Vatican City", None, 41.902, 12.453, 19, 0.44, half=0.01),
    _Cell(9113, "Uranus", "United States", "Missouri", 37.83, -91.98, 350, 5.0, half=0.05),
    _Cell(9114, "Batman", "Türkiye", None, 37.88, 41.13, 540, 15.0, half=0.05),
    _Cell(9115, "Hell", "Norge", None, 63.44, 10.90, 5, 3.0, half=0.05),
    _Cell(9116, "Toilettes", "France", "Bretagne", 47.60, -2.80, 20, 4.0, half=0.05),
    _Cell(9117, "Puno", "Perú", None, -15.75, -69.35, 3830, 460.0, half=0.05),
    _Cell(9118, "Tromsø", "Norge", None, 69.65, 18.95, 10, 2521.0, half=0.05),
    _Cell(9119, "Incrocio", "Italia", "Piemonte", 45.00, 8.00, 100, 10.0, half=0.05),
    _Cell(9120, "Rijeka", "Hrvatska", None, 45.33, 14.44, 5, 44.0, half=0.05),
]
BY_ID = {c.osm_id: c for c in WORLD}


def geo():
    return FakeGeocoder(WORLD)


def dep(conn, uid, osm_id, ts, *, photo=True, dlat=0.0, dlon=0.0):
    c = BY_ID[osm_id]
    return add_deposit(conn, user_id=uid, ts=ts, lat=c.lat + dlat, lon=c.lon + dlon,
                       source="telegram", photo_ref="x.jpg" if photo else None)


def codes(conn):
    run_all(conn, geo())
    out: dict[int, set] = {}
    for a in evaluate(conn):
        out.setdefault(a.user_id, set()).add(a.code)
    return out


# --- sequenze internazionali ------------------------------------------------

def test_anschluss_stesso_giorno(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9106, "2026-05-01 09:00:00")   # Berlin (DE)
    dep(conn, a, 9107, "2026-05-01 18:00:00")   # Wien (AT) stesso giorno
    assert "anschluss" in codes(conn)[a]


def test_anschluss_non_scatta_giorni_diversi(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9106, "2026-05-01 09:00:00")
    dep(conn, a, 9107, "2026-05-02 09:00:00")   # giorno dopo
    assert "anschluss" not in codes(conn).get(a, set())


def test_neutralita_armata_secret(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9101, "2026-05-01 09:00:00")   # Roma (IT)
    dep(conn, a, 9108, "2026-05-10 09:00:00")   # Zürich (CH) dopo
    assert "neutralita_armata" in codes(conn)[a]


def test_barbarossa_entro_5_giorni(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9106, "2026-05-01 09:00:00")   # DE
    dep(conn, a, 9110, "2026-05-04 09:00:00")   # RU entro 5g
    assert "barbarossa" in codes(conn)[a]


def test_fuck_brexit_secret(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9101, "2026-05-01 09:00:00")   # EU (IT)
    dep(conn, a, 9111, "2026-05-02 09:00:00")   # UK
    dep(conn, a, 9103, "2026-05-03 09:00:00")   # EU (FR) entro 5g
    assert "fuck_brexit" in codes(conn)[a]


def test_sudetenland_stesso_giorno(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9106, "2026-05-01 08:00:00")   # DE
    dep(conn, a, 9109, "2026-05-01 20:00:00")   # CZ stesso giorno
    assert "sudetenland" in codes(conn)[a]


# --- possesso aggregato di stati --------------------------------------------

def test_colonialista_due_stati(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9101, "2026-05-01 09:00:00")   # possiede Roma (IT)
    dep(conn, a, 9103, "2026-05-02 09:00:00")   # possiede Paris (FR) → owner-aggregato di 2 stati
    c = codes(conn)[a]
    assert "colonialista_anale" in c
    assert "imperialista_anale" not in c


def test_imperialista_quattro_stati(conn):
    a = add_user(conn, "A")
    for i, osm in enumerate([9101, 9103, 9106, 9108]):   # IT, FR, DE, CH
        dep(conn, a, osm, f"2026-05-0{i+1} 09:00:00")
    assert "imperialista_anale" in codes(conn)[a]


# --- luoghi -----------------------------------------------------------------

def test_checkpoint_charlie_berlino(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9106, "2026-05-01 09:00:00")
    assert "checkpoint_charlie" in codes(conn)[a]


def test_pellegrino_vaticano_secret(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9112, "2026-05-01 09:00:00")
    assert "pellegrino" in codes(conn)[a]


def test_hell_and_back(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9115, "2026-05-01 09:00:00")
    assert "hell_and_back" in codes(conn)[a]


def test_uranus_missouri(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9113, "2026-05-01 09:00:00")
    assert "uranus" in codes(conn)[a]


def test_meta_cacca_nome_scatologico(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9116, "2026-05-01 09:00:00")   # "Toilettes"
    assert "meta_cacca" in codes(conn)[a]


def test_d_day_normandia(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9105, "2026-05-01 09:00:00")   # Caen, Normandie
    assert "d_day" in codes(conn)[a]


def test_titicacca_vicino_al_lago(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9117, "2026-05-01 09:00:00")   # Puno, sul lago
    assert "titicacca" in codes(conn)[a]


def test_ultima_thule_oltre_artico(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9118, "2026-05-01 09:00:00")   # Tromsø, lat 69.6
    assert "ultima_thule" in codes(conn)[a]


def test_precisino_incrocio_intero(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9119, "2026-05-01 09:00:00", dlat=0.001, dlon=0.001)  # ~45.001, 8.001
    assert "precisino" in codes(conn)[a]


def test_serenissima_venezia_secret(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9102, "2026-05-01 09:00:00")
    assert "serenissima" in codes(conn)[a]


# --- flip nel tempo ---------------------------------------------------------

def test_vendicatore_di_fiume(conn):
    a = add_user(conn, "A")
    dep(conn, a, 9120, "2026-05-01 09:00:00")   # conquista Rijeka
    assert "vendicatore_fiume" in codes(conn)[a]


def test_vendetta_fredda(conn):
    a = add_user(conn, "A")
    b = add_user(conn, "B")
    dep(conn, a, 9101, "2026-01-01 09:00:00")   # A possiede Roma
    dep(conn, b, 9101, "2026-01-02 09:00:00")   # 1-1 conteso (A perde owner)
    dep(conn, b, 9101, "2026-01-03 09:00:00")   # B owner
    dep(conn, a, 9101, "2026-03-01 09:00:00")   # A pareggia (>30g dopo la perdita)
    dep(conn, a, 9101, "2026-03-02 09:00:00")   # A riprende Roma
    assert "vendetta_fredda" in codes(conn)[a]


def test_avignone(conn):
    a = add_user(conn, "A")
    b = add_user(conn, "B")
    dep(conn, a, 9101, "2026-01-01 09:00:00")   # A prende Roma
    dep(conn, b, 9101, "2026-02-01 09:00:00")   # 1-1 conteso
    dep(conn, b, 9101, "2026-02-02 09:00:00")   # B prende Roma → A l'ha persa
    dep(conn, a, 9104, "2026-03-01 09:00:00")   # A conquista Avignone
    assert "avignone" in codes(conn)[a]


def test_campagna_elettorale(conn):
    a = add_user(conn, "A")
    b = add_user(conn, "B")
    dep(conn, b, 9101, "2026-01-01 09:00:00")   # B 1
    dep(conn, b, 9101, "2026-01-02 09:00:00")   # B 2 → owner
    # A fa 3 cacate in una settimana e supera B (3 > 2) → furto al 3° deposito
    dep(conn, a, 9101, "2026-02-01 09:00:00")   # 1-2
    dep(conn, a, 9101, "2026-02-02 09:00:00")   # 2-2 conteso
    dep(conn, a, 9101, "2026-02-03 09:00:00")   # 3-2 furto (3 cacate in una settimana)
    assert "campagna_elettorale" in codes(conn)[a]
