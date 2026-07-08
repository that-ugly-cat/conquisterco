"""FastAPI app della dashboard."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ..db import connect, init_db
from ..geo import FakeGeocoder
from ..pipeline import run_all
from ..seed import build_world, seed_deposits
from . import data

APP_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("CONQUISTERCO_DB", str(APP_DIR.parent.parent / "conquisterco.db"))
# password condivisa minimale (Fase 4 la sostituirà con utenti/admin veri)
SHARED_PASSWORD = os.environ.get("CONQUISTERCO_PASSWORD", "cacca")
DEMO_SEED = os.environ.get("CONQUISTERCO_DEMO", "1") == "1"

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(title="Conquisterco")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("CONQUISTERCO_SECRET", secrets.token_hex(16)))
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


# --- DB -------------------------------------------------------------------

def ensure_db() -> None:
    fresh = not Path(DB_PATH).exists()
    conn = connect(DB_PATH)
    try:
        if fresh:
            init_db(conn)
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
    return bool(request.session.get("auth"))


def require_login(request: Request) -> None:
    if not is_logged(request):
        raise HTTPException(status_code=401, detail="login richiesto")


ensure_db()


# --- Pagine ---------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"logged": is_logged(request)})


@app.post("/login")
def login(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, SHARED_PASSWORD):
        request.session["auth"] = True
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# --- API pubbliche --------------------------------------------------------

@app.get("/api/me")
def api_me(request: Request):
    return {"logged": is_logged(request)}


@app.get("/api/map/territories")
def api_territories(conn=Depends(get_db)):
    return data.territories_geo(conn)


@app.get("/api/leaderboard")
def api_leaderboard(conn=Depends(get_db)):
    return data.leaderboard(conn)


@app.get("/api/feed")
def api_feed(conn=Depends(get_db)):
    return data.feed(conn)


@app.get("/api/territory/{osm_id}")
def api_territory(osm_id: int, conn=Depends(get_db)):
    return data.territory_detail(conn, osm_id)


@app.get("/api/profile/{user_id}")
def api_profile(user_id: int, conn=Depends(get_db)):
    p = data.profile(conn, user_id)
    if p is None:
        raise HTTPException(status_code=404, detail="giocatore non trovato")
    return p


# --- API gated (solo loggati): pin dei dump + selfie ----------------------

@app.get("/api/map/dumps")
def api_dumps(request: Request, conn=Depends(get_db)):
    require_login(request)
    return data.dumps_geo(conn)


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
