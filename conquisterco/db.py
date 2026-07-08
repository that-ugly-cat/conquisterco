"""Accesso SQLite: connessione + init schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def connect(path: str = ":memory:") -> sqlite3.Connection:
    # check_same_thread=False: FastAPI serve gli endpoint sync su un threadpool e
    # la connessione può cambiare thread tra apertura e uso. Ogni richiesta ha
    # comunque la sua connessione (nessuna condivisione concorrente).
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Applica schema.sql (idempotente: usa CREATE TABLE, quindi su un DB già
    inizializzato va chiamato solo su DB nuovo)."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def fresh_db(path: str = ":memory:") -> sqlite3.Connection:
    conn = connect(path)
    init_db(conn)
    return conn
