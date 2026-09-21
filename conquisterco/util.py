"""Piccole utility condivise."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TS_FMT = "%Y-%m-%d %H:%M:%S"

# --- L'orologio del cacasto ------------------------------------------------
# Tutti i timestamp in tabella sono **ora locale italiana, senza fuso scritto**:
# lo erano gia' i 599 depositi importati da WhatsApp, che portano l'ora com'era
# scritta in chat, e un badge che dice "fra mezzanotte e le 5" parla dell'ora
# dell'orologio in bagno, non di un istante assoluto.
#
# Il fuso sta scritto **qui e non nell'ambiente**, di proposito. Con la sola
# `TZ` del container il significato di un dato gia' salvato dipenderebbe da una
# variabile che si puo' perdere a un redeploy, e il 21 set 2026 si e' visto cosa
# costa: il bot girava senza `TZ`, salvava l'ora UTC, e in due mesi e mezzo ha
# prodotto 172 cacate fra le 4 e le 6 del mattino contro le 2 degli otto anni
# precedenti. Erano le 6-8, e intanto 133 "Alba del Nuovo Regno" su 135 sono
# andate a gente che cagava alle 7 passate.
ROME = ZoneInfo("Europe/Rome")


def now_local() -> datetime:
    """Adesso in Italia, naive: stesso formato di quello che c'e' in tabella.
    Da usare al posto di `datetime.now()`, che segue il fuso del processo, e al
    posto del `datetime('now')` di SQLite, che invece e' sempre UTC."""
    return datetime.now(ROME).replace(tzinfo=None)


def ts_now() -> str:
    """`now_local()` gia' formattato, per le INSERT."""
    return fmt_ts(now_local())


def local_from_epoch(epoch: float) -> datetime:
    """Un istante assoluto (i secondi Unix di un messaggio Telegram) letto come
    ora italiana. Naive in uscita, come tutto il resto."""
    return datetime.fromtimestamp(epoch, timezone.utc).astimezone(ROME).replace(tzinfo=None)

VIDEO_EXT = {"mp4", "mov", "webm", "mkv", "avi", "3gp", "m4v", "ogv"}


def is_video(ref: str | None) -> bool:
    """Un selfie e' un video? Si guarda l'estensione del file salvato."""
    return bool(ref) and "." in ref and ref.rsplit(".", 1)[-1].lower() in VIDEO_EXT


def parse_ts(s: str) -> datetime:
    """Parsa un timestamp ISO-ish. Tollerante al separatore 'T'."""
    return datetime.fromisoformat(s)


def fmt_ts(dt: datetime) -> str:
    return dt.strftime(TS_FMT)


def anonymize_name(full: str) -> str:
    """'Giovanni Spitale' -> 'Giovanni_S'. Nome intero + iniziale del cognome
    (ultimo token). Un solo token resta com'è."""
    parts = full.strip().split()
    if not parts:
        return full
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]}_{parts[-1][0].upper()}"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in km tra due coordinate (formula dell'emisenoverso)."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
