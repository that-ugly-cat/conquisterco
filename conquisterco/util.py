"""Piccole utility condivise."""

from __future__ import annotations

import math
from datetime import datetime

TS_FMT = "%Y-%m-%d %H:%M:%S"


def parse_ts(s: str) -> datetime:
    """Parsa un timestamp ISO-ish. Tollerante al separatore 'T'."""
    return datetime.fromisoformat(s)


def fmt_ts(dt: datetime) -> str:
    return dt.strftime(TS_FMT)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in km tra due coordinate (formula dell'emisenoverso)."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
