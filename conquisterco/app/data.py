"""Query di lettura per la dashboard (ritornano dict serializzabili)."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

# peso medio stimato di un deposito (g). Fonte: peso medio delle feci ~128 g.
AVG_DUMP_G = 128

from ..leaderboards import _streaks, main_leaderboard, records
from ..recompute import owner_of

_RECORD_LABELS = {
    "nord": "Più a Nord", "sud": "Più a Sud", "est": "Più a Est", "ovest": "Più a Ovest",
    "piu_in_alto": "Più in alto", "piu_in_basso": "Più in basso", "trasferta": "Trasferta",
    "esploratore": "Esploratore", "volume": "Volume", "passaporto": "Passaporto",
    "streak": "Streak", "latifondista": "Latifondista",
}


def _names(conn):
    return {r["id"]: r for r in conn.execute("SELECT * FROM users")}


def _pub(row) -> str | None:
    """Nome pubblico (mostrato ovunque), con fallback allo username."""
    if row is None:
        return None
    return row["public_name"] or row["display_name"]


def territories_geo(conn: sqlite3.Connection) -> list[dict]:
    """Comuni toccati, con centroide (media dei depositi), owner e stato.
    Il centroide evita di dover storare la geometria: buono per i marker."""
    centroids = {
        r["t"]: (r["clat"], r["clon"], r["n"])
        for r in conn.execute(
            """SELECT territory_osm_id AS t, AVG(lat) AS clat, AVG(lon) AS clon, COUNT(*) AS n
               FROM deposits WHERE territory_osm_id IS NOT NULL
               GROUP BY territory_osm_id"""
        )
    }
    users = _names(conn)
    out = []
    for r in conn.execute(
        """SELECT o.territory_osm_id AS t, o.owner_user_id AS uid, o.is_contested AS c,
                  o.top_count AS tc, t.name AS name, t.country AS country,
                  t.region AS region, t.area_km2 AS area
           FROM territory_ownership o JOIN territories t ON t.osm_id=o.territory_osm_id"""
    ):
        cen = centroids.get(r["t"])
        if not cen:
            continue
        owner = users.get(r["uid"]) if r["uid"] else None
        out.append({
            "osm_id": r["t"], "name": r["name"], "country": r["country"],
            "region": r["region"], "area_km2": r["area"],
            "lat": round(cen[0], 5), "lon": round(cen[1], 5), "deposits": cen[2],
            "top_count": r["tc"], "is_contested": bool(r["c"]),
            "owner_id": r["uid"],
            "owner_name": _pub(owner),
            "owner_color": owner["color"] if owner else None,
        })
    return out


def _contenders(conn: sqlite3.Connection) -> dict[int, list[str]]:
    """Per i COMUNI contesi, i giocatori in parità in testa (tra chi e chi)."""
    users = _names(conn)
    out: dict[int, list[str]] = defaultdict(list)
    for r in conn.execute(
        """SELECT s.territory_osm_id t, s.user_id u
           FROM standings s JOIN territory_ownership o ON o.territory_osm_id = s.territory_osm_id
           WHERE o.is_contested = 1 AND s.deposit_count = o.top_count ORDER BY s.user_id"""
    ):
        out[r["t"]].append(_pub(users.get(r["u"])))
    return out


def _unit_geo(conn: sqlite3.Connection, osm_id: int) -> dict | None:
    """Nome + centroide + geometria di un'unità (admin_unit o comune)."""
    for tbl in ("admin_units", "territories"):
        r = conn.execute(
            f"SELECT name, centroid_lat clat, centroid_lon clon, geometry_geojson geo "
            f"FROM {tbl} WHERE osm_id=?", (osm_id,)).fetchone()
        if r and r["geo"]:
            return {"name": r["name"], "geometry": json.loads(r["geo"]),
                    "centroid": [r["clat"], r["clon"]] if r["clat"] is not None else None}
    return None


def _feature(osm_id, name, level, geo, owner_id, owner, contested, count, contenders) -> dict:
    return {
        "osm_id": osm_id, "name": name, "level": level,
        "centroid": geo["centroid"], "geometry": geo["geometry"],
        "owner_id": owner_id, "owner_name": _pub(owner),
        "owner_color": owner["color"] if owner else None,
        "owner_flag": f"/media/flag/{owner_id}" if owner and owner["flag_ref"] else None,
        "is_contested": bool(contested), "count": count,
        "contenders": contenders if contested else None,
    }


# antenati da guardare per livello, dal più fine al più grosso
_LEVEL_CHAIN = {
    "province": ("province_osm_id",),
    "region": ("region_osm_id", "province_osm_id"),
    "country": ("country_osm_id", "region_osm_id", "province_osm_id"),
}


def areas(conn: sqlite3.Connection, level: str) -> list[dict]:
    """Aree con geometria per un livello del LOD. Il comune usa territories; gli
    aggregati usano un 'rappresentante' per comune (primo antenato disponibile,
    o il comune stesso se la gerarchia è piatta) → nessuna area cacata sparisce
    nei paesi senza province/regioni distinte (Croazia, Slovenia, Islanda…)."""
    users = _names(conn)
    if level == "comune":
        contenders = _contenders(conn)
        out = []
        for r in conn.execute(
            """SELECT t.osm_id, t.name, t.centroid_lat clat, t.centroid_lon clon,
                      t.geometry_geojson geo, o.owner_user_id uid, o.is_contested c, o.top_count cnt
               FROM territories t LEFT JOIN territory_ownership o ON o.territory_osm_id = t.osm_id
               WHERE t.geometry_geojson IS NOT NULL"""
        ):
            owner = users.get(r["uid"]) if r["uid"] else None
            geo = {"geometry": json.loads(r["geo"]),
                   "centroid": [r["clat"], r["clon"]] if r["clat"] is not None else None}
            out.append(_feature(r["osm_id"], r["name"], "comune", geo, r["uid"], owner,
                                r["c"], r["cnt"] or 0, contenders.get(r["osm_id"])))
        return out
    return _aggregate_areas(conn, level, users)


def _aggregate_areas(conn: sqlite3.Connection, level: str, users: dict) -> list[dict]:
    chain = _LEVEL_CHAIN[level]
    # contendenti (top-count) dei comuni contesi
    contested_comuni: dict[int, list[int]] = defaultdict(list)
    for r in conn.execute(
        """SELECT s.territory_osm_id t, s.user_id u FROM standings s
           JOIN territory_ownership o ON o.territory_osm_id = s.territory_osm_id
           WHERE o.is_contested = 1 AND s.deposit_count = o.top_count ORDER BY s.user_id"""
    ):
        contested_comuni[r["t"]].append(r["u"])
    # raggruppa i comuni per rappresentante a questo livello
    members: dict[int, list] = defaultdict(list)
    for c in conn.execute(
        """SELECT t.osm_id, t.province_osm_id, t.region_osm_id, t.country_osm_id,
                  o.owner_user_id owner FROM territories t
           LEFT JOIN territory_ownership o ON o.territory_osm_id = t.osm_id
           WHERE t.geometry_geojson IS NOT NULL"""
    ):
        rep = next((c[col] for col in chain if c[col] is not None), None) or c["osm_id"]
        members[rep].append(c)

    out = []
    for rep, ms in members.items():
        geo = _unit_geo(conn, rep)
        if geo is None:
            continue
        owned = Counter(m["owner"] for m in ms if m["owner"] is not None)
        owner_id, top, contested = owner_of(dict(owned))
        contenders = None
        if not owned:            # nessun comune posseduto → conteso
            contested = True
            people = sorted({u for m in ms for u in contested_comuni.get(m["osm_id"], [])})
            contenders = [_pub(users.get(u)) for u in people] or None
        elif contested:          # pareggio tra chi possiede più comuni
            contenders = [_pub(users.get(u)) for u, n in sorted(owned.items()) if n == top]
        owner = users.get(owner_id) if owner_id else None
        out.append(_feature(rep, geo["name"], level, geo, owner_id, owner, contested, top, contenders))
    return out


def dumps_geo(conn: sqlite3.Connection) -> list[dict]:
    """Singoli depositi (GATED: solo utenti loggati)."""
    users = _names(conn)
    out = []
    for r in conn.execute(
        """SELECT id, user_id, ts, lat, lon, altitude, photo_ref, territory_osm_id
           FROM deposits ORDER BY ts"""
    ):
        u = users.get(r["user_id"])
        out.append({
            "id": r["id"], "user_name": _pub(u) or "?",
            "color": u["color"] if u else "#888",
            "ts": r["ts"], "lat": r["lat"], "lon": r["lon"],
            "altitude": r["altitude"],
            "has_photo": r["photo_ref"] is not None,  # False → placeholder coniglio
        })
    return out


def leaderboard(conn: sqlite3.Connection) -> dict:
    main = main_leaderboard(conn)
    meta = {r["id"]: r for r in conn.execute("SELECT id, color, flag_ref FROM users")}
    for row in main:
        u = meta.get(row["user_id"])
        row["color"] = u["color"] if u else None
        row["flag"] = f"/media/flag/{row['user_id']}" if u and u["flag_ref"] else None
    return {"main": main, "records": records(conn)}


def feed(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Cronologia dei flip con attaccante e attaccato. Scorre tutti i flip in
    ordine per ricostruire l'ultimo owner reale (chi viene spodestato), poi
    ritorna i più recenti. Frasi costruite lato client (i18n)."""
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, COALESCE(public_name, display_name) AS name FROM users")}
    rows = conn.execute(
        """SELECT f.ts, f.territory_osm_id AS t, f.prev_owner_user_id AS p,
                  f.new_owner_user_id AS nw, d.user_id AS by_user, tt.name AS tn
           FROM flips f
           JOIN territories tt ON tt.osm_id = f.territory_osm_id
           LEFT JOIN deposits d ON d.id = f.deposit_id
           ORDER BY f.ts, f.id"""
    ).fetchall()

    last_real: dict[int, int] = {}   # territorio → ultimo owner reale
    items = []
    for r in rows:
        t, nw = r["t"], r["nw"]
        if nw is None:
            # pareggio: attaccante = autore del deposito, difensore = chi possedeva
            items.append({"ts": r["ts"], "kind": "contested", "territory": r["tn"],
                          "by": names.get(r["by_user"]), "defender": names.get(r["p"])})
        else:
            displaced = last_real.get(t)
            if displaced == nw:
                displaced = None            # riconquista dopo pareggio, non un furto
            kind = "steal" if displaced else "conquer"
            items.append({"ts": r["ts"], "kind": kind, "territory": r["tn"],
                          "actor": names.get(nw), "displaced": names.get(displaced) if displaced else None})
            last_real[t] = nw

    items.reverse()   # più recenti prima
    return items[:limit]


def weekly_recap(conn: sqlite3.Connection) -> dict:
    """Riepilogo della settimana corrente (da lunedì 00:00). `dumpers`: chi ha
    cagato, con quante volte, in ordine. `slackers`: chi è attivo di recente
    (≥1 deposito negli ultimi 30 giorni) ma questa settimana ha fatto zero."""
    now = datetime.now()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    active_since = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

    week = {r["u"]: r["n"] for r in conn.execute(
        "SELECT user_id u, COUNT(*) n FROM deposits WHERE ts>=? GROUP BY user_id", (week_start,))}
    active = conn.execute(
        """SELECT u.id, COALESCE(u.public_name, u.display_name) name FROM users u
           WHERE EXISTS (SELECT 1 FROM deposits d WHERE d.user_id=u.id AND d.ts>=?)
           ORDER BY name""", (active_since,)).fetchall()

    dumpers = sorted(((r["name"], week.get(r["id"], 0)) for r in active if week.get(r["id"], 0) > 0),
                     key=lambda x: -x[1])
    slackers = [r["name"] for r in active if week.get(r["id"], 0) == 0]
    return {"dumpers": dumpers, "slackers": slackers}


def record_holders(conn: sqlite3.Connection) -> dict[str, int | None]:
    """Detentore corrente di ogni record superlativo (per rilevare i sorpassi)."""
    return {k: (v["user_id"] if v else None) for k, v in records(conn).items()}


def award_events(conn: sqlite3.Connection) -> set:
    """Insieme degli award (code, user, ts, context) — per il diff dei badge nuovi."""
    return {(r["code"], r["user_id"], r["ts_earned"], r["context"])
            for r in conn.execute(
                """SELECT a.code, w.user_id, w.ts_earned, w.context
                   FROM awards w JOIN achievements a ON a.id = w.achievement_id""")}


def contested_contenders(conn: sqlite3.Connection) -> dict[int, tuple]:
    """Per ogni COMUNE conteso, gli id (ordinati) di tutti i giocatori in parità
    in testa. Serve al bot per annunciare i pareggi anche a 3+ (e rilevarne la
    crescita nel tempo)."""
    out: dict[int, list] = defaultdict(list)
    for r in conn.execute(
        """SELECT s.territory_osm_id t, s.user_id u FROM standings s
           JOIN territory_ownership o ON o.territory_osm_id = s.territory_osm_id
           WHERE o.is_contested = 1 AND s.deposit_count = o.top_count ORDER BY s.user_id"""
    ):
        out[r["t"]].append(r["u"])
    return {k: tuple(v) for k, v in out.items()}


def feed_line_for_deposit(conn: sqlite3.Connection, deposit_id: int) -> dict | None:
    """Evento del feed causato da un deposito (per l'annuncio del bot), o None."""
    f = conn.execute(
        """SELECT f.territory_osm_id t, f.id, f.ts, f.prev_owner_user_id p,
                  f.new_owner_user_id nw, d.user_id by_user, tt.name tn
           FROM flips f JOIN territories tt ON tt.osm_id = f.territory_osm_id
           LEFT JOIN deposits d ON d.id = f.deposit_id
           WHERE f.deposit_id = ? LIMIT 1""", (deposit_id,)).fetchone()
    if f is None:
        return None
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, COALESCE(public_name, display_name) AS name FROM users")}
    if f["nw"] is None:  # pareggio subìto
        return {"kind": "contested", "territory": f["tn"],
                "by": names.get(f["by_user"]), "defender": names.get(f["p"])}
    # displaced = ultimo owner reale prima di questo flip
    disp = conn.execute(
        """SELECT new_owner_user_id nw FROM flips
           WHERE territory_osm_id=? AND (ts<? OR (ts=? AND id<?)) AND new_owner_user_id IS NOT NULL
           ORDER BY ts DESC, id DESC LIMIT 1""",
        (f["t"], f["ts"], f["ts"], f["id"])).fetchone()
    displaced = disp["nw"] if disp else None
    if displaced == f["nw"]:
        displaced = None
    return {"kind": "steal" if displaced else "conquer", "territory": f["tn"],
            "actor": names.get(f["nw"]), "displaced": names.get(displaced) if displaced else None}


def my_stats(conn: sqlite3.Connection, uid: int, t: dict | None = None) -> dict | None:
    """Statistiche personali per la pagina profilo."""
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if u is None:
        return None
    prof = profile(conn, uid, t)  # comuni, km2, territories, badges (code + descr tradotta)

    lb = main_leaderboard(conn)
    rank = next((i + 1 for i, r in enumerate(lb) if r["user_id"] == uid), None)

    c = conn.execute(
        """SELECT COUNT(*) tot, COUNT(DISTINCT d.territory_osm_id) comuni,
                  COUNT(DISTINCT t.country) nazioni, COUNT(DISTINCT t.region_osm_id) regioni,
                  MIN(d.ts) first, MAX(d.ts) last
           FROM deposits d LEFT JOIN territories t ON t.osm_id = d.territory_osm_id
           WHERE d.user_id=?""", (uid,)
    ).fetchone()

    recs = records(conn)
    # chiavi dei record detenuti (tradotte nel template)
    held = [key for key in _RECORD_LABELS
            if recs.get(key) and recs[key]["user_id"] == uid]

    return {
        "id": uid, "name": _pub(u), "username": u["display_name"],
        "public_name": u["public_name"], "color": u["color"],
        "has_flag": bool(u["flag_ref"]),
        "rank": rank, "players": len(lb),
        "comuni": prof["comuni"], "km2": prof["km2"],
        "deposits": c["tot"], "comuni_visitati": c["comuni"],
        "nazioni": c["nazioni"], "regioni": c["regioni"],
        "streak": _streaks(conn).get(uid, 0),
        "primo": c["first"], "ultimo": c["last"],
        "badges": prof["badges"], "records": held,
        "activity": monthly_activity(conn, uid),
        "weight_kg": round(c["tot"] * AVG_DUMP_G / 1000.0, 1),
        "no_selfie": bool(u["no_selfie"]),
        "telegram_id": u["telegram_id"],
        "telegram_linked": bool(u["telegram_user_id"]),
        "selfie_count": conn.execute(
            "SELECT COUNT(*) FROM deposits WHERE user_id=? AND photo_ref IS NOT NULL",
            (uid,)).fetchone()[0],
    }


def delete_user_selfies(conn: sqlite3.Connection, uid: int, media_dir) -> int:
    """Rimuove solo i selfie dell'utente (photo_ref → NULL + file), tenendo
    depositi e conquiste. Non serve recompute (le foto non toccano il gioco)."""
    from pathlib import Path
    media_dir = Path(media_dir)
    refs = [r["photo_ref"] for r in conn.execute(
        "SELECT photo_ref FROM deposits WHERE user_id=? AND photo_ref IS NOT NULL", (uid,))]
    conn.execute("UPDATE deposits SET photo_ref=NULL WHERE user_id=?", (uid,))
    conn.commit()
    for ref in refs:
        p = (media_dir / ref).resolve()
        if str(p).startswith(str(media_dir.resolve())) and p.exists():
            p.unlink()
    return len(refs)


def monthly_activity(conn: sqlite3.Connection, uid: int, months: int = 12) -> list[dict]:
    """Depositi per mese negli ultimi `months` mesi (istogramma). Mesi vuoti = 0."""
    today = date.today()
    seq = []
    y, m = today.year, today.month
    for i in range(months - 1, -1, -1):
        mm, yy = m - i, y
        while mm <= 0:
            mm += 12
            yy -= 1
        seq.append((yy, mm))
    counts = {r["ym"]: r["n"] for r in conn.execute(
        "SELECT strftime('%Y-%m', ts) ym, COUNT(*) n FROM deposits WHERE user_id=? GROUP BY ym",
        (uid,))}
    return [{"ym": f"{yy:04d}-{mm:02d}", "month": mm, "year": yy,
             "count": counts.get(f"{yy:04d}-{mm:02d}", 0)} for yy, mm in seq]


def delete_user(conn: sqlite3.Connection, uid: int, media_dir) -> None:
    """Cancella l'utente e TUTTI i suoi dati (depositi + media), poi rigenera lo
    stato derivato senza di lui. Irreversibile."""
    from pathlib import Path

    from ..pipeline import finalize

    media_dir = Path(media_dir)
    refs = [r["photo_ref"] for r in conn.execute(
        "SELECT photo_ref FROM deposits WHERE user_id=? AND photo_ref IS NOT NULL", (uid,))]
    urow = conn.execute("SELECT avatar_ref, flag_ref FROM users WHERE id=?", (uid,)).fetchone()

    # svuota le tabelle derivate (referenziano depositi/utenti); finalize le
    # ricostruisce. Va fatto prima di cancellare i depositi per non violare i FK.
    for tbl in ("awards", "flips", "aggregate_ownership", "territory_ownership", "standings"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.execute("DELETE FROM deposits WHERE user_id=?", (uid,))
    conn.commit()
    finalize(conn)  # standings/ownership/flips/aggregati/awards senza l'utente
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()

    for ref in refs + [urow["avatar_ref"], urow["flag_ref"]]:
        if not ref:
            continue
        p = (media_dir / ref).resolve()
        if str(p).startswith(str(media_dir.resolve())) and p.exists():
            p.unlink()


def gallery(conn: sqlite3.Connection, user_id: int, limit: int = 1000) -> dict | None:
    """Cacate di un utente in ordine temporale (più recenti prima)."""
    u = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if u is None:
        return None
    dumps = [
        {"id": r["id"], "ts": r["ts"], "has_photo": r["photo_ref"] is not None,
         "comune": r["cname"]}
        for r in conn.execute(
            """SELECT d.id, d.ts, d.photo_ref, t.name AS cname
               FROM deposits d LEFT JOIN territories t ON t.osm_id = d.territory_osm_id
               WHERE d.user_id=? ORDER BY d.ts DESC LIMIT ?""", (user_id, limit))
    ]
    return {"id": u["id"], "name": _pub(u), "color": u["color"], "dumps": dumps}


def list_users(conn: sqlite3.Connection) -> list[dict]:
    """Anagrafica per il pannello admin."""
    return [
        {"id": r["id"], "name": r["display_name"],
         "public": r["public_name"] or r["display_name"], "role": r["role"],
         "has_password": bool(r["password_hash"]),
         "telegram": r["telegram_id"], "tg_linked": bool(r["telegram_user_id"]),
         "provisional": bool(r["provisional"]), "deposits": r["n"]}
        for r in conn.execute(
            """SELECT u.id, u.display_name, u.public_name, u.role, u.password_hash,
                      u.telegram_id, u.telegram_user_id, u.provisional,
                      (SELECT COUNT(*) FROM deposits d WHERE d.user_id=u.id) AS n
               FROM users u ORDER BY n DESC, u.display_name"""
        )
    ]


def merge_users(conn: sqlite3.Connection, src: int, dst: int) -> bool:
    """Fonde l'utente `src` in `dst`: sposta i depositi, porta l'identità Telegram
    su `dst`, rigenera lo stato e cancella `src`. Per unire un provvisorio del bot
    nell'account reale. Ritorna False se non applicabile."""
    from ..pipeline import finalize
    if src == dst:
        return False
    s = conn.execute("SELECT telegram_user_id, telegram_id FROM users WHERE id=?", (src,)).fetchone()
    d = conn.execute("SELECT telegram_user_id FROM users WHERE id=?", (dst,)).fetchone()
    if s is None or d is None:
        return False

    conn.execute("UPDATE deposits SET user_id=? WHERE user_id=?", (dst, src))
    # rilascia l'id Telegram su src (è UNIQUE) e portalo su dst se dst non ne ha
    conn.execute("UPDATE users SET telegram_user_id=NULL WHERE id=?", (src,))
    if s["telegram_user_id"] is not None and d["telegram_user_id"] is None:
        conn.execute("UPDATE users SET telegram_user_id=? WHERE id=?", (s["telegram_user_id"], dst))
    if s["telegram_id"]:  # preferisci l'@username del provvisorio all'eventuale numero
        conn.execute("UPDATE users SET telegram_id=? WHERE id=?", (s["telegram_id"], dst))
    conn.execute("DELETE FROM tg_link_tokens WHERE user_id=?", (src,))
    if s["telegram_user_id"] is not None:
        conn.execute("DELETE FROM tg_pending_photo WHERE telegram_user_id=?", (s["telegram_user_id"],))
    # derivate → finalize ricostruisce senza src
    for tbl in ("awards", "flips", "aggregate_ownership", "territory_ownership", "standings"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.execute("DELETE FROM users WHERE id=?", (src,))
    conn.commit()
    finalize(conn)
    return True


def achievements(conn: sqlite3.Connection, t: dict | None = None) -> list[dict]:
    """Legenda dei badge: nome, descrizione, icona + quanti li hanno presi.
    Se `t` (tabella traduzioni) è dato, nome/descrizione sono tradotti per codice."""
    out = []
    for r in conn.execute(
        """SELECT a.code, a.name, a.description, a.icon_ref, a.type,
                  COUNT(DISTINCT w.user_id) AS holders
           FROM achievements a
           LEFT JOIN awards w ON w.achievement_id = a.id
           WHERE a.active = 1 AND a.secret = 0
           GROUP BY a.id ORDER BY a.name"""
    ):
        name, desc = r["name"], r["description"]
        if t:
            name = t.get(f"ach_{r['code']}", name)
            desc = t.get(f"ach_{r['code']}_d", desc)
        out.append({"code": r["code"], "name": name, "description": desc,
                    "icon": r["icon_ref"], "type": r["type"], "holders": r["holders"]})
    return out


def territory_detail(conn: sqlite3.Connection, osm_id: int) -> dict:
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, COALESCE(public_name, display_name) AS name FROM users")}
    t = conn.execute("SELECT * FROM territories WHERE osm_id=?", (osm_id,)).fetchone()
    standings = [
        {"user": names.get(r["user_id"], "?"), "count": r["deposit_count"]}
        for r in conn.execute(
            "SELECT user_id, deposit_count FROM standings WHERE territory_osm_id=? ORDER BY deposit_count DESC",
            (osm_id,),
        )
    ]
    history = [
        {"ts": r["ts"],
         "prev": names.get(r["prev_owner_user_id"]) if r["prev_owner_user_id"] else None,
         "new": names.get(r["new_owner_user_id"]) if r["new_owner_user_id"] else None}
        for r in conn.execute(
            "SELECT * FROM flips WHERE territory_osm_id=? ORDER BY ts, id", (osm_id,)
        )
    ]
    return {
        "name": t["name"] if t else str(osm_id),
        "country": t["country"] if t else None,
        "area_km2": t["area_km2"] if t else None,
        "standings": standings, "history": history,
    }


def profile(conn: sqlite3.Connection, user_id: int, t: dict | None = None) -> dict | None:
    u = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if u is None:
        return None
    owned = conn.execute(
        """SELECT t.name AS name, t.country AS country, t.area_km2 AS area
           FROM territory_ownership o JOIN territories t ON t.osm_id=o.territory_osm_id
           WHERE o.owner_user_id=? ORDER BY t.name""", (user_id,)
    ).fetchall()
    # nome/descrizione tradotti per codice (il modale "come si prende" riusa il testo)
    badges = conn.execute(
        """SELECT a.code AS code, a.name AS name, a.description AS descr,
                  a.icon_ref AS icon, COUNT(*) AS c
           FROM awards w JOIN achievements a ON a.id=w.achievement_id
           WHERE w.user_id=? GROUP BY a.id ORDER BY a.name""", (user_id,)
    ).fetchall()
    return {
        "id": u["id"], "name": _pub(u), "color": u["color"],
        "comuni": len(owned),
        "km2": round(sum(o["area"] or 0 for o in owned), 1),
        "territories": [{"name": o["name"], "country": o["country"]} for o in owned],
        "badges": [{
            "code": b["code"], "icon": b["icon"], "count": b["c"],
            "name": (t.get(f"ach_{b['code']}", b["name"]) if t else b["name"]),
            "description": (t.get(f"ach_{b['code']}_d", b["descr"]) if t else b["descr"]),
        } for b in badges],
    }


def badge_holders(conn: sqlite3.Connection, code: str) -> list[dict]:
    """Utenti che hanno un badge (nome pubblico + quante volte), per il modale
    'chi l'ha preso' della legenda. Pubblico come la classifica."""
    return [
        {"name": r["name"], "count": r["c"]}
        for r in conn.execute(
            """SELECT COALESCE(u.public_name, u.display_name) AS name, COUNT(*) AS c
               FROM awards w JOIN achievements a ON a.id = w.achievement_id
               JOIN users u ON u.id = w.user_id
               WHERE a.code = ? GROUP BY u.id ORDER BY c DESC, name""", (code,))
    ]
