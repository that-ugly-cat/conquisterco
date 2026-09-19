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


def test_un_ristretto_e_fuori_dal_voto(conn, geo):
    """La superficie piu' pericolosa: un selfie ristretto messo ai voti
    verrebbe mostrato a tutti, e il vincitore ripubblicato in chat dal recap."""
    ris, altro, terzo = (add_user(conn, n) for n in ("Ris", "Altro", "Terzo"))
    now = datetime.now()
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


def test_il_recap_non_ripubblica_una_foto_ristretta(conn, geo, tmp_path, monkeypatch):
    """Cintura e bretelle. Se per un errore a monte un ristretto risultasse
    eletto, la foto non deve comunque partire verso la chat."""
    from conquisterco.app import bot
    from tests.test_bot import FakeTG

    monkeypatch.setattr(bot, "ALLOWED_CHAT", "1")
    ris, altro = add_user(conn, "Ris"), add_user(conn, "Altro")
    now = datetime.now()
    suo = dep(conn, ris, 1012, _ts(now - timedelta(hours=6)))
    run_all(conn, geo)
    (tmp_path / "x.jpg").write_bytes(b"byte")
    _livello(conn, ris, visibilita.RISTRETTO)

    tg = FakeTG()
    eletto = {"deposit_id": suo, "author": "Ris", "total": 9, "voters": 3}
    assert bot._manda_selfie_proclamato(conn, eletto, tg, tmp_path) is False
    assert tg.media == []
