"""Il pannello admin dal lato delle rotte: il reset password e la sua conferma.

Cambiare una password senza che lo schermo dica niente e' il modo migliore per
farlo due volte, o per crederlo fatto sulla riga sbagliata. Qui si prova che la
conferma c'e', che porta il nome giusto, e che sparisce dall'indirizzo.
"""

from conquisterco.app.auth import verify_password

from .conftest import PW_TEST, entra


def _hash(web, nome):
    c = web.connect(web.DB_PATH)
    try:
        return c.execute("SELECT id, password_hash FROM users WHERE display_name=?",
                         (nome,)).fetchone()
    finally:
        c.close()


def test_il_reset_torna_col_nome_per_il_toast(client, web):
    entra(client, "Capo")
    uid = _hash(web, "Tizio")["id"]
    r = client.post("/admin/reset", data={"user_id": uid, "password": "nuova-pw"})
    assert r.status_code == 303
    assert r.headers["location"] == "/admin?fatto=pw&chi=Tizio"

    # la password e' cambiata davvero, non solo il messaggio
    assert verify_password("nuova-pw", _hash(web, "Tizio")["password_hash"])
    # e si rimette com'era, che gli altri test entrano ancora come Tizio
    client.post("/admin/reset", data={"user_id": uid, "password": PW_TEST})


def test_la_pagina_mostra_il_toast_col_nome(client):
    entra(client, "Capo")
    r = client.get("/admin?fatto=pw&chi=Tizio")
    assert r.status_code == 200
    assert 'class="toast"' in r.text
    assert "Tizio" in r.text.split('class="toast"')[1][:120]


def test_senza_parametro_niente_toast(client):
    entra(client, "Capo")
    r = client.get("/admin")
    assert r.status_code == 200
    assert 'class="toast"' not in r.text


def test_il_reset_resta_roba_da_admin(client, web):
    uid = _hash(web, "Tizio")["id"]
    r = client.post("/admin/reset", data={"user_id": uid, "password": "scippo"})
    assert r.status_code == 401                  # anonimo: manca il login
    entra(client, "Tizio")
    r = client.post("/admin/reset", data={"user_id": uid, "password": "scippo"})
    assert r.status_code == 403                  # loggato, ma non e' admin
    assert verify_password(PW_TEST, _hash(web, "Tizio")["password_hash"])


def test_ogni_azione_del_pannello_lascia_una_ricevuta(client, web):
    """Le altre quattro conferme. Il nome viaggia nell'indirizzo, la frase no:
    la compone la pagina, che e' l'unica a sapere in che lingua parla."""
    entra(client, "Capo")

    r = client.post("/admin/create", data={"display_name": "Nuovo_X",
                                           "password": "pw", "role": "user"})
    assert r.headers["location"] == "/admin?fatto=creato&chi=Nuovo_X&extra=user"

    uid = _hash(web, "Nuovo_X")["id"]
    r = client.post("/admin/role", data={"user_id": uid, "role": "admin"})
    assert r.headers["location"] == "/admin?fatto=ruolo&chi=Nuovo_X&extra=admin"

    # un ruolo inventato non cambia niente e non annuncia niente
    r = client.post("/admin/role", data={"user_id": uid, "role": "imperatore"})
    assert r.headers["location"] == "/admin"

    # il merge: il nome di chi sparisce si legge PRIMA di farlo sparire
    r = client.post("/admin/create", data={"display_name": "Doppio_X",
                                           "password": "pw", "role": "user"})
    doppio = _hash(web, "Doppio_X")["id"]
    r = client.post("/admin/merge", data={"from_user": doppio, "into_user": uid})
    assert r.headers["location"] == "/admin?fatto=merge&chi=Doppio_X&extra=Nuovo_X"


def test_la_ricevuta_del_badge_porta_il_nome_e_non_il_codice(client, web):
    entra(client, "Capo")
    uid = _hash(web, "Tizio")["id"]
    # un badge manuale vero: la tabella achievements la riscrive il registro a
    # ogni finalize, quindi uno inventato qui sparirebbe sotto i piedi al test
    r = client.post("/admin/badge", data={"user_id": uid, "code": "gatto_sul_cesso",
                                          "action": "grant"})
    assert r.headers["location"] == "/admin?fatto=badge&chi=Tizio&extra=Gatto+sul+Cesso"
    r = client.post("/admin/badge", data={"user_id": uid, "code": "gatto_sul_cesso",
                                          "action": "revoke"})
    assert r.headers["location"] == "/admin?fatto=badge_tolto&chi=Tizio&extra=Gatto+sul+Cesso"
