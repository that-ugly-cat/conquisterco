"""Motore achievement: registry flessibile + regole + evaluator.

Ogni achievement è una funzione `fn(ctx) -> list[Award]` registrata con
`@achievement(...)`. La riga in tabella `achievements` porta i soli metadati di
visualizzazione (sincronizzati da qui). Aggiungere un badge = aggiungere una
funzione + un decoratore. L'evaluator rilancia tutte le regole su TUTTO lo
storico a ogni giro: gli award sono derivati e ricostruibili.

I badge `secret=True` sono comunque assegnati e mostrati sul profilo di chi li
prende, ma la legenda del modale li nasconde (colonna `secret` in `achievements`).
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from . import config, geonames
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
    secret: bool
    manual: bool   # assegnato a mano dal Sistema (via manual_awards), non derivato
    fn: Callable[["EvalContext"], list[Award]]


REGISTRY: dict[str, AchievementDef] = {}


def achievement(code: str, name: str, description: str, *,
                type: str = "repeatable", icon: str | None = None,
                secret: bool = False, manual: bool = False):
    def deco(fn: Callable[["EvalContext"], list[Award]]):
        if code in REGISTRY:
            raise ValueError(f"achievement duplicato: {code}")
        REGISTRY[code] = AchievementDef(code, name, description, type, icon, secret, manual, fn)
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
        # nazione RAW (nome nativo, per display) e CODE canonico (per la logica)
        self.territory_country_raw = {
            t: meta.get("country") for t, meta in self.territory.items()
        }
        self.territory_country = {
            t: geonames.country_code(meta.get("country"))
            for t, meta in self.territory.items()
        }
        # osm_id dei luoghi speciali (per i badge-luogo basati su flip)
        self.place_osm: dict[str, set[int]] = defaultdict(set)
        for osm, meta in self.territory.items():
            for key in ("rijeka", "roma", "avignon"):
                if geonames.place_is(meta.get("name"), key):
                    self.place_osm[key].add(osm)

        self.deposits = [
            {
                "id": r["id"], "user_id": r["user_id"], "ts": r["ts"],
                "dt": parse_ts(r["ts"]), "lat": r["lat"], "lon": r["lon"],
                "altitude": r["altitude"], "territory": r["territory_osm_id"],
                "name": (self.territory.get(r["territory_osm_id"]) or {}).get("name"),
                "country": self.territory_country_raw.get(r["territory_osm_id"]),
                "ccode": self.territory_country.get(r["territory_osm_id"]),
                "region": (self.territory.get(r["territory_osm_id"]) or {}).get("region"),
                "photo": r["photo_ref"] is not None,
            }
            for r in conn.execute(
                """SELECT id, user_id, ts, lat, lon, altitude, territory_osm_id, photo_ref
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
                "dt": parse_ts(r["ts"]), "deposit_id": r["deposit_id"],
                "prev_owner": r["prev_owner_user_id"],
                "new_owner": r["new_owner_user_id"],
            }
            for r in conn.execute(
                "SELECT * FROM flips ORDER BY ts, id"
            )
        ]

        # un solo replay condiviso, con la Polonia tracciata per codice
        self.replay = replay_flips(
            self.flips, self.territory_country, track_countries=("PL",),
        )

        # assegnazioni manuali del "Sistema" (persistenti, non derivate dai dump)
        self.manual_awards = [
            {"user_id": r["user_id"], "code": r["code"], "ts": r["ts"], "context": r["context"]}
            for r in conn.execute("SELECT user_id, code, ts, context FROM manual_awards")
        ]

    def tname(self, osm_id: int) -> str:
        meta = self.territory.get(osm_id)
        return meta["name"] if meta else str(osm_id)

    def last_flip_ts_for(self, uid: int) -> str:
        """Ultimo ts in cui l'utente ha conquistato qualcosa (fallback: ultimo
        deposito). Serve a datare i badge di possesso simultaneo, che il replay
        non aggancia a un istante puntuale."""
        ts = None
        for f in self.flips:
            if f["new_owner"] == uid:
                ts = f["ts"]
        if ts:
            return ts
        deps = self.deposits_by_user.get(uid, [])
        return deps[-1]["ts"] if deps else "1970-01-01 00:00:00"


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


def _distinct_dates(deps: list[dict]) -> list[date]:
    return sorted({d["dt"].date() for d in deps})


def _streak_reach(dates: list[date], k: int) -> date | None:
    """Prima data in cui una serie di giorni consecutivi raggiunge k. None se mai."""
    if k <= 1:
        return dates[0] if dates else None
    run = 1
    for i in range(1, len(dates)):
        run = run + 1 if (dates[i] - dates[i - 1]).days == 1 else 1
        if run >= k:
            return dates[i]
    return None


def _seq(deps: list[dict], from_codes: set[str] | None, to_code: str, *,
         same_day: bool = False, days: int | None = None) -> list[str]:
    """ts di ogni deposito in `to_code` preceduto nel tempo da uno in
    `from_codes` (None = qualunque altro paese), sotto il vincolo temporale:
    `same_day` = stesso giorno di calendario; `days` = entro N giorni; entrambi
    None = in qualunque momento precedente."""
    out = []
    for i, b in enumerate(deps):
        if b["ccode"] != to_code:
            continue
        for a in deps[:i]:
            ca = a["ccode"]
            if ca is None:
                continue
            if from_codes is not None and ca not in from_codes:
                continue
            if from_codes is None and ca == to_code:
                continue
            if same_day:
                if a["dt"].date() == b["dt"].date():
                    out.append(b["ts"]); break
            elif days is not None:
                if timedelta() < (b["dt"] - a["dt"]) <= timedelta(days=days):
                    out.append(b["ts"]); break
            else:
                out.append(b["ts"]); break
    return out


# ---------------------------------------------------------------------------
# Regole storiche
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
            if d["ccode"]:
                nations.add(d["ccode"])
            if len(nations) >= config.PASSAPORTO_NATIONS:
                out.append(Award("passaporto", uid, d["ts"], f"{len(nations)} nazioni"))
                break
    return out


@achievement("grand_tour", "Grand Tour", "Un deposito in ognuna delle 20 regioni italiane.", type="one_shot")
def _grand_tour(ctx: EvalContext) -> list[Award]:
    out = []
    target = len(geonames.ITALIAN_REGIONS)
    for uid, deps in ctx.deposits_by_user.items():
        regions: set[str] = set()
        for d in deps:
            if d["ccode"] == "IT":
                reg = geonames.italian_region(d["region"])
                if reg:
                    regions.add(reg)
            if len(regions) >= target:
                out.append(Award("grand_tour", uid, d["ts"], "20/20 regioni"))
                break
    return out


@achievement("waterloo", "Waterloo", "Depositi in almeno 3 comuni francesi distinti.", type="one_shot")
def _waterloo(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        fr: set[int] = set()
        for d in deps:
            if d["ccode"] == "FR":
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
    n = config.POLONIA_COMUNI
    pl_max = ctx.replay.max_owned_by_country.get("PL", {})
    pl_first = ctx.replay.first_by_country.get("PL", {})
    out = []
    for uid, mx in pl_max.items():
        if mx >= n:
            ts = _first_reach(pl_first, uid, n) or ctx.last_flip_ts_for(uid)
            out.append(Award("spartizione_polonia", uid, ts, f"≥{n} comuni PL"))
    return out


# ---------------------------------------------------------------------------
# Ora del giorno / calendario (dedup per giorno o per anno, per non intasare)
# ---------------------------------------------------------------------------

@achievement("turno_notte", "Turno di Notte", "Cacata registrata tra mezzanotte e le 5.", icon="🌙")
def _turno_notte(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        seen: set[date] = set()
        for d in deps:
            if d["dt"].hour < config.NIGHT_END_H and d["dt"].date() not in seen:
                seen.add(d["dt"].date())
                out.append(Award("turno_notte", uid, d["ts"], ctx.tname(d["territory"])))
    return out


@achievement("alba_regno", "L'Alba del Nuovo Regno", "Cacata tra le 5 e le 7 del mattino.", icon="🌅")
def _alba_regno(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        seen: set[date] = set()
        for d in deps:
            if config.DAWN_START_H <= d["dt"].hour < config.DAWN_END_H and d["dt"].date() not in seen:
                seen.add(d["dt"].date())
                out.append(Award("alba_regno", uid, d["ts"], ctx.tname(d["territory"])))
    return out


@achievement("natale_fecale", "Natale Fecale", "Cacata il 25 dicembre.", icon="🎄")
def _natale(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        seen: set[int] = set()
        for d in deps:
            if d["dt"].month == 12 and d["dt"].day == 25 and d["dt"].year not in seen:
                seen.add(d["dt"].year)
                out.append(Award("natale_fecale", uid, d["ts"], str(d["dt"].year)))
    return out


@achievement("anno_bisesto", "Anno Bisesto, Cesso Onesto", "Cacca il 29 febbraio.", icon="🗓️")
def _bisesto(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        seen: set[int] = set()
        for d in deps:
            if d["dt"].month == 2 and d["dt"].day == 29 and d["dt"].year not in seen:
                seen.add(d["dt"].year)
                out.append(Award("anno_bisesto", uid, d["ts"], str(d["dt"].year)))
    return out


@achievement("capodanno", "Capodanno Col Botto", "La prima cacata dell'anno di tutto il gruppo.", icon="🎆")
def _capodanno(ctx: EvalContext) -> list[Award]:
    # superlativo di gruppo: UN solo detentore per anno = chi ha cagato per primo.
    first: dict[int, dict] = {}
    for d in ctx.deposits:  # ordinati per ts asc → il primo di ogni anno
        first.setdefault(d["dt"].year, d)
    return [Award("capodanno", d["user_id"], d["ts"], str(y)) for y, d in first.items()]


@achievement("ultima_chiamata", "Ultima Chiamata", "L'ultima cacata dell'anno di tutto il gruppo.", icon="⏳")
def _ultima_chiamata(ctx: EvalContext) -> list[Award]:
    # superlativo di gruppo, SOLO anni conclusi (nell'anno in corso "l'ultima
    # finora" cambierebbe a ogni dump). UN detentore per anno.
    this_year = date.today().year
    last: dict[int, dict] = {}
    for d in ctx.deposits:  # ordinati asc → resta l'ultimo di ogni anno
        if d["dt"].year < this_year:
            last[d["dt"].year] = d
    return [Award("ultima_chiamata", d["user_id"], d["ts"], str(y)) for y, d in last.items()]


# ---------------------------------------------------------------------------
# Streak / assiduità
# ---------------------------------------------------------------------------

@achievement("orologio", "Regolare come un Orologio",
             f"Almeno una cacata al giorno per {config.OROLOGIO_STREAK} giorni.",
             type="one_shot", icon="⏰")
def _orologio(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        d = _streak_reach(_distinct_dates(deps), config.OROLOGIO_STREAK)
        if d:
            out.append(Award("orologio", uid, f"{d} 00:00:00", f"{config.OROLOGIO_STREAK} giorni di fila"))
    return out


@achievement("metronomo", "Metronomo Intestinale",
             f"Streak di {config.METRONOMO_STREAK} giorni consecutivi.",
             type="one_shot", icon="🥁")
def _metronomo(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        d = _streak_reach(_distinct_dates(deps), config.METRONOMO_STREAK)
        if d:
            out.append(Award("metronomo", uid, f"{d} 00:00:00", f"{config.METRONOMO_STREAK} giorni di fila"))
    return out


@achievement("pilastro", "Pilastro",
             f"Registra una cacata per {config.PILASTRO_DAYS} giorni complessivi.",
             type="one_shot", icon="🏛️")
def _pilastro(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        dates = _distinct_dates(deps)
        if len(dates) >= config.PILASTRO_DAYS:
            d = dates[config.PILASTRO_DAYS - 1]
            out.append(Award("pilastro", uid, f"{d} 00:00:00", f"{config.PILASTRO_DAYS} giorni totali"))
    return out


# ---------------------------------------------------------------------------
# Selfie caricati
# ---------------------------------------------------------------------------

def _selfie_award(ctx: EvalContext, code: str, n: int) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        photos = [d for d in deps if d["photo"]]
        if len(photos) >= n:
            out.append(Award(code, uid, photos[n - 1]["ts"], f"{n} selfie"))
    return out


@achievement("gallerista", "Gallerista", f"{config.GALLERISTA_SELFIE} selfie caricati.",
             type="one_shot", icon="🖼️")
def _gallerista(ctx: EvalContext) -> list[Award]:
    return _selfie_award(ctx, "gallerista", config.GALLERISTA_SELFIE)


@achievement("archivista", "Archivista", f"{config.ARCHIVISTA_SELFIE} selfie caricati.",
             type="one_shot", icon="🗄️")
def _archivista(ctx: EvalContext) -> list[Award]:
    return _selfie_award(ctx, "archivista", config.ARCHIVISTA_SELFIE)


@achievement("museo_orrori", "Museo degli Orrori", f"{config.MUSEO_SELFIE} selfie caricati.",
             type="one_shot", icon="🏛️")
def _museo(ctx: EvalContext) -> list[Award]:
    return _selfie_award(ctx, "museo_orrori", config.MUSEO_SELFIE)


# ---------------------------------------------------------------------------
# Luoghi (nome comune, primo deposito) + coordinate
# ---------------------------------------------------------------------------

def _first_where(ctx: EvalContext, code: str, pred) -> list[Award]:
    """Un award one-shot al primo deposito di ogni utente che soddisfa `pred(d)`."""
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        for d in deps:
            if pred(d):
                out.append(Award(code, uid, d["ts"], d["name"] or ctx.tname(d["territory"])))
                break
    return out


@achievement("checkpoint_charlie", "Checkpoint Charlie", "Cacca a Berlino.", type="one_shot", icon="🧱")
def _checkpoint(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "checkpoint_charlie",
                        lambda d: geonames.place_is(d["name"], "berlin") and d["ccode"] == "DE")


@achievement("uranus", "Uranus", "Cacca a Uranus, Missouri.", type="one_shot", icon="🪐")
def _uranus(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "uranus",
                        lambda d: geonames.place_is(d["name"], "uranus") and d["ccode"] == "US")


@achievement("middelfart", "Middelfart", "Cacca a Middelfart, Danimarca. Incredibile e computabilissima.",
             type="one_shot", icon="💨")
def _middelfart(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "middelfart",
                        lambda d: geonames.place_is(d["name"], "middelfart") and d["ccode"] == "DK")


@achievement("cavaliere_oscuro", "Cavaliere Oscuro", "Cacca a Batman, Turchia.", type="one_shot", icon="🦇")
def _batman(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "cavaliere_oscuro",
                        lambda d: geonames.place_is(d["name"], "batman") and d["ccode"] == "TR")


@achievement("hell_and_back", "Hell and Back", "Cacca in un posto chiamato Hell.", type="one_shot", icon="😈")
def _hell(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "hell_and_back", lambda d: geonames.place_is(d["name"], "hell"))


@achievement("meta_cacca", "Meta-Cacca",
             "Cacca in un luogo il cui nome contiene poo/loo/shit/toilet/bath/merda/cacca/cesso.",
             icon="🚽")
def _meta_cacca(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        seen: set[int] = set()
        for d in deps:
            if geonames.name_contains_scat(d["name"]) and d["territory"] not in seen:
                seen.add(d["territory"])
                out.append(Award("meta_cacca", uid, d["ts"], d["name"]))
    return out


@achievement("d_day", "D-Day", "Prima cacca in Normandia.", type="one_shot", icon="🪂")
def _d_day(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "d_day",
                        lambda d: d["ccode"] == "FR" and d["region"] and "normand" in d["region"].casefold())


@achievement("ultima_thule", "Ultima Thule", "Cacca sopra il Circolo Polare Artico.", type="one_shot", icon="🧊")
def _ultima_thule(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "ultima_thule", lambda d: d["lat"] >= geonames.ARCTIC_CIRCLE_LAT)


@achievement("titicacca", "Titicacca", "Cacca vicino al lago Titicaca.", type="one_shot", icon="🏞️")
def _titicacca(ctx: EvalContext) -> list[Award]:
    return _first_where(
        ctx, "titicacca",
        lambda d: haversine_km(d["lat"], d["lon"], geonames.TITICACA_LAT, geonames.TITICACA_LON)
        <= config.TITICACA_RADIUS_KM)


@achievement("precisino", "Precisin*", "Cacca all'incrocio fra un meridiano e un parallelo interi.", icon="🎯")
def _precisino(ctx: EvalContext) -> list[Award]:
    tol = config.PRECISINO_TOL_DEG
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        seen: set[tuple[int, int]] = set()
        for d in deps:
            if abs(d["lat"] - round(d["lat"])) <= tol and abs(d["lon"] - round(d["lon"])) <= tol:
                key = (round(d["lat"]), round(d["lon"]))
                if key not in seen:
                    seen.add(key)
                    out.append(Award("precisino", uid, d["ts"], f"{key[0]}°, {key[1]}°"))
    return out


# ---------------------------------------------------------------------------
# Sequenze internazionali
# ---------------------------------------------------------------------------

def _seq_by_day(deps: list[dict], from_codes: set[str], to_code: str) -> list[str]:
    """Come `_seq(same_day=True)` ma con un solo award per giorno."""
    by_day: dict[date, str] = {}
    for ts in _seq(deps, from_codes, to_code, same_day=True):
        by_day[parse_ts(ts).date()] = ts
    return list(by_day.values())


@achievement("anschluss", "Anschluss", "Una cacca in Germania e poi una in Austria lo stesso giorno.", icon="🇦🇹")
def _anschluss(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        for ts in _seq_by_day(deps, {"DE"}, "AT"):
            out.append(Award("anschluss", uid, ts, "DE → AT"))
    return out


def _first_reach(m: dict[int, dict[int, str]], uid: int, threshold: int) -> str | None:
    """Primo ts in cui l'utente ha raggiunto un conteggio >= soglia (ts STABILE:
    non si sposta all'arrivo di dump successivi). None se mai raggiunta."""
    reached = [ts for c, ts in m.get(uid, {}).items() if c >= threshold]
    return min(reached) if reached else None


@achievement("colonialista_anale", "Colonialista Anale",
             f"Sei owner-aggregato di almeno {config.COLONIALISTA_STATES} stati insieme.",
             type="one_shot", icon="🗺️")
def _colonialista(ctx: EvalContext) -> list[Award]:
    n = config.COLONIALISTA_STATES
    return [
        Award("colonialista_anale", uid,
              _first_reach(ctx.replay.first_states, uid, n) or ctx.last_flip_ts_for(uid),
              f"≥{n} stati")
        for uid, mx in ctx.replay.max_states.items() if mx >= n
    ]


@achievement("imperialista_anale", "Imperialista Anale",
             f"Sei owner-aggregato di almeno {config.IMPERIALISTA_STATES} stati insieme.",
             type="one_shot", icon="👑")
def _imperialista(ctx: EvalContext) -> list[Award]:
    n = config.IMPERIALISTA_STATES
    return [
        Award("imperialista_anale", uid,
              _first_reach(ctx.replay.first_states, uid, n) or ctx.last_flip_ts_for(uid),
              f"≥{n} stati")
        for uid, mx in ctx.replay.max_states.items() if mx >= n
    ]


@achievement("granduca_colon", "Granduca del Colon",
             f"Possiedi almeno {config.GRANDUCA_COMUNI} comuni in contemporanea.",
             type="one_shot", icon="🎖️")
def _granduca(ctx: EvalContext) -> list[Award]:
    n = config.GRANDUCA_COMUNI
    return [
        Award("granduca_colon", uid,
              _first_reach(ctx.replay.first_owned, uid, n) or ctx.last_flip_ts_for(uid),
              f"≥{n} comuni")
        for uid, mx in ctx.replay.max_owned.items() if mx >= n
    ]


# ---------------------------------------------------------------------------
# Flip nel tempo
# ---------------------------------------------------------------------------

@achievement("vendicatore_fiume", "Vendicatore di Fiume", "Conquisti Rijeka (Fiume).",
             type="one_shot", icon="🇮🇹")
def _vendicatore(ctx: EvalContext) -> list[Award]:
    rijeka = ctx.place_osm.get("rijeka", set())
    out = []
    seen: set[int] = set()
    for f in ctx.flips:
        if f["territory"] in rijeka and f["new_owner"] is not None and f["new_owner"] not in seen:
            seen.add(f["new_owner"])
            out.append(Award("vendicatore_fiume", f["new_owner"], f["ts"], "Rijeka"))
    return out


@achievement("campagna_elettorale", "Campagna Elettorale",
             f"Almeno {config.CAMPAGNA_COUNT} cacate nello stesso comune in una settimana, "
             "che lo strappano a un altro giocatore.")
def _campagna(ctx: EvalContext) -> list[Award]:
    win = timedelta(days=config.CAMPAGNA_WINDOW_DAYS)
    out = []
    for c in ctx.replay.conquests:   # conquiste = furti a un altro giocatore
        ts = parse_ts(c.ts)
        cnt = sum(
            1 for d in ctx.deposits_by_user.get(c.new_owner, [])
            if d["territory"] == c.territory and timedelta() <= ts - d["dt"] <= win
        )
        if cnt >= config.CAMPAGNA_COUNT:
            out.append(Award("campagna_elettorale", c.new_owner, c.ts, ctx.tname(c.territory)))
    return out


@achievement("vendetta_fredda", "Vendetta Fredda",
             f"Riconquisti un comune perso da almeno {config.VENDETTA_DAYS} giorni.", icon="🧊")
def _vendetta(ctx: EvalContext) -> list[Award]:
    lost: dict[tuple[int, int], object] = {}   # (comune, utente) -> dt della perdita
    out = []
    for f in ctx.flips:
        t, prev, nw = f["territory"], f["prev_owner"], f["new_owner"]
        if prev is not None and nw != prev:
            lost[(t, prev)] = f["dt"]
        if nw is not None and (t, nw) in lost:
            if (f["dt"] - lost[(t, nw)]).days >= config.VENDETTA_DAYS:
                out.append(Award("vendetta_fredda", nw, f["ts"], ctx.tname(t)))
            del lost[(t, nw)]
    return out


@achievement("avignone", "Avignone", "Conquisti Roma, perdi Roma, conquisti Avignone.",
             type="one_shot", icon="⛪")
def _avignone(ctx: EvalContext) -> list[Award]:
    roma = ctx.place_osm.get("roma", set())
    avig = ctx.place_osm.get("avignon", set())
    state: dict[int, int] = {}   # 0 niente · 1 ha avuto Roma · 2 ha perso Roma · 3 fatto
    out = []
    for f in ctx.flips:
        t, prev, nw = f["territory"], f["prev_owner"], f["new_owner"]
        if t in roma:
            if nw is not None:
                state[nw] = max(state.get(nw, 0), 1)
            if prev is not None and state.get(prev, 0) >= 1 and nw != prev:
                state[prev] = 2
        if t in avig and nw is not None and state.get(nw, 0) == 2:
            state[nw] = 3
            out.append(Award("avignone", nw, f["ts"], "Roma → Avignone"))
    return out


# ---------------------------------------------------------------------------
# Badge MANUALI (assegnati dal "Sistema" via tabella manual_awards, non derivati)
# ---------------------------------------------------------------------------

@achievement("gatto_sul_cesso", "Gatto sul Cesso",
             "Solo per gatti molto speciali. Lo assegna il Sistema.",
             type="one_shot", icon="🐱", manual=True)
def _gatto_sul_cesso(ctx: EvalContext) -> list[Award]:
    return [Award("gatto_sul_cesso", m["user_id"], m["ts"], m["context"])
            for m in ctx.manual_awards if m["code"] == "gatto_sul_cesso"]


# ---------------------------------------------------------------------------
# Badge SEGRETI (assegnati e mostrati sul profilo, nascosti dalla legenda)
# ---------------------------------------------------------------------------

@achievement("pellegrino", "Il Pellegrino", "Cacca in Vaticano.", type="one_shot", secret=True, icon="⛪")
def _pellegrino(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "pellegrino", lambda d: d["ccode"] == "VA")


@achievement("serenissima", "Serenissima Deposizione", "Prima cacca a Venezia.",
             type="one_shot", secret=True, icon="🦁")
def _serenissima(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "serenissima",
                        lambda d: geonames.place_is(d["name"], "venezia") and d["ccode"] == "IT")


@achievement("danzica_libera", "Danzica Libera", "Prima cacca a Gdańsk.",
             type="one_shot", secret=True, icon="⚓")
def _danzica(ctx: EvalContext) -> list[Award]:
    return _first_where(ctx, "danzica_libera",
                        lambda d: geonames.place_is(d["name"], "gdansk") and d["ccode"] == "PL")


@achievement("neutralita_armata", "Neutralità Armata",
             "Cacca in Svizzera dopo aver cacato in Italia, Germania, Francia o Austria.",
             type="one_shot", secret=True, icon="🏔️")
def _neutralita(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        seq = _seq(deps, {"IT", "DE", "FR", "AT"}, "CH")
        if seq:
            out.append(Award("neutralita_armata", uid, seq[0], "→ CH"))
    return out


@achievement("sudetenland", "Sudetenland", "Cacca in Germania e poi in Repubblica Ceca lo stesso giorno.",
             secret=True, icon="🏞️")
def _sudetenland(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        for ts in _seq_by_day(deps, {"DE"}, "CZ"):
            out.append(Award("sudetenland", uid, ts, "DE → CZ"))
    return out


@achievement("barbarossa", "Operazione Barbarossa",
             f"Cacca in Germania e poi in Russia in massimo {config.TRIP_WINDOW_DAYS} giorni.",
             type="one_shot", secret=True, icon="❄️")
def _barbarossa(ctx: EvalContext) -> list[Award]:
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        seq = _seq(deps, {"DE"}, "RU", days=config.TRIP_WINDOW_DAYS)
        if seq:
            out.append(Award("barbarossa", uid, seq[0], "DE → RU"))
    return out


@achievement("fuck_brexit", "Fuck Brexit",
             f"Cacca in Europa, poi nel Regno Unito, poi in Europa, in massimo {config.TRIP_WINDOW_DAYS} giorni.",
             type="one_shot", secret=True, icon="🇪🇺")
def _fuck_brexit(ctx: EvalContext) -> list[Award]:
    win = timedelta(days=config.TRIP_WINDOW_DAYS)
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        done = False
        for g in (d for d in deps if d["ccode"] == "GB"):
            before = [a for a in deps if a["ccode"] in geonames.EU and a["dt"] < g["dt"]]
            after = [c for c in deps if c["ccode"] in geonames.EU and c["dt"] > g["dt"]]
            for a in before:
                for c in after:
                    if (c["dt"] - a["dt"]) <= win:
                        out.append(Award("fuck_brexit", uid, c["ts"], "EU → UK → EU"))
                        done = True
                        break
                if done:
                    break
            if done:
                break
    return out


@achievement("cortina_igienica", "La Cortina di Carta Igienica",
             f"Cacca in un ex paese occidentale e in un ex paese orientale entro {config.TRIP_WINDOW_DAYS} giorni.",
             type="one_shot", secret=True, icon="🧻")
def _cortina(ctx: EvalContext) -> list[Award]:
    win = timedelta(days=config.TRIP_WINDOW_DAYS)
    out = []
    for uid, deps in ctx.deposits_by_user.items():
        done = False
        for i, a in enumerate(deps):
            if done:
                break
            for b in deps[i + 1:]:
                if (b["dt"] - a["dt"]) > win:
                    break
                ca, cb = a["ccode"], b["ccode"]
                if ((ca in geonames.COLD_WAR_WEST and cb in geonames.COLD_WAR_EAST)
                        or (ca in geonames.COLD_WAR_EAST and cb in geonames.COLD_WAR_WEST)):
                    out.append(Award("cortina_igienica", uid, b["ts"], "Ovest ↔ Est"))
                    done = True
                    break
    return out


@achievement("incontro_teano", "Incontro di Te-ano",
             "Due giocatori cacano lo stesso giorno nello stesso comune, che diventa conteso.",
             secret=True, icon="🤝")
def _teano(ctx: EvalContext) -> list[Award]:
    day_users: dict[tuple[int, date], set[int]] = defaultdict(set)
    for d in ctx.deposits:
        day_users[(d["territory"], d["dt"].date())].add(d["user_id"])
    out = []
    seen: set[tuple[int, int, date]] = set()
    for f in ctx.flips:
        if f["new_owner"] is not None:      # ci interessa il passaggio a CONTESO
            continue
        day = f["dt"].date()
        users = day_users.get((f["territory"], day), set())
        if len(users) >= 2:
            for u in users:
                key = (u, f["territory"], day)
                if key not in seen:
                    seen.add(key)
                    out.append(Award("incontro_teano", u, f["ts"], ctx.tname(f["territory"])))
    return out


# ---------------------------------------------------------------------------
# Sync metadati + evaluate
# ---------------------------------------------------------------------------

def sync_achievements(conn: sqlite3.Connection) -> None:
    """Allinea la tabella `achievements` col registry (upsert per code)."""
    for d in REGISTRY.values():
        conn.execute(
            """INSERT INTO achievements (code, name, description, type, icon_ref, secret, manual, active)
               VALUES (?,?,?,?,?,?,?,1)
               ON CONFLICT(code) DO UPDATE SET
                 name=excluded.name, description=excluded.description,
                 type=excluded.type, icon_ref=excluded.icon_ref,
                 secret=excluded.secret, manual=excluded.manual""",
            (d.code, d.name, d.description, d.type, d.icon, int(d.secret), int(d.manual)),
        )
    conn.commit()


def evaluate(conn: sqlite3.Connection) -> list[Award]:
    """Lancia tutte le regole e ritorna gli award (non li persiste)."""
    ctx = EvalContext(conn)
    awards: list[Award] = []
    for d in REGISTRY.values():
        awards.extend(d.fn(ctx))
    return awards
