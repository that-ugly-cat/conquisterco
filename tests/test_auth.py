from conquisterco.app.auth import hash_password, verify_password
from conquisterco.util import anonymize_name


def test_hash_verify_roundtrip():
    h = hash_password("segreto")
    assert verify_password("segreto", h)
    assert not verify_password("sbagliato", h)
    assert not verify_password("segreto", None)
    assert not verify_password("segreto", "malformato")


def test_hash_ha_salt_casuale():
    assert hash_password("x") != hash_password("x")


def test_anonymize_name():
    assert anonymize_name("Giovanni Spitale") == "Giovanni_S"
    assert anonymize_name("Anna Maria Bertazzo") == "Anna_B"   # iniziale ultimo token
    assert anonymize_name("Madonna") == "Madonna"              # un solo token


def test_un_broadcast_fallito_restituisce_il_testo(monkeypatch, tmp_path):
    """Il 19 set 2026 un annuncio di cinquemila caratteri e' andato perso
    perche' l'invio e' fallito e la pagina rimbalzava su un redirect. Ora il
    testo torna nella casella."""
    from conquisterco.app import bot, main

    monkeypatch.setattr(bot, "BOT_TOKEN", "T")
    monkeypatch.setattr(bot, "ALLOWED_CHAT", "42")
    monkeypatch.setattr(bot, "broadcast", lambda t, client=None: (False, "Bad Request: prova"))

    class FintaRichiesta:
        session = {"uid": 1, "role": "admin", "name": "admin"}
        cookies = {}
        scope = {"type": "http"}

    catturato = {}

    def finto_render(request, nome, ctx):
        catturato.update(ctx)
        return "reso"

    monkeypatch.setattr(main.templates, "TemplateResponse", finto_render)
    monkeypatch.setattr(main.data, "list_users", lambda c: [])
    monkeypatch.setattr(main.data, "manual_badges", lambda c: [])
    monkeypatch.setattr(main.data, "manual_assignments", lambda c: [])

    testo = "un annuncio lungo " * 50
    main.admin_broadcast(FintaRichiesta(), message=testo, conn=None)
    assert catturato["sent"] == "fail"
    assert catturato["perche"] == "Bad Request: prova"
    assert catturato["bozza"] == testo.strip()
