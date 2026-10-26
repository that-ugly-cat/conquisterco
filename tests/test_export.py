"""L'export del pannello admin: cosa c'e' nello zip, e cosa NON c'e' nei file
anonimi.

Il controllo che conta e' il secondo. Un export pieno sbagliato si vede a occhio
aprendolo; un anonimo che si porta dietro una colonna di troppo si vede quando
il file e' gia' fuori dal gruppo, e allora e' tardi.
"""

import csv
import io
import zipfile

from conquisterco.app import export

from .conftest import PW_TEST, dep, entra, mkuser

COMUNE = 1001


def _tre_cacate(conn):
    """Due giocatori, tre depositi, un badge ripetibile preso due volte."""
    a = mkuser(conn, "Giovanni_S")
    b = mkuser(conn, "Martina_M")
    conn.execute("UPDATE users SET public_name='Spit' WHERE id=?", (a,))
    dep(conn, a, COMUNE, "2026-10-01 08:00:00")
    dep(conn, a, COMUNE, "2026-10-02 09:30:00")
    dep(conn, b, COMUNE, "2026-10-03 10:15:00", photo=False)
    conn.execute(
        "INSERT INTO achievements (id, code, name, description, type, points, decay)"
        " VALUES (1, 'blitz', 'Blitz', 'tre comuni', 'repeatable', 10.0, 0.8)")
    for ts in ("2026-10-01 08:00:00", "2026-10-02 09:30:00"):
        conn.execute("INSERT INTO awards (achievement_id, user_id, ts_earned, context)"
                     " VALUES (1, ?, ?, 'Bassano')", (a, ts))
    conn.commit()
    return a, b


def _leggi(blob: bytes, nome: str):
    """Un CSV dello zip come (intestazione, righe)."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        testo = z.read(nome).decode("utf-8-sig")
    righe = list(csv.DictReader(io.StringIO(testo), delimiter=";"))
    return list(righe[0].keys()) if righe else [], righe


# --- cosa c'e' dentro ------------------------------------------------------

def test_lo_zip_porta_le_tre_tabelle_nei_due_tagli_e_il_leggimi(conn):
    _tre_cacate(conn)
    with zipfile.ZipFile(io.BytesIO(export.build_zip(conn))) as z:
        assert sorted(z.namelist()) == sorted([
            "cacate.csv", "cacate-anonime.csv",
            "settimane.csv", "settimane-anonime.csv",
            "badge.csv", "badge-anonimi.csv", "LEGGIMI.txt"])


def test_i_due_tagli_hanno_le_stesse_righe(conn):
    _tre_cacate(conn)
    blob = export.build_zip(conn)
    atteso = conn.execute("SELECT COUNT(*) AS n FROM deposits").fetchone()["n"]
    for nome in ("cacate.csv", "cacate-anonime.csv"):
        _, righe = _leggi(blob, nome)
        assert len(righe) == atteso == 3
    # anonimizzare toglie colonne, non persone
    assert len(_leggi(blob, "badge.csv")[1]) == len(_leggi(blob, "badge-anonimi.csv")[1]) == 2


def test_il_leggimi_conta_le_righe_di_ogni_file(conn):
    _tre_cacate(conn)
    with zipfile.ZipFile(io.BytesIO(export.build_zip(conn))) as z:
        testo = z.read("LEGGIMI.txt").decode("utf-8")
    assert "cacate.csv" in testo and "3 righe" in testo


def test_il_csv_si_apre_in_excel_italiano(conn):
    """BOM e punto e virgola: senza, Excel mette tutto in una colonna e sbaglia
    gli accenti."""
    _tre_cacate(conn)
    with zipfile.ZipFile(io.BytesIO(export.build_zip(conn))) as z:
        grezzo = z.read("cacate.csv")
    assert grezzo.startswith(b"\xef\xbb\xbf")
    assert grezzo.split(b"\r\n")[0].count(b";") > 5


# --- cosa NON c'e' nei file anonimi ---------------------------------------

def test_l_anonimo_non_ha_le_colonne_che_identificano(conn):
    _tre_cacate(conn)
    campi, _ = _leggi(export.build_zip(conn), "cacate-anonime.csv")
    for vietata in ("utente", "username", "lat", "lon", "ora",
                    "media_ref", "raw_ref", "inserito_il_utc"):
        assert vietata not in campi
    # ...ma il comune resta: e' l'unita' del gioco
    assert {"comune", "provincia", "regione", "stato"} <= set(campi)


def test_l_anonimo_non_nomina_nessuno_in_nessun_file(conn):
    _tre_cacate(conn)
    blob = export.build_zip(conn)
    for nome in ("cacate-anonime.csv", "settimane-anonime.csv", "badge-anonimi.csv"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            testo = z.read(nome).decode("utf-8-sig")
        for vietato in ("Giovanni_S", "Spit", "Martina_M", "x.jpg"):
            assert vietato not in testo, f"{vietato} in {nome}"


def test_il_pieno_invece_dice_tutto(conn):
    _tre_cacate(conn)
    campi, righe = _leggi(export.build_zip(conn), "cacate.csv")
    assert {"utente", "username", "lat", "lon", "media_ref"} <= set(campi)
    assert righe[0]["utente"] == "Spit" and righe[0]["username"] == "Giovanni_S"
    assert righe[0]["media_ref"] == "x.jpg"
    assert righe[2]["media"] == "coniglio"       # senza selfie


def test_lo_pseudonimo_e_lo_stesso_in_ogni_tabella_e_a_ogni_export(conn):
    a, _ = _tre_cacate(conn)
    sigla = export.pseudonimo(a)
    _, cacate = _leggi(export.build_zip(conn), "cacate-anonime.csv")
    _, badge = _leggi(export.build_zip(conn), "badge-anonimi.csv")
    assert cacate[0]["giocatore"] == sigla
    assert badge[0]["giocatore"] == sigla
    # stabile: un secondo export della stessa persona da' la stessa sigla
    _, ancora = _leggi(export.build_zip(conn), "cacate-anonime.csv")
    assert ancora[0]["giocatore"] == sigla
    assert sigla != export.pseudonimo(a + 1)


def test_nessun_vincitore_non_diventa_un_giocatore(conn):
    """Una settimana contesa non ha vincitore: la cella resta vuota, non
    `giocatore-None`."""
    _tre_cacate(conn)
    conn.execute("INSERT INTO weeks (start_ts, end_ts, closed_at, winner_user_id,"
                 " contested) VALUES ('2026-09-28 00:00:00', '2026-10-04 21:30:00',"
                 " '2026-10-04 21:30:00', NULL, 1)")
    conn.commit()
    _, righe = _leggi(export.build_zip(conn), "settimane-anonime.csv")
    assert righe[0]["vincitore"] == ""
    assert righe[0]["contesa"] == "si"


# --- i badge ---------------------------------------------------------------

def test_le_prese_sono_numerate_e_la_seconda_vale_meno(conn):
    _tre_cacate(conn)
    _, righe = _leggi(export.build_zip(conn), "badge.csv")
    assert [r["presa_n"] for r in righe] == ["1", "2"]
    assert float(righe[0]["punti_presa"]) == 10.0
    assert float(righe[1]["punti_presa"]) == 8.0      # decay 0.8, sopra il pavimento


def test_i_badge_del_sistema_finiscono_nell_export(conn):
    """`manual_awards` e' una tabella a parte: pescata male, l'export perde
    esattamente i badge che un umano ha deciso a mano."""
    a, _ = _tre_cacate(conn)
    conn.execute("UPDATE achievements SET manual=1 WHERE code='blitz'")
    conn.execute("INSERT INTO achievements (id, code, name, type, manual, points, decay)"
                 " VALUES (2, 'faccia', 'Faccia di merda', 'repeatable', 1, 15.0, 0.5)")
    conn.execute("INSERT INTO manual_awards (user_id, code, ts, context)"
                 " VALUES (?, 'faccia', '2026-10-05 12:00:00', 'votata dal gruppo')", (a,))
    conn.commit()
    _, righe = _leggi(export.build_zip(conn), "badge.csv")
    sistema = [r for r in righe if r["dal_sistema"] == "si"]
    assert len(sistema) == 1
    assert sistema[0]["badge"] == "faccia"
    assert float(sistema[0]["punti_presa"]) == 15.0


def test_un_segreto_vale_doppio(conn):
    a, _ = _tre_cacate(conn)
    conn.execute("INSERT INTO achievements (id, code, name, type, secret, points, decay)"
                 " VALUES (3, 'ombra', 'Ombra', 'one_shot', 1, 10.0, 0.5)")
    conn.execute("INSERT INTO awards (achievement_id, user_id, ts_earned)"
                 " VALUES (3, ?, '2026-10-06 07:00:00')", (a,))
    conn.commit()
    _, righe = _leggi(export.build_zip(conn), "badge.csv")
    ombra = next(r for r in righe if r["badge"] == "ombra")
    assert ombra["segreto"] == "si"
    assert float(ombra["punti_presa"]) == 20.0


# --- la rotta --------------------------------------------------------------

def test_lo_scarico_resta_roba_da_admin(client):
    assert client.get("/admin/export").status_code == 401     # anonimo
    entra(client, "Tizio")
    assert client.get("/admin/export").status_code == 403     # loggato, non admin


def test_l_admin_scarica_uno_zip_col_nome_della_data(client):
    entra(client, "Capo")
    r = client.get("/admin/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert export.nome_file() in r.headers["content-disposition"]
    assert r.content.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert "cacate-anonime.csv" in z.namelist()


def test_il_pannello_mostra_il_bottone(client):
    entra(client, "Capo")
    r = client.get("/admin")
    assert '/admin/export' in r.text
    assert PW_TEST not in r.text        # la pagina non e' il posto per le password
