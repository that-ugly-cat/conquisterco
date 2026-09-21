"""La pagina di login, e chi ci finisce sopra.

Il link del voto arriva su Telegram e si apre dal telefono, dove la sessione
spesso non c'e'. Prima di questi test quel link produceva un 401 nudo: una
pagina di errore del browser, senza un posto dove mettere la password. Qui si
prova che chiedere una pagina senza sessione porta al login, che dopo il login
si finisce dove si stava andando, e che `next` non puo' portare fuori dal sito.

Il file gira solo quando ci sono fastapi e httpx (extra `web` piu' `dev`);
altrimenti si salta, cosi' `uv run --extra dev pytest` resta verde.
"""

import os
import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

_tmp = tempfile.mkdtemp(prefix="conquisterco-login-")
os.environ["CONQUISTERCO_DB"] = os.path.join(_tmp, "test.db")
os.environ["CONQUISTERCO_MEDIA"] = os.path.join(_tmp, "media")
os.environ["CONQUISTERCO_DEMO"] = "0"
os.environ["CONQUISTERCO_SECRET"] = "chiave-di-test"

from starlette.testclient import TestClient          # noqa: E402

from conquisterco.app import main as appmod          # noqa: E402
from conquisterco.app.auth import hash_password      # noqa: E402

PW = "cacca-segreta"


@pytest.fixture(scope="module")
def client():
    conn = appmod.connect(appmod.DB_PATH)
    for nome, ruolo in (("Tizio", "user"), ("Capo", "admin")):
        conn.execute(
            "INSERT OR IGNORE INTO users (display_name, password_hash, role) VALUES (?,?,?)",
            (nome, hash_password(PW), ruolo))
    conn.commit()
    conn.close()
    with TestClient(appmod.app, follow_redirects=False) as c:
        yield c


def _entra(client, nome, pw=PW, next=""):
    return client.post("/login", data={"username": nome, "password": pw, "next": next})


def test_una_pagina_senza_sessione_porta_al_login(client):
    r = client.get("/vote", headers={"accept": "text/html"})
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=%2Fvote"


def test_la_pagina_di_login_esiste_ed_e_una_pagina(client):
    r = client.get("/login?next=%2Fvote")
    assert r.status_code == 200
    assert 'action="/login"' in r.text
    assert 'name="next" value="/vote"' in r.text


def test_dopo_il_login_si_finisce_dove_si_stava_andando(client):
    r = _entra(client, "Tizio", next="/vote")
    assert r.status_code == 303 and r.headers["location"] == "/vote"
    client.post("/logout")


def test_la_password_sbagliata_lo_dice_e_non_perde_la_destinazione(client):
    r = _entra(client, "Tizio", pw="sbagliata", next="/vote")
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=%2Fvote&errore=1"
    pagina = client.get(r.headers["location"])
    assert pagina.status_code == 200
    assert "sbagliat" in pagina.text.lower()


@pytest.mark.parametrize("fuori", [
    "https://esempio.invalido/",
    "//esempio.invalido/",
    "esempio.invalido",
])
def test_next_non_porta_fuori_dal_sito(client, fuori):
    r = _entra(client, "Tizio", next=fuori)
    assert r.status_code == 303 and r.headers["location"] == "/"
    client.post("/logout")


def test_le_api_rispondono_ancora_401_e_non_una_pagina(client):
    # un fetch che riceve una redirect a HTML non se ne accorge e fa il parse
    # di una pagina: sotto /api/ il 401 deve restare un 401.
    r = client.get("/api/selfie/1", headers={"accept": "text/html"})
    assert r.status_code == 401


def test_chi_e_gia_dentro_non_vede_la_pagina_di_login(client):
    _entra(client, "Tizio")
    r = client.get("/login?next=%2Fvote")
    assert r.status_code == 303 and r.headers["location"] == "/vote"
    client.post("/logout")


def test_admin_anonimo_al_login_admin_sbagliato_no(client):
    r = client.get("/admin", headers={"accept": "text/html"})
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Fadmin"
    _entra(client, "Tizio")                      # loggato ma non admin
    r = client.get("/admin", headers={"accept": "text/html"})
    assert r.status_code == 403                  # qui manca il permesso, non il login
    client.post("/logout")
