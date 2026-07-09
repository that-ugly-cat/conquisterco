from conquisterco.app import bot
from conquisterco.db import fresh_db
from conquisterco.geo_osm import Resolution, Unit

from .conftest import mkuser

# niente chiamate di rete per la quota nei test
bot._elevate = lambda conn: None


class FakeTG:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))

    def file_path(self, file_id):
        return f"photos/{file_id}.jpg"

    def download(self, fp):
        return b"img-bytes"

    def set_webhook(self, url):
        return {}


class FakeResolver:
    def resolve(self, lat, lon):
        oid = int(abs(lat * 1000)) * 100000 + int(abs(lon * 1000))
        c = Unit(oid, f"Comune{oid}", "comune", lat, lon,
                 '{"type":"Polygon","coordinates":[]}', country="Italia", region="R", province="P")
        return Resolution(comune=c)


def loc(from_id, lat=45.1, lon=11.1, *, chat=1, date=1000, username=None, mid=1, first="Tizio"):
    return {"message": {"message_id": mid, "date": date, "chat": {"id": chat},
                        "from": {"id": from_id, "username": username, "first_name": first},
                        "location": {"latitude": lat, "longitude": lon}}}


def photo(from_id, file_id="F1", *, chat=1, date=1000, username=None, mid=2, first="Tizio"):
    return {"message": {"message_id": mid, "date": date, "chat": {"id": chat},
                        "from": {"id": from_id, "username": username, "first_name": first},
                        "photo": [{"file_id": file_id}]}}


def start(from_id, token, *, username=None):
    return {"message": {"message_id": 1, "date": 1000, "chat": {"id": 99, "type": "private"},
                        "from": {"id": from_id, "username": username, "first_name": "X"},
                        "text": f"/start {token}"}}


def run(conn, upd, tmp_path):
    bot.process_update(conn, upd, client=FakeTG(), resolver=FakeResolver(), media_dir=tmp_path)


def test_pin_crea_dump_e_provvisorio(tmp_path):
    conn = fresh_db(":memory:")
    run(conn, loc(555, username="marco"), tmp_path)
    u = conn.execute("SELECT provisional FROM users WHERE telegram_user_id=555").fetchone()
    assert u and u["provisional"] == 1
    d = conn.execute("SELECT source, territory_osm_id FROM deposits").fetchone()
    assert d["source"] == "telegram" and d["territory_osm_id"] is not None


def test_foto_dopo_il_pin_si_aggancia(tmp_path):
    conn = fresh_db(":memory:")
    run(conn, loc(555, date=1000, username="marco", mid=1), tmp_path)
    run(conn, photo(555, date=1060, username="marco", mid=2), tmp_path)  # +60s
    ref = conn.execute("SELECT photo_ref FROM deposits").fetchone()[0]
    assert ref and (tmp_path / ref).exists()


def test_foto_prima_del_pin_bufferizzata(tmp_path):
    conn = fresh_db(":memory:")
    run(conn, photo(555, date=1000, username="marco", mid=1), tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM tg_pending_photo").fetchone()[0] == 1
    run(conn, loc(555, date=1030, username="marco", mid=2), tmp_path)
    assert conn.execute("SELECT photo_ref FROM deposits").fetchone()[0] is not None
    assert conn.execute("SELECT COUNT(*) FROM tg_pending_photo").fetchone()[0] == 0


def test_match_per_username_cattura_id(tmp_path):
    conn = fresh_db(":memory:")
    a = mkuser(conn, "Spit")
    conn.execute("UPDATE users SET telegram_id='un_gatto' WHERE id=?", (a,))
    conn.commit()
    run(conn, loc(777, username="un_gatto"), tmp_path)
    assert conn.execute("SELECT telegram_user_id FROM users WHERE id=?", (a,)).fetchone()[0] == 777
    assert conn.execute("SELECT user_id FROM deposits").fetchone()[0] == a
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1  # niente provvisorio


def test_deeplink_fonde_il_provvisorio(tmp_path):
    conn = fresh_db(":memory:")
    run(conn, loc(555, username="marco"), tmp_path)
    prov = conn.execute("SELECT id FROM users WHERE telegram_user_id=555").fetchone()[0]
    real = mkuser(conn, "MarcoReal")
    conn.execute("INSERT INTO tg_link_tokens (token, user_id) VALUES ('TK', ?)", (real,))
    conn.commit()
    run(conn, start(555, "TK", username="marco"), tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id=?", (prov,)).fetchone()[0] == 0
    assert conn.execute("SELECT user_id FROM deposits").fetchone()[0] == real
    assert conn.execute("SELECT telegram_user_id FROM users WHERE id=?", (real,)).fetchone()[0] == 555


def test_no_selfie_scarta_la_foto(tmp_path):
    conn = fresh_db(":memory:")
    a = mkuser(conn, "S")
    conn.execute("UPDATE users SET telegram_id='ng', no_selfie=1 WHERE id=?", (a,))
    conn.commit()
    run(conn, loc(1, username="ng"), tmp_path)
    run(conn, photo(1, date=1030, username="ng"), tmp_path)
    assert conn.execute("SELECT photo_ref FROM deposits").fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM tg_pending_photo").fetchone()[0] == 0


def test_confirm_message_bilingue():
    for _ in range(15):  # copre le varianti pescate a caso
        m = bot._confirm_message("Trento")
        assert "🇮🇹" in m and "🇬🇧" in m and "Trento" in m
    unk = bot._confirm_message(None)
    assert "🇮🇹" in unk and "🇬🇧" in unk


def test_annuncio_feed_bilingue(tmp_path):
    conn = fresh_db(":memory:")
    tg = FakeTG()
    bot.process_update(conn, loc(555, username="marco"), client=tg,
                       resolver=FakeResolver(), media_dir=tmp_path)
    joined = " ".join(t for _, t in tg.sent)
    assert "conquistato" in joined and "conquered" in joined   # IT + EN


def test_start_onboarding(tmp_path):
    conn = fresh_db(":memory:")
    tg = FakeTG()
    upd = {"message": {"message_id": 1, "date": 1000, "chat": {"id": 99},
                       "from": {"id": 1, "first_name": "X"}, "text": "/start"}}
    bot.process_update(conn, upd, client=tg, resolver=FakeResolver(), media_dir=tmp_path)
    assert tg.sent and "Conquisterco" in tg.sent[0][1]
    assert conn.execute("SELECT COUNT(*) FROM deposits").fetchone()[0] == 0  # nessun dump


def test_help(tmp_path):
    conn = fresh_db(":memory:")
    tg = FakeTG()
    upd = {"message": {"message_id": 1, "date": 1000, "chat": {"id": 1},
                       "from": {"id": 1}, "text": "/help@conquisterco_bot"}}
    bot.process_update(conn, upd, client=tg, resolver=FakeResolver(), media_dir=tmp_path)
    assert tg.sent and "How to play" in tg.sent[0][1]


def test_solo_dal_gruppo_autorizzato(tmp_path):
    conn = fresh_db(":memory:")
    old = bot.ALLOWED_CHAT
    bot.ALLOWED_CHAT = "1"
    try:
        run(conn, loc(1, chat=999, username="x"), tmp_path)  # chat sbagliato
        assert conn.execute("SELECT COUNT(*) FROM deposits").fetchone()[0] == 0
    finally:
        bot.ALLOWED_CHAT = old
