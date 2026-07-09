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


def test_annuncio_flip_badge_record(tmp_path):
    conn = fresh_db(":memory:")
    tg = FakeTG()
    bot.process_update(conn, loc(555, username="marco"), client=tg,
                       resolver=FakeResolver(), media_dir=tmp_path)
    joined = " ".join(t for _, t in tg.sent)
    assert "Tizio" in joined            # il flip nomina l'utente (nome del provvisorio)
    assert "Colonizzatore" in joined    # badge annunciato (nome IT nel messaggio bilingue)
    assert "🇮🇹" in joined and "🇬🇧" in joined


def test_badge_message_segreto_vs_pubblico():
    pub = bot._badge_message("Tizio", "blitz")
    assert "Blitz" in pub
    assert "secret" not in pub.lower() and "segreto" not in pub.lower()

    sec = bot._badge_message("Tizio", "serenissima")
    assert "Serenissima Deposizione" in sec   # il nome segreto è tradotto
    assert "secret" in sec.lower()             # notifica speciale bilingue
    assert "🇮🇹" in sec and "🇬🇧" in sec


def test_broadcast_disabilitato_se_bot_non_configurato(monkeypatch):
    monkeypatch.setattr(bot, "BOT_TOKEN", "")
    monkeypatch.setattr(bot, "ALLOWED_CHAT", None)
    assert bot.bot_enabled() is False
    assert bot.broadcast("ciao") is False   # nessuna rete, ritorna subito


def test_broadcast_invia_al_gruppo(monkeypatch):
    monkeypatch.setattr(bot, "BOT_TOKEN", "T")
    monkeypatch.setattr(bot, "ALLOWED_CHAT", "42")

    class C:
        def __init__(self):
            self.calls = []

        def _api(self, method, params):
            self.calls.append((method, params))
            return {"ok": True}

    c = C()
    assert bot.broadcast("ciao a tutti", client=c) is True
    assert c.calls[0][0] == "sendMessage"
    assert c.calls[0][1]["chat_id"] == "42"
    assert c.calls[0][1]["text"] == "ciao a tutti"


def test_pareggio_a_tre_elenca_tutti(tmp_path):
    conn = fresh_db(":memory:")
    R = FakeResolver()

    def dump(fid, name, date):
        u = {"message": {"message_id": fid, "date": date, "chat": {"id": 1},
                         "from": {"id": fid, "first_name": name},
                         "location": {"latitude": 45.1, "longitude": 11.1}}}
        tg = FakeTG()
        bot.process_update(conn, u, client=tg, resolver=R, media_dir=tmp_path)
        return " ".join(t for _, t in tg.sent)

    dump(1, "Alice", 1000)          # Alice conquista il comune
    m2 = dump(2, "Bob", 2000)       # pareggio Alice–Bob
    m3 = dump(3, "Carol", 3000)     # pareggio a tre
    assert "Alice" in m2 and "Bob" in m2
    assert "Alice" in m3 and "Bob" in m3 and "Carol" in m3   # elenca TUTTI e tre


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


def test_weekly_recap():
    from datetime import datetime, timedelta

    from conquisterco.app import data
    from conquisterco.ingest import add_deposit, add_user
    conn = fresh_db(":memory:")
    now = datetime.now()

    def ts(dt):
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    a = add_user(conn, "Alice")
    b = add_user(conn, "Bob")
    c = add_user(conn, "Carol")
    # questa settimana: Alice ×2, Bob ×1
    add_deposit(conn, user_id=a, ts=ts(now), lat=1.0, lon=1.0, source="telegram")
    add_deposit(conn, user_id=a, ts=ts(now), lat=1.1, lon=1.0, source="telegram")
    add_deposit(conn, user_id=b, ts=ts(now), lat=2.0, lon=2.0, source="telegram")
    # Carol: attiva (10 gg fa) ma zero questa settimana → latitante
    add_deposit(conn, user_id=c, ts=ts(now - timedelta(days=10)), lat=3.0, lon=3.0, source="telegram")

    rec = data.weekly_recap(conn)
    assert dict(rec["dumpers"]) == {"Alice": 2, "Bob": 1}
    assert rec["slackers"] == ["Carol"]

    msg = bot._recap_message(rec)
    assert "Alice — 2 💩" in msg and "Bob — 1 💩" in msg
    assert "Carol" in msg and "🇮🇹" in msg and "🇬🇧" in msg


def test_solo_dal_gruppo_autorizzato(tmp_path):
    conn = fresh_db(":memory:")
    old = bot.ALLOWED_CHAT
    bot.ALLOWED_CHAT = "1"
    try:
        run(conn, loc(1, chat=999, username="x"), tmp_path)  # chat sbagliato
        assert conn.execute("SELECT COUNT(*) FROM deposits").fetchone()[0] == 0
    finally:
        bot.ALLOWED_CHAT = old
