"""CLI del recap settimanale — da schedulare via cron (Domenica 20:00).

    conquisterco-recap

Calcola la settimana corrente e manda il recap al gruppo Telegram (usa
TELEGRAM_CHAT_ID / TELEGRAM_BOT_TOKEN dall'ambiente). Vedi DEPLOY.md.
"""

from __future__ import annotations

import os

from ..db import connect
from . import bot


def main() -> None:
    conn = connect(os.environ.get("CONQUISTERCO_DB", "conquisterco_real.db"))
    if bot.send_weekly_recap(conn):
        print("recap inviato al gruppo")
    else:
        print("niente da inviare (nessun attivo, o TELEGRAM_CHAT_ID/token mancanti)")


if __name__ == "__main__":
    main()
