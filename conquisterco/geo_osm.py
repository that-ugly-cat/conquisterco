"""Resolver amministrativo via Nominatim (OSM pubblico).

Per ogni coordinata fa reverse-geocoding a zoom decrescenti (10/8/6/3) e ottiene
comune → provincia → regione → stato, ognuno con osm_id, nome, centroide e
geometria (GeoJSON semplificato). Logica pura + rete: `fetch` è iniettabile,
così i test girano senza toccare Internet.

Nominatim TOS: max ~1 req/s, User-Agent identificativo. Rispettati qui.
La cache (idempotenza, egress una tantum) vive nel layer di enrich, non qui.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

BASE_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = "conquisterco/0.1 (il Cacasto; https://github.com/that-ugly-cat)"

# zoom Nominatim -> (kind, soglia di semplificazione poligono in gradi)
_LEVELS = [
    (10, "comune", 0.0003),
    (8, "province", 0.001),
    (6, "region", 0.003),
    (3, "country", 0.01),
]


@dataclass
class Unit:
    osm_id: int
    name: str
    kind: str
    lat: float
    lon: float
    geometry: str | None            # GeoJSON (stringa) della geometria
    country: str | None = None      # nomi leggibili (solo per il comune)
    region: str | None = None
    province: str | None = None


@dataclass
class Resolution:
    comune: Unit | None = None
    province: Unit | None = None
    region: Unit | None = None
    country: Unit | None = None

    def units(self) -> list[Unit]:
        return [u for u in (self.comune, self.province, self.region, self.country) if u]


def _default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


class OSMResolver:
    def __init__(self, *, base_url: str = BASE_URL, min_interval: float = 1.1, fetch=None):
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self._fetch = fetch or _default_fetch
        self._last = 0.0
        # cache dei genitori per (kind, nome, stato): un'unità aggregata (regione,
        # provincia, stato) è condivisa da tanti comuni → la geometria si scarica
        # una volta sola invece che a ogni punto.
        self._parent_cache: dict[tuple, Unit] = {}

    def _throttle(self) -> None:
        dt = time.monotonic() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.monotonic()

    def _reverse(self, lat: float, lon: float, zoom: int, threshold: float) -> dict | None:
        q = urllib.parse.urlencode({
            "lat": lat, "lon": lon, "format": "jsonv2", "zoom": zoom,
            "addressdetails": 1, "polygon_geojson": 1, "polygon_threshold": threshold,
        })
        self._throttle()
        try:
            data = json.loads(self._fetch(f"{self.base_url}/reverse?{q}"))
        except Exception:
            return None
        return data if isinstance(data, dict) and data.get("osm_id") else None

    @staticmethod
    def _unit(d: dict, kind: str) -> Unit:
        return Unit(
            osm_id=int(d["osm_id"]), name=d.get("name") or "?", kind=kind,
            lat=float(d["lat"]), lon=float(d["lon"]),
            geometry=json.dumps(d["geojson"]) if d.get("geojson") else None,
        )

    def resolve(self, lat: float, lon: float) -> Resolution:
        res = Resolution()
        # 1) comune (zoom 10): sempre una chiamata, porta anche i NOMI dei genitori
        d10 = self._reverse(lat, lon, 10, _LEVELS[0][2])
        if d10 is None:
            return res
        comune = self._unit(d10, "comune")
        addr = d10.get("address", {})
        comune.country = addr.get("country")
        comune.region = addr.get("state")
        comune.province = addr.get("county")
        res.comune = comune
        seen = {comune.osm_id}

        # 2) genitori: chiamata solo per quelli mai visti (cache per nome+stato)
        country = addr.get("country")
        specs = [
            ("province", 8, _LEVELS[1][2], addr.get("county")),
            ("region", 6, _LEVELS[2][2], addr.get("state")),
            ("country", 3, _LEVELS[3][2], country),
        ]
        for kind, zoom, thr, name in specs:
            if not name:
                continue
            key = (kind, name, country)
            unit = self._parent_cache.get(key)
            if unit is None:
                d = self._reverse(lat, lon, zoom, thr)
                if d is None or int(d["osm_id"]) in seen:
                    continue
                unit = self._unit(d, kind)
                self._parent_cache[key] = unit
            if unit.osm_id in seen:
                continue
            seen.add(unit.osm_id)
            setattr(res, kind, unit)
        return res
