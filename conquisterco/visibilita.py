"""Chi può vedere i selfie di chi.

Un selfie è l'unico dato del cacasto che riguarda una persona e non un
territorio, quindi è l'unico che ha bisogno di un permesso. Tutto il resto —
pin, conquiste, punteggi — è pubblico per costruzione.

Tre livelli, dichiarati dal proprietario nel suo profilo:

    pubblico    chiunque abbia un account (era il comportamento unico)
    ristretto   io, gli admin, e una lista di persone che scelgo
    niente      nessuno, e il bot non lo salva nemmeno

`niente` prende il posto del vecchio flag `no_selfie`: erano la stessa domanda
fatta due volte, e due flag che dicono cose vicine divergono sempre.

**Il controllo sta in un posto solo** perché un selfie esce da cinque: la rotta
che serve i byte, la galleria, i pin della mappa, i candidati al voto della
faccia di merda e la foto che il recap manda in chat. Sparpagliare la regola
significherebbe, prima o poi, dimenticarne una — e dimenticarne una qui vuol
dire pubblicare la foto di qualcuno che aveva chiesto di no.

Cosa questo NON fa, e va detto a chi lo usa: i file stanno in chiaro sul volume
`/data`, finiscono nel backup, e un admin del sito li vede tutti. «Ristretto»
vuol dire ristretto **fra i giocatori**, non cifrato.
"""

from __future__ import annotations

import sqlite3

PUBBLICO = "pubblico"
RISTRETTO = "ristretto"
NIENTE = "niente"
LIVELLI = (PUBBLICO, RISTRETTO, NIENTE)


def livello(conn: sqlite3.Connection, proprietario: int) -> str:
    r = conn.execute("SELECT selfie_visibility FROM users WHERE id=?",
                     (proprietario,)).fetchone()
    return (r["selfie_visibility"] if r else PUBBLICO) or PUBBLICO


def salva_i_selfie(conn: sqlite3.Connection, proprietario: int) -> bool:
    """Il bot deve tenere il selfie di questo utente? Falso solo per `niente`."""
    return livello(conn, proprietario) != NIENTE


def ammessi(conn: sqlite3.Connection, proprietario: int) -> list[int]:
    """Gli id che il proprietario ha messo nella propria lista."""
    return [r["viewer_user_id"] for r in conn.execute(
        "SELECT viewer_user_id FROM selfie_grants WHERE owner_user_id=? ORDER BY viewer_user_id",
        (proprietario,))]


def imposta_ammessi(conn: sqlite3.Connection, proprietario: int, spettatori: list[int]) -> None:
    conn.execute("DELETE FROM selfie_grants WHERE owner_user_id=?", (proprietario,))
    conn.executemany(
        "INSERT OR IGNORE INTO selfie_grants (owner_user_id, viewer_user_id) VALUES (?,?)",
        [(proprietario, s) for s in spettatori if s != proprietario])
    conn.commit()


def proprietari_visibili(conn: sqlite3.Connection, spettatore: int | None,
                         *, admin: bool = False) -> set[int]:
    """Gli utenti di cui `spettatore` può vedere i selfie.

    Ritorna un insieme invece di rispondere una riga alla volta perché le
    superfici che contano (galleria, mappa, voto) lavorano su liste, e una
    query per foto sarebbe una query per foto."""
    if spettatore is None:
        return set()                     # senza login non si vede nessun selfie
    visti = {spettatore}                 # i propri si vedono sempre
    for r in conn.execute("SELECT id, selfie_visibility FROM users"):
        liv = r["selfie_visibility"] or PUBBLICO
        if liv == PUBBLICO or (admin and liv != NIENTE):
            visti.add(r["id"])
    for r in conn.execute("SELECT owner_user_id FROM selfie_grants WHERE viewer_user_id=?",
                          (spettatore,)):
        visti.add(r["owner_user_id"])
    return visti


def puo_vedere(conn: sqlite3.Connection, spettatore: int | None, proprietario: int,
               *, admin: bool = False) -> bool:
    """Il caso singolo, per la rotta che serve i byte."""
    return proprietario in proprietari_visibili(conn, spettatore, admin=admin)


def in_gara_al_voto(conn: sqlite3.Connection) -> set[int]:
    """Chi può finire nel voto della faccia di merda: solo i `pubblico`.

    Un selfie ristretto messo ai voti sarebbe mostrato a tutti, e il vincitore
    verrebbe pure ripubblicato in chat dal recap — cioè esattamente dove la
    modalità privata l'aveva tolto. Quindi chi si mette in ristretto **esce dal
    gioco della faccia di merda**: è il prezzo, ed è esplicito."""
    return {r["id"] for r in conn.execute(
        "SELECT id FROM users WHERE COALESCE(selfie_visibility,?)=?", (PUBBLICO, PUBBLICO))}
