from conquisterco.app import bot, triggers
from conquisterco.db import fresh_db


class FakeTG:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def _txt(text, *, from_id=9, is_bot=False):
    frm = {"id": from_id, "first_name": "T"}
    if is_bot:
        frm["is_bot"] = True
    return {"message": {"message_id": 1, "date": 1, "chat": {"id": 1},
                        "from": frm, "text": text}}


def test_reply_for_match_bilingue():
    for phrase in ("oggi mangio un kebab", "anschluss", "che noia", "cacca", "birra fredda"):
        r = triggers.reply_for(phrase)
        assert r is not None, phrase
        assert "🇮🇹" in r and "🇬🇧" in r


def test_reply_for_nessun_match():
    assert triggers.reply_for("ci vediamo più tardi in centro") is None
    assert triggers.reply_for("") is None


def test_word_boundary_niente_falsi_positivi():
    # 'ai' non è un trigger: la preposizione non deve innescare la battuta sull'IA
    assert triggers.reply_for("vado ai giardini con i bambini") is None


def test_process_update_risponde_al_trigger():
    conn = fresh_db(":memory:")
    tg = FakeTG()
    bot.process_update(conn, _txt("che palle sta conferenza"),
                       client=tg, resolver=None, media_dir=None)
    assert tg.sent and "🇮🇹" in tg.sent[-1][1]


def test_process_update_ignora_i_bot():
    conn = fresh_db(":memory:")
    tg = FakeTG()
    bot.process_update(conn, _txt("kebab", is_bot=True),
                       client=tg, resolver=None, media_dir=None)
    assert not tg.sent


def test_process_update_ignora_i_comandi():
    conn = fresh_db(":memory:")
    tg = FakeTG()
    # "/classifica" inizia con '/': non deve innescare il trigger 'classifica'
    bot.process_update(conn, _txt("/classifica"),
                       client=tg, resolver=None, media_dir=None)
    assert not tg.sent
