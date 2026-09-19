"""Settimane: chiusura, vincitore a punti, classifica per settimane vinte.

La settimana è un delta fra due istantanee del punteggio, e il verdetto lo
congela il recap: sono le due cose che questi test tengono ferme.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from conquisterco import weeks
from conquisterco.ingest import add_user
from conquisterco.pipeline import run_all

from .conftest import dep


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def test_punti_della_settimana_sono_un_delta(conn, geo):
    a = add_user(conn, "A")
    now = datetime.now()
    dep(conn, a, 1012, _ts(now - timedelta(days=20)))   # vecchio: fuori settimana
    run_all(conn, geo)
    prima = weeks.score_snapshot(conn)[a]

    dep(conn, a, 1005, _ts(now - timedelta(hours=2)))   # nuovo comune, questa settimana
    run_all(conn, geo)

    g = weeks.running_gains(conn)
    assert g[a] > 0
    assert abs(weeks.score_snapshot(conn)[a] - prima - g[a]) < 1e-6


def test_snapshot_di_adesso_coincide_con_la_classifica(conn, geo):
    """`_owned_at` ricostruisce dai flip quello che `territory_ownership` tiene
    gia' calcolato: se le due strade divergono, una delle due e' rotta."""
    from conquisterco.leaderboards import main_leaderboard
    a, b = add_user(conn, "A"), add_user(conn, "B")
    dep(conn, a, 1012, "2026-05-01 10:00:00")
    dep(conn, b, 1005, "2026-05-02 10:00:00")
    dep(conn, b, 1005, "2026-05-03 10:00:00")
    run_all(conn, geo)
    snap = weeks.score_snapshot(conn)
    for row in main_leaderboard(conn):
        assert round(snap.get(row["user_id"], 0.0)) == row["score"]


def test_vince_chi_guadagna_di_piu_non_chi_caga_di_piu(conn, geo):
    """B fa una cacata sola ma prende un comune grande; A ne fa due nello
    stesso comune gia' suo e non guadagna niente."""
    a, b = add_user(conn, "A"), add_user(conn, "B")
    now = datetime.now()
    dep(conn, a, 1012, _ts(now - timedelta(days=40)))   # A possiede gia' 1012
    run_all(conn, geo)
    weeks.close_due_weeks(conn)                          # storico chiuso, si riparte

    dep(conn, a, 1012, _ts(now - timedelta(hours=5)))    # nessun guadagno: era gia' suo
    dep(conn, a, 1012, _ts(now - timedelta(hours=4)))
    dep(conn, b, 1005, _ts(now - timedelta(hours=3)))    # comune nuovo: guadagno
    run_all(conn, geo)

    closed = weeks.close_due_weeks(conn, closing_now=True)
    assert closed, "la settimana in corso doveva chiudersi"
    assert closed[-1]["winner_user_id"] == b


def test_parita_rende_la_settimana_contesa():
    """La regola madre del gioco applicata alla settimana: massimo STRETTO,
    altrimenti non la vince nessuno (SPEC §2). Unitaria, perché fabbricare due
    guadagni identici da depositi veri e' quasi impossibile — i badge divergono
    sempre di qualcosa, ed è proprio questo che rende la parità rara."""
    assert weeks._winner({1: 30.0, 2: 10.0}) == (1, False)
    assert weeks._winner({1: 30.0, 2: 30.0}) == (None, True)
    assert weeks._winner({1: 30.0, 2: 30.0, 3: 5.0}) == (None, True)
    assert weeks._winner({}) == (None, False)   # settimana vuota, non contesa


def test_una_settimana_chiusa_non_si_ricalcola(conn, geo):
    a, b = add_user(conn, "A"), add_user(conn, "B")
    now = datetime.now()
    dep(conn, a, 1012, _ts(now - timedelta(hours=6)))
    run_all(conn, geo)
    closed = weeks.close_due_weeks(conn, closing_now=True)
    wid, winner = closed[-1]["id"], closed[-1]["winner_user_id"]
    assert winner == a

    # arriva altro storico DENTRO quella settimana: il verdetto non si muove
    dep(conn, b, 1005, _ts(now - timedelta(hours=5)))
    dep(conn, b, 1004, _ts(now - timedelta(hours=5)))
    run_all(conn, geo)
    weeks.close_due_weeks(conn, closing_now=True)
    row = conn.execute("SELECT winner_user_id FROM weeks WHERE id=?", (wid,)).fetchone()
    assert row["winner_user_id"] == winner


def test_recap_ravvicinato_non_fabbrica_una_settimana(conn, geo):
    a = add_user(conn, "A")
    now = datetime.now()
    dep(conn, a, 1012, _ts(now - timedelta(hours=3)))
    run_all(conn, geo)
    assert weeks.close_due_weeks(conn, closing_now=True)      # la prima chiude
    assert weeks.close_due_weeks(conn, closing_now=True) == []  # la seconda no


def test_storico_si_chiude_retroattivamente_sulla_griglia(conn, geo):
    """Tutte le settimane passate senza recap entrano in una volta sola, e
    la seconda chiamata non ne aggiunge altre."""
    a = add_user(conn, "A")
    now = datetime.now()
    for w in range(6, 0, -1):
        dep(conn, a, 1012, _ts(now - timedelta(weeks=w)))
    run_all(conn, geo)
    first = weeks.close_due_weeks(conn)
    assert len(first) >= 5
    assert weeks.close_due_weeks(conn) == []
    # tessellano senza buchi: ogni settimana riparte dove finisce la precedente
    rows = conn.execute("SELECT start_ts, end_ts FROM weeks ORDER BY start_ts").fetchall()
    for prev, nxt in zip(rows, rows[1:]):
        assert prev["end_ts"] == nxt["start_ts"]


def test_classifica_settimane_vinte_su_giocate(conn, geo):
    a, b = add_user(conn, "A"), add_user(conn, "B")
    now = datetime.now()
    dep(conn, a, 1012, _ts(now - timedelta(weeks=3)))
    dep(conn, b, 1005, _ts(now - timedelta(weeks=2)))
    dep(conn, b, 1004, _ts(now - timedelta(weeks=2)))
    run_all(conn, geo)
    weeks.close_due_weeks(conn)

    lb = {r["name"]: r for r in weeks.weeks_leaderboard(conn)}
    assert lb["A"]["won"] == 1 and lb["A"]["played"] == 1
    assert lb["B"]["won"] == 1 and lb["B"]["played"] == 1
    # il rateo e' vinte/giocate, e `played` va sempre mostrato accanto
    for r in lb.values():
        assert r["ratio"] == round(r["won"] / r["played"], 3)


def test_il_recap_chiude_la_settimana_proclama_e_riapre(conn, geo, monkeypatch):
    """Il giro completo del recap: chiude la settimana, elegge la faccia di
    merda di quella prima, e apre il voto su quella appena chiusa."""
    from conquisterco import faces
    from conquisterco.app import bot
    from tests.test_bot import FakeTG

    monkeypatch.setattr(bot, "ALLOWED_CHAT", "1")
    monkeypatch.setattr(bot, "PUBLIC_URL", "https://conquisterco.example")
    a, b, c = add_user(conn, "A"), add_user(conn, "B"), add_user(conn, "C")
    now = datetime.now()
    dep(conn, a, 1012, _ts(now - timedelta(hours=8)))
    dep(conn, b, 1005, _ts(now - timedelta(hours=7)))
    run_all(conn, geo)

    tg = FakeTG()
    assert bot.send_weekly_recap(conn, tg)            # primo recap: chiude e apre il voto
    assert "/vote" in tg.sent[0][1]
    aperta = faces.open_vote_week(conn)
    assert aperta is not None

    # si vota, poi passa una settimana e il recap successivo proclama
    dbid = [x["id"] for x in faces.candidates(conn, aperta["id"], a)][0]
    faces.cast_vote(conn, aperta["id"], dbid, a, 5)
    faces.cast_vote(conn, aperta["id"], dbid, c, 3)

    dopo = now + timedelta(days=7)
    # una settimana avanti: weeks usa datetime solo per now()
    monkeypatch.setattr(weeks, "datetime", SimpleNamespace(now=lambda: dopo))
    tg2 = FakeTG()
    assert bot.send_weekly_recap(conn, tg2)
    assert "Faccia di merda della settimana scorsa" in tg2.sent[0][1]
    assert conn.execute(
        "SELECT face_deposit_id FROM weeks WHERE id=?", (aperta["id"],)
    ).fetchone()["face_deposit_id"] == dbid
