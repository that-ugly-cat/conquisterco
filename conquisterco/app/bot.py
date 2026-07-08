"""Bot Telegram (Fase 5): riceve pin + selfie dal gruppo e crea i dump.

Webhook nell'app FastAPI. Regole:
  - un PIN è un dump (foto opzionale); la foto si aggancia al pin più vicino
    entro una finestra, anche se arriva PRIMA del pin (buffer);
  - il mittente si riconosce per id numerico Telegram, poi per @username (che
    viene catturato come id la prima volta); se sconosciuto → account
    PROVVISORIO reclamabile via deep-link;
  - i dump si accettano solo dal chat del gruppo (allowlist);
  - si rispetta il flag `no_selfie`.

Client Telegram e geocoder sono iniettabili → la logica è testabile senza rete.
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime

from ..enrich_osm import enrich_deposits_osm
from ..ingest import add_deposit
from ..pipeline import finalize
from ..util import parse_ts

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
ALLOWED_CHAT = os.environ.get("TELEGRAM_CHAT_ID")          # id del gruppo (str)
BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "conquisterco_bot")
PUBLIC_URL = os.environ.get("CONQUISTERCO_PUBLIC_URL", "")
PAIR_WINDOW_S = 300


# ---------------------------------------------------------------------------
# Client Telegram
# ---------------------------------------------------------------------------

def _default_fetch(url: str, data: bytes | None = None) -> bytes:
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


class TelegramClient:
    def __init__(self, token: str = "", fetch=None):
        self.token = token or BOT_TOKEN
        self._fetch = fetch or _default_fetch

    def _api(self, method: str, params: dict) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode()
        try:
            return json.loads(self._fetch(url, data))
        except Exception:
            return {}

    def send_message(self, chat_id, text: str) -> None:
        self._api("sendMessage", {"chat_id": chat_id, "text": text})

    def file_path(self, file_id: str) -> str | None:
        return (self._api("getFile", {"file_id": file_id}).get("result") or {}).get("file_path")

    def download(self, file_path: str) -> bytes:
        return self._fetch(f"https://api.telegram.org/file/bot{self.token}/{file_path}")

    def set_webhook(self, url: str) -> dict:
        return self._api("setWebhook", {"url": url})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg_ts(msg: dict) -> str:
    return datetime.fromtimestamp(msg.get("date", 0)).strftime("%Y-%m-%d %H:%M:%S")


def _within(a: str, b: str) -> bool:
    return abs((parse_ts(a) - parse_ts(b)).total_seconds()) <= PAIR_WINDOW_S


def _no_selfie(conn, uid: int) -> bool:
    r = conn.execute("SELECT no_selfie FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r["no_selfie"])


def _unique_display(conn, base: str) -> str:
    base = (base or "tg").strip().replace(" ", "_")[:24] or "tg"
    name, i = base, 1
    while conn.execute("SELECT 1 FROM users WHERE display_name=?", (name,)).fetchone():
        i += 1
        name = f"{base}_{i}"
    return name


def resolve_sender(conn, frm: dict) -> int:
    """id utente per il mittente Telegram; crea un provvisorio se sconosciuto."""
    fid = frm.get("id")
    uname = (frm.get("username") or "").strip()
    r = conn.execute("SELECT id FROM users WHERE telegram_user_id=?", (fid,)).fetchone()
    if r:
        return r["id"]
    if uname:
        r = conn.execute("SELECT id FROM users WHERE lower(telegram_id)=lower(?)", (uname,)).fetchone()
        if r:  # match per username → cattura l'id numerico per il futuro
            conn.execute("UPDATE users SET telegram_user_id=? WHERE id=?", (fid, r["id"]))
            return r["id"]
    display = _unique_display(conn, uname or frm.get("first_name") or f"tg{fid}")
    cur = conn.execute(
        """INSERT INTO users (display_name, public_name, telegram_user_id, telegram_id, provisional, role)
           VALUES (?,?,?,?,1,'user')""",
        (display, frm.get("first_name") or display, fid, uname or None),
    )
    return cur.lastrowid


def _save_photo(client: TelegramClient, file_id: str, media_dir) -> str | None:
    from pathlib import Path
    fp = client.file_path(file_id)
    if not fp:
        return None
    ext = fp.rsplit(".", 1)[-1] if "." in fp else "jpg"
    rel = f"telegram/{file_id}.{ext}"
    dest = Path(media_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(client.download(fp))
    return rel


def _comune_of(conn, deposit_id: int) -> str | None:
    r = conn.execute(
        """SELECT t.name FROM deposits d JOIN territories t ON t.osm_id=d.territory_osm_id
           WHERE d.id=?""", (deposit_id,)).fetchone()
    return r["name"] if r else None


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def _handle_start(conn, frm: dict, token: str, client, chat) -> None:
    row = conn.execute("SELECT user_id FROM tg_link_tokens WHERE token=?", (token,)).fetchone() if token else None
    if not row:
        client.send_message(chat.get("id"), "Link non valido o scaduto. Riprova dal tuo profilo.")
        return
    uid = row["user_id"]
    conn.execute("DELETE FROM tg_link_tokens WHERE token=?", (token,))
    fid = frm.get("id")

    # eventuale account provvisorio con lo stesso id → fondi i suoi dump
    prov = conn.execute(
        "SELECT id FROM users WHERE telegram_user_id=? AND id<>?", (fid, uid)).fetchone()
    if prov:
        conn.execute("UPDATE deposits SET user_id=? WHERE user_id=?", (uid, prov["id"]))
        conn.execute("UPDATE users SET telegram_user_id=NULL WHERE id=?", (prov["id"],))
        # svuota le derivate (referenziano l'utente); finalize le ricostruisce
        for tbl in ("awards", "flips", "aggregate_ownership", "territory_ownership", "standings"):
            conn.execute(f"DELETE FROM {tbl}")
        conn.execute("DELETE FROM users WHERE id=? AND provisional=1", (prov["id"],))

    conn.execute("UPDATE users SET telegram_user_id=?, telegram_id=COALESCE(?, telegram_id) WHERE id=?",
                 (fid, frm.get("username"), uid))
    conn.commit()
    finalize(conn)  # i dump fusi cambiano proprietario
    client.send_message(chat.get("id"), "Collegato ✓  I tuoi dump Telegram ora vanno sul tuo account.")


def _handle_location(conn, msg: dict, client, resolver, media_dir) -> None:
    frm, loc = msg["from"], msg["location"]
    uid = resolve_sender(conn, frm)
    ts = _msg_ts(msg)
    did = add_deposit(conn, user_id=uid, ts=ts, lat=loc["latitude"], lon=loc["longitude"],
                      source="telegram", raw_ref=f"tg:{msg.get('message_id')}")
    if did is None:  # duplicato
        return

    # foto arrivata prima del pin?
    buf = conn.execute("SELECT file_id, ts FROM tg_pending_photo WHERE telegram_user_id=?",
                       (frm.get("id"),)).fetchone()
    if buf and _within(buf["ts"], ts) and not _no_selfie(conn, uid):
        ref = _save_photo(client, buf["file_id"], media_dir)
        if ref:
            conn.execute("UPDATE deposits SET photo_ref=? WHERE id=?", (ref, did))
    conn.execute("DELETE FROM tg_pending_photo WHERE telegram_user_id=?", (frm.get("id"),))
    conn.commit()

    enrich_deposits_osm(conn, resolver)
    finalize(conn)
    client.send_message(msg["chat"]["id"], f"💩 registrato: {_comune_of(conn, did) or '??'}")


def _handle_photo(conn, msg: dict, client, media_dir) -> None:
    frm = msg["from"]
    uid = resolve_sender(conn, frm)
    if _no_selfie(conn, uid):
        return
    file_id = msg["photo"][-1]["file_id"]   # risoluzione massima
    ts = _msg_ts(msg)
    dep = conn.execute(
        """SELECT id, ts FROM deposits WHERE user_id=? AND source='telegram' AND photo_ref IS NULL
           ORDER BY ts DESC LIMIT 1""", (uid,)).fetchone()
    if dep and _within(dep["ts"], ts):
        ref = _save_photo(client, file_id, media_dir)
        if ref:
            conn.execute("UPDATE deposits SET photo_ref=? WHERE id=?", (ref, dep["id"]))
            conn.commit()
    else:  # nessun pin recente: tieni in sospeso
        conn.execute("INSERT OR REPLACE INTO tg_pending_photo (telegram_user_id, file_id, ts) VALUES (?,?,?)",
                     (frm.get("id"), file_id, ts))
        conn.commit()


def process_update(conn: sqlite3.Connection, update: dict, *, client, resolver, media_dir) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg or "from" not in msg:
        return
    text = msg.get("text", "") or ""

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        _handle_start(conn, msg["from"], parts[1].strip() if len(parts) > 1 else "", client, msg.get("chat", {}))
        return

    # dump: solo dal gruppo autorizzato
    if ALLOWED_CHAT and str(msg.get("chat", {}).get("id")) != str(ALLOWED_CHAT):
        return
    if "location" in msg:
        _handle_location(conn, msg, client, resolver, media_dir)
    elif "photo" in msg:
        _handle_photo(conn, msg, client, media_dir)
