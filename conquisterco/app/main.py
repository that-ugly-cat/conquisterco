"""FastAPI app della dashboard."""

from __future__ import annotations

import os
import secrets
import urllib.parse
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .. import config, faces, visibilita, weeks
from ..db import connect, init_db
from ..geo import FakeGeocoder
from ..geo_osm import OSMResolver
from ..pipeline import run_all
from ..seed import build_world, seed_deposits
from . import bot, data
from .auth import hash_password, verify_password
from .translations import SUPPORTED_LANGUAGES, get_lang, get_t

# resolver condiviso per i dump del bot (la cache dei genitori persiste)
_tg_resolver = OSMResolver()

APP_DIR = Path(__file__).resolve().parent
_ROOT = APP_DIR.parent.parent
# se esiste il DB coi dati storici lo si preferisce, altrimenti il DB demo
_default_db = _ROOT / "conquisterco_real.db"
if not _default_db.exists():
    _default_db = _ROOT / "conquisterco.db"
DB_PATH = os.environ.get("CONQUISTERCO_DB", str(_default_db))
MEDIA_DIR = Path(os.environ.get("CONQUISTERCO_MEDIA", str(_ROOT / "media"))).resolve()
DEMO_SEED = os.environ.get("CONQUISTERCO_DEMO", "1") == "1"
BS = chr(92)   # per non scrivere un backslash nudo nei confronti

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def _static_version() -> int:
    """mtime del file statico più recente → query ?v=... per bustare la cache."""
    try:
        return int(max(p.stat().st_mtime for p in (APP_DIR / "static").iterdir() if p.is_file()))
    except ValueError:
        return 0


STATIC_V = _static_version()

app = FastAPI(title="Conquisterco")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("CONQUISTERCO_SECRET", secrets.token_hex(16)))
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


# --- DB -------------------------------------------------------------------

def _migrate(conn) -> None:
    """Migrazioni leggere additive per DB già esistenti."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "no_selfie" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN no_selfie INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    if "public_name" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN public_name TEXT")
        # utenti esistenti: nome pubblico = username
        conn.execute("UPDATE users SET public_name=display_name WHERE public_name IS NULL")
        conn.commit()
    if "telegram_user_id" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN telegram_user_id INTEGER")
        conn.commit()
    if "provisional" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN provisional INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    if "selfie_visibility" not in cols:
        conn.execute("""ALTER TABLE users ADD COLUMN selfie_visibility TEXT
                        NOT NULL DEFAULT 'pubblico'""")
        # il vecchio booleano diventa il terzo livello: erano la stessa domanda
        conn.execute("UPDATE users SET selfie_visibility='niente' WHERE no_selfie=1")
        conn.commit()
    if "pulisci_chat" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN pulisci_chat INTEGER NOT NULL DEFAULT 0")
        # chi e' gia' ristretto lo vuole per forza: altrimenti la foto resta in
        # chat per sempre e «ristretto» sarebbe teatro
        conn.execute("UPDATE users SET pulisci_chat=1 WHERE selfie_visibility='ristretto'")
        conn.commit()
    buf_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tg_pending_photo)")}
    if buf_cols and "message_id" not in buf_cols:
        conn.execute("ALTER TABLE tg_pending_photo ADD COLUMN message_id INTEGER")
        conn.commit()
    if "stitico" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN stitico INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    ach_cols = {r["name"] for r in conn.execute("PRAGMA table_info(achievements)")}
    if "secret" not in ach_cols:
        conn.execute("ALTER TABLE achievements ADD COLUMN secret INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    if "manual" not in ach_cols:
        conn.execute("ALTER TABLE achievements ADD COLUMN manual INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    if "points" not in ach_cols:
        # i valori veri li riscrive sync_achievements dal registry a ogni finalize
        conn.execute("ALTER TABLE achievements ADD COLUMN points REAL NOT NULL DEFAULT 10.0")
        conn.execute("ALTER TABLE achievements ADD COLUMN decay REAL NOT NULL DEFAULT 0.5")
        conn.commit()
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_awards (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        code TEXT NOT NULL, ts TEXT NOT NULL, context TEXT,
        PRIMARY KEY (user_id, code))""")
    conn.commit()
    conn.execute("""CREATE TABLE IF NOT EXISTS selfie_grants (
        owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        viewer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        PRIMARY KEY (owner_user_id, viewer_user_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_grants_viewer ON selfie_grants(viewer_user_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS stitico_periods (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        from_ts TEXT NOT NULL, to_ts TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stitico_user ON stitico_periods(user_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS weeks (
        id INTEGER PRIMARY KEY,
        start_ts TEXT NOT NULL UNIQUE, end_ts TEXT NOT NULL, closed_at TEXT NOT NULL,
        winner_user_id INTEGER REFERENCES users(id),
        contested INTEGER NOT NULL DEFAULT 0,
        face_deposit_id INTEGER REFERENCES deposits(id),
        face_closed_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS selfie_votes (
        week_id INTEGER NOT NULL REFERENCES weeks(id) ON DELETE CASCADE,
        deposit_id INTEGER NOT NULL REFERENCES deposits(id) ON DELETE CASCADE,
        voter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
        ts TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (week_id, deposit_id, voter_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_votes_week ON selfie_votes(week_id)")
    conn.commit()
    conn.execute("""CREATE TABLE IF NOT EXISTS tg_link_tokens (
        token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS tg_pending_photo (
        telegram_user_id INTEGER PRIMARY KEY, file_id TEXT NOT NULL, ts TEXT NOT NULL)""")
    conn.commit()


def ensure_db() -> None:
    fresh = not Path(DB_PATH).exists()
    conn = connect(DB_PATH)
    try:
        if fresh:
            init_db(conn)
        _migrate(conn)
        if DEMO_SEED and conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            users = build_world(conn)
            seed_deposits(conn, users)
            run_all(conn, FakeGeocoder())
        # Le settimane gia' finite si chiudono qui, non solo al recap della
        # domenica: altrimenti dopo un aggiornamento la classifica «settimane
        # vinte» resta VUOTA fino al primo recap utile, e una pagina vuota
        # sembra rotta anche quando non lo e'. Lo storico e' derivabile subito,
        # quindi si deriva subito. E' idempotente e costa un SELECT quando non
        # c'e' niente da chiudere; la settimana IN CORSO resta al recap, che e'
        # l'unico a chiuderla (vedi weeks.py).
        weeks.close_due_weeks(conn)
    finally:
        conn.close()


def get_db():
    conn = connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def is_logged(request: Request) -> bool:
    return request.session.get("uid") is not None


def is_admin(request: Request) -> bool:
    return request.session.get("role") == "admin"


def require_login(request: Request) -> None:
    if not is_logged(request):
        raise HTTPException(status_code=401, detail="login richiesto")


def require_admin(request: Request) -> None:
    require_login(request)   # senza sessione manca il login, non il permesso
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="serve un admin")


def _ctx(request: Request, **extra) -> dict:
    """Contesto template con traduzioni + lingua correnti (pattern autocode)."""
    return {"T": get_t(request), "lang": get_lang(request), "static_v": STATIC_V, **extra}


ensure_db()


# --- Pagine ---------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", _ctx(
        request, logged=is_logged(request), admin=is_admin(request),
        me=request.session.get("name")))


def _dove_tornare(grezzo: str | None) -> str:
    """Il `next` del login, ripulito: solo path interni di questo sito.

    Un `next` che punta altrove sarebbe un redirect aperto, e il posto dove si
    finisce subito dopo aver scritto la password è esattamente quello che non
    deve poter scegliere un link arrivato da fuori."""
    if not grezzo or not grezzo.startswith("/"):
        return ""
    if grezzo.startswith("//") or grezzo.startswith("/" + BS):
        return ""
    return grezzo


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "", errore: int = 0):
    dove = _dove_tornare(next)
    if is_logged(request):
        return RedirectResponse(dove or "/", status_code=303)
    return templates.TemplateResponse(request, "login.html", _ctx(
        request, dove=dove, errore=bool(errore)))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          next: str = Form(""), conn=Depends(get_db)):
    dove = _dove_tornare(next)
    row = conn.execute(
        "SELECT id, role, password_hash, display_name FROM users WHERE display_name=?",
        (username.strip(),),
    ).fetchone()
    if row and verify_password(password, row["password_hash"]):
        request.session.update(uid=row["id"], role=row["role"], name=row["display_name"])
        return RedirectResponse(dove or "/", status_code=303)
    # password sbagliata: si torna alla pagina di login, che lo dice
    q = urllib.parse.urlencode({"next": dove, "errore": 1})
    return RedirectResponse("/login?" + q, status_code=303)


@app.exception_handler(StarletteHTTPException)
async def _pagina_senza_login(request: Request, exc: StarletteHTTPException):
    """Una pagina chiesta senza sessione non è un errore da mostrare: è un
    login mancante. Il link del voto arriva su Telegram e si apre dal telefono,
    dove la sessione spesso non c'è — un 401 nudo lì vuol dire non votare.

    Vale solo per le pagine: le chiamate sotto /api/ continuano a rispondere
    401 in JSON, perché un fetch che riceve una redirect a HTML non se ne
    accorge e si ritrova a fare il parse di una pagina."""
    pagina = (exc.status_code == 401 and request.method == "GET"
              and "text/html" in (request.headers.get("accept") or "")
              and not request.url.path.startswith("/api/"))
    if pagina:
        intero = request.url.path + (("?" + request.url.query) if request.url.query else "")
        q = urllib.parse.urlencode({"next": intero})
        return RedirectResponse("/login?" + q, status_code=303)
    return await http_exception_handler(request, exc)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacy.html", _ctx(request))


@app.get("/lang/{code}")
def set_lang(code: str, request: Request):
    resp = RedirectResponse(request.headers.get("referer") or "/", status_code=303)
    if code in SUPPORTED_LANGUAGES:
        resp.set_cookie("lang", code, max_age=31_536_000, samesite="lax")
    return resp


# --- API pubbliche --------------------------------------------------------

@app.get("/api/me")
def api_me(request: Request):
    return {"logged": is_logged(request), "admin": is_admin(request),
            "name": request.session.get("name")}


@app.get("/api/map/territories")
def api_territories(conn=Depends(get_db)):
    return data.territories_geo(conn)


@app.get("/api/map/areas")
def api_areas(level: str = "comune", conn=Depends(get_db)):
    if level not in ("comune", "province", "region", "country"):
        raise HTTPException(status_code=400, detail="livello non valido")
    return data.areas(conn, level)


@app.get("/api/leaderboard")
def api_leaderboard(conn=Depends(get_db)):
    return data.leaderboard(conn)


@app.get("/api/feed")
def api_feed(conn=Depends(get_db)):
    return data.feed(conn)


@app.get("/api/achievements")
def api_achievements(request: Request, conn=Depends(get_db)):
    return data.achievements(conn, get_t(request))


@app.get("/api/badge/{code}/holders")
def api_badge_holders(code: str, conn=Depends(get_db)):
    return data.badge_holders(conn, code)


@app.get("/api/territory/{osm_id}")
def api_territory(osm_id: int, conn=Depends(get_db)):
    return data.territory_detail(conn, osm_id)


@app.get("/api/profile/{user_id}")
def api_profile(user_id: int, request: Request, conn=Depends(get_db)):
    p = data.profile(conn, user_id, get_t(request))
    if p is None:
        raise HTTPException(status_code=404, detail="giocatore non trovato")
    return p


@app.get("/gallery/{user_id}", response_class=HTMLResponse)
def gallery_page(user_id: int, request: Request, conn=Depends(get_db)):
    require_login(request)   # foto = dato sensibile, come i pin dump
    g = data.gallery(conn, user_id, spettatore=request.session.get("uid"),
                     admin=is_admin(request))
    if g is None:
        raise HTTPException(status_code=404, detail="giocatore non trovato")
    return templates.TemplateResponse(request, "gallery.html", _ctx(
        request, g=g, me=request.session.get("name"), admin=is_admin(request)))


# --- API gated (solo loggati): pin dei dump + selfie ----------------------

@app.get("/api/map/dumps")
def api_dumps(request: Request, conn=Depends(get_db)):
    require_login(request)
    return data.dumps_geo(conn, request.session.get("uid"), admin=is_admin(request))


@app.get("/api/selfie/{deposit_id}")
def api_selfie(deposit_id: int, request: Request, conn=Depends(get_db)):
    require_login(request)
    row = conn.execute("SELECT photo_ref, user_id FROM deposits WHERE id=?",
                       (deposit_id,)).fetchone()
    if row is None or not row["photo_ref"]:
        raise HTTPException(status_code=404, detail="nessun selfie")
    if not visibilita.puo_vedere(conn, request.session.get("uid"), row["user_id"],
                                 admin=is_admin(request)):
        # 404 e non 403: chi non può vedere la foto non ha motivo di sapere
        # che esiste, e la rotta dice già "nessun selfie" quando manca davvero
        raise HTTPException(status_code=404, detail="nessun selfie")
    path = (MEDIA_DIR / row["photo_ref"]).resolve()
    # difesa da path traversal: deve restare dentro MEDIA_DIR
    if not str(path).startswith(str(MEDIA_DIR)) or not path.exists():
        raise HTTPException(status_code=404, detail="file non trovato")
    return FileResponse(path)


# --- Profilo utente (self-service) ----------------------------------------

_IMG_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
_MAX_IMG = 6_000_000  # 6 MB


def _save_image(file: UploadFile, kind: str, uid: int) -> str:
    if file.content_type not in _IMG_EXT:
        raise HTTPException(status_code=400, detail="serve un'immagine png/jpg/webp/gif")
    blob = file.file.read(_MAX_IMG + 1)
    if len(blob) > _MAX_IMG:
        raise HTTPException(status_code=413, detail="immagine troppo grande (max 6 MB)")
    ext = _IMG_EXT[file.content_type]
    dest = MEDIA_DIR / f"profiles/{uid}/{kind}.{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for old in dest.parent.glob(f"{kind}.*"):   # scarta eventuali estensioni vecchie
        old.unlink()
    dest.write_bytes(blob)
    return f"profiles/{uid}/{kind}.{ext}"


def _serve_profile_image(conn, uid: int, column: str):
    row = conn.execute(f"SELECT {column} AS ref FROM users WHERE id=?", (uid,)).fetchone()
    if row is None or not row["ref"]:
        raise HTTPException(status_code=404, detail="nessuna immagine")
    path = (MEDIA_DIR / row["ref"]).resolve()
    if not str(path).startswith(str(MEDIA_DIR)) or not path.exists():
        raise HTTPException(status_code=404, detail="file non trovato")
    return FileResponse(path)


@app.get("/me", response_class=HTMLResponse)
def me_page(request: Request, conn=Depends(get_db)):
    require_login(request)
    stats = data.my_stats(conn, request.session["uid"], get_t(request))
    if stats is None:
        request.session.clear()
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "profile.html", _ctx(
        request, s=stats, me=request.session.get("name"), admin=is_admin(request),
        legend=data.achievements(conn, get_t(request))))


@app.post("/me/flag")
def me_flag(request: Request, file: UploadFile = File(...), conn=Depends(get_db)):
    require_login(request)
    ref = _save_image(file, "flag", request.session["uid"])
    conn.execute("UPDATE users SET flag_ref=? WHERE id=?", (ref, request.session["uid"]))
    conn.commit()
    return RedirectResponse("/me", status_code=303)


@app.post("/me/password")
def me_password(request: Request, current: str = Form(...), new: str = Form(...),
                conn=Depends(get_db)):
    require_login(request)
    row = conn.execute("SELECT password_hash FROM users WHERE id=?",
                       (request.session["uid"],)).fetchone()
    if not verify_password(current, row["password_hash"]):
        raise HTTPException(status_code=403, detail="password attuale errata")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (hash_password(new), request.session["uid"]))
    conn.commit()
    return RedirectResponse("/me", status_code=303)


@app.post("/me/public-name")
def me_public_name(request: Request, public_name: str = Form(...), conn=Depends(get_db)):
    require_login(request)
    name = public_name.strip() or None   # vuoto → torna allo username
    conn.execute("UPDATE users SET public_name=? WHERE id=?", (name, request.session["uid"]))
    conn.commit()
    return RedirectResponse("/me", status_code=303)


@app.post("/me/telegram")
def me_telegram(request: Request, telegram: str = Form(""), conn=Depends(get_db)):
    require_login(request)
    tg = telegram.strip().lstrip("@") or None   # accetta con o senza @
    conn.execute("UPDATE users SET telegram_id=? WHERE id=?", (tg, request.session["uid"]))
    conn.commit()
    return RedirectResponse("/me", status_code=303)


@app.post("/me/telegram-link")
def me_telegram_link(request: Request, conn=Depends(get_db)):
    require_login(request)
    token = secrets.token_urlsafe(12)
    conn.execute("INSERT INTO tg_link_tokens (token, user_id) VALUES (?,?)",
                 (token, request.session["uid"]))
    conn.commit()
    # apre Telegram sul bot con /start <token>: il bot collega e assorbe i provvisori
    return RedirectResponse(f"https://t.me/{bot.BOT_USERNAME}?start={token}", status_code=303)


@app.post("/me/selfies")
def me_selfie_pref(request: Request, livello: str = Form("pubblico"),
                   ammessi: list[int] = Form(default=[]),
                   pulisci_chat: str = Form(None), conn=Depends(get_db)):
    """Tre livelli piu' la lista di chi è ammesso. La lista si salva anche
    quando il livello non è «ristretto»: così chi torna pubblico e poi cambia
    idea non deve rifarla da capo."""
    require_login(request)
    if livello not in visibilita.LIVELLI:
        livello = visibilita.PUBBLICO
    uid = request.session["uid"]
    prima = visibilita.livello(conn, uid)
    pulisce = bool(pulisci_chat)
    if livello == visibilita.RISTRETTO and prima != visibilita.RISTRETTO:
        # si accende da se' quando si PASSA a ristretto, anche senza javascript:
        # altrimenti ristretto sarebbe teatro, con la foto in chat per sempre
        pulisce = True
    conn.execute("""UPDATE users SET selfie_visibility=?, no_selfie=?, pulisci_chat=?
                    WHERE id=?""",
                 (livello, 1 if livello == visibilita.NIENTE else 0, int(pulisce), uid))
    visibilita.imposta_ammessi(conn, uid, ammessi)
    conn.commit()
    return RedirectResponse("/me", status_code=303)


@app.post("/me/stitico")
def me_stitico(request: Request, stitico: str = Form(None), conn=Depends(get_db)):
    """La dichiarazione di stitichezza vale DA ADESSO e finisce quando la
    togli: si apre e si chiude un periodo, non si sposta un booleano. Così i
    Gnnn! già guadagnati restano dove sono anche se cambi idea."""
    require_login(request)
    uid = request.session["uid"]
    on = bool(stitico)
    cur = conn.execute("SELECT stitico FROM users WHERE id=?", (uid,)).fetchone()
    if on and not cur["stitico"]:
        conn.execute(
            "INSERT INTO stitico_periods (user_id, from_ts) VALUES (?, datetime('now'))", (uid,))
    elif not on and cur["stitico"]:
        conn.execute(
            """UPDATE stitico_periods SET to_ts = datetime('now')
               WHERE user_id=? AND to_ts IS NULL""", (uid,))
    conn.execute("UPDATE users SET stitico=? WHERE id=?", (int(on), uid))
    conn.commit()
    return RedirectResponse("/me", status_code=303)


@app.post("/me/selfies/delete")
def me_delete_selfies(request: Request, conn=Depends(get_db)):
    require_login(request)
    data.delete_user_selfies(conn, request.session["uid"], MEDIA_DIR)
    return RedirectResponse("/me", status_code=303)


@app.post("/me/delete")
def me_delete(request: Request, conn=Depends(get_db)):
    require_login(request)
    data.delete_user(conn, request.session["uid"], MEDIA_DIR)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# --- Faccia di merda della settimana --------------------------------------

@app.get("/vote", response_class=HTMLResponse)
def vote_page(request: Request, conn=Depends(get_db)):
    require_login(request)   # i selfie stanno dietro login, e il voto pure
    week = faces.open_vote_week(conn)
    cands = (faces.candidates(conn, week["id"], request.session["uid"], MEDIA_DIR)
             if week else [])
    return templates.TemplateResponse(request, "vote.html", _ctx(
        request, week=week, cands=cands, max_vote=config.FACE_MAX_VOTE,
        me=request.session.get("name"), admin=is_admin(request)))


@app.post("/api/vote")
def api_vote(request: Request, deposit_id: int = Form(...), score: int = Form(...),
             conn=Depends(get_db)):
    require_login(request)
    week = faces.open_vote_week(conn)
    if week is None:
        raise HTTPException(status_code=409, detail="voto chiuso")
    ok = faces.cast_vote(conn, week["id"], deposit_id, request.session["uid"], score)
    if not ok:
        raise HTTPException(status_code=400, detail="voto non valido")
    return {"ok": True, "deposit_id": deposit_id, "score": score}


@app.post("/api/vote/undo")
def api_vote_undo(request: Request, deposit_id: int = Form(...), conn=Depends(get_db)):
    require_login(request)
    week = faces.open_vote_week(conn)
    if week is None:
        raise HTTPException(status_code=409, detail="voto chiuso")
    faces.clear_vote(conn, week["id"], deposit_id, request.session["uid"])
    return {"ok": True, "deposit_id": deposit_id, "score": None}


@app.get("/api/weeks")
def api_weeks(conn=Depends(get_db)):
    return data.weeks_panel(conn)


@app.get("/media/flag/{uid}")
def media_flag(uid: int, conn=Depends(get_db)):
    return _serve_profile_image(conn, uid, "flag_ref")


# --- Admin (gestione utenti) ----------------------------------------------

def _admin_view(request: Request, conn, *, sent: str = "", perche: str = "",
                bozza: str = "", pw_di: str = ""):
    """Rende il pannello. `bozza` ripopola la casella del messaggio: dopo un
    invio fallito il testo deve tornare indietro, non sparire — il 19 set 2026
    un annuncio di cinquemila caratteri e' andato perso così, per un rifiuto
    di Telegram e un redirect."""
    return templates.TemplateResponse(request, "admin.html", _ctx(
        request, users=data.list_users(conn), me=request.session.get("name"),
        bot_ok=bot.bot_enabled(), sent=sent, perche=perche, bozza=bozza, pw_di=pw_di,
        manual_badges=data.manual_badges(conn),
        manual_assignments=data.manual_assignments(conn)))


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, sent: str = "", perche: str = "", pw: str = "",
               conn=Depends(get_db)):
    require_admin(request)
    return _admin_view(request, conn, sent=sent, perche=perche, pw_di=pw)


@app.post("/admin/badge")
def admin_badge(request: Request, user_id: int = Form(...), code: str = Form(...),
                action: str = Form("grant"), conn=Depends(get_db)):
    require_admin(request)
    if action == "revoke":
        data.revoke_manual_badge(conn, user_id, code)
    else:
        data.grant_manual_badge(conn, user_id, code, context="assegnato dall'admin")
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/broadcast")
def admin_broadcast(request: Request, message: str = Form(""), conn=Depends(get_db)):
    require_admin(request)
    text = message.strip()
    if not text:
        return RedirectResponse("/admin?sent=empty", status_code=303)
    if not bot.bot_enabled():
        return RedirectResponse("/admin?sent=off", status_code=303)
    ok, motivo = bot.broadcast(text)
    if ok:
        q = urllib.parse.quote(motivo or "")
        return RedirectResponse(f"/admin?sent=ok&perche={q}", status_code=303)
    # fallito: si rende la pagina qui invece di rimbalzare, così il testo torna
    # nella casella. Un redirect lo butterebbe via, e riscrivere un annuncio
    # lungo perché il bot ha detto no e' una punizione sproporzionata.
    return _admin_view(request, conn, sent="fail", perche=motivo, bozza=text)


@app.post("/admin/create")
def admin_create(request: Request, display_name: str = Form(...),
                 password: str = Form(...), role: str = Form("user"),
                 conn=Depends(get_db)):
    require_admin(request)
    if role not in ("user", "admin"):
        role = "user"
    name = display_name.strip()
    existing = conn.execute("SELECT id FROM users WHERE display_name=?", (name,)).fetchone()
    if existing:
        conn.execute("UPDATE users SET role=?, password_hash=? WHERE id=?",
                     (role, hash_password(password), existing["id"]))
    else:
        conn.execute("INSERT INTO users (display_name, role, password_hash) VALUES (?,?,?)",
                     (name, role, hash_password(password)))
    conn.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/reset")
def admin_reset(request: Request, user_id: int = Form(...),
                password: str = Form(...), conn=Depends(get_db)):
    require_admin(request)
    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (hash_password(password), user_id))
    conn.commit()
    # il nome torna indietro nell'indirizzo solo per il toast: cambiare una
    # password senza che lo schermo dica niente e' il modo migliore per farlo
    # due volte, o per crederlo fatto sulla riga sbagliata
    r = conn.execute("SELECT display_name FROM users WHERE id=?", (user_id,)).fetchone()
    q = urllib.parse.urlencode({"pw": r["display_name"] if r else ""})
    return RedirectResponse("/admin?" + q, status_code=303)


@app.post("/admin/role")
def admin_role(request: Request, user_id: int = Form(...),
               role: str = Form(...), conn=Depends(get_db)):
    require_admin(request)
    if role in ("user", "admin"):
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        conn.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/merge")
def admin_merge(request: Request, from_user: int = Form(...),
                into_user: int = Form(...), conn=Depends(get_db)):
    require_admin(request)
    data.merge_users(conn, from_user, into_user)   # unisce from_user in into_user
    return RedirectResponse("/admin", status_code=303)


# --- Bot Telegram ----------------------------------------------------------

@app.post("/tg/{secret}")
async def telegram_webhook(secret: str, request: Request, conn=Depends(get_db)):
    if not bot.WEBHOOK_SECRET or secret != bot.WEBHOOK_SECRET:
        raise HTTPException(status_code=404, detail="not found")
    update = await request.json()
    try:
        bot.process_update(conn, update, client=bot.TelegramClient(),
                           resolver=_tg_resolver, media_dir=MEDIA_DIR)
    except Exception:
        pass   # non far ritentare Telegram all'infinito per un errore isolato
    return {"ok": True}


@app.on_event("startup")
def _register_webhook() -> None:
    if bot.BOT_TOKEN and bot.WEBHOOK_SECRET and bot.PUBLIC_URL:
        url = f"{bot.PUBLIC_URL.rstrip('/')}/tg/{bot.WEBHOOK_SECRET}"
        bot.TelegramClient().set_webhook(url)


def serve() -> None:
    import uvicorn
    uvicorn.run(
        "conquisterco.app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8077")),
        reload=False,
    )


if __name__ == "__main__":
    serve()
