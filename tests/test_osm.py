import json
import urllib.parse

from conquisterco.db import fresh_db
from conquisterco.enrich_osm import drop_fallback_territories, enrich_deposits_osm
from conquisterco.geo_osm import OSMResolver, Resolution, Unit
from conquisterco.ingest import add_deposit
from conquisterco.recompute import recompute

from .conftest import mkuser

# --- resolver con fetch finto (niente rete) --------------------------------

_RESP = {
    10: {"osm_id": 46663, "name": "Trento", "lat": "46.066", "lon": "11.125",
         "addresstype": "city",
         "address": {"country": "Italia", "state": "Trentino", "county": "Provincia di Trento"},
         "geojson": {"type": "Polygon", "coordinates": [[[11, 46], [11, 46.1], [11.1, 46.1], [11, 46]]]}},
    8: {"osm_id": 45756, "name": "Provincia di Trento", "lat": "46.0", "lon": "11.1",
        "geojson": {"type": "Polygon", "coordinates": [[[10, 45], [11, 46], [12, 45], [10, 45]]]}},
    6: {"osm_id": 45757, "name": "Trentino-Alto Adige", "lat": "46.4", "lon": "11.3"},
    3: {"osm_id": 365331, "name": "Italia", "lat": "42.5", "lon": "12.5"},
}


def _fake_fetch(url):
    q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
    return json.dumps(_RESP[int(q["zoom"])]).encode()


def test_resolver_catena_completa():
    r = OSMResolver(min_interval=0, fetch=_fake_fetch).resolve(46.07, 11.12)
    assert r.comune.osm_id == 46663 and r.comune.name == "Trento"
    assert r.comune.country == "Italia" and r.comune.province == "Provincia di Trento"
    assert r.comune.geometry is not None
    assert r.province.osm_id == 45756
    assert r.region.osm_id == 45757
    assert r.country.osm_id == 365331


def test_resolver_scarta_addresstype_grosso():
    # a zoom 10 torna un "country" (punto in mare / paese senza comuni) → nessun comune
    resp = dict(_RESP)
    resp[10] = dict(_RESP[10])
    resp[10]["addresstype"] = "country"

    def fetch(url):
        q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
        return json.dumps(resp[int(q["zoom"])]).encode()

    r = OSMResolver(min_interval=0, fetch=fetch).resolve(46.07, 11.12)
    assert r.comune is None


def test_drop_fallback_territories():
    conn = fresh_db(":memory:")
    a = mkuser(conn, "A")
    # unità aggregata (paese) osm_id 999; un "comune" con lo STESSO osm_id = fallback
    conn.execute("INSERT INTO admin_units (osm_id, kind, name) VALUES (999,'country','X')")
    conn.execute("INSERT INTO territories (osm_id, name) VALUES (999,'Paese-come-comune')")
    conn.execute("INSERT INTO territories (osm_id, name) VALUES (1,'Comune vero')")
    d1 = add_deposit(conn, user_id=a, ts="2024-01-01 10:00:00", lat=1, lon=1, source="telegram")
    conn.execute("UPDATE deposits SET territory_osm_id=999 WHERE id=?", (d1,))
    conn.execute("INSERT INTO geocode_cache (lat, lon, comune_osm_id, payload_json) VALUES (1,1,999,'{}')")
    conn.commit()

    assert drop_fallback_territories(conn) == 1
    assert conn.execute("SELECT territory_osm_id FROM deposits WHERE id=?", (d1,)).fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM territories WHERE osm_id=999").fetchone()[0] == 0
    assert conn.execute("SELECT comune_osm_id FROM geocode_cache WHERE lat=1 AND lon=1").fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM territories WHERE osm_id=1").fetchone()[0] == 1  # il vero resta


def test_resolver_dedup_osm_id_ripetuti():
    # se un livello superiore torna lo stesso osm_id del comune, non lo duplica
    resp = dict(_RESP)
    resp[8] = dict(_RESP[10])  # provincia == comune (città metropolitana)
    def fetch(url):
        q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
        return json.dumps(resp[int(q["zoom"])]).encode()
    r = OSMResolver(min_interval=0, fetch=fetch).resolve(46.07, 11.12)
    assert r.province is None  # scartato perché stesso osm_id del comune


# --- enrich reale + aggregati (resolver finto in-memory) -------------------

def _res(comune_id):
    country = Unit(200, "Italia", "country", 42, 12, None)
    region = Unit(100, "Veneto", "region", 45.5, 11.5, '{"type":"Polygon","coordinates":[]}')
    province = Unit(300, "Provincia X", "province", 45.5, 11.5, None)
    comune = Unit(comune_id, f"Comune{comune_id}", "comune", 45.5, 11.5,
                  '{"type":"Polygon","coordinates":[]}',
                  country="Italia", region="Veneto", province="Provincia X")
    return Resolution(comune=comune, province=province, region=region, country=country)


class _FakeResolver:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = 0

    def resolve(self, lat, lon):
        self.calls += 1
        return self.mapping[(round(lat, 6), round(lon, 6))]


def test_enrich_osm_persiste_e_cacha():
    conn = fresh_db(":memory:")
    from conquisterco.ingest import add_deposit
    a = mkuser(conn, "A")
    add_deposit(conn, user_id=a, ts="2024-01-01 10:00:00", lat=45.10, lon=11.10, source="telegram")
    add_deposit(conn, user_id=a, ts="2024-01-02 10:00:00", lat=45.20, lon=11.20, source="telegram")

    resolver = _FakeResolver({
        (45.1, 11.1): _res(1),
        (45.2, 11.2): _res(2),
    })
    stats = enrich_deposits_osm(conn, resolver)
    assert stats["geocoded"] == 2 and stats["cache_hits"] == 0

    # comuni + aggregati persistiti
    assert conn.execute("SELECT COUNT(*) FROM territories").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM admin_units").fetchone()[0] == 3  # prov+reg+paese
    t = conn.execute("SELECT region_osm_id, geometry_geojson FROM territories WHERE osm_id=1").fetchone()
    assert t["region_osm_id"] == 100 and t["geometry_geojson"] is not None

    # ri-enrich: nulla da fare (già assegnati) → 0 chiamate nuove
    resolver.calls = 0
    stats2 = enrich_deposits_osm(conn, resolver)
    assert stats2["total"] == 0 and resolver.calls == 0


def test_aggregate_ownership_logica_a():
    conn = fresh_db(":memory:")
    from conquisterco.ingest import add_deposit
    a = mkuser(conn, "A")
    b = mkuser(conn, "B")
    # A prende comune 1 e 2, B prende comune 3 — tutti nella regione 100
    add_deposit(conn, user_id=a, ts="2024-01-01 10:00:00", lat=45.10, lon=11.10, source="telegram")
    add_deposit(conn, user_id=a, ts="2024-01-02 10:00:00", lat=45.20, lon=11.20, source="telegram")
    add_deposit(conn, user_id=b, ts="2024-01-03 10:00:00", lat=45.30, lon=11.30, source="telegram")
    resolver = _FakeResolver({(45.1, 11.1): _res(1), (45.2, 11.2): _res(2), (45.3, 11.3): _res(3)})
    enrich_deposits_osm(conn, resolver)
    recompute(conn)

    # regione 100: A possiede 2 comuni, B 1 → owner = A
    row = conn.execute("SELECT owner_user_id, is_contested, comuni_owned FROM aggregate_ownership WHERE unit_osm_id=100").fetchone()
    assert row["owner_user_id"] == a and row["is_contested"] == 0 and row["comuni_owned"] == 2


def test_aggregato_conteso_se_comuni_tutti_contesi():
    conn = fresh_db(":memory:")
    a = mkuser(conn, "A")
    b = mkuser(conn, "B")
    # A e B pareggiano sullo stesso comune (regione 100) → comune conteso
    add_deposit(conn, user_id=a, ts="2024-01-01 10:00:00", lat=45.10, lon=11.10, source="telegram")
    add_deposit(conn, user_id=b, ts="2024-01-02 10:00:00", lat=45.10, lon=11.10, source="telegram")
    enrich_deposits_osm(conn, _FakeResolver({(45.1, 11.1): _res(1)}))
    recompute(conn)

    assert conn.execute("SELECT is_contested FROM territory_ownership WHERE territory_osm_id=1").fetchone()[0] == 1
    # la regione 100 (unico comune, conteso) è CONTESA, non senza riga/owner
    row = conn.execute("SELECT owner_user_id, is_contested FROM aggregate_ownership WHERE unit_osm_id=100").fetchone()
    assert row is not None and row["owner_user_id"] is None and row["is_contested"] == 1
