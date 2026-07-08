"""FastAPI app della dashboard."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

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


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          conn=Depends(get_db)):
    row = conn.execute(
        "SELECT id, role, password_hash, display_name FROM users WHERE display_name=?",
        (username.strip(),),
    ).fetchone()
    if row and verify_password(password, row["password_hash"]):
        request.session.update(uid=row["id"], role=row["role"], name=row["display_name"])
    return RedirectResponse("/", status_code=303)


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


@app.get("/api/territory/{osm_id}")
def api_territory(osm_id: int, conn=Depends(get_db)):
    return data.territory_detail(conn, osm_id)


@app.get("/api/profile/{user_id}")
def api_profile(user_id: int, conn=Depends(get_db)):
    p = data.profile(conn, user_id)
    if p is None:
        raise HTTPException(status_code=404, detail="giocatore non trovato")
    return p


@app.get("/gallery/{user_id}", response_class=HTMLResponse)
def gallery_page(user_id: int, request: Request, conn=Depends(get_db)):
    require_login(request)   # foto = dato sensibile, come i pin dump
    g = data.gallery(conn, user_id)
    if g is None:
        raise HTTPException(status_code=404, detail="giocatore non trovato")
    return templates.TemplateResponse(request, "gallery.html", _ctx(
        request, g=g, me=request.session.get("name"), admin=is_admin(request)))


# --- API gated (solo loggati): pin dei dump + selfie ----------------------

@app.get("/api/map/dumps")
def api_dumps(request: Request, conn=Depends(get_db)):
    require_login(request)
    return data.dumps_geo(conn)


@app.get("/api/selfie/{deposit_id}")
def api_selfie(deposit_id: int, request: Request, conn=Depends(get_db)):
    require_login(request)
    row = conn.execute("SELECT photo_ref FROM deposits WHERE id=?", (deposit_id,)).fetchone()
    if row is None or not row["photo_ref"]:
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
    stats = data.my_stats(conn, request.session["uid"])
    if stats is None:
        request.session.clear()
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "profile.html", _ctx(
        request, s=stats, me=request.session.get("name"), admin=is_admin(request),
        legend=data.achievements(conn, get_t(request))))


@app.post("/me/avatar")
def me_avatar(request: Request, file: UploadFile = File(...), conn=Depends(get_db)):
    require_login(request)
    ref = _save_image(file, "avatar", request.session["uid"])
    conn.execute("UPDATE users SET avatar_ref=? WHERE id=?", (ref, request.session["uid"]))
    conn.commit()
    return RedirectResponse("/me", status_code=303)


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
def me_selfie_pref(request: Request, no_selfie: str = Form(None), conn=Depends(get_db)):
    require_login(request)
    conn.execute("UPDATE users SET no_selfie=? WHERE id=?",
                 (1 if no_selfie else 0, request.session["uid"]))
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


@app.get("/media/avatar/{uid}")
def media_avatar(uid: int, conn=Depends(get_db)):
    return _serve_profile_image(conn, uid, "avatar_ref")


@app.get("/media/flag/{uid}")
def media_flag(uid: int, conn=Depends(get_db)):
    return _serve_profile_image(conn, uid, "flag_ref")


# --- Admin (gestione utenti) ----------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, conn=Depends(get_db)):
    require_admin(request)
    return templates.TemplateResponse(request, "admin.html", _ctx(
        request, users=data.list_users(conn), me=request.session.get("name")))


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
    return RedirectResponse("/admin", status_code=303)


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
