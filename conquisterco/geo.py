"""Geocoding pluggable: coordinata -> comune, coordinata -> quota.

L'interfaccia `Geocoder` isola il resto della pipeline dalla sorgente geografica.
In Fase 1 usiamo `FakeGeocoder` (catalogo a bounding-box, zero dipendenze) per
girare e testare tutto offline. `OSMGeocoder` è lo stub della versione reale
(point-in-polygon con shapely su poligoni OSM + DEM per la quota), da riempire
in fase successiva.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Territory


class Geocoder(Protocol):
    def locate(self, lat: float, lon: float) -> Territory | None:
        """Comune che contiene il punto, o None se fuori copertura."""
        ...

    def elevation(self, lat: float, lon: float) -> float | None:
        """Quota stimata (m). None se ignota."""
        ...


# ---------------------------------------------------------------------------
# Catalogo fittizio: comuni con centro, quota e semi-lato del bounding box.
# Copre le 20 regioni italiane (una capoluogo ciascuna) + comuni esteri per
# esercitare Passaporto/Polonia/Waterloo + un comune d'alta quota e uno sotto
# il livello del mare. area_km2 varia per rendere interessante la board km².
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Cell:
    osm_id: int
    name: str
    country: str
    region: str | None
    lat: float
    lon: float
    elev: float
    area_km2: float
    half: float = 0.12  # semi-lato del bbox in gradi


_CATALOG: list[_Cell] = [
    # --- Italia: un capoluogo per regione ---
    _Cell(1001, "Aosta", "Italy", "Valle d'Aosta", 45.7372, 7.3206, 583, 21.4),
    _Cell(1002, "Torino", "Italy", "Piemonte", 45.0703, 7.6869, 239, 130.0),
    _Cell(1003, "Milano", "Italy", "Lombardia", 45.4642, 9.1900, 120, 181.7),
    _Cell(1004, "Trento", "Italy", "Trentino-Alto Adige", 46.0704, 11.1211, 194, 157.9),
    _Cell(1005, "Venezia", "Italy", "Veneto", 45.4408, 12.3155, 1, 415.9),
    _Cell(1006, "Trieste", "Italy", "Friuli-Venezia Giulia", 45.6495, 13.7768, 2, 84.5),
    _Cell(1007, "Genova", "Italy", "Liguria", 44.4056, 8.9463, 20, 240.3),
    _Cell(1008, "Bologna", "Italy", "Emilia-Romagna", 44.4949, 11.3426, 54, 140.9),
    _Cell(1009, "Firenze", "Italy", "Toscana", 43.7696, 11.2558, 50, 102.3),
    _Cell(1010, "Perugia", "Italy", "Umbria", 43.1107, 12.3908, 493, 449.9),
    _Cell(1011, "Ancona", "Italy", "Marche", 43.6158, 13.5189, 16, 124.8),
    _Cell(1012, "Roma", "Italy", "Lazio", 41.9028, 12.4964, 21, 1287.4),
    _Cell(1013, "L'Aquila", "Italy", "Abruzzo", 42.3498, 13.3995, 714, 466.9),
    _Cell(1014, "Campobasso", "Italy", "Molise", 41.5603, 14.6627, 701, 55.6),
    _Cell(1015, "Napoli", "Italy", "Campania", 40.8518, 14.2681, 17, 119.0),
    _Cell(1016, "Bari", "Italy", "Puglia", 41.1171, 16.8719, 5, 116.2),
    _Cell(1017, "Potenza", "Italy", "Basilicata", 40.6420, 15.8056, 819, 175.4),
    _Cell(1018, "Catanzaro", "Italy", "Calabria", 38.9098, 16.5877, 320, 112.7),
    _Cell(1019, "Palermo", "Italy", "Sicilia", 38.1157, 13.3615, 14, 160.6),
    _Cell(1020, "Cagliari", "Italy", "Sardegna", 39.2238, 9.1217, 4, 85.0),
    # --- casi speciali quota ---
    _Cell(1050, "Breuil-Cervinia", "Italy", "Valle d'Aosta", 45.9360, 7.6310, 2050, 200.0, half=0.05),
    _Cell(1051, "Jolanda di Savoia", "Italy", "Emilia-Romagna", 44.8830, 11.9800, -2, 108.0, half=0.05),
    # --- Francia (Waterloo: >=3 comuni distinti) ---
    _Cell(2001, "Paris", "France", None, 48.8566, 2.3522, 35, 105.4),
    _Cell(2002, "Lyon", "France", None, 45.7640, 4.8357, 170, 47.9),
    _Cell(2003, "Marseille", "France", None, 43.2965, 5.3698, 12, 240.6),
    _Cell(2004, "Nice", "France", None, 43.7102, 7.2620, 15, 71.9),
    # --- Polonia (Spartizione: >=3 comuni posseduti insieme) ---
    _Cell(3001, "Warszawa", "Poland", None, 52.2297, 21.0122, 100, 517.2),
    _Cell(3002, "Kraków", "Poland", None, 50.0647, 19.9450, 219, 326.8),
    _Cell(3003, "Gdańsk", "Poland", None, 54.3520, 18.6466, 5, 262.0),
    _Cell(3004, "Wrocław", "Poland", None, 51.1079, 17.0385, 111, 293.0),
    # --- altre nazioni (Passaporto: >=5 nazioni) ---
    _Cell(4001, "Madrid", "Spain", None, 40.4168, -3.7038, 667, 604.3),
    _Cell(4002, "Berlin", "Germany", None, 52.5200, 13.4050, 34, 891.7),
    _Cell(4003, "Zürich", "Switzerland", None, 47.3769, 8.5417, 408, 87.9),
    _Cell(4004, "Rotterdam", "Netherlands", None, 51.9244, 4.4777, -2, 324.1),  # sotto il mare
]


class FakeGeocoder:
    """Geocoder deterministico basato su bounding-box. Nessuna dipendenza."""

    def __init__(self, catalog: list[_Cell] | None = None):
        self._cells = catalog if catalog is not None else _CATALOG

    def _cell_at(self, lat: float, lon: float) -> _Cell | None:
        for c in self._cells:
            if (c.lat - c.half <= lat <= c.lat + c.half
                    and c.lon - c.half <= lon <= c.lon + c.half):
                return c
        return None

    def locate(self, lat: float, lon: float) -> Territory | None:
        c = self._cell_at(lat, lon)
        if c is None:
            return None
        return Territory(
            osm_id=c.osm_id, name=c.name, admin_level=8,
            country=c.country, region=c.region, area_km2=c.area_km2,
        )

    def elevation(self, lat: float, lon: float) -> float | None:
        c = self._cell_at(lat, lon)
        return None if c is None else c.elev

    # comodo per il generatore di dati fittizi
    @property
    def cells(self) -> list[_Cell]:
        return self._cells


class OSMGeocoder:
    """Stub della versione reale (Fase futura): point-in-polygon con shapely su
    poligoni OSM + DEM per la quota. Da implementare."""

    def locate(self, lat: float, lon: float) -> Territory | None:  # pragma: no cover
        raise NotImplementedError(
            "OSMGeocoder arriverà con shapely + poligoni OSM. Per ora usa FakeGeocoder."
        )

    def elevation(self, lat: float, lon: float) -> float | None:  # pragma: no cover
        raise NotImplementedError
