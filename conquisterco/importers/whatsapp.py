"""Parsing dell'export WhatsApp + rilevamento evento dump (logica pura).

Formato osservato (export italiano):
    GG/MM/AA, HH:MM - Mittente: corpo
    <righe senza timestamp> = continuazione del messaggio precedente
    foto:  NOMEFILE.jpg (file allegato)
    pin:   posizione: https://maps.google.com/?q=lat,lon

Evento dump (decisione di Spit): ogni PIN è un dump; gli si attacca la foto
dello stesso mittente più vicina nel tempo entro una finestra (default 5 min).
Se non c'è foto, il dump resta valido con selfie mancante (coniglio).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

MSG_START = re.compile(
    r"^(\d{2})/(\d{2})/(\d{2}),\s(\d{1,2}):(\d{2})\s-\s([^:]+?):\s(.*)$"
)
COORDS = re.compile(r"[?&]q=(-?\d+\.\d+),\s*(-?\d+\.\d+)")
MEDIA = re.compile(
    r"([\w.\- ]+?\.(?:jpg|jpeg|png|webp|gif|mp4|opus))\s*\(file allegato\)",
    re.IGNORECASE,
)
LRM = "‎"  # left-to-right mark che WhatsApp infila davanti agli allegati


@dataclass
class Message:
    ts: datetime
    sender: str
    body: str
    lineno: int
    media: str | None = None
    coords: tuple[float, float] | None = None


@dataclass
class DumpEvent:
    ts: datetime
    sender: str
    lat: float
    lon: float
    photo: str | None
    lineno: int


def parse_chat(text: str) -> list[Message]:
    """Testo dell'export -> lista di messaggi (con media/coords estratti)."""
    msgs: list[Message] = []
    cur: Message | None = None
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.replace(LRM, "")
        m = MSG_START.match(line)
        if m:
            dd, mm, yy, hh, mn, sender, body = m.groups()
            ts = datetime(2000 + int(yy), int(mm), int(dd), int(hh), int(mn))
            cur = Message(ts=ts, sender=sender.strip(), body=body, lineno=i)
            msgs.append(cur)
        elif cur is not None:
            cur.body += "\n" + line  # continuazione (es. didascalia foto)
    for msg in msgs:
        cm = MEDIA.search(msg.body)
        if cm:
            msg.media = cm.group(1).strip()
        qm = COORDS.search(msg.body)
        if qm:
            msg.coords = (float(qm.group(1)), float(qm.group(2)))
    return msgs


def detect_dumps(messages: list[Message], window_min: int = 5) -> list[DumpEvent]:
    """Ogni pin è un dump; foto = allegato stesso mittente più vicino entro la
    finestra. Ogni foto è usata al più una volta (la coppia più stretta vince)."""
    window = timedelta(minutes=window_min)
    media_msgs = [m for m in messages if m.media]
    used: set[int] = set()  # id() dei media già abbinati
    pins = [m for m in messages if m.coords]

    # abbina prima le coppie più strette, così una foto non viene "rubata"
    candidates = []
    for p in pins:
        for mm in media_msgs:
            if mm.sender != p.sender:
                continue
            dt = abs((mm.ts - p.ts).total_seconds())
            if dt <= window.total_seconds():
                candidates.append((dt, p, mm))
    candidates.sort(key=lambda c: c[0])

    photo_of: dict[int, str] = {}
    for dt, p, mm in candidates:
        if id(p) in photo_of or id(mm) in used:
            continue
        photo_of[id(p)] = mm.media
        used.add(id(mm))

    dumps = []
    for p in pins:
        lat, lon = p.coords
        dumps.append(DumpEvent(
            ts=p.ts, sender=p.sender, lat=lat, lon=lon,
            photo=photo_of.get(id(p)), lineno=p.lineno,
        ))
    dumps.sort(key=lambda d: d.ts)
    return dumps


def roster(messages: list[Message]) -> dict[str, int]:
    """Mittenti -> numero di messaggi (per costruire l'anagrafica)."""
    out: dict[str, int] = {}
    for m in messages:
        out[m.sender] = out.get(m.sender, 0) + 1
    return out


def date_range(messages: list[Message]) -> tuple[datetime, datetime] | None:
    if not messages:
        return None
    ts = [m.ts for m in messages]
    return (min(ts), max(ts))
