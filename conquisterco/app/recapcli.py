"""CLI del recap settimanale — da schedulare via cron (domenica 21:30, ora di Roma).

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
    media = os.environ.get("CONQUISTERCO_MEDIA", "media")
    if bot.send_weekly_recap(conn, media_dir=media):
        print("recap inviato al gruppo")
    else:
        print("niente da inviare (nessun attivo, o TELEGRAM_CHAT_ID/token mancanti)")


if __name__ == "__main__":
    main()
