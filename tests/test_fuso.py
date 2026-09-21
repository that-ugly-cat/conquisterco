"""L'orologio del cacasto: ora locale italiana, scritta dal codice.

Il 21 set 2026 si e' scoperto che il bot salvava l'ora UTC. Il sintomo non era
un errore ma una statistica assurda: 172 cacate fra le 4 e le 6 del mattino in
due mesi e mezzo, contro 2 negli otto anni di import WhatsApp. Erano le 6-8, e
133 "Alba del Nuovo Regno" su 135 erano andate a gente che cagava alle 7
passate.

Qui si fissa che la conversione **non dipende dal fuso del processo**. Non lo
si prova spostando `TZ` (su Windows non si puo', e la macchina di Spit e' gia'
sull'ora di Roma, quindi un test cosi' passerebbe per il motivo sbagliato): lo
si prova convertendo istanti assoluti noti, che e' la stessa cosa detta bene.
"""

from datetime import datetime, timezone

from conquisterco.app.bot import _msg_ts
from conquisterco.util import ROME, local_from_epoch, now_local, parse_ts, ts_now


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp()


def test_epoch_diventa_ora_italiana():
    # 04:30 UTC del 21 set 2026 sono le 06:30 in Italia (ora legale)
    assert local_from_epoch(_utc(2026, 9, 21, 4, 30)) == datetime(2026, 9, 21, 6, 30)


def test_ora_solare_e_ora_legale_si_distinguono():
    """Non e' un +2 fisso: a gennaio l'Italia e' a +1. Serve saperlo prima di
    scrivere un backfill a mano con '+2 hours', che e' giusto solo dentro
    l'ora legale."""
    assert local_from_epoch(_utc(2026, 7, 1, 10)).hour == 12
    assert local_from_epoch(_utc(2026, 1, 1, 10)).hour == 11


def test_msg_ts_del_bot_e_ora_italiana():
    """La cacata delle 7 del mattino deve stare in tabella alle 7, non alle 5:
    e' su quel numero che scattano Turno di Notte e Alba del Nuovo Regno."""
    assert _msg_ts({"date": _utc(2026, 9, 21, 5)}) == "2026-09-21 07:00:00"


def test_msg_ts_senza_data_non_esplode():
    """Telegram la manda sempre, ma il default era gia' li' e il codice nuovo
    non deve rompere quel caso."""
    assert len(_msg_ts({})) == 19


def test_now_local_e_ts_now_concordano_e_sono_nel_formato_della_tabella():
    s = ts_now()
    assert len(s) == 19 and s[10] == " "
    assert abs((parse_ts(s) - now_local()).total_seconds()) < 5
    assert abs((parse_ts(s) - datetime.now(ROME).replace(tzinfo=None)).total_seconds()) < 5


def test_il_datetime_now_di_sqlite_non_e_l_orologio_del_gioco(conn):
    """`stitico_periods.from_ts` e `selfie_votes.ts` si confrontano con
    `deposits.ts`, che e' ora locale. Il `datetime('now')` di SQLite e' UTC
    sempre, in qualunque container: finche' lo si usava, i due estremi vivevano
    su orologi diversi e la cosa non si vedeva solo perche' anche il container
    era in UTC. Questo test dice di quanto sbaglierebbe, oggi."""
    sqlite_now = conn.execute("SELECT datetime('now')").fetchone()[0]
    scarto = (parse_ts(ts_now()) - parse_ts(sqlite_now)).total_seconds()
    assert 3595 <= scarto <= 7205   # +1h d'inverno, +2h d'estate
