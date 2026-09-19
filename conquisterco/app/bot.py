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
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from ..achievements import REGISTRY
from ..elevation import enrich_altitude
from ..enrich_osm import enrich_deposits_osm
from ..ingest import add_deposit
from ..pipeline import finalize
from .. import faces, visibilita, weeks
from ..util import is_video, parse_ts
from . import data, triggers
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
# Probabilità di rispondere quando un trigger testuale combacia (1.0 = sempre).
# Abbassala se il bot diventa troppo chiacchierone.
TRIGGER_CHANCE = float(os.environ.get("CONQUISTERCO_TRIGGER_CHANCE", "1.0"))


# ---------------------------------------------------------------------------
# Client Telegram
# ---------------------------------------------------------------------------

def _default_fetch(url: str, data: bytes | None = None,
                   headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _multipart(campi: dict, nome_file_field: str, filename: str, blob: bytes) -> tuple[bytes, str]:
    """Corpo `multipart/form-data` scritto a mano. L'alternativa era aggiungere
    una dipendenza HTTP al progetto per mandare una foto alla settimana."""
    b = "----conquisterco" + secrets.token_hex(8)
    crlf = chr(13) + chr(10)
    out = bytearray()
    for k, v in campi.items():
        out += (f'--{b}{crlf}Content-Disposition: form-data; name="{k}"'
                f'{crlf}{crlf}{v}{crlf}').encode()
    out += (f'--{b}{crlf}Content-Disposition: form-data; name="{nome_file_field}"; '
            f'filename="{filename}"{crlf}'
            f'Content-Type: application/octet-stream{crlf}{crlf}').encode()
    out += blob + crlf.encode()
    out += f"--{b}--{crlf}".encode()
    return bytes(out), f"multipart/form-data; boundary={b}"


class TelegramClient:
    def __init__(self, token: str = "", fetch=None):
        self.token = token or BOT_TOKEN
        self._fetch = fetch or _default_fetch

    def _api(self, method: str, params: dict) -> dict:
        """Ritorna sempre un dict. In caso di rifiuto di Telegram conserva la
        `description`: inghiottirla faceva sembrare un token sbagliato quello
        che era un messaggio troppo lungo, e il pannello admin accusava il
        token per qualunque causa."""
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode()
        try:
            return json.loads(self._fetch(url, data))
        except urllib.error.HTTPError as e:      # 400/403: il corpo dice perché
            try:
                return json.loads(e.read())
            except Exception:
                return {"ok": False, "description": f"HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "description": str(e) or e.__class__.__name__}

    def send_message(self, chat_id, text: str) -> None:
        self._api("sendMessage", {"chat_id": chat_id, "text": text})

    def file_path(self, file_id: str) -> str | None:
        return (self._api("getFile", {"file_id": file_id}).get("result") or {}).get("file_path")

    def download(self, file_path: str) -> bytes:
        return self._fetch(f"https://api.telegram.org/file/bot{self.token}/{file_path}")

    def send_media(self, chat_id, blob: bytes, filename: str, caption: str,
                   *, video: bool = False) -> bool:
        """Carica i byte invece di riusare il `file_id` di Telegram. Il file_id
        ci sarebbe (i selfie del bot sono salvati col file_id come nome) e
        risparmierebbe l'upload, ma non ce l'hanno i selfie importati da
        WhatsApp: due percorsi per una foto a settimana non valgono il risparmio."""
        metodo, campo = ("sendVideo", "video") if video else ("sendPhoto", "photo")
        body, ctype = _multipart({"chat_id": str(chat_id), "caption": caption},
                                 campo, filename, blob)
        try:
            r = json.loads(self._fetch(f"https://api.telegram.org/bot{self.token}/{metodo}",
                                       body, {"Content-Type": ctype}))
            return bool(r.get("ok"))
        except Exception:
            return False

    def set_webhook(self, url: str) -> dict:
        return self._api("setWebhook", {"url": url})


def bot_enabled() -> bool:
    """True se il bot è configurato (token + chat del gruppo)."""
    return bool(BOT_TOKEN and ALLOWED_CHAT)


TG_MAX_UNITS = 4096      # limite di un messaggio, in unità UTF-16 (non caratteri)


def _lunghezza_tg(s: str) -> int:
    """Quanto è lungo un testo *per Telegram*: unità UTF-16, non caratteri
    Python. Un'emoji ne vale 2 e una bandierina 🇮🇹 ne vale 4, perché è una
    coppia di indicatori regionali. Contare i caratteri sottostima, e su un
    annuncio pieno di bandierine sottostima di parecchio."""
    return len(s.encode("utf-16-le")) // 2


def spezza_per_telegram(text: str, limite: int = TG_MAX_UNITS) -> list[str]:
    """Divide un testo in messaggi che Telegram accetta, tagliando dove fa meno
    male: prima fra i paragrafi, poi fra le righe, e solo in ultimo dentro una
    riga. Un testo già corto resta un pezzo solo."""
    if _lunghezza_tg(text) <= limite:
        return [text]

    def taglia(blocchi: list[str], colla: str) -> list[str]:
        fuori, cur = [], ""
        for b in blocchi:
            prova = f"{cur}{colla}{b}" if cur else b
            if _lunghezza_tg(prova) <= limite:
                cur = prova
            else:
                if cur:
                    fuori.append(cur)
                cur = b
        if cur:
            fuori.append(cur)
        return fuori

    pezzi = taglia(text.split("\n\n"), "\n\n")
    fuori = []
    for p in pezzi:
        if _lunghezza_tg(p) <= limite:
            fuori.append(p)
            continue
        for q in taglia(p.split("\n"), "\n"):          # secondo tentativo: le righe
            while _lunghezza_tg(q) > limite:           # ultima risorsa: taglio netto
                n = limite
                while _lunghezza_tg(q[:n]) > limite:
                    n -= 16
                fuori.append(q[:n])
                q = q[n:]
            if q:
                fuori.append(q)
    return fuori


def broadcast(text: str, client: "TelegramClient | None" = None) -> tuple[bool, str]:
    """Manda un messaggio libero al gruppo (usato dal pannello admin).

    Ritorna (riuscito, motivo). Il testo lungo viene **spezzato** invece di
    essere rifiutato: un pannello che serve a mandare annunci deve accettare un
    annuncio. E il motivo del rifiuto arriva da Telegram, non inventato qui."""
    if not bot_enabled():
        return (False, "bot non configurato")
    c = client or TelegramClient()
    pezzi = spezza_per_telegram(text)
    for i, p in enumerate(pezzi, 1):
        res = c._api("sendMessage", {"chat_id": ALLOWED_CHAT, "text": p})
        if not res.get("ok"):
            motivo = res.get("description") or "causa sconosciuta"
            if len(pezzi) > 1:
                motivo = f"pezzo {i} di {len(pezzi)}: {motivo}"
            return (False, motivo)
    return (True, f"{len(pezzi)} messaggi" if len(pezzi) > 1 else "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg_ts(msg: dict) -> str:
    return datetime.fromtimestamp(msg.get("date", 0)).strftime("%Y-%m-%d %H:%M:%S")


def _within(a: str, b: str) -> bool:
    return abs((parse_ts(a) - parse_ts(b)).total_seconds()) <= PAIR_WINDOW_S


def _no_selfie(conn, uid: int) -> bool:
    """Il bot deve scartare il selfie di questo utente? Ora lo decide il
    livello di visibilita' (`niente`), che ha preso il posto del vecchio
    booleano `no_selfie`."""
    return not visibilita.salva_i_selfie(conn, uid)


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

# --- BADGE SEGRETO: notifica speciale (le meccaniche nascoste del mondo)
_BADGE_SECRET = [
    ("🕵️ BADGE SEGRETO! {x} sblocca «{b}» — qualcuno sta svelando le meccaniche nascoste del mondo.",
     "🕵️ SECRET BADGE! {x} unlocks «{b}» — someone is uncovering the world's hidden mechanics."),
    ("🔓 Meccanica occulta rivelata: {x} conquista il badge segreto «{b}». Non doveva saperlo nessuno.",
     "🔓 Hidden mechanic revealed: {x} earns the secret badge «{b}». Nobody was supposed to know."),
    ("👁️ {x} inciampa in un badge SEGRETO: «{b}». Gli dèi del cacasto sussurrano, e puzzano.",
     "👁️ {x} stumbles into a SECRET badge: «{b}». The gods of the cadastre whisper, and reek."),
    ("🤫 Psst… {x} ha appena sbloccato il badge segreto «{b}». Ora fai finta di niente.",
     "🤫 Psst… {x} just unlocked the secret badge «{b}». Now act natural."),
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


def _is_secret(code: str) -> bool:
    d = REGISTRY.get(code)
    return bool(d and d.secret)


def _badge_message(user: str, code: str) -> str:
    it, en = random.choice(_BADGE_SECRET if _is_secret(code) else _BADGE)
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


def _recap_message(recap: dict, *, face: dict | None = None,
                   vote_url: str | None = None) -> str | None:
    ranked, slackers = recap["ranked"], recap["slackers"]
    if not ranked and not slackers:
        return None   # niente da dire
    lines = ["🇮🇹 📅 Recap della settimana — il cacasto fecale tira le somme.",
             "🇬🇧 📅 Weekly recap — the fecal cadastre tallies up.", ""]
    if ranked:
        lines += ["🇮🇹 📈 Punti della settimana (le cacate fra parentesi):",
                  "🇬🇧 📈 Points this week (dumps in brackets):"]
        lines += [f"{i}. {name} — {pts} pt ({n} 💩)"
                  for i, (name, pts, n) in enumerate(ranked, 1)]
        if recap.get("winner"):
            lines += ["", f"🇮🇹 👑 Vince la settimana: {recap['winner']}.",
                      f"🇬🇧 👑 Winner of the week: {recap['winner']}."]
        elif recap.get("contested"):
            lines += ["", "🇮🇹 ⚔️ Parità in testa: settimana contesa, non la vince nessuno.",
                      "🇬🇧 ⚔️ Tie at the top: contested week, nobody wins it."]
    else:
        lines += ["🇮🇹 Nessuno ha cagato. Silenzio tombale (e intestinale).",
                  "🇬🇧 Nobody dumped. Deathly (and intestinal) silence."]
    if face:
        lines += ["", f"🇮🇹 💩 Faccia di merda della settimana scorsa: {face['author']} "
                      f"({face['total']} 💩 da {face['voters']} votanti).",
                  f"🇬🇧 💩 Last week's shit face: {face['author']} "
                  f"({face['total']} 💩 from {face['voters']} voters)."]
    if vote_url:
        lines += ["", f"🇮🇹 🗳️ Vota la faccia di merda di questa settimana: {vote_url}",
                  f"🇬🇧 🗳️ Vote this week's shit face: {vote_url}"]
    podium = recap.get("podium") or []
    if podium:
        lines += ["", "🇮🇹 🏆 Podio a punti — chi domina il cacasto:",
                  "🇬🇧 🏆 Score podium — who rules the cadastre:"]
        lines += [f"{m} {name} — {score}"
                  for m, (name, score) in zip(("🥇", "🥈", "🥉"), podium)]
    if slackers:
        it, en = random.choice(_NUDGE)
        lines += ["", f"🇮🇹 {it.format(who=_join_names(slackers, 'e'))}",
                  f"🇬🇧 {en.format(who=_join_names(slackers, 'and'))}"]
    return "\n".join(lines)


def _manda_selfie_proclamato(conn, eletto: dict, client, media_dir) -> bool:
    """Manda il selfie della faccia di merda come messaggio a parte.

    A parte e non come didascalia del recap per due ragioni: la didascalia di
    Telegram si ferma a 1024 caratteri e il recap ne fa mille abbondanti, e se
    l'invio della foto fallisce il verdetto e' gia' stato annunciato a parole,
    che e' la cosa che conta."""
    if not media_dir or not ALLOWED_CHAT:
        return False
    row = conn.execute("SELECT photo_ref, user_id FROM deposits WHERE id=?",
                       (eletto["deposit_id"],)).fetchone()
    if row is None or not row["photo_ref"]:
        return False
    if row["user_id"] not in visibilita.in_gara_al_voto(conn):
        return False      # non dovrebbe mai capitare: i ristretti sono fuori dal
                          # voto. Ma qui si ripubblica in chat una foto, e un
                          # errore a monte non deve diventare una foto in chiaro.
    base = Path(media_dir).resolve()
    f = (base / row["photo_ref"]).resolve()
    if not str(f).startswith(str(base)) or not f.exists():
        return False      # il file non c'e' piu': nove su 1252 sono cosi'
    didascalia = "\n".join([
        f"💩 Faccia di merda della settimana: {eletto['author']} "
        f"— {eletto['total']} 💩 da {eletto['voters']} votanti.",
        f"💩 Shit face of the week: {eletto['author']} "
        f"— {eletto['total']} 💩 from {eletto['voters']} voters.",
    ])
    return client.send_media(ALLOWED_CHAT, f.read_bytes(), f.name, didascalia,
                             video=is_video(row["photo_ref"]))


def send_weekly_recap(conn, client=None, media_dir=None) -> bool:
    """Il recap è l'evento che chiude la settimana, non solo il messaggio che la
    racconta. Nell'ordine: proclama la faccia di merda votata (quella della
    settimana prima, il cui voto si chiude adesso), chiude la settimana in
    corso scrivendone il verdetto, e apre il voto sui selfie appena chiusi.

    Il finalize dopo la proclamazione serve a far comparire il badge della
    faccia di merda, che si rilegge da `weeks`. Ritorna True se ha inviato."""
    prev = faces.open_vote_week(conn)
    elected = faces.elect(conn, prev["id"]) if prev else None
    closed = weeks.close_due_weeks(conn, closing_now=True)
    week = closed[-1] if closed else None
    if week:
        # il verdetto della settimana è appena nato: rigenera gli award
        finalize(conn)

    face = None
    if elected:
        face = {"author": elected["author"], "total": elected["total"],
                "voters": elected["voters"]}
    vote_url = None
    if week and PUBLIC_URL and faces.candidates(conn, week["id"]):
        vote_url = f"{PUBLIC_URL.rstrip('/')}/vote"

    msg = _recap_message(data.weekly_recap(conn, week), face=face, vote_url=vote_url)
    if not msg or not ALLOWED_CHAT:
        return False
    client = client or TelegramClient()
    client.send_message(ALLOWED_CHAT, msg)
    if elected:
        _manda_selfie_proclamato(conn, elected, client, media_dir)
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
    elif text and not text.startswith("/") and not msg["from"].get("is_bot"):
        reply = triggers.reply_for(text)
        if reply and random.random() <= TRIGGER_CHANCE:
            client.send_message(chat.get("id"), reply)
