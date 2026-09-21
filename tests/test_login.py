"""La pagina di login, e chi ci finisce sopra.

Il link del voto arriva su Telegram e si apre dal telefono, dove la sessione
spesso non c'e'. Prima di questi test quel link produceva un 401 nudo: una
pagina di errore del browser, senza un posto dove mettere la password. Qui si
prova che chiedere una pagina senza sessione porta al login, che dopo il login
si finisce dove si stava andando, e che `next` non puo' portare fuori dal sito.

L'app e il client stanno in `conftest.py` (fixture `web` e `client`), e si
saltano da soli quando manca l'extra `web`.
"""

import pytest

from .conftest import entra


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
    r = entra(client, "Tizio", next="/vote")
    assert r.status_code == 303 and r.headers["location"] == "/vote"


def test_la_password_sbagliata_lo_dice_e_non_perde_la_destinazione(client):
    r = entra(client, "Tizio", pw="sbagliata", next="/vote")
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
    r = entra(client, "Tizio", next=fuori)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_le_api_rispondono_ancora_401_e_non_una_pagina(client):
    # un fetch che riceve una redirect a HTML non se ne accorge e fa il parse
    # di una pagina: sotto /api/ il 401 deve restare un 401.
    r = client.get("/api/selfie/1", headers={"accept": "text/html"})
    assert r.status_code == 401


def test_chi_e_gia_dentro_non_vede_la_pagina_di_login(client):
    entra(client, "Tizio")
    r = client.get("/login?next=%2Fvote")
    assert r.status_code == 303 and r.headers["location"] == "/vote"


def test_admin_anonimo_al_login_admin_sbagliato_no(client):
    r = client.get("/admin", headers={"accept": "text/html"})
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Fadmin"
    entra(client, "Tizio")                       # loggato ma non admin
    r = client.get("/admin", headers={"accept": "text/html"})
    assert r.status_code == 403                  # qui manca il permesso, non il login
