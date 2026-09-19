"""Gnnn! (badge degli stitici) e faccia di merda della settimana."""

from datetime import datetime, timedelta

from conquisterco import config, faces, weeks
from conquisterco.achievements import evaluate
from conquisterco.ingest import add_user
from conquisterco.pipeline import run_all

from .conftest import dep


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _stitico(conn, uid, da, a=None):
    conn.execute("INSERT INTO stitico_periods (user_id, from_ts, to_ts) VALUES (?,?,?)",
                 (uid, da, a))
    conn.execute("UPDATE users SET stitico=? WHERE id=?", (int(a is None), uid))
    conn.commit()


def _awards(conn, code, uid):
    return [a for a in evaluate(conn) if a.code == code and a.user_id == uid]


# --- Gnnn! -----------------------------------------------------------------

def test_gnnn_solo_dentro_il_periodo_dichiarato(conn, geo):
    """Il flag non e' retroattivo: le cacate di prima non diventano Gnnn!."""
    a = add_user(conn, "A")
    dep(conn, a, 1012, "2026-01-01 10:00:00")    # prima della dichiarazione
    dep(conn, a, 1012, "2026-06-01 10:00:00")    # dentro
    dep(conn, a, 1012, "2026-06-02 10:00:00")    # dentro
    run_all(conn, geo)
    _stitico(conn, a, "2026-05-01 00:00:00")

    got = _awards(conn, "gnnn", a)
    assert len(got) == 2
    assert all(g.ts_earned >= "2026-05-01" for g in got)


def test_gnnn_sopravvive_a_spegnere_il_flag(conn, geo):
    """Chi smette di dichiararsi stitico non perde i Gnnn! gia' guadagnati:
    e' la ragione per cui i periodi sono una tabella e non un booleano."""
    a = add_user(conn, "A")
    dep(conn, a, 1012, "2026-06-01 10:00:00")    # dentro il periodo
    dep(conn, a, 1012, "2026-08-01 10:00:00")    # dopo che l'ha tolto
    run_all(conn, geo)
    _stitico(conn, a, "2026-05-01 00:00:00", "2026-07-01 00:00:00")

    got = _awards(conn, "gnnn", a)
    assert len(got) == 1 and got[0].ts_earned.startswith("2026-06-01")


def test_gnnn_non_decade_mai(conn, geo):
    """L'incentivo e' a valore fisso: la decima cacata vale come la prima."""
    from conquisterco.achievements import REGISTRY
    from conquisterco.leaderboards import _decayed
    assert REGISTRY["gnnn"].points == config.GNNN_POINTS
    assert REGISTRY["gnnn"].decay == 1.0
    assert _decayed(config.GNNN_POINTS, 1.0, 10) == config.GNNN_POINTS * 10


def test_gnnn_entra_nel_punteggio(conn, geo):
    from conquisterco.leaderboards import badge_points
    a = add_user(conn, "A")
    dep(conn, a, 1012, "2026-06-01 10:00:00")
    run_all(conn, geo)
    prima = badge_points(conn)[a]
    _stitico(conn, a, "2026-05-01 00:00:00")
    run_all(conn, geo)
    assert badge_points(conn)[a] == prima + config.GNNN_POINTS


# --- Faccia di merda -------------------------------------------------------

def _settimana_con_selfie(conn, geo):
    """Chiude una settimana che contiene i selfie di due giocatori."""
    a, b = add_user(conn, "A"), add_user(conn, "B")
    now = datetime.now()
    da = dep(conn, a, 1012, _ts(now - timedelta(hours=6)))
    db = dep(conn, b, 1005, _ts(now - timedelta(hours=5)))
    run_all(conn, geo)
    week = weeks.close_due_weeks(conn, closing_now=True)[-1]
    return a, b, da, db, week


def test_non_si_votano_i_propri_selfie(conn, geo):
    a, b, da, db, week = _settimana_con_selfie(conn, geo)
    ids = [c["id"] for c in faces.candidates(conn, week["id"], a)]
    assert da not in ids and db in ids
    assert faces.cast_vote(conn, week["id"], da, a, 5) is False


def test_voto_e_undo(conn, geo):
    a, b, da, db, week = _settimana_con_selfie(conn, geo)
    assert faces.cast_vote(conn, week["id"], db, a, 4)
    assert faces.candidates(conn, week["id"], a)[0]["my_vote"] == 4
    assert faces.cast_vote(conn, week["id"], db, a, 2)          # cambio idea
    assert faces.candidates(conn, week["id"], a)[0]["my_vote"] == 2
    assert faces.clear_vote(conn, week["id"], db, a)            # undo
    assert faces.candidates(conn, week["id"], a)[0]["my_vote"] is None


def test_voto_fuori_scala_rifiutato(conn, geo):
    a, b, da, db, week = _settimana_con_selfie(conn, geo)
    assert faces.cast_vote(conn, week["id"], db, a, 0) is False
    assert faces.cast_vote(conn, week["id"], db, a, config.FACE_MAX_VOTE + 1) is False


def test_vince_chi_raccoglie_piu_merda(conn, geo):
    a, b, da, db, week = _settimana_con_selfie(conn, geo)
    c = add_user(conn, "C")
    faces.cast_vote(conn, week["id"], db, a, 5)
    faces.cast_vote(conn, week["id"], db, c, 3)
    faces.cast_vote(conn, week["id"], da, b, 4)
    faces.cast_vote(conn, week["id"], da, c, 2)
    vincitore = faces.elect(conn, week["id"])
    assert vincitore["deposit_id"] == db and vincitore["total"] == 8


def test_troppi_pochi_votanti_non_eleggono_ma_chiudono(conn, geo):
    a, b, da, db, week = _settimana_con_selfie(conn, geo)
    faces.cast_vote(conn, week["id"], db, a, 5)     # un solo votante
    assert faces.elect(conn, week["id"]) is None
    row = conn.execute("SELECT face_deposit_id, face_closed_at FROM weeks WHERE id=?",
                       (week["id"],)).fetchone()
    assert row["face_deposit_id"] is None
    assert row["face_closed_at"] is not None        # chiusa lo stesso
    assert faces.cast_vote(conn, week["id"], db, b, 5) is False   # voto chiuso


def test_la_faccia_eletta_diventa_un_badge(conn, geo):
    a, b, da, db, week = _settimana_con_selfie(conn, geo)
    c = add_user(conn, "C")
    faces.cast_vote(conn, week["id"], db, a, 5)
    faces.cast_vote(conn, week["id"], db, c, 4)
    faces.elect(conn, week["id"])
    assert _awards(conn, "faccia_di_merda", b)
    assert not _awards(conn, "faccia_di_merda", a)


def test_una_sola_settimana_aperta_al_voto(conn, geo):
    a, b, da, db, week = _settimana_con_selfie(conn, geo)
    assert faces.open_vote_week(conn)["id"] == week["id"]
    faces.elect(conn, week["id"])
    assert faces.open_vote_week(conn) is None


def test_selfie_con_file_sparito_e_fuori_gara(conn, geo, tmp_path):
    """Un `photo_ref` che punta al nulla in galleria e' un'immagine rotta; qui
    sarebbe un riquadro grigio votabile, cioe' un voto dato a niente."""
    a, b, da, db, week = _settimana_con_selfie(conn, geo)
    (tmp_path / "x.jpg").write_bytes(b"finta")   # esiste solo quella di `a`
    conn.execute("UPDATE deposits SET photo_ref='sparito.jpg' WHERE id=?", (db,))
    conn.commit()

    senza_controllo = [c["id"] for c in faces.candidates(conn, week["id"], a)]
    con_controllo = [c["id"] for c in faces.candidates(conn, week["id"], a, tmp_path)]
    assert db in senza_controllo          # il DB non sa che il file non c'e'
    assert db not in con_controllo        # il filesystem si'
