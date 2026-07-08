"""Motore achievement: registry flessibile + regole + evaluator.

Ogni achievement è una funzione `fn(ctx) -> list[Award]` registrata con
`@achievement(...)`. La riga in tabella `achievements` porta i soli metadati di
visualizzazione (sincronizzati da qui). Aggiungere un badge = aggiungere una
funzione + un decoratore. L'evaluator rilancia tutte le regole su TUTTO lo
storico a ogni giro: gli award sono derivati e ricostruibili.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from . import config
from .models import Award
from .ownership import replay_flips
from .util import haversine_km, parse_ts

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AchievementDef:
    code: str
    name: str
    description: str
    type: str  # 'one_shot' | 'repeatable'
    icon: str | None
    fn: Callable[["EvalContext"], list[Award]]


REGISTRY: dict[str, AchievementDef] = {}


def achievement(code: str, name: str, description: str, *,
                type: str = "repeatable", icon: str | None = None):
    def deco(fn: Callable[["EvalContext"], list[Award]]):
        if code in REGISTRY:
            raise ValueError(f"achievement duplicato: {code}")
        REGISTRY[code] = AchievementDef(code, name, description, type, icon, fn)
        return fn
    return deco


# ---------------------------------------------------------------------------
# Contesto di valutazione (caricato una volta dal DB)
# ---------------------------------------------------------------------------

class EvalContext:
    def __init__(self, conn: sqlite3.Connection):
        self.territory: dict[int, dict] = {
            r["osm_id"]: dict(r)
            for r in conn.execute("SELECT * FROM territories")
        }
        self.territory_country = {
            t: meta.get("country") for t, meta in self.territory.items()
        }

        self.deposits = [
            {
                "id": r["id"], "user_id": r["user_id"], "ts": r["ts"],
                "dt": parse_ts(r["ts"]), "lat": r["lat"], "lon": r["lon"],
                "altitude": r["altitude"], "territory": r["territory_osm_id"],
                "country": self.territory_country.get(r["territory_osm_id"]),
                "region": (self.territory.get(r["territory_osm_id"]) or {}).get("region"),
            }
            for r in conn.execute(
                """SELECT id, user_id, ts, lat, lon, altitude, territory_osm_id
                   FROM deposits WHERE territory_osm_id IS NOT NULL
                   ORDER BY ts, id"""
            )
        ]
        self.deposits_by_user: dict[int, list[dict]] = {}
        for d in self.deposits:
            self.deposits_by_user.setdefault(d["user_id"], []).append(d)

        self.flips = [
            {
                "territory": r["territory_osm_id"], "ts": r["ts"],
                "deposit_id": r["deposit_id"],
                "prev_owner": r["prev_owner_user_id"],
                "new_owner": r["new_owner_user_id"],
            }
            for r in conn.execute(
                "SELECT * FROM flips ORDER BY ts, id"
            )
        ]

        # un solo replay condiviso, con la Polonia tracciata
        self.replay = replay_flips(
            self.flips, self.territory_country, track_countries=("Poland",),
        )

    def tname(self, osm_id: int) -> str:
        meta = self.territory.get(osm_id)
        return meta["name"] if meta else str(osm_id)


def _sliding_distinct(deps: list[dict], k: int, window: timedelta):
    """Emette (ts, n_territori) ogni volta che una finestra scorrevole raggiunge
    per la prima volta k comuni distinti; poi riparte oltre il punto scatenante."""
    out = []
    n = len(deps)
    start = 0
    j = 0
    while j < n:
        while deps[start]["dt"] < deps[j]["dt"] - window:
            start += 1
        distinct = {deps[t]["territory"] for t in range(start, j + 1)}
        if len(distinct) >= k:
            out.append((deps[j]["ts"], len(distinct)))
            start = j + 1
        j += 1
    return out


# ---------------------------------------------------------------------------
# Regole
# ---------------------------------------------------------------------------

@achievement("blitz", "Blitz", "3 comuni distinti in 24 ore.")
def _blitz(ctx: EvalContext) -> list[Award]:
    out = []
    win = timedelta(hours=config.BLITZ_WINDOW_H)
    for uid, deps in ctx.deposits_by_user.items():
        for ts, n in _sliding_distinct(deps, config.BLITZ_COUNT, win):
            out.append(Award("blitz", uid, ts, f"{n} comuni in {config.BLITZ_WINDOW_H}h"))
    return out


@achievement("pendolare", "Pendolare", "5 comuni distinti in una settimana.")
def _pendolare(ctx: EvalContext) -> list[Award]:
    out = []
    win = timedelta(days=config.PENDOLARE_WINDOW_DAYS)
    for uid, deps in ctx.deposits_by_user.items():
        for ts, n in _sliding_distinct(deps, config.PENDOLARE_COUNT, win):
            out.append(Award("pendolare", uid, ts, f"{n} comuni in {config.PENDOLARE_WINDOW_DAYS}g"))
    return out


@achievement("colonizzatore", "Colonizzatore", "Primo del gruppo in assoluto in un comune.")
def _colonizzatore(ctx: EvalContext) -> list[Award]:
    out = []
    seen: set[int] = set()
    for d in ctx.deposits:  # già ordinati per ts
        if d["territory"] not in seen:
            seen.add(d["territory"])
            out.append(Award("colonizzatore", d["user_id"], d["ts"], ctx.tname(d["territory"])))
    return out


@achievement("passaporto", "Passaporto", "Depositi in almeno 5 nazioni.", type="one_shot")
def _passaporto(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        nations: set[str] = set()
        for d in deps:
            if d["country"]:
                nations.add(d["country"])
            if len(nations) >= config.PASSAPORTO_NATIONS:
                out.append(Award("passaporto", uid, d["ts"], f"{len(nations)} nazioni"))
                break
    return out


@achievement("grand_tour", "Grand Tour", "Un deposito in ognuna delle 20 regioni italiane.", type="one_shot")
def _grand_tour(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        regions: set[str] = set()
        for d in deps:
            if d["country"] == "Italy" and d["region"] in config.ITALIAN_REGIONS:
                regions.add(d["region"])
            if len(regions) >= len(config.ITALIAN_REGIONS):
                out.append(Award("grand_tour", uid, d["ts"], "20/20 regioni"))
                break
    return out


@achievement("waterloo", "Waterloo", "Depositi in almeno 3 comuni francesi distinti.", type="one_shot")
def _waterloo(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        fr: set[int] = set()
        for d in deps:
            if d["country"] == "France":
                fr.add(d["territory"])
            if len(fr) >= config.WATERLOO_COMUNI:
                out.append(Award("waterloo", uid, d["ts"], f"{len(fr)} comuni FR"))
                break
    return out


@achievement("scalatore", "Scalatore", f"Deposito sopra i {int(config.SCALATORE_M)} m.")
def _scalatore(ctx: EvalContext) -> list[Award]:
    return [
        Award("scalatore", d["user_id"], d["ts"], f"{ctx.tname(d['territory'])} {d['altitude']:.0f} m")
        for d in ctx.deposits
        if d["altitude"] is not None and d["altitude"] > config.SCALATORE_M
    ]


@achievement("batisfera", "Batisfera", "Deposito sotto il livello del mare.")
def _batisfera(ctx: EvalContext) -> list[Award]:
    return [
        Award("batisfera", d["user_id"], d["ts"], f"{ctx.tname(d['territory'])} {d['altitude']:.0f} m")
        for d in ctx.deposits
        if d["altitude"] is not None and d["altitude"] < config.BATISFERA_M
    ]


@achievement("teletrasporto", "Teletrasporto sospetto", "Due depositi troppo lontani nel tempo che hai.", icon="🛸")
def _teletrasporto(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        for a, b in zip(deps, deps[1:]):
            dt_h = (b["dt"] - a["dt"]).total_seconds() / 3600.0
            if dt_h <= 0:
                continue
            km = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            if km / dt_h > config.TELETRASPORTO_KMH:
                out.append(Award("teletrasporto", uid, b["ts"], f"{km/dt_h:.0f} km/h"))
    return out


@achievement("conquistador", "Conquistador", "Rubi un comune a un altro giocatore.")
def _conquistador(ctx: EvalContext) -> list[Award]:
    return [
        Award("conquistador", c.new_owner, c.ts, ctx.tname(c.territory))
        for c in ctx.replay.conquests
    ]


@achievement("regicidio", "Regicidio", "Rubi un comune a chi è in testa alla classifica.")
def _regicidio(ctx: EvalContext) -> list[Award]:
    return [
        Award("regicidio", c.new_owner, c.ts, ctx.tname(c.territory))
        for c in ctx.replay.conquests
        if c.leader_before is not None and c.displaced == c.leader_before
    ]


@achievement("guardiano", "Guardiano", "Riprendi un tuo comune dopo un pareggio subìto.")
def _guardiano(ctx: EvalContext) -> list[Award]:
    return [
        Award("guardiano", g.user, g.ts, ctx.tname(g.territory))
        for g in ctx.replay.guards
    ]


@achievement("spartizione_polonia", "Spartizione della Polonia",
             f"Possiedi {config.POLONIA_COMUNI} comuni polacchi in contemporanea.", icon="🇵🇱")
def _spartizione(ctx: EvalContext) -> list[Award]:
    out = []
    pl = ctx.replay.max_owned_by_country.get("Poland", {})
    for uid, mx in pl.items():
        if mx >= config.POLONIA_COMUNI:
            # ts non ricostruito puntualmente nel replay: usiamo l'ultimo flip PL utile
            out.append(Award("spartizione_polonia", uid, _last_pl_flip_ts(ctx, uid), f"{mx} comuni PL"))
    return out


def _last_pl_flip_ts(ctx: EvalContext, uid: int) -> str:
    ts = None
    for f in ctx.flips:
        if f["new_owner"] == uid and ctx.territory_country.get(f["territory"]) == "Poland":
            ts = f["ts"]
    return ts or (ctx.deposits[-1]["ts"] if ctx.deposits else "1970-01-01 00:00:00")


# ---------------------------------------------------------------------------
# Sync metadati + evaluate
# ---------------------------------------------------------------------------

def sync_achievements(conn: sqlite3.Connection) -> None:
    """Allinea la tabella `achievements` col registry (upsert per code)."""
    for d in REGISTRY.values():
        conn.execute(
            """INSERT INTO achievements (code, name, description, type, icon_ref, active)
               VALUES (?,?,?,?,?,1)
               ON CONFLICT(code) DO UPDATE SET
                 name=excluded.name, description=excluded.description,
                 type=excluded.type, icon_ref=excluded.icon_ref""",
            (d.code, d.name, d.description, d.type, d.icon),
        )
    conn.commit()


def evaluate(conn: sqlite3.Connection) -> list[Award]:
    """Lancia tutte le regole e ritorna gli award (non li persiste)."""
    ctx = EvalContext(conn)
    awards: list[Award] = []
    for d in REGISTRY.values():
        awards.extend(d.fn(ctx))
    return awards
