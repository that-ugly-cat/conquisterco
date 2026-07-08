"""Orchestrazione della pipeline derivata (idempotente, ri-eseguibile).

    depositi grezzi
      → enrich    (comune + quota)
      → recompute (standings, ownership, flips)
      → evaluate  (awards)
"""

from __future__ import annotations

import sqlite3

from .achievements import evaluate, sync_achievements
from .enrich import enrich_deposits
from .geo import Geocoder
from .recompute import recompute


def _persist_awards(conn: sqlite3.Connection, awards) -> None:
    conn.execute("DELETE FROM awards")
    code_to_id = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM achievements")}
    conn.executemany(
        "INSERT INTO awards (achievement_id, user_id, ts_earned, context) VALUES (?,?,?,?)",
        [(code_to_id[a.code], a.user_id, a.ts_earned, a.context) for a in awards],
    )
    conn.commit()


def run_all(conn: sqlite3.Connection, geocoder: Geocoder, *, force_enrich: bool = False) -> dict:
    """Esegue l'intera pipeline. Ritorna un piccolo riepilogo."""
    enriched = enrich_deposits(conn, geocoder, force=force_enrich)
    recompute(conn)
    sync_achievements(conn)
    awards = evaluate(conn)
    _persist_awards(conn, awards)
    return {"enriched": enriched, "awards": len(awards)}
