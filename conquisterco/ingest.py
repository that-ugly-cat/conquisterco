"""Ingestione normalizzata dei depositi (source-agnostica).

WhatsApp / Telegram / mappa confluiscono tutti qui: un `Deposit` normalizzato.
La dedup (indice `idx_deposits_dedup`, su utente+pin+minuto) scarta i re-import
dello stesso evento -> l'import è idempotente.
"""

from __future__ import annotations

import sqlite3

VALID_SOURCES = {"whatsapp_import", "telegram", "map_manual"}


def add_user(conn: sqlite3.Connection, display_name: str, *, role: str = "user",
             wa_handle: str | None = None, telegram_id: str | None = None,
             color: str | None = None, flag_ref: str | None = None,
             avatar_ref: str | None = None,
             home_lat: float | None = None, home_lon: float | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO users
           (display_name, role, wa_handle, telegram_id, color, flag_ref,
            avatar_ref, home_lat, home_lon)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (display_name, role, wa_handle, telegram_id, color, flag_ref,
         avatar_ref, home_lat, home_lon),
    )
    conn.commit()
    return cur.lastrowid


def add_deposit(conn: sqlite3.Connection, *, user_id: int, ts: str,
                lat: float, lon: float, source: str,
                photo_ref: str | None = None,
                altitude: float | None = None, alt_source: str | None = None,
                raw_ref: str | None = None) -> int | None:
    """Inserisce un deposito. Ritorna l'id, o None se scartato come duplicato."""
    if source not in VALID_SOURCES:
        raise ValueError(f"source non valida: {source!r}")
    cur = conn.execute(
        """INSERT OR IGNORE INTO deposits
           (user_id, ts, lat, lon, altitude, alt_source, photo_ref, source, raw_ref)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, ts, lat, lon, altitude, alt_source, photo_ref, source, raw_ref),
    )
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


def add_deposits(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Ingestione in blocco. Ritorna il numero di depositi effettivamente inseriti
    (i duplicati non contano)."""
    inserted = 0
    for r in rows:
        if add_deposit(conn, **r) is not None:
            inserted += 1
    return inserted
