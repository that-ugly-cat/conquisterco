"""Orchestrazione import: zip WhatsApp -> depositi nel DB (+ copia media).

Regole di Spit:
  - ogni pin è un dump (foto opzionale -> coniglio se manca);
  - mondo unico su più chat; si tengono SOLO gli utenti del gruppo corrente
    (l'anagrafica `allowed`), scartando chi era solo in gruppi vecchi;
  - identità per nome visualizzato (i nomi combaciano tra le chat).
"""

from __future__ import annotations

import shutil
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

from ..ingest import add_deposit, add_user
from ..util import anonymize_name
from .whatsapp import date_range, detect_dumps, parse_chat, roster


def _txt_of(z: zipfile.ZipFile) -> str:
    name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
    return z.read(name).decode("utf-8")


def _copy_media(z: zipfile.ZipFile, name: str, media_dir: Path, stem: str) -> str | None:
    """Copia il file media dallo zip nello store, ritorna il path relativo
    (photo_ref). None se l'export non contiene il file (media omessi)."""
    if name not in z.namelist():
        return None
    rel = f"whatsapp/{stem}/{name}"
    dest = media_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    with z.open(name) as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)
    return rel


def current_roster(zip_path: str | Path) -> set[str]:
    """Anagrafica (mittenti) di una chat."""
    with zipfile.ZipFile(zip_path) as z:
        return set(roster(parse_chat(_txt_of(z))))


def import_zip(conn: sqlite3.Connection, zip_path: str | Path, *,
               media_dir: str | Path, allowed: set[str] | None = None,
               identity: dict[str, str] | None = None,
               window_min: int = 5) -> dict:
    """Importa una chat. `allowed`: se dato, tiene solo quei nomi (canonici)."""
    identity = identity or {}
    media_dir = Path(media_dir)
    stem = Path(zip_path).stem
    stats: Counter = Counter()

    users = {r["display_name"]: r["id"]
             for r in conn.execute("SELECT id, display_name FROM users")}

    with zipfile.ZipFile(zip_path) as z:
        dumps = detect_dumps(parse_chat(_txt_of(z)), window_min)
        for d in dumps:
            stats["dumps"] += 1
            canon = identity.get(d.sender, d.sender)
            if allowed is not None and canon not in allowed:
                stats["skipped_user"] += 1
                continue
            display = anonymize_name(canon)   # 'Giovanni Spitale' → 'Giovanni_S'
            uid = users.get(display)
            if uid is None:
                uid = add_user(conn, display, wa_handle=canon)
                users[display] = uid
            photo_ref = _copy_media(z, d.photo, media_dir, stem) if d.photo else None
            stats["with_photo" if photo_ref else "no_photo"] += 1
            did = add_deposit(
                conn, user_id=uid, ts=d.ts.strftime("%Y-%m-%d %H:%M:%S"),
                lat=d.lat, lon=d.lon, source="whatsapp_import",
                photo_ref=photo_ref, raw_ref=f"{stem}:{d.lineno}",
            )
            stats["imported" if did else "dup"] += 1
    conn.commit()
    return dict(stats)


def import_dir(conn: sqlite3.Connection, hist_dir: str | Path, *,
               media_dir: str | Path, window_min: int = 5) -> dict:
    """Importa tutte le chat in una cartella. Il gruppo 'corrente' (quello che
    finisce più tardi) definisce l'anagrafica `allowed`; degli altri si tengono
    solo gli utenti presenti nel corrente."""
    zips = sorted(Path(hist_dir).glob("*.zip"))
    if not zips:
        raise FileNotFoundError(f"nessuno zip in {hist_dir}")

    # trova il gruppo corrente = fine più recente
    ends = {}
    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            dr = date_range(parse_chat(_txt_of(z)))
        ends[zp] = dr[1] if dr else None
    current = max(zips, key=lambda p: ends[p])
    allowed = current_roster(current)

    total: Counter = Counter()
    per_chat = {}
    for zp in zips:
        s = import_zip(conn, zp, media_dir=media_dir, allowed=allowed, window_min=window_min)
        per_chat[zp.name] = s
        total.update(s)
    return {"current_group": current.name, "allowed_count": len(allowed),
            "per_chat": per_chat, "total": dict(total)}
