"""Canonicalizzazione geografica per gli achievement.

Il geocoder reale (Nominatim) restituisce nazioni e regioni nel **nome nativo**
(`Italia`, `Deutschland`, `Österreich`, `Schweiz/Suisse/Svizzera/Svizra`…),
mentre il geocoder fittizio dei test usa i nomi **inglesi** (`Italy`, `Germany`).
Le regole-badge non devono conoscere questa varietà: passano da qui.

- `country_code(name)` → codice ISO-2 canonico ('IT','DE',…) da qualunque grafia.
- `italian_region(name)` → regione italiana canonica (match per sottostringa,
  robusto ai nomi bilingui tipo `Trentino-Alto Adige/Südtirol`).
- `place_is(name, key)` / `name_matches(name, keywords)` → match sui nomi comune
  per i badge-luogo (Rijeka, Batman, Hell, Meta-Cacca…).
- Insiemi Guerra Fredda / UE per i badge di sequenza.
"""

from __future__ import annotations

import re

# --- Nazioni: grafie note (inglese + nativo) → codice ISO-2 ------------------
# La chiave di match è casefold; per i nomi-slash (CH) si spezza su '/' e ','.
_COUNTRY_ALIASES: dict[str, set[str]] = {
    "IT": {"italy", "italia"},
    "FR": {"france", "francia"},
    "DE": {"germany", "deutschland", "germania"},
    "AT": {"austria", "österreich", "osterreich"},
    "CH": {"switzerland", "schweiz", "suisse", "svizzera", "svizra", "svizzero"},
    "ES": {"spain", "españa", "espana", "spagna"},
    "HR": {"croatia", "hrvatska", "croazia"},
    "CZ": {"czechia", "czech republic", "česko", "cesko", "repubblica ceca"},
    "SK": {"slovakia", "slovensko", "slovacchia"},
    "PL": {"poland", "polska", "polonia"},
    "RU": {"russia", "российская федерация", "россия", "rossiya"},
    "UA": {"ukraine", "ukraïna", "україна", "ucraina"},
    "GB": {"united kingdom", "uk", "great britain", "england", "scotland",
           "wales", "regno unito"},
    "VA": {"vatican city", "holy see", "città del vaticano", "vaticano",
           "stato della città del vaticano"},
    "US": {"united states", "united states of america", "usa", "stati uniti"},
    "TR": {"türkiye", "turkiye", "turkey", "turchia"},
    "NL": {"netherlands", "nederland", "paesi bassi", "olanda"},
    "BE": {"belgium", "belgië", "belgique", "belgio"},
    "DK": {"denmark", "danmark", "danimarca"},
    "NO": {"norway", "norge", "norvegia"},
    "SE": {"sweden", "sverige", "svezia"},
    "PT": {"portugal", "portogallo"},
    "IE": {"ireland", "éire", "eire", "irlanda"},
    "SI": {"slovenia", "slovenija"},
    "HU": {"hungary", "magyarország", "ungheria"},
    "RO": {"romania", "românia"},
    "GR": {"greece", "ελλάς", "ελλάδα", "grecia"},
}

_ALIAS_TO_CODE: dict[str, str] = {
    a: code for code, aliases in _COUNTRY_ALIASES.items() for a in aliases
}


def country_code(name: str | None) -> str | None:
    """Codice ISO-2 canonico dalla grafia (inglese o nativa). None se ignoto."""
    if not name:
        return None
    n = name.strip().casefold()
    if n in _ALIAS_TO_CODE:
        return _ALIAS_TO_CODE[n]
    # nomi multi-lingua separati da '/' o ',' (es. Schweiz/Suisse/Svizzera/Svizra)
    for part in re.split(r"[/,]", n):
        part = part.strip()
        if part in _ALIAS_TO_CODE:
            return _ALIAS_TO_CODE[part]
    return None


def is_country(name: str | None, code: str) -> bool:
    return country_code(name) == code


# --- Regioni italiane: nome canonico per sottostringa -----------------------
# I nomi reali sono spesso bilingui ("Sardigna/Sardegna", "Valle d'Aosta /
# Vallée d'Aoste"): il match è per sottostringa casefold sul token canonico.
ITALIAN_REGIONS: tuple[str, ...] = (
    "valle d'aosta", "piemonte", "lombardia", "trentino-alto adige", "veneto",
    "friuli-venezia giulia", "liguria", "emilia-romagna", "toscana", "umbria",
    "marche", "lazio", "abruzzo", "molise", "campania", "puglia", "basilicata",
    "calabria", "sicilia", "sardegna",
)


def italian_region(name: str | None) -> str | None:
    """Regione italiana canonica (o None). Robusto ai nomi bilingui."""
    if not name:
        return None
    n = name.casefold()
    for canon in ITALIAN_REGIONS:
        if canon in n:
            return canon
    return None


# --- Luoghi speciali: alias sui nomi comune ---------------------------------
# Match ESATTO (casefold) su una delle grafie. Serve ai badge-luogo dove il
# nome del comune è la chiave (Rijeka/Fiume, Danzica/Gdańsk, …).
_PLACE_ALIASES: dict[str, set[str]] = {
    "rijeka": {"rijeka", "fiume"},
    "berlin": {"berlin", "berlino"},
    "venezia": {"venezia", "venice", "venedig", "venise"},
    "gdansk": {"gdańsk", "gdansk", "danzig", "danzica"},
    "roma": {"roma", "rome", "rom"},
    "avignon": {"avignon", "avignone"},
    "uranus": {"uranus"},
    "batman": {"batman"},
    "middelfart": {"middelfart"},
    "hell": {"hell"},
}


def place_is(name: str | None, key: str) -> bool:
    """True se il nome comune corrisponde (esatto, casefold) a uno degli alias
    del luogo `key`."""
    if not name:
        return False
    return name.strip().casefold() in _PLACE_ALIASES.get(key, {key})


# Meta-Cacca: nomi che contengono una di queste sottostringhe (scatologiche).
META_KEYWORDS: tuple[str, ...] = (
    "poo", "loo", "shit", "toilet", "bath", "merda", "cacca", "cesso",
)


def name_contains_scat(name: str | None) -> bool:
    if not name:
        return False
    n = name.casefold()
    return any(k in n for k in META_KEYWORDS)


# --- Insiemi per i badge di sequenza ----------------------------------------
# UE (stati membri, per Fuck Brexit / La Cortina). Approssimazione ragionevole.
EU: frozenset[str] = frozenset({
    "IT", "FR", "DE", "AT", "ES", "HR", "CZ", "SK", "PL", "NL", "BE", "DK",
    "SE", "PT", "IE", "SI", "HU", "RO", "GR",
})

# Guerra Fredda: partizione stilizzata ex-Ovest / ex-Est (Cortina di ferro).
# Non è storiografia: è il gancio narrativo del badge "Cortina di carta igienica".
COLD_WAR_WEST: frozenset[str] = frozenset({
    "IT", "FR", "DE", "ES", "PT", "GB", "IE", "NL", "BE", "DK", "NO", "GR", "TR",
})
COLD_WAR_EAST: frozenset[str] = frozenset({
    "PL", "CZ", "SK", "HU", "RO", "RU", "UA", "HR", "SI",
})

# --- Coordinate di riferimento ----------------------------------------------
ARCTIC_CIRCLE_LAT = 66.5           # Ultima Thule: oltre il Circolo Polare Artico
TITICACA_LAT, TITICACA_LON = -15.75, -69.35   # centro lago Titicaca
