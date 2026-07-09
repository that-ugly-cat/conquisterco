"""Test dei badge temporali / assiduità / selfie + occultamento dei segreti.
Usano il catalogo fittizio di base (fixture conftest)."""

from datetime import datetime, timedelta

from conquisterco.achievements import evaluate
from conquisterco.app import data
from conquisterco.pipeline import run_all

from .conftest import dep


def _codes(conn, geo):
    run_all(conn, geo)
    out: dict[int, set] = {}
    for a in evaluate(conn):
        out.setdefault(a.user_id, set()).add(a.code)
    return out


def test_turno_notte_e_alba(conn, geo):
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    dep(conn, a, 1012, "2026-05-01 03:30:00")   # notte
    dep(conn, a, 1012, "2026-05-02 06:15:00")   # alba
    c = _codes(conn, geo)[a]
    assert "turno_notte" in c
    assert "alba_regno" in c


def test_natale_e_bisesto(conn, geo):
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    dep(conn, a, 1012, "2024-02-29 10:00:00")   # anno bisestile
    dep(conn, a, 1012, "2026-12-25 10:00:00")   # Natale
    c = _codes(conn, geo)[a]
    assert "anno_bisesto" in c
    assert "natale_fecale" in c


def test_capodanno_e_ultima_di_gruppo(conn, geo):
    """Superlativi di gruppo: la prima e l'ultima cacata dell'anno tra TUTTI gli
    utenti — un solo detentore per anno, non uno per utente."""
    from datetime import date

    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    b = add_user(conn, "B")
    ly = date.today().year - 1                    # anno concluso
    dep(conn, a, 1012, f"{ly}-01-05 10:00:00")    # A: prima del gruppo
    dep(conn, b, 1003, f"{ly}-06-01 10:00:00")    # B: in mezzo (né primo né ultimo)
    dep(conn, a, 1005, f"{ly}-12-20 10:00:00")    # A: ultima del gruppo
    codes = _codes(conn, geo)
    assert "capodanno" in codes[a] and "ultima_chiamata" in codes[a]
    assert "capodanno" not in codes.get(b, set())         # B non è il primo del gruppo
    assert "ultima_chiamata" not in codes.get(b, set())   # né l'ultimo


def test_ultima_chiamata_non_scatta_per_anno_in_corso(conn, geo):
    """Regressione: nell'anno in corso 'l'ultima cacata' cambia a ogni dump, quindi
    NON deve assegnare il badge (altrimenti lo si ri-prende in continuazione)."""
    from datetime import date

    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    ty = date.today().year
    dep(conn, a, 1012, f"{ty}-01-05 10:00:00")
    dep(conn, a, 1012, f"{ty}-02-05 10:00:00")   # ultima "finora" dell'anno in corso
    assert "ultima_chiamata" not in _codes(conn, geo).get(a, set())


def test_streak_e_selfie(conn, geo):
    """50 depositi con foto in 50 giorni consecutivi → orologio(7), metronomo(30),
    pilastro(50 giorni), gallerista(50 selfie)."""
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    start = datetime(2026, 1, 1, 10, 0, 0)
    for i in range(50):
        ts = (start + timedelta(days=i)).strftime("%Y-%m-%d %H:%M:%S")
        dep(conn, a, 1012, ts, photo=True)
    c = _codes(conn, geo)[a]
    assert {"orologio", "metronomo", "pilastro", "gallerista"} <= c
    assert "archivista" not in c   # servono 100 selfie


def test_badge_holders_e_descrizione_profilo(conn, geo):
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    b = add_user(conn, "B")
    dep(conn, a, 1012, "2026-04-01 10:00:00")   # A colonizza Roma
    dep(conn, b, 1001, "2026-04-01 10:00:00")   # B colonizza Aosta
    run_all(conn, geo)

    holders = {h["name"] for h in data.badge_holders(conn, "colonizzatore")}
    assert {"A", "B"} <= holders

    # profilo: ogni badge porta code + descrizione (tradotta col dict fornito)
    prof = data.profile(conn, a, {"ach_colonizzatore_d": "testo come-si-prende"})
    byc = {x["code"]: x for x in prof["badges"]}
    assert "colonizzatore" in byc
    assert byc["colonizzatore"]["description"] == "testo come-si-prende"


def test_punteggio_ordina_la_classifica(conn, geo):
    from conquisterco.ingest import add_user
    from conquisterco.leaderboards import main_leaderboard
    a = add_user(conn, "A")
    b = add_user(conn, "B")
    dep(conn, a, 1012, "2026-04-01 10:00:00")   # Roma
    dep(conn, b, 1003, "2026-04-01 10:00:00")   # Milano
    run_all(conn, geo)
    lb = main_leaderboard(conn)
    assert all("score" in r for r in lb)
    scores = [r["score"] for r in lb]
    assert scores == sorted(scores, reverse=True)   # ordinata per punteggio desc


def test_badge_ripetibili_una_volta_e_segreti_doppi(conn, geo):
    from conquisterco import config
    from conquisterco.ingest import add_user
    from conquisterco.leaderboards import _badge_counts, _score
    a = add_user(conn, "A")
    dep(conn, a, 1012, "2025-01-01 10:00:00")   # colonizzatore + capodanno'25 + ultima'25
    dep(conn, a, 1012, "2026-01-01 10:00:00")   # capodanno'26 + ultima'26 (ripetibili ×2)
    b = add_user(conn, "B")
    dep(conn, b, 1005, "2026-05-01 10:00:00")   # Venezia → serenissima (SEGRETO) + altri
    run_all(conn, geo)

    nb_a, sb_a = _badge_counts(conn)[a]
    assert nb_a == 3 and sb_a == 0            # ripetibili contano una volta per tipo
    nb_b, sb_b = _badge_counts(conn)[b]
    assert sb_b >= 1                           # serenissima è segreto
    # il segreto pesa doppio nella somma
    assert _score(0, 0, (nb_b, sb_b)) == config.SCORE_PT_BADGE * (nb_b + config.SCORE_SECRET_MULT * sb_b)


def test_gatto_sul_cesso_manuale_sopravvive_al_finalize(conn, geo):
    """Badge assegnato dal Sistema via manual_awards: scatta e NON viene azzerato
    dal finalize (le regole lo ri-derivano dalla tabella persistente)."""
    from conquisterco.ingest import add_user
    a = add_user(conn, "Tiglia")
    dep(conn, a, 1012, "2025-01-18 10:34:00")
    conn.execute("INSERT INTO manual_awards (user_id, code, ts, context) VALUES (?, 'gatto_sul_cesso', ?, ?)",
                 (a, "2025-01-18 10:34:00", "colta sul fatto"))
    conn.commit()
    assert "gatto_sul_cesso" in _codes(conn, geo).get(a, set())   # run_all fa anche finalize
    # verifica che sia PERSISTITO negli awards (sopravvissuto al DELETE/re-insert)
    awarded = {r["code"] for r in conn.execute(
        "SELECT a.code FROM awards w JOIN achievements a ON a.id=w.achievement_id WHERE w.user_id=?", (a,))}
    assert "gatto_sul_cesso" in awarded


def test_segreti_nascosti_dalla_legenda_ma_assegnati(conn, geo):
    """Un badge segreto scatta e finisce negli award, ma NON compare nella
    legenda pubblica del modale."""
    from conquisterco.ingest import add_user
    a = add_user(conn, "A")
    # Venezia (1005) = Serenissima Deposizione (segreto)
    dep(conn, a, 1005, "2026-05-01 10:00:00")
    run_all(conn, geo)

    legend_codes = {b["code"] for b in data.achievements(conn)}
    assert "serenissima" not in legend_codes            # nascosto dalla legenda
    awarded = {r["code"] for r in conn.execute(
        "SELECT a.code FROM awards w JOIN achievements a ON a.id=w.achievement_id")}
    assert "serenissima" in awarded                     # ma assegnato davvero
