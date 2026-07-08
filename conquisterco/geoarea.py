"""Area di un poligono GeoJSON in km² (approssimazione sferica).

Formula di Chamberlain & Duquette (eccesso sferico), sui ring lon/lat. Buona per
la leaderboard km² senza tirarsi dentro shapely/pyproj. Le geometrie sono già
semplificate, quindi è comunque un valore di gioco, non catastale.
"""

from __future__ import annotations

import math

_R = 6371.0088  # raggio medio terrestre (km)


def _ring_area(ring: list) -> float:
    n = len(ring)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        lon1, lat1 = ring[i][0], ring[i][1]
        lon2, lat2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        total += math.radians(lon2 - lon1) * (
            2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2))
        )
    return abs(total * _R * _R / 2.0)


def _polygon_area(poly: list) -> float:
    if not poly:
        return 0.0
    area = _ring_area(poly[0])                      # anello esterno
    for hole in poly[1:]:
        area -= _ring_area(hole)                     # buchi
    return max(area, 0.0)


def geojson_area_km2(geometry: dict | None) -> float | None:
    """Area in km² di una geometria GeoJSON Polygon/MultiPolygon."""
    if not geometry:
        return None
    t = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if t == "Polygon":
        return round(_polygon_area(coords), 1)
    if t == "MultiPolygon":
        return round(sum(_polygon_area(p) for p in coords), 1)
    return None
