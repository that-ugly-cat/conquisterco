"""Dataclass di dominio (leggere; il DB resta la fonte di verità)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Territory:
    osm_id: int
    name: str
    admin_level: int | None
    country: str | None
    region: str | None
    area_km2: float | None
    geometry_ref: str | None = None


@dataclass(frozen=True)
class Award:
    """Un badge assegnato. `code` = achievement, `context` = cosa l'ha scatenato."""
    code: str
    user_id: int
    ts_earned: str
    context: str | None = None
