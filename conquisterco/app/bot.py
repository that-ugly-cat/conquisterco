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
import random
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime

from ..elevation import enrich_altitude
from ..enrich_osm import enrich_deposits_osm
from ..ingest import add_deposit
from ..pipeline import finalize
from ..util import parse_ts
from . import data
from .translations import TRANSLATIONS

# indirezione per iniettare l'enrich altitudine nei test (evita chiamate di rete)
_elevate = enrich_altitude

ONBOARDING = (
    "👋 Conquisterco — il gioco del cacasto.\n"
    "Gli account li crea l'admin. Quando ne hai uno: sul sito → Profilo → "
    "«Collega Telegram» per agganciarti.\n"
    "Poi gioca: manda un PIN (posizione) nel gruppo e un selfie entro 2 minuti. "
    "Ogni pin è una conquista! Comandi: /help\n\n"
    "🇬🇧 Conquisterco — the fecal-cadastre game.\n"
    "Accounts are created by the admin. Once you have one: on the site → Profile "
    "→ «Link Telegram».\n"
    "Then play: send a PIN (location) in the group and a selfie within 2 minutes. "
    "Every pin is a conquest! Commands: /help"
)

HELP = (
    "📍 Come si gioca:\n"
    "1) Manda la tua posizione (PIN) nel gruppo.\n"
    "2) Manda un selfie entro 2 minuti (anche prima del pin).\n"
    "Chi caga di più in un comune lo possiede; si ruba superando l'owner.\n"
    "Account e password li gestisce l'admin; il Telegram lo colleghi dal Profilo.\n\n"
    "🇬🇧 How to play:\n"
    "1) Send your location (PIN) in the group.\n"
    "2) Send a selfie within 2 minutes (or before the pin).\n"
    "Whoever dumps most in a town owns it; steal it by beating the owner.\n"
    "Accounts & passwords are managed by the admin; link Telegram from your Profile."
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
ALLOWED_CHAT = os.environ.get("TELEGRAM_CHAT_ID")          # id del gruppo (str)
BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "conquisterco_bot")
PUBLIC_URL = os.environ.get("CONQUISTERCO_PUBLIC_URL", "")
PAIR_WINDOW_S = 120   # finestra di accoppiamento pin↔foto (2 minuti)


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


# Conferme del dump, voce "System" (à la Dungeon Crawler Carl): sardonica,
# teatrale, mock-corporate. Pescate a caso, bilingui. {c} = comune.
_CONFIRMS = [
    ("🏴 {c} è caduta. Il tuo intestino non fa prigionieri.",
     "🏴 {c} has fallen. Your bowels take no prisoners."),
    ("🗂️ Pratica evasa a {c}. Timbrata, protocollata, puzzolente.",
     "🗂️ Paperwork cleared in {c}. Stamped, filed, fragrant."),
    ("📺 Deposito a {c} offerto da: la tua dieta discutibile.",
     "📺 Deposit in {c} brought to you by: your questionable diet."),
    ("🕯️ Qualcosa è stato lasciato a {c}. Non tornerà a prenderlo nessuno.",
     "🕯️ Something was left in {c}. No one is coming back for it."),
    ("🎉 Complimenti! Hai reso {c} leggermente peggiore.",
     "🎉 Congratulations! You've made {c} slightly worse."),
    ("👀 Il pubblico trattiene il fiato... e per ottime ragioni. Registrato a {c}.",
     "👀 The audience holds its breath... for excellent reasons. Logged in {c}."),
    ("🔬 Campione biologico depositato a {c}. Rigore metodologico impeccabile.",
     "🔬 Biological sample deposited in {c}. Impeccable methodology."),
    ("🚩 Vessillo (fecale) issato su {c}. Che i posteri giudichino.",
     "🚩 A (fecal) banner raised over {c}. Let posterity judge."),
    ("😐 Registrato: {c}. Sì. È successo davvero. Andiamo avanti.",
     "😐 Logged: {c}. Yes. It really happened. Let's move on."),
    ("📜 Le leggende parleranno di ciò che hai fatto a {c}. Sottovoce.",
     "📜 Legends will speak of what you did in {c}. In hushed tones."),
]

_CONFIRM_UNKNOWN = (
    "🌀 Deposito registrato... da qualche parte. Nemmeno la mappa sa dove hai osato.",
    "🌀 Deposit logged... somewhere. Even the map doesn't know where you dared.")


def _confirm_message(comune: str | None) -> str:
    it, en = _CONFIRM_UNKNOWN if not comune else random.choice(_CONFIRMS)
    return f"🇮🇹 {it.format(c=comune)}\n🇬🇧 {en.format(c=comune)}"


def _bi(variants: list, **kw) -> str:
    """Sceglie una variante (it, en) e la formatta in entrambe le lingue."""
    it, en = random.choice(variants)
    return f"🇮🇹 {it.format(**kw)}\n🇬🇧 {en.format(**kw)}"


# --- FLIP: conquista comune libero, furto, pareggio ({x}{z} utenti, {c} comune)
_FLIP_CONQUER = [
    ("🚩 {x} pianta la bandiera su {c}. Nessuno gliel'ha chiesto, ma eccoci qua.",
     "🚩 {x} plants a flag on {c}. Nobody asked, but here we are."),
    ("🗺️ {x} rivendica {c}. La cartografia mondiale se ne pentirà.",
     "🗺️ {x} claims {c}. World cartography will regret this."),
    ("👑 {c} ha un nuovo, discutibile sovrano: {x}.",
     "👑 {c} has a new, questionable ruler: {x}."),
]
_FLIP_STEAL = [
    ("⚔️ {x} strappa {c} dalle chiappe di {z}. Colpo di stato fecale.",
     "⚔️ {x} rips {c} from {z}'s cheeks. A fecal coup."),
    ("💥 {z} perde {c}: {x} ha cagato di più, e con più convinzione.",
     "💥 {z} loses {c}: {x} dumped more, and with more conviction."),
    ("🔥 {x} detronizza {z} a {c}. La corona era comunque appiccicosa.",
     "🔥 {x} dethrones {z} in {c}. The crown was sticky anyway."),
]
_FLIP_TIE = [
    ("🤝 {x} pareggia i conti con {z} a {c}. Nessuno comanda. Che squallore.",
     "🤝 {x} ties {z} in {c}. Nobody's in charge. How bleak."),
    ("⚖️ Stallo a {c}: {x} e {z} appaiati. La giustizia è cieca, e si tappa il naso.",
     "⚖️ Deadlock in {c}: {x} and {z} tied. Justice is blind, and holding its nose."),
    ("🌗 {x} riporta {c} nel limbo dei territori contesi, spalla a spalla con {z}.",
     "🌗 {x} drags {c} back into contested territories limbo, shoulder to shoulder with {z}."),
]

# --- BADGE ({x} utente, {b} nome badge tradotto)
_BADGE = [
    ("🎖️ {x} sblocca il badge «{b}». La commissione etica è preoccupata.",
     "🎖️ {x} unlocks the «{b}» badge. The ethics board is concerned."),
    ("🏅 Achievement sbloccato: «{b}». {x}, saremmo fieri se non fosse questo il gioco.",
     "🏅 Achievement unlocked: «{b}». {x}, we'd be proud if this weren't the game."),
    ("✨ {x} si guadagna «{b}». Da incorniciare, lontano dal tavolo da pranzo.",
     "✨ {x} earns «{b}». Frame it, far from the dinner table."),
    ("📛 Nuovo distintivo per {x}: «{b}». Portalo con orgoglio, o con vergogna.",
     "📛 New badge for {x}: «{b}». Wear it with pride. Or shame."),
]

# --- RECORD ({x} nuovo detentore, {r} nome record tradotto, {z} spodestato)
_RECORD_TAKE = [
    ("🏆 Record infranto: {x} è ora «{r}». {z} può solo guardare, e annusare.",
     "🏆 Record broken: {x} is now «{r}». {z} can only watch, and sniff."),
    ("📈 {x} soffia il record «{r}» a {z}. La competizione tocca vette imbarazzanti.",
     "📈 {x} snatches the «{r}» record from {z}. Competition reaches embarrassing heights."),
    ("🥇 Nuovo primato «{r}»: {x} supera {z}. La targa verrà consegnata con i guanti.",
     "🥇 New «{r}» record: {x} beats {z}. The plaque will be handed over with gloves."),
]
_RECORD_FIRST = [
    ("🏆 Primo record «{r}» della storia, e va a {x}. Che orgoglio. Immagino.",
     "🏆 The first-ever «{r}» record goes to {x}. Such pride. I suppose."),
    ("🥇 {x} inaugura il record «{r}». Nessuno voleva batterlo, ma comunque.",
     "🥇 {x} sets the first «{r}» record. No one wanted to beat it, but still."),
]


def _flip_message(item: dict) -> str | None:
    c = item["territory"]
    if item["kind"] == "steal" and item.get("displaced"):
        return _bi(_FLIP_STEAL, x=item["actor"], z=item["displaced"], c=c)
    if item["kind"] == "conquer":
        return _bi(_FLIP_CONQUER, x=item["actor"], c=c)
    if item["kind"] == "contested" and item.get("defender"):
        return _bi(_FLIP_TIE, x=item["by"], z=item["defender"], c=c)
    return None


def _badge_message(user: str, code: str) -> str:
    it, en = random.choice(_BADGE)
    bi = TRANSLATIONS["it"].get(f"ach_{code}", code)
    be = TRANSLATIONS["en"].get(f"ach_{code}", code)
    return f"🇮🇹 {it.format(x=user, b=bi)}\n🇬🇧 {en.format(x=user, b=be)}"


def _record_message(user: str, key: str, prev: str | None) -> str:
    ri = TRANSLATIONS["it"].get(f"rec_{key}", key)
    re_ = TRANSLATIONS["en"].get(f"rec_{key}", key)
    variants = _RECORD_TAKE if prev else _RECORD_FIRST
    it, en = random.choice(variants)
    kw_it = {"x": user, "r": ri, "z": prev}
    kw_en = {"x": user, "r": re_, "z": prev}
    return f"🇮🇹 {it.format(**kw_it)}\n🇬🇧 {en.format(**kw_en)}"


# --- PAREGGIO a N ({c} comune, {who} elenco di TUTTI i contendenti)
_TIE_N = [
    ("🤝 {c} sprofonda nel pareggio: {who}. Nessuno comanda, tutti perdono.",
     "🤝 {c} sinks into a tie: {who}. Nobody rules, everybody loses."),
    ("⚖️ Stallo a {c}: {who} appaiati. La targa resta in cantina.",
     "⚖️ Deadlock in {c}: {who} tied. The plaque stays in the basement."),
    ("🌀 {c} è terra di nessuno: {who} a pari merito. Che disastro condiviso.",
     "🌀 {c} is no man's land: {who} neck and neck. A shared disaster."),
]


def _join_names(items: list, conj: str) -> str:
    if len(items) <= 1:
        return items[0] if items else "?"
    return ", ".join(items[:-1]) + f" {conj} " + items[-1]


def _tie_message(comune: str, contenders: list) -> str:
    it, en = random.choice(_TIE_N)
    who_it = _join_names(contenders, "e")
    who_en = _join_names(contenders, "and")
    return f"🇮🇹 {it.format(c=comune, who=who_it)}\n🇬🇧 {en.format(c=comune, who=who_en)}"


# --- RECAP settimanale: frecciatina ai latitanti ({who} = chi ha fatto zero)
_NUDGE = [
    ("💤 {who}: stitici o solo timidi? Il vostro colon manda i saluti.",
     "💤 {who}: constipated or just shy? Your colon says hi."),
    ("🚽 {who} non hanno prodotto nulla. La montagna resta, e non partorisce nemmeno un topolino.",
     "🚽 {who} produced nothing. The mountain remains, and not even a mouse comes out."),
    ("🧻 Settimana a secco per {who}. Più fibre, meno scuse.",
     "🧻 A dry week for {who}. More fiber, fewer excuses."),
    ("😳 {who}, la timidezza da bagno pubblico non è una scusa. Vi aspettiamo.",
     "😳 {who}, public-toilet shyness is no excuse. We're waiting."),
    ("🪨 {who} sono in blocco totale. Si consigliano prugne, e coraggio.",
     "🪨 {who} are fully blocked. We recommend prunes, and courage."),
    ("📉 Zero depositi per {who}. Il gioco è a base fecale: si partecipa.",
     "📉 Zero deposits from {who}. The game runs on poop: participate."),
    ("🐢 {who} latitano. O stitici, o senza fegato. Entrambe curabili.",
     "🐢 {who} are AWOL. Constipated or gutless. Both are curable."),
    ("🕳️ {who} non hanno lasciato traccia. La leggenda vuole che esistano ancora.",
     "🕳️ {who} left no trace. Legend says they still exist."),
    ("⏳ {who}: la settimana è finita, il vostro intestino no. Datevi da fare.",
     "⏳ {who}: the week is over, your bowels aren't. Get to it."),
    ("🎭 {who}, o siete stitici o vi vergognate. In entrambi i casi, il gruppo giudica.",
     "🎭 {who}, either constipated or embarrassed. Either way, the group is judging."),
]


def _recap_message(recap: dict) -> str | None:
    dumpers, slackers = recap["dumpers"], recap["slackers"]
    if not dumpers and not slackers:
        return None   # niente da dire
    lines = ["🇮🇹 📅 Recap della settimana — il catasto fecale tira le somme.",
             "🇬🇧 📅 Weekly recap — the fecal cadastre tallies up.", ""]
    if dumpers:
        lines += [f"{i}. {name} — {n} 💩" for i, (name, n) in enumerate(dumpers, 1)]
    else:
        lines += ["🇮🇹 Nessuno ha cagato. Silenzio tombale (e intestinale).",
                  "🇬🇧 Nobody dumped. Deathly (and intestinal) silence."]
    if slackers:
        it, en = random.choice(_NUDGE)
        lines += ["", f"🇮🇹 {it.format(who=_join_names(slackers, 'e'))}",
                  f"🇬🇧 {en.format(who=_join_names(slackers, 'and'))}"]
    return "\n".join(lines)


def send_weekly_recap(conn, client=None) -> bool:
    """Costruisce e invia il recap al gruppo. Ritorna True se inviato."""
    msg = _recap_message(data.weekly_recap(conn))
    if not msg or not ALLOWED_CHAT:
        return False
    (client or TelegramClient()).send_message(ALLOWED_CHAT, msg)
    return True


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
    # stato PRIMA del dump, per rilevare badge, record e pareggi nuovi/cresciuti
    rec_before = data.record_holders(conn)
    awards_before = data.award_events(conn)
    contested_before = data.contested_contenders(conn)

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
    _elevate(conn)            # quota da DEM (open-meteo)
    finalize(conn)

    chat_id = msg["chat"]["id"]
    client.send_message(chat_id, _confirm_message(_comune_of(conn, did)))
    _announce_events(conn, client, chat_id, uid, did, rec_before, awards_before, contested_before)


def _announce_events(conn, client, chat_id, uid, did, rec_before, awards_before, contested_before) -> None:
    """Annuncia, distinti e con i nomi: flip (conquista/furto/pareggio anche a
    3+), badge nuovi e record superati causati da questo dump."""
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, COALESCE(public_name, display_name) AS name FROM users")}
    uname = names.get(uid, "?")

    # 1) evento sul comune del dump. Se ora è conteso, elenca TUTTI i contendenti
    #    (gestisce il pareggio a 2 e la crescita a 3+); altrimenti conquista/furto.
    row = conn.execute("SELECT territory_osm_id t FROM deposits WHERE id=?", (did,)).fetchone()
    comune_osm = row["t"] if row else None
    if comune_osm is not None:
        o = conn.execute("SELECT is_contested FROM territory_ownership WHERE territory_osm_id=?",
                         (comune_osm,)).fetchone()
        if o and o["is_contested"]:
            after = data.contested_contenders(conn).get(comune_osm, ())
            if after and after != contested_before.get(comune_osm, ()):   # nuovo o cresciuto
                who = [names.get(u, "?") for u in after]
                client.send_message(chat_id, _tie_message(_comune_of(conn, did) or "?", who))
        else:
            line = data.feed_line_for_deposit(conn, did)
            if line and line["kind"] in ("conquer", "steal") and (m := _flip_message(line)):
                client.send_message(chat_id, m)

    # 2) badge nuovi dell'autore
    for code, u, _ts, _ctx in sorted(data.award_events(conn) - awards_before):
        if u == uid:
            client.send_message(chat_id, _badge_message(uname, code))

    # 3) record superati dall'autore (solo veri sorpassi: c'era un detentore
    #    diverso; evita il flood quando il DB è quasi vuoto)
    rec_after = data.record_holders(conn)
    for key, holder in rec_after.items():
        prev_id = rec_before.get(key)
        if holder == uid and prev_id not in (None, uid):
            client.send_message(chat_id, _record_message(uname, key, names.get(prev_id)))


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
    chat = msg.get("chat", {})
    cmd = text.split()[0].split("@")[0] if text else ""  # gestisce anche /help@bot

    if cmd == "/start":
        parts = text.split(maxsplit=1)
        token = parts[1].strip() if len(parts) > 1 else ""
        if token:
            _handle_start(conn, msg["from"], token, client, chat)
        else:
            client.send_message(chat.get("id"), ONBOARDING)
        return
    if cmd in ("/help", "/aiuto", "/istruzioni"):
        client.send_message(chat.get("id"), HELP)
        return

    # dump: solo dal gruppo autorizzato
    if ALLOWED_CHAT and str(msg.get("chat", {}).get("id")) != str(ALLOWED_CHAT):
        return
    if "location" in msg:
        _handle_location(conn, msg, client, resolver, media_dir)
    elif "photo" in msg:
        _handle_photo(conn, msg, client, media_dir)
