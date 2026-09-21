"""Faccia di merda della settimana: i selfie si votano, uno vince.

Il recap della domenica chiude la settimana e apre il voto sui selfie di quella
settimana. Si vota fino al recap successivo, che proclama e chiude. Una
settimana ha quindi un solo voto aperto alla volta, e il voto vive dentro la
settimana che l'ha generato.

I voti sono **dato grezzo**, non derivato: stanno in `selfie_votes`, il
`finalize` non li tocca, e il badge della faccia di merda si rilegge da
`weeks.face_deposit_id` come i badge manuali si rileggono da `manual_awards`.

Punteggio di un selfie = **somma** dei voti ricevuti, non media: chi raccoglie
più merda vince, e tre persone che ti danno 2 battono una che ne dà 5. Parita'
= nessuna proclamazione, la stessa regola dei comuni.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config, visibilita
from .util import is_video


def open_vote_week(conn: sqlite3.Connection) -> dict | None:
    """La settimana il cui voto e' aperto: l'ultima chiusa che non ha ancora
    proclamato. None se non c'e' niente da votare."""
    r = conn.execute(
        """SELECT * FROM weeks WHERE face_closed_at IS NULL
           ORDER BY end_ts DESC LIMIT 1""").fetchone()
    return dict(r) if r else None


def candidates(conn: sqlite3.Connection, week_id: int, voter_id: int | None = None,
               media_dir=None) -> list[dict]:
    """I selfie in gara per una settimana, col voto di chi guarda. Solo i
    depositi con foto o video: chi non ha caricato niente non e' in gara.

    Con `media_dir` si scartano anche i `photo_ref` che puntano a un file che
    non c'e'. Sulla produzione sono nove su 1252, e in galleria passano per
    immagini rotte — ma qui diventerebbero riquadri grigi su cui si puo'
    comunque votare, che e' peggio: un voto dato a niente."""
    w = conn.execute("SELECT start_ts, end_ts FROM weeks WHERE id=?", (week_id,)).fetchone()
    if w is None:
        return []
    rows = conn.execute(
        """SELECT d.id, d.ts, d.photo_ref, d.user_id,
                  COALESCE(u.public_name, u.display_name) AS author,
                  t.name AS comune,
                  (SELECT score FROM selfie_votes v
                    WHERE v.week_id=? AND v.deposit_id=d.id AND v.voter_id=?) AS my_vote
           FROM deposits d
           JOIN users u ON u.id = d.user_id
           LEFT JOIN territories t ON t.osm_id = d.territory_osm_id
           WHERE d.photo_ref IS NOT NULL AND d.ts >= ? AND d.ts < ?
           ORDER BY d.ts""",
        (week_id, voter_id, w["start_ts"], w["end_ts"])).fetchall()
    out = []
    base = Path(media_dir).resolve() if media_dir else None
    in_gara = visibilita.in_gara_al_voto(conn)
    for r in rows:
        if r["user_id"] not in in_gara:
            continue      # selfie ristretto: fuori dal voto (vedi visibilita.py)
        if not config.FACE_SELF_VOTE and voter_id is not None and r["user_id"] == voter_id:
            continue      # i propri selfie non si votano: non compaiono proprio
        if base is not None:
            f = (base / r["photo_ref"]).resolve()
            if not (str(f).startswith(str(base)) and f.exists()):
                continue  # file sparito: fuori gara, non un riquadro grigio
        out.append({"id": r["id"], "ts": r["ts"], "author": r["author"],
                    "user_id": r["user_id"], "comune": r["comune"],
                    "is_video": is_video(r["photo_ref"]), "my_vote": r["my_vote"]})
    return out


def _eligible(conn: sqlite3.Connection, week_id: int, deposit_id: int, voter_id: int) -> bool:
    """Il selfie e' di questa settimana, ha una foto, e non e' del votante."""
    r = conn.execute(
        """SELECT d.user_id FROM deposits d JOIN weeks w ON w.id = ?
           WHERE d.id = ? AND d.photo_ref IS NOT NULL
             AND d.ts >= w.start_ts AND d.ts < w.end_ts""",
        (week_id, deposit_id)).fetchone()
    if r is None:
        return False
    if r["user_id"] not in visibilita.in_gara_al_voto(conn):
        return False      # non basta nasconderlo: il voto va anche rifiutato
    return config.FACE_SELF_VOTE or r["user_id"] != voter_id


def cast_vote(conn: sqlite3.Connection, week_id: int, deposit_id: int,
              voter_id: int, score: int) -> bool:
    """Vota (o cambia voto). False se il voto e' chiuso, il selfie non e' in
    gara o il punteggio e' fuori scala."""
    if not 1 <= score <= config.FACE_MAX_VOTE:
        return False
    w = conn.execute("SELECT face_closed_at FROM weeks WHERE id=?", (week_id,)).fetchone()
    if w is None or w["face_closed_at"] is not None:
        return False
    if not _eligible(conn, week_id, deposit_id, voter_id):
        return False
    conn.execute(
        """INSERT INTO selfie_votes (week_id, deposit_id, voter_id, score)
           VALUES (?,?,?,?)
           ON CONFLICT(week_id, deposit_id, voter_id) DO UPDATE SET
             score=excluded.score, ts=datetime('now')""",
        (week_id, deposit_id, voter_id, score))
    conn.commit()
    return True


def clear_vote(conn: sqlite3.Connection, week_id: int, deposit_id: int, voter_id: int) -> bool:
    """L'undo: cancella il proprio voto. False se il voto e' gia' chiuso."""
    w = conn.execute("SELECT face_closed_at FROM weeks WHERE id=?", (week_id,)).fetchone()
    if w is None or w["face_closed_at"] is not None:
        return False
    conn.execute(
        "DELETE FROM selfie_votes WHERE week_id=? AND deposit_id=? AND voter_id=?",
        (week_id, deposit_id, voter_id))
    conn.commit()
    return True


def tally(conn: sqlite3.Connection, week_id: int) -> list[dict]:
    """Spoglio: per selfie, merda totale e quanti l'hanno votato. Ordinato.

    **Esclude chi non e' piu' in gara.** Filtrare i candidati e rifiutare i
    voti nuovi non basta: chi passa a «ristretto» a meta' settimana si porta
    dietro i voti gia' presi, e senza questo filtro potrebbe vincere — con
    proclamazione a nome suo su un selfie che nessuno puo' piu' vedere. I voti
    restano in tabella e tornerebbero a contare se tornasse pubblico: erano
    stati dati onestamente su un selfie allora visibile."""
    in_gara = visibilita.in_gara_al_voto(conn)
    return [dict(r) for r in conn.execute(
        """SELECT v.deposit_id, SUM(v.score) AS total, COUNT(*) AS voters,
                  d.user_id, COALESCE(u.public_name, u.display_name) AS author
           FROM selfie_votes v
           JOIN deposits d ON d.id = v.deposit_id
           JOIN users u ON u.id = d.user_id
           WHERE v.week_id = ?
           GROUP BY v.deposit_id
           ORDER BY total DESC, voters DESC""", (week_id,))
        if r["user_id"] in in_gara]


def elect(conn: sqlite3.Connection, week_id: int, *, now: str | None = None) -> dict | None:
    """Chiude il voto e proclama. Ritorna il vincitore, o None se non si elegge
    nessuno — troppo pochi votanti, oppure parita' in testa. In entrambi i casi
    il voto si chiude lo stesso: una settimana non resta aperta in eterno."""
    w = conn.execute("SELECT face_closed_at FROM weeks WHERE id=?", (week_id,)).fetchone()
    if w is None or w["face_closed_at"] is not None:
        return None
    rows = tally(conn, week_id)
    voters = {r["voter_id"] for r in conn.execute(
        "SELECT DISTINCT voter_id FROM selfie_votes WHERE week_id=?", (week_id,))}
    winner = None
    if rows and len(voters) >= config.FACE_MIN_VOTERS:
        top = rows[0]
        rivals = [r for r in rows if r["total"] == top["total"] and r["voters"] == top["voters"]]
        if len(rivals) == 1:
            winner = top
    conn.execute(
        "UPDATE weeks SET face_deposit_id=?, face_closed_at=COALESCE(?, datetime('now')) WHERE id=?",
        (winner["deposit_id"] if winner else None, now, week_id))
    conn.commit()
    return winner
