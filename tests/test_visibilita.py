"""Chi vede i selfie di chi.

Questo file vale più degli altri: un buco qui non fa perdere punti a qualcuno,
pubblica la foto di una persona che aveva chiesto di no. Quindi si prova la
matrice intera, e soprattutto le due superfici che ripubblicano — il voto e la
foto che il recap manda in chat.
"""

from datetime import datetime, timedelta

from conquisterco import faces, visibilita, weeks
from conquisterco.app import data
from conquisterco.ingest import add_user
from conquisterco.pipeline import run_all

from .conftest import dep


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _livello(conn, uid, liv):
    conn.execute("UPDATE users SET selfie_visibility=? WHERE id=?", (liv, uid))
    conn.commit()


def test_matrice_dei_permessi(conn, geo):
    pub, ris, nul, tizio = (add_user(conn, n) for n in ("Pub", "Ris", "Nul", "Tizio"))
    admin = add_user(conn, "Admin")
    _livello(conn, ris, visibilita.RISTRETTO)
    _livello(conn, nul, visibilita.NIENTE)
    visibilita.imposta_ammessi(conn, ris, [tizio])

    def vede(chi, di_chi, **kw):
        return visibilita.puo_vedere(conn, chi, di_chi, **kw)

    # pubblico: lo vedono tutti i loggati, nessuno se non loggato
    assert vede(tizio, pub) and vede(ris, pub)
    assert vede(None, pub) is False

    # ristretto: il proprietario, l'ammesso e l'admin. Non gli altri.
    assert vede(ris, ris) and vede(tizio, ris)
    assert vede(pub, ris) is False
    assert vede(pub, ris, admin=True) is True

    # niente: nemmeno l'admin, perche' la foto non esiste proprio
    assert vede(nul, nul) is True          # i propri (se ne avesse) si vedono
    assert vede(admin, nul, admin=True) is False


def test_il_livello_niente_dice_al_bot_di_non_salvare(conn, geo):
    a = add_user(conn, "A")
    assert visibilita.salva_i_selfie(conn, a) is True
    _livello(conn, a, visibilita.NIENTE)
    assert visibilita.salva_i_selfie(conn, a) is False
    _livello(conn, a, visibilita.RISTRETTO)
    assert visibilita.salva_i_selfie(conn, a) is True   # ristretto si salva, si nasconde


def test_i_pin_restano_le_foto_no(conn, geo):
    """La posizione non e' il dato protetto: il pin si vede lo stesso, la foto
    diventa il coniglio che l'interfaccia usa gia' per i dump senza selfie."""
    ris, tale = add_user(conn, "Ris"), add_user(conn, "Tale")
    dep(conn, ris, 1012, "2026-05-01 10:00:00")
    run_all(conn, geo)
    _livello(conn, ris, visibilita.RISTRETTO)

    estraneo = data.dumps_geo(conn, tale)
    assert len(estraneo) == 1                      # il pin c'e'
    assert estraneo[0]["has_photo"] is False       # la foto no

    suo = data.dumps_geo(conn, ris)
    assert suo[0]["has_photo"] is True

    visibilita.imposta_ammessi(conn, ris, [tale])
    assert data.dumps_geo(conn, tale)[0]["has_photo"] is True


def test_un_ristretto_e_fuori_dal_voto(conn, geo, domenica):
    """La superficie piu' pericolosa: un selfie ristretto messo ai voti
    verrebbe mostrato a tutti, e il vincitore ripubblicato in chat dal recap."""
    ris, altro, terzo = (add_user(conn, n) for n in ("Ris", "Altro", "Terzo"))
    now = domenica
    suo = dep(conn, ris, 1012, _ts(now - timedelta(hours=6)))
    dep(conn, altro, 1005, _ts(now - timedelta(hours=5)))
    run_all(conn, geo)
    week = weeks.close_due_weeks(conn, closing_now=True)[-1]

    # finche' e' pubblico e' in gara
    assert suo in [c["id"] for c in faces.candidates(conn, week["id"], terzo)]

    _livello(conn, ris, visibilita.RISTRETTO)
    assert suo not in [c["id"] for c in faces.candidates(conn, week["id"], terzo)]
    # e non basta nasconderlo: un voto arrivato lo stesso va rifiutato
    assert faces.cast_vote(conn, week["id"], suo, terzo, 5) is False


def test_il_recap_non_ripubblica_una_foto_ristretta(conn, geo, tmp_path, monkeypatch, domenica):
    """Cintura e bretelle. Se per un errore a monte un ristretto risultasse
    eletto, la foto non deve comunque partire verso la chat."""
    from conquisterco.app import bot
    from tests.test_bot import FakeTG

    monkeypatch.setattr(bot, "ALLOWED_CHAT", "1")
    ris, altro = add_user(conn, "Ris"), add_user(conn, "Altro")
    now = domenica
    suo = dep(conn, ris, 1012, _ts(now - timedelta(hours=6)))
    run_all(conn, geo)
    (tmp_path / "x.jpg").write_bytes(b"byte")
    _livello(conn, ris, visibilita.RISTRETTO)

    tg = FakeTG()
    eletto = {"deposit_id": suo, "author": "Ris", "total": 9, "voters": 3}
    assert bot._manda_selfie_proclamato(conn, eletto, tg, tmp_path) is False
    assert tg.media == []


# --- pulizia della chat ----------------------------------------------------

def _pulisci_chat(conn, uid, acceso=True):
    conn.execute("UPDATE users SET pulisci_chat=? WHERE id=?", (int(acceso), uid))
    conn.commit()


def test_pin_e_foto_spariscono_dalla_chat(conn, geo, tmp_path):
    """Con la manopola accesa il bot toglie dalla chat sia la foto sia il pin,
    e lo fa DOPO aver scaricato: il file resta sul volume."""
    from conquisterco.app import bot
    from tests.test_bot import FakeResolver, FakeTG, loc, photo

    from conquisterco.ingest import add_user as _au
    a = _au(conn, "A")
    conn.execute("UPDATE users SET telegram_id='pulito' WHERE id=?", (a,))
    conn.commit()
    _pulisci_chat(conn, a)

    tg = FakeTG()
    bot.process_update(conn, loc(1, username="pulito", mid=11), client=tg,
                       resolver=FakeResolver(), media_dir=tmp_path)
    bot.process_update(conn, photo(1, date=1030, username="pulito", mid=12), client=tg,
                       resolver=FakeResolver(), media_dir=tmp_path)

    cancellati = [m for _, m in tg.cancellati]
    assert 11 in cancellati and 12 in cancellati
    ref = conn.execute("SELECT photo_ref FROM deposits").fetchone()[0]
    assert ref and (tmp_path / ref).exists(), "la foto deve restare sul volume"


def test_senza_manopola_la_chat_non_si_tocca(conn, geo, tmp_path):
    from conquisterco.app import bot
    from tests.test_bot import FakeResolver, FakeTG, loc, photo

    from conquisterco.ingest import add_user as _au
    a = _au(conn, "A")
    conn.execute("UPDATE users SET telegram_id='sporco' WHERE id=?", (a,))
    conn.commit()

    tg = FakeTG()
    bot.process_update(conn, loc(2, username="sporco", mid=21), client=tg,
                       resolver=FakeResolver(), media_dir=tmp_path)
    bot.process_update(conn, photo(2, date=1030, username="sporco", mid=22), client=tg,
                       resolver=FakeResolver(), media_dir=tmp_path)
    assert tg.cancellati == []


def test_foto_prima_del_pin_viene_cancellata_quando_il_pin_la_consuma(conn, geo, tmp_path):
    """Il caso scomodo: la foto arriva prima, va in buffer, e si puo'
    cancellare solo quando il pin la consuma — prima si scarica, poi si toglie."""
    from conquisterco.app import bot
    from tests.test_bot import FakeResolver, FakeTG, loc, photo

    from conquisterco.ingest import add_user as _au
    a = _au(conn, "A")
    conn.execute("UPDATE users SET telegram_id='prima' WHERE id=?", (a,))
    conn.commit()
    _pulisci_chat(conn, a)

    tg = FakeTG()
    bot.process_update(conn, photo(3, date=1000, username="prima", mid=31), client=tg,
                       resolver=FakeResolver(), media_dir=tmp_path)
    assert tg.cancellati == [], "in buffer non si cancella ancora: il file non c'e'"
    bot.process_update(conn, loc(3, date=1030, username="prima", mid=32), client=tg,
                       resolver=FakeResolver(), media_dir=tmp_path)

    cancellati = [m for _, m in tg.cancellati]
    assert 31 in cancellati and 32 in cancellati
    assert conn.execute("SELECT photo_ref FROM deposits").fetchone()[0] is not None


def test_chi_non_salva_i_selfie_li_toglie_comunque_dalla_chat(conn, geo, tmp_path):
    """«Niente» e «pulisci la chat» sono due domande diverse: chi non vuole la
    foto salvata di certo non la vuole nella cronologia."""
    from conquisterco.app import bot
    from tests.test_bot import FakeResolver, FakeTG, photo

    from conquisterco.ingest import add_user as _au
    a = _au(conn, "A")
    conn.execute("""UPDATE users SET telegram_id='niente', selfie_visibility='niente',
                    pulisci_chat=1 WHERE id=?""", (a,))
    conn.commit()

    tg = FakeTG()
    bot.process_update(conn, photo(4, username="niente", mid=41), client=tg,
                       resolver=FakeResolver(), media_dir=tmp_path)
    assert [m for _, m in tg.cancellati] == [41]
    assert conn.execute("SELECT COUNT(*) FROM tg_pending_photo").fetchone()[0] == 0


def test_passare_a_ristretto_accende_la_pulizia_anche_senza_javascript(monkeypatch):
    """Il server fa da se' quello che fa il javascript: chi passa a ristretto
    si trova la pulizia accesa, altrimenti la foto resta in chat e la scelta
    non serve a niente."""
    from conquisterco.app import main
    from conquisterco.db import fresh_db
    from conquisterco.ingest import add_user as _au

    conn = fresh_db(":memory:")
    a = _au(conn, "A")

    class Req:
        session = {"uid": a, "role": "user", "name": "A"}

    main.me_selfie_pref(Req(), livello="ristretto", ammessi=[], pulisci_chat=None, conn=conn)
    r = conn.execute("SELECT selfie_visibility, pulisci_chat FROM users WHERE id=?", (a,)).fetchone()
    assert r["selfie_visibility"] == "ristretto" and r["pulisci_chat"] == 1

    # ma resta sbarrabile a mano una volta che sei gia' ristretto
    main.me_selfie_pref(Req(), livello="ristretto", ammessi=[], pulisci_chat=None, conn=conn)
    assert conn.execute("SELECT pulisci_chat FROM users WHERE id=?", (a,)).fetchone()[0] == 0
    conn.close()


def test_chi_diventa_ristretto_a_meta_settimana_esce_anche_dallo_spoglio(conn, geo, domenica):
    """Il buco trovato il 21 set: filtrare i candidati e rifiutare i voti nuovi
    non basta. Chi passa a ristretto dopo essere stato votato si porta dietro i
    voti presi, e senza questo filtro vincerebbe — con proclamazione a nome suo
    su un selfie che nessuno puo' piu' vedere."""
    tizio, caio, votante = (add_user(conn, n) for n in ("Tizio", "Caio", "Votante"))
    now = domenica
    suo = dep(conn, tizio, 1012, _ts(now - timedelta(hours=6)))
    altro = dep(conn, caio, 1005, _ts(now - timedelta(hours=5)))
    run_all(conn, geo)
    week = weeks.close_due_weeks(conn, closing_now=True)[-1]

    # mentre e' pubblico prende piu' voti di tutti
    assert faces.cast_vote(conn, week["id"], suo, votante, 5)
    assert faces.cast_vote(conn, week["id"], suo, caio, 5)
    assert faces.cast_vote(conn, week["id"], altro, votante, 1)
    assert faces.tally(conn, week["id"])[0]["deposit_id"] == suo

    # poi si mette in ristretto: esce dallo spoglio, e non puo' vincere
    _livello(conn, tizio, visibilita.RISTRETTO)
    spoglio = faces.tally(conn, week["id"])
    assert [r["deposit_id"] for r in spoglio] == [altro]

    vincitore = faces.elect(conn, week["id"])
    assert vincitore is None or vincitore["deposit_id"] != suo

    # i voti restano pero' in tabella: tornando pubblico tornano a contare
    assert conn.execute("SELECT COUNT(*) FROM selfie_votes WHERE deposit_id=?",
                        (suo,)).fetchone()[0] == 2
