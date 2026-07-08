"""Recompute: dal flusso dei depositi a standings / ownership / flips.

Regola di ownership (SPEC §2):
  - owner = chi ha il conteggio massimo in modo STRETTO;
  - parità sul massimo = contested (nessun owner, vale 0);
  - per rubare devi SUPERARE (pareggiare rende conteso).

`owner_of(counts)` è quindi una funzione pura del vettore dei conteggi. I flip
sono i cambi di stato-owner nel tempo (owner -> owner, owner -> contested,
contested -> owner), ognuno agganciato al deposito che l'ha causato.

Tutto qui è derivato: le tre tabelle si azzerano e si rigenerano.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict


def owner_of(counts: dict[int, int]) -> tuple[int | None, int, bool]:
    """Ritorna (owner_user_id | None, top_count, is_contested)."""
    if not counts:
        return (None, 0, False)
    top = max(counts.values())
    holders = [u for u, c in counts.items() if c == top]
    if len(holders) == 1:
        return (holders[0], top, False)
    return (None, top, True)


def recompute(conn: sqlite3.Connection) -> None:
    """Rigenera standings, territory_ownership e flips dai depositi arricchiti."""
    conn.execute("DELETE FROM flips")
    conn.execute("DELETE FROM territory_ownership")
    conn.execute("DELETE FROM standings")

    deposits = conn.execute(
        """SELECT id, user_id, ts, territory_osm_id
           FROM deposits
           WHERE territory_osm_id IS NOT NULL
           ORDER BY ts, id"""
    ).fetchall()

    counts: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    owner_state: dict[int, int | None] = {}   # territorio -> owner corrente (None=conteso)
    seen: set[int] = set()                     # territori già toccati
    contested: dict[int, bool] = {}
    top_counts: dict[int, int] = {}
    last_flip_ts: dict[int, str] = {}
    flips: list[tuple] = []

    for d in deposits:
        t = d["territory_osm_id"]
        u = d["user_id"]
        counts[t][u] += 1
        owner, top, is_contested = owner_of(counts[t])

        prev_owner = owner_state.get(t)
        first_touch = t not in seen
        # Un flip è un cambio di stato-owner. Alla prima conquista prev_owner=None.
        if first_touch or owner != prev_owner:
            flips.append((t, d["ts"], d["id"], prev_owner, owner))
            last_flip_ts[t] = d["ts"]

        owner_state[t] = owner
        contested[t] = is_contested
        top_counts[t] = top
        seen.add(t)

    # persist standings
    conn.executemany(
        "INSERT INTO standings (territory_osm_id, user_id, deposit_count) VALUES (?,?,?)",
        [(t, u, c) for t, us in counts.items() for u, c in us.items()],
    )
    # persist ownership
    conn.executemany(
        """INSERT INTO territory_ownership
           (territory_osm_id, owner_user_id, is_contested, top_count, last_flip_ts)
           VALUES (?,?,?,?,?)""",
        [(t, owner_state[t], int(contested[t]), top_counts[t], last_flip_ts.get(t))
         for t in seen],
    )
    # persist flips (in ordine)
    conn.executemany(
        """INSERT INTO flips
           (territory_osm_id, ts, deposit_id, prev_owner_user_id, new_owner_user_id)
           VALUES (?,?,?,?,?)""",
        flips,
    )
    conn.commit()
