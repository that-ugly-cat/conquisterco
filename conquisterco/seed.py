"""Dati fittizi + demo end-to-end.

`python -m conquisterco.seed` (o `conquisterco-demo`) costruisce un mondo di
prova, lancia l'intera pipeline e stampa un report: leaderboard, record, feed
dei flip e bacheca badge. Scenario deterministico, pensato per innescare le
meccaniche (conquiste, pareggi, furti, gran parte degli achievement).
"""

from __future__ import annotations

import sqlite3

from .db import fresh_db
from .geo import FakeGeocoder
from .ingest import add_deposit, add_user
from .leaderboards import main_leaderboard, records
from .pipeline import run_all

_CENTERS = {c.osm_id: c for c in FakeGeocoder().cells}


def _dep(conn, uid, osm_id, ts, *, photo=True):
    c = _CENTERS[osm_id]
    add_deposit(
        conn, user_id=uid, ts=ts,
        lat=c.lat + 0.001, lon=c.lon + 0.001,
        source="telegram",
        photo_ref=f"media/{ts.replace(' ', '_').replace(':', '')}.jpg" if photo else None,
    )


def build_world(conn: sqlite3.Connection) -> dict[str, int]:
    spit = add_user(conn, "Spit", role="admin", color="#8B4513",
                    home_lat=46.07, home_lon=11.12)
    fede = add_user(conn, "Fede", color="#B5651D", home_lat=41.90, home_lon=12.50)
    bru = add_user(conn, "Bru", color="#6F4E37", home_lat=45.46, home_lon=9.19)
    ranz = add_user(conn, "Ranz", color="#A0522D", home_lat=40.85, home_lon=14.27)
    return {"spit": spit, "fede": fede, "bru": bru, "ranz": ranz}


def seed_deposits(conn: sqlite3.Connection, u: dict[str, int]) -> None:
    n = 0

    # --- Spit: Grand Tour delle 20 regioni, uno al giorno ---
    for i, osm in enumerate(range(1001, 1021), start=1):
        _dep(conn, u["spit"], osm, f"2026-01-{i:02d} 09:00:00", photo=(i % 4 != 0))
        n += 1

    # --- Milano (1003): Spit consolida, Fede pareggia, Spit si riprende → Guardiano ---
    _dep(conn, u["spit"], 1003, "2026-01-20 18:00:00")   # Spit 2 a Milano
    _dep(conn, u["fede"], 1003, "2026-01-21 09:00:00")   # 1-2
    _dep(conn, u["fede"], 1003, "2026-01-21 10:00:00")   # 2-2 → conteso
    _dep(conn, u["spit"], 1003, "2026-01-22 09:00:00")   # 3-2 → Spit riprende (Guardiano)

    # --- Roma (1012): Fede ruba al leader → Conquistador + Regicidio ---
    _dep(conn, u["fede"], 1012, "2026-01-23 09:00:00")   # 1-1 → conteso
    _dep(conn, u["fede"], 1012, "2026-01-23 09:30:00")   # 2-1 → Fede owner (furto al leader)

    # --- Bru: tris polacco → Spartizione della Polonia (+ Colonizzatore) ---
    _dep(conn, u["bru"], 3001, "2026-01-05 09:00:00")
    _dep(conn, u["bru"], 3002, "2026-01-06 09:00:00")
    _dep(conn, u["bru"], 3003, "2026-01-07 09:00:00")

    # --- Ranz: tris francese in mezz'ora → Blitz + Waterloo + Teletrasporto ---
    _dep(conn, u["ranz"], 2001, "2026-01-05 12:00:00")   # Paris
    _dep(conn, u["ranz"], 2002, "2026-01-05 12:10:00")   # Lyon
    _dep(conn, u["ranz"], 2003, "2026-01-05 12:20:00")   # Marseille

    # --- Spit: giro europeo → Passaporto (5 nazioni) + Batisfera + Scalatore ---
    _dep(conn, u["spit"], 4001, "2026-01-25 09:00:00")   # Madrid  (Spagna)
    _dep(conn, u["spit"], 4002, "2026-01-26 09:00:00")   # Berlin  (Germania)
    _dep(conn, u["spit"], 4003, "2026-01-27 09:00:00")   # Zürich  (Svizzera)
    _dep(conn, u["spit"], 4004, "2026-01-28 09:00:00")   # Rotterdam (Paesi Bassi, -2 m → Batisfera)
    _dep(conn, u["spit"], 1050, "2026-01-29 09:00:00")   # Breuil-Cervinia (2050 m → Scalatore)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _hr(title: str) -> str:
    return f"\n{'─' * 4} {title} {'─' * max(2, 56 - len(title))}"


def _fmt_rec(rec) -> str:
    if not rec:
        return "—"
    val = rec["value"]
    if isinstance(val, float):
        val = f"{val:.3f}".rstrip("0").rstrip(".")
    where = f" @ {rec['where']}" if rec.get("where") else ""
    return f"{rec['name']} ({val}){where}"


def report(conn: sqlite3.Connection) -> str:
    names = {r["id"]: r["display_name"] for r in conn.execute("SELECT id, display_name FROM users")}
    out: list[str] = []
    out.append("💩  CONQUISTERCO — report demo  💩")

    # leaderboard principale
    out.append(_hr("Classifica territori (comuni · km²)"))
    for i, row in enumerate(main_leaderboard(conn), 1):
        out.append(f"  {i}. {row['name']:<6} {row['comuni']:>3} comuni   {row['km2']:>8.1f} km²")

    # ownership
    tot = conn.execute("SELECT COUNT(*) FROM territory_ownership").fetchone()[0]
    owned = conn.execute("SELECT COUNT(*) FROM territory_ownership WHERE owner_user_id IS NOT NULL").fetchone()[0]
    contested = conn.execute("SELECT COUNT(*) FROM territory_ownership WHERE is_contested=1").fetchone()[0]
    out.append(_hr("Mappa"))
    out.append(f"  comuni toccati: {tot}   posseduti: {owned}   contesi: {contested}")

    # record
    rec = records(conn)
    out.append(_hr("Record"))
    labels = {
        "nord": "Più a Nord", "sud": "Più a Sud", "est": "Più a Est", "ovest": "Più a Ovest",
        "piu_in_alto": "Più in alto", "piu_in_basso": "Più in basso", "trasferta": "Trasferta",
        "esploratore": "Esploratore", "volume": "Volume", "passaporto": "Passaporto",
        "streak": "Streak", "latifondista": "Latifondista",
    }
    for key, lab in labels.items():
        out.append(f"  {lab:<14} {_fmt_rec(rec.get(key))}")

    # feed flip
    out.append(_hr("Feed (ultimi flip)"))
    flips = conn.execute(
        """SELECT f.ts, f.prev_owner_user_id AS p, f.new_owner_user_id AS nw, t.name AS tn
           FROM flips f JOIN territories t ON t.osm_id=f.territory_osm_id
           ORDER BY f.ts DESC, f.id DESC LIMIT 10"""
    ).fetchall()
    for f in flips:
        nw = names.get(f["nw"]) if f["nw"] else None
        p = names.get(f["p"]) if f["p"] else None
        if nw is None:
            line = f"{f['tn']} è diventato conteso"
        elif p is None:
            line = f"{nw} ha conquistato {f['tn']}"
        else:
            line = f"{nw} ha strappato {f['tn']} a {p}"
        out.append(f"  {f['ts'][:10]}  {line}")

    # bacheca badge
    out.append(_hr("Bacheca badge"))
    rows = conn.execute(
        """SELECT u.display_name AS nm, a.name AS an, COUNT(*) AS c
           FROM awards w JOIN users u ON u.id=w.user_id JOIN achievements a ON a.id=w.achievement_id
           GROUP BY w.user_id, a.id ORDER BY u.display_name, a.name"""
    ).fetchall()
    by_user: dict[str, list[str]] = {}
    for r in rows:
        tag = r["an"] + (f" ×{r['c']}" if r["c"] > 1 else "")
        by_user.setdefault(r["nm"], []).append(tag)
    for nm, badges in by_user.items():
        out.append(f"  {nm:<6} {', '.join(badges)}")

    return "\n".join(out)


def main() -> None:
    # console Windows: forza UTF-8 così emoji e box-drawing non esplodono
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    conn = fresh_db(":memory:")
    users = build_world(conn)
    seed_deposits(conn, users)
    summary = run_all(conn, FakeGeocoder())
    print(report(conn))
    print(f"\n[pipeline] depositi arricchiti: {summary['enriched']} · award: {summary['awards']}")


if __name__ == "__main__":
    main()
