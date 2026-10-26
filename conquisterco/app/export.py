"""Export dei dati del cacasto: un bottone, uno zip, sei CSV.

Tre tabelle — cacate, settimane, badge — ognuna in due tagli:

- **pieno**: nomi veri, coordinate esatte, orari al secondo e i riferimenti ai
  selfie e ai messaggi Telegram. È il backup leggibile del gioco.
- **anonimo**: pseudonimo al posto del nome, niente coordinate, niente
  riferimenti ai media, data senza ora. Resta il comune, che è l'unità del
  gioco: sotto quel livello non si scende.

Gli pseudonimi sono **stabili**, derivati dall'id utente: `giocatore-07` è la
stessa persona anche fra due export a mesi di distanza, così due scarichi si
possono confrontare nel tempo. Il prezzo è scritto nel LEGGIMI e va detto: chi
ha in mano anche un file pieno, o un export vecchio, decodifica gli pseudonimi
in un attimo. I file anonimi proteggono da chi riceve **solo quelli**.

I punti per presa non si ricalcolano qui: si chiede la differenza a
`leaderboards._decayed`, che è la funzione che decide la classifica vera. Una
seconda implementazione della stessa regola divergerebbe senza dirlo.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import zipfile

from .. import config
from ..leaderboards import _decayed
from ..util import now_local

VIDEO = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".3gp"}


def pseudonimo(uid: int | None) -> str:
    """Sigla stabile di un giocatore. Vuota per nessun giocatore (una settimana
    contesa non ha vincitore, e non deve diventare `giocatore-None`)."""
    return "" if uid is None else f"giocatore-{uid:02d}"


def _media(ref: str | None) -> str:
    """Che cosa documenta il deposito, senza dire quale file."""
    if not ref:
        return "coniglio"
    punto = ref.rfind(".")
    return "video" if punto >= 0 and ref[punto:].lower() in VIDEO else "foto"


def _si_no(v) -> str:
    return "si" if v else "no"


def _data(ts: str | None) -> str:
    """Solo il giorno di un timestamp 'YYYY-MM-DD HH:MM:SS'."""
    return (ts or "").split(" ")[0]


# --- le tre tabelle --------------------------------------------------------

_Q_CACATE = """
SELECT d.id, d.ts, d.user_id,
       COALESCE(NULLIF(u.public_name, ''), u.display_name) AS utente,
       u.display_name AS username,
       t.name AS comune, t.province AS provincia,
       t.region AS regione, t.country AS stato,
       d.territory_osm_id, d.lat, d.lon, d.altitude, d.alt_source,
       d.photo_ref, d.source, d.raw_ref, d.created_at
  FROM deposits d
  JOIN users u ON u.id = d.user_id
  LEFT JOIN territories t ON t.osm_id = d.territory_osm_id
 ORDER BY d.ts, d.id
"""


def cacate(conn: sqlite3.Connection, *, anonimo: bool) -> tuple[list[str], list[dict]]:
    """Un deposito per riga: il dato grezzo da cui tutto il resto è derivato."""
    campi = (["id", "data", "giocatore", "comune", "provincia", "regione", "stato",
              "quota_m", "media", "origine"]
             if anonimo else
             ["id", "data", "ora", "utente", "username",
              "comune", "provincia", "regione", "stato", "osm_id_comune",
              "lat", "lon", "quota_m", "quota_fonte",
              "media", "media_ref", "origine", "raw_ref", "inserito_il_utc"])
    righe = []
    for r in conn.execute(_Q_CACATE):
        data, _, ora = (r["ts"] or "").partition(" ")
        quota = "" if r["altitude"] is None else round(r["altitude"], 1)
        comune = {"comune": r["comune"] or "", "provincia": r["provincia"] or "",
                  "regione": r["regione"] or "", "stato": r["stato"] or ""}
        if anonimo:
            righe.append({"id": r["id"], "data": data,
                          "giocatore": pseudonimo(r["user_id"]), **comune,
                          "quota_m": quota, "media": _media(r["photo_ref"]),
                          "origine": r["source"]})
        else:
            righe.append({"id": r["id"], "data": data, "ora": ora,
                          "utente": r["utente"], "username": r["username"], **comune,
                          "osm_id_comune": r["territory_osm_id"] or "",
                          "lat": r["lat"], "lon": r["lon"],
                          "quota_m": quota, "quota_fonte": r["alt_source"] or "",
                          "media": _media(r["photo_ref"]),
                          "media_ref": r["photo_ref"] or "",
                          "origine": r["source"], "raw_ref": r["raw_ref"] or "",
                          "inserito_il_utc": r["created_at"]})
    return campi, righe


_Q_SETTIMANE = """
SELECT w.id, w.start_ts, w.end_ts, w.closed_at, w.contested,
       w.winner_user_id, w.face_deposit_id, w.face_closed_at,
       COALESCE(NULLIF(u.public_name, ''), u.display_name) AS vincitore,
       u.display_name AS vincitore_username,
       d.user_id AS faccia_user_id,
       COALESCE(NULLIF(f.public_name, ''), f.display_name) AS faccia
  FROM weeks w
  LEFT JOIN users u ON u.id = w.winner_user_id
  LEFT JOIN deposits d ON d.id = w.face_deposit_id
  LEFT JOIN users f ON f.id = d.user_id
 ORDER BY w.start_ts
"""


def settimane(conn: sqlite3.Connection, *, anonimo: bool) -> tuple[list[str], list[dict]]:
    """Una settimana chiusa per riga, col verdetto come il recap l'ha annunciato.

    Gli istanti delle settimane restano interi anche nel taglio anonimo: sono
    eventi del gruppo (quando è partito il recap), non di una persona."""
    campi = (["id", "inizio", "fine", "chiusa_il", "vincitore", "contesa",
              "faccia_autore", "faccia_votata_fino_al"]
             if anonimo else
             ["id", "inizio", "fine", "chiusa_il", "vincitore", "vincitore_username",
              "contesa", "faccia_deposito_id", "faccia_autore", "faccia_votata_fino_al"])
    righe = []
    for r in conn.execute(_Q_SETTIMANE):
        comune = {"id": r["id"], "inizio": r["start_ts"], "fine": r["end_ts"],
                  "chiusa_il": r["closed_at"], "contesa": _si_no(r["contested"]),
                  "faccia_votata_fino_al": r["face_closed_at"] or ""}
        if anonimo:
            righe.append({**comune,
                          "vincitore": pseudonimo(r["winner_user_id"]),
                          "faccia_autore": pseudonimo(r["faccia_user_id"])})
        else:
            righe.append({**comune,
                          "vincitore": r["vincitore"] or "",
                          "vincitore_username": r["vincitore_username"] or "",
                          "faccia_deposito_id": r["face_deposit_id"] or "",
                          "faccia_autore": r["faccia"] or ""})
    return campi, righe


_Q_BADGE = """
SELECT w.id, w.user_id, w.ts_earned AS ts, w.context,
       COALESCE(NULLIF(u.public_name, ''), u.display_name) AS utente,
       u.display_name AS username,
       a.code, a.name, a.type, a.secret, a.manual, a.points, a.decay
  FROM awards w
  JOIN achievements a ON a.id = w.achievement_id
  JOIN users u ON u.id = w.user_id
 ORDER BY w.ts_earned, w.id
"""

# I badge del Sistema stanno in `manual_awards` e non in `awards`: sono dato
# grezzo, immuni al finalize, quindi vanno pescati a parte o l'export perde
# esattamente i badge che un umano ha deciso a mano.
_Q_MANUALI = """
SELECT m.user_id, m.ts, m.context,
       COALESCE(NULLIF(u.public_name, ''), u.display_name) AS utente,
       u.display_name AS username,
       m.code, a.name, a.type, a.secret, a.points, a.decay
  FROM manual_awards m
  JOIN users u ON u.id = m.user_id
  LEFT JOIN achievements a ON a.code = m.code
 ORDER BY m.ts, m.user_id
"""


def badge(conn: sqlite3.Connection, *, anonimo: bool) -> tuple[list[str], list[dict]]:
    """Una presa di badge per riga, automatica o del Sistema.

    `presa_n` è la progressione di quel badge per quel giocatore e `punti_presa`
    quanto ha aggiunto *quella* presa: la differenza fra il valore di n prese e
    quello di n-1, moltiplicata per i segreti. È la stessa curva della
    classifica, chiesta alla funzione che la calcola."""
    campi = (["giocatore", "badge", "nome", "tipo", "segreto", "dal_sistema",
              "data", "presa_n", "punti_presa", "contesto"]
             if anonimo else
             ["id", "utente", "username", "badge", "nome", "tipo", "segreto",
              "dal_sistema", "assegnato_il", "presa_n", "punti_presa", "contesto"])

    grezze = [(r, False) for r in conn.execute(_Q_BADGE)]
    grezze += [(r, True) for r in conn.execute(_Q_MANUALI)]
    grezze.sort(key=lambda t: (t[0]["ts"] or "", t[0]["code"]))

    prese: dict[tuple[int, str], int] = {}
    righe = []
    for r, sistema in grezze:
        chiave = (r["user_id"], r["code"])
        n = prese[chiave] = prese.get(chiave, 0) + 1
        punti = r["points"] if r["points"] is not None else 0.0
        decay = r["decay"] if r["decay"] is not None else 0.5
        valore = _decayed(punti, decay, n) - _decayed(punti, decay, n - 1)
        if r["secret"]:
            valore *= config.SCORE_SECRET_MULT
        comune = {"badge": r["code"], "nome": r["name"] or r["code"],
                  "tipo": r["type"] or "", "segreto": _si_no(r["secret"]),
                  "dal_sistema": _si_no(sistema), "presa_n": n,
                  "punti_presa": round(valore, 2), "contesto": r["context"] or ""}
        if anonimo:
            righe.append({"giocatore": pseudonimo(r["user_id"]),
                          "data": _data(r["ts"]), **comune})
        else:
            righe.append({"id": "" if sistema else r["id"],
                          "utente": r["utente"], "username": r["username"],
                          "assegnato_il": r["ts"], **comune})
    return campi, righe


# --- lo zip ----------------------------------------------------------------

def _csv_bytes(campi: list[str], righe: list[dict]) -> bytes:
    """CSV col punto e virgola e il BOM: è il dialetto che Excel in italiano
    apre senza chiedere niente e senza impastare `Zürich`."""
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=campi, delimiter=";",
                       lineterminator="\r\n", extrasaction="raise")
    w.writeheader()
    w.writerows(righe)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


LEGGIMI = """\
Conquisterco — export del {quando}

Tre tabelle, due tagli ciascuna.

  cacate.csv            un deposito per riga: il dato grezzo del gioco, da cui
                        owner, classifiche, record e badge sono tutti derivati.
  settimane.csv         una settimana chiusa per riga, col verdetto come il
                        recap lo ha annunciato al gruppo (e non si ricalcola).
  badge.csv             una presa di badge per riga, automatica o del Sistema.

  *-anonime.csv         lo stesso, con lo pseudonimo al posto del nome, senza
  badge-anonimi.csv     coordinate, senza riferimenti ai selfie e ai messaggi,
                        e con la data senza ora. Resta il comune.

Gli pseudonimi sono stabili: giocatore-07 e' la stessa persona anche in un
export fra sei mesi, cosi' due scarichi si possono confrontare nel tempo.

ATTENZIONE, e vale la pena leggerlo due volte: i file anonimi sono anonimi
solo per chi riceve SOLO QUELLI. In questo zip ci sono anche i file pieni, e le
righe condividono gli stessi id: chi ha entrambi risale ai nomi in un minuto.
Se li mandi a qualcuno fuori dal gruppo, mandagli i soli file anonimi.

Le colonne, dove non si spiegano da sole:

  data / ora            orologio di Roma, come sta nel database.
  inserito_il_utc       quando la riga e' stata scritta, in UTC: serve a
                        distinguere l'import storico dal bot, non il gioco.
  quota_m               stimata dal modello del terreno, non dal telefono
                        (quota_fonte dice quale delle due).
  media                 foto, video, o coniglio se il selfie non c'e'.
  origine               whatsapp_import (storico), telegram (bot), map_manual.
  contesa               settimana con due giocatori a pari punti: non la vince
                        nessuno, come un comune in parita'.
  presa_n               la quante volte quel giocatore ha preso quel badge.
  punti_presa           quanto ha aggiunto quella presa, decadimento e
                        moltiplicatore dei segreti compresi.

{righe}
"""


NOMI = {
    "cacate.csv": (cacate, False),
    "cacate-anonime.csv": (cacate, True),
    "settimane.csv": (settimane, False),
    "settimane-anonime.csv": (settimane, True),
    "badge.csv": (badge, False),
    "badge-anonimi.csv": (badge, True),
}


def build_zip(conn: sqlite3.Connection) -> bytes:
    """Lo zip completo, in memoria: sei CSV piu' il LEGGIMI.

    In memoria e non in un file temporaneo perche' il piu' grande dei sei, sul
    database vero, sta sotto il mezzo megabyte: un export che pesa meno di un
    selfie non ha bisogno di toccare il disco del server."""
    buf = io.BytesIO()
    conteggi = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, (fn, anonimo) in NOMI.items():
            campi, righe = fn(conn, anonimo=anonimo)
            z.writestr(nome, _csv_bytes(campi, righe))
            conteggi.append(f"  {nome:24s} {len(righe)} righe")
        z.writestr("LEGGIMI.txt", LEGGIMI.format(
            quando=now_local().strftime("%d/%m/%Y alle %H:%M"),
            righe="\n".join(conteggi)).encode("utf-8"))
    return buf.getvalue()


def nome_file(oggi=None) -> str:
    return f"conquisterco-export-{(oggi or now_local()).strftime('%Y%m%d')}.zip"
