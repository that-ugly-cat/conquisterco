from conquisterco.geoarea import geojson_area_km2


def test_box_un_grado_all_equatore():
    # ~1°×1° all'equatore ≈ 111 km × 111 km ≈ 12300 km²
    box = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    a = geojson_area_km2(box)
    assert 11000 < a < 13000


def test_multipolygon_somma():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    multi = {"type": "MultiPolygon", "coordinates": [poly["coordinates"], poly["coordinates"]]}
    assert abs(geojson_area_km2(multi) - 2 * geojson_area_km2(poly)) < 1


def test_none_e_tipi_ignoti():
    assert geojson_area_km2(None) is None
    assert geojson_area_km2({"type": "Point", "coordinates": [0, 0]}) is None
