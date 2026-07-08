"""CLI per creare/aggiornare un utente con password (bootstrap del primo admin).

    conquisterco-admin Giovanni_S --password ****** --role admin

Serve a impostare le credenziali senza passare dal pannello (che a sua volta
richiede già un admin). Da usare al primo avvio / in deploy.
"""

from __future__ import annotations

import argparse

from ..db import connect
from .auth import hash_password


def main() -> None:
    ap = argparse.ArgumentParser(prog="conquisterco-admin")
    ap.add_argument("display_name")
    ap.add_argument("--password", required=True)
    ap.add_argument("--role", default="admin", choices=["user", "admin"])
    ap.add_argument("--db", default="conquisterco_real.db")
    a = ap.parse_args()

    conn = connect(a.db)
    row = conn.execute("SELECT id FROM users WHERE display_name=?", (a.display_name,)).fetchone()
    if row:
        conn.execute("UPDATE users SET role=?, password_hash=? WHERE id=?",
                     (a.role, hash_password(a.password), row["id"]))
        verb = "aggiornato"
    else:
        conn.execute("INSERT INTO users (display_name, role, password_hash) VALUES (?,?,?)",
                     (a.display_name, a.role, hash_password(a.password)))
        verb = "creato"
    conn.commit()
    print(f"{verb}: {a.display_name} ({a.role})")


if __name__ == "__main__":
    main()
