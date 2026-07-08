"""CLI di import: `conquisterco-import <cartella_zip> [--db ...] [--media ...]`.

Importa i depositi dagli export WhatsApp in un DB. NON esegue geo-enrich né
recompute: quelli servono il geocoder reale (coordinate -> comuni), che arriva
come passo successivo. Finché non c'è, i depositi restano senza comune.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..db import connect, init_db
from .loader import import_dir


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(prog="conquisterco-import")
    ap.add_argument("hist_dir", help="cartella con gli zip di export WhatsApp")
    ap.add_argument("--db", default="conquisterco_real.db")
    ap.add_argument("--media", default="media")
    ap.add_argument("--window", type=int, default=5, help="finestra pin-foto (min)")
    args = ap.parse_args()

    conn = connect(args.db)
    if not Path(args.db).exists() or conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='deposits'"
    ).fetchone()[0] == 0:
        init_db(conn)

    res = import_dir(conn, args.hist_dir, media_dir=args.media, window_min=args.window)

    print(f"gruppo corrente : {res['current_group']}")
    print(f"utenti tenuti   : {res['allowed_count']}")
    for chat, s in res["per_chat"].items():
        print(f"  {chat}: {s}")
    print(f"TOTALE          : {res['total']}")
    print(f"\nDB: {args.db}  ·  media: {args.media}")
    print("Prossimo passo: geo-enrich (coordinate → comuni) col geocoder reale.")


if __name__ == "__main__":
    main()
