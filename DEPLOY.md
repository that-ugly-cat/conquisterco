# Deploy (Docker)

App FastAPI dietro Caddy. DB SQLite + selfie su volume `/data` (fuori
dall'immagine; **i dati veri non sono su git**).

## Build & run

```bash
cd /opt/app
git clone https://github.com/that-ugly-cat/conquisterco.git .   # prima volta
git pull                                                        # aggiornamenti

# secret di sessione fisso, in .env (gitignored)
echo "CONQUISTERCO_SECRET=$(openssl rand -hex 32)" > .env

docker compose up -d --build
```

Aggiornare dopo un push:
```bash
git pull && docker compose up -d --build
```

## Dati veri

`./data/conquisterco.db` + `./data/media/` sono il DB e i selfie. Portali dal PC
(non sono in git):

```powershell
scp -i <chiave> conquisterco_real.db  spit@178.105.139.118:/opt/app/data/conquisterco.db
scp -i <chiave> -r media              spit@178.105.139.118:/opt/app/data/
```
poi `docker compose restart`.

Senza DB reale e con `CONQUISTERCO_DEMO=0`, il DB parte vuoto: crea un admin
dentro al container
```bash
docker compose exec conquisterco uv run --no-sync \
  conquisterco-admin Giovanni_S --password '******' --db /data/conquisterco.db
```

## Caddy (reverse proxy)

```
conquisterco.borant.eu {
    reverse_proxy 127.0.0.1:8077
}
```

## Variabili (in `docker-compose.yml`, valori sensibili in `.env`)

| var | |
|---|---|
| `CONQUISTERCO_SECRET` | **obbligatoria**: secret di sessione fisso |
| `CONQUISTERCO_DEMO` | `0` in produzione (niente auto-seed) |
| `CONQUISTERCO_DB` / `CONQUISTERCO_MEDIA` | `/data/conquisterco.db`, `/data/media` |
| `CONQUISTERCO_PUBLIC_URL` | es. `https://conquisterco.borant.eu` (webhook + deep-link) |
| `TELEGRAM_BOT_TOKEN` | token BotFather (segreto → `.env`) |
| `TELEGRAM_WEBHOOK_SECRET` | stringa casuale: path del webhook `/tg/<secret>` |
| `TELEGRAM_CHAT_ID` | id del gruppo: i dump si accettano solo da lì |
| `TELEGRAM_BOT_USERNAME` | default `conquisterco_bot` |

## Bot Telegram

1. Nel `.env` (gitignored) sul VPS, oltre al secret di sessione:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_WEBHOOK_SECRET=<openssl rand -hex 16>
   TELEGRAM_CHAT_ID=<id del gruppo>
   ```
   L'id del gruppo lo ottieni aggiungendo il bot al gruppo e leggendo
   `chat.id` da `https://api.telegram.org/bot<token>/getUpdates`.
2. `docker compose up -d --build`. All'avvio l'app registra da sola il webhook
   (`CONQUISTERCO_PUBLIC_URL` deve essere raggiungibile via HTTPS da Caddy).
3. In BotFather disabilita la **privacy mode** del bot (`/setprivacy` → Disable)
   così riceve i messaggi normali del gruppo (pin e foto), non solo i comandi.

Ogni pin nel gruppo = un dump; la foto (entro 2 min, anche prima del pin) fa da
selfie. Chi non è agganciato ottiene un account provvisorio, reclamabile dal
profilo con **Collega Telegram** (deep-link).

## Recap settimanale (cron)

Il bot manda un riepilogo ogni **domenica alle 20:00 di Roma** tramite cron dell'host.
L'host sta in **UTC** e ci resta (nello stesso crontab ci sono i job di borant-backup,
con ore scelte in sequenza: cambiare il fuso della macchina sposterebbe anche quelli).
Quindi la riga prova a entrambe le ore UTC in cui a Roma possono essere le 20 e si
difende da sola. `crontab -e`:

```
0 18,19 * * 0  [ "$(TZ=Europe/Rome date +\%H)" = "20" ] && cd /opt/apps/conquisterco && docker compose exec -T conquisterco uv run --no-sync conquisterco-recap
```

Due trappole, entrambe pagate il 21 set 2026:

- **`CRON_TZ=Europe/Rome` non funziona qui.** È una funzione di cronie; questo è il cron
  di Debian/Ubuntu (vixie 3.0pl1) e la ignora. Verificato con una sonda: la riga sotto
  `CRON_TZ` non scattava, la stessa riga senza CRON_TZ all'ora UTC sì.
- **Il `%` va scappato con la barra rovesciata.** In un crontab significa a-capo: senza
  la barra il comando viene troncato prima del confronto e **la guardia passa sempre**,
  cioè fallisce nel modo che non si vede. Provato in tutte e due le direzioni, con un
  job che deve scattare e uno che non deve.

**Il recap non è solo un messaggio: è l'evento che chiude la settimana.** Nell'ordine
proclama la faccia di merda votata (quella della settimana prima, il cui voto si chiude
adesso), scrive il verdetto della settimana in corso, rigenera gli award e apre il voto
sui selfie appena chiusi. Il verdetto scritto non si ricalcola più, quindi **una
domenica saltata non si recupera annunciandola**: quella settimana verrà chiusa
retroattivamente sulla griglia dei lunedì, in silenzio, al primo recap successivo.

Alla **prima esecuzione dopo l'aggiornamento** il recap chiude in un colpo solo tutte le
settimane dello storico (poco meno di mezzo secondo su 600 depositi) e da lì la
classifica «settimane vinte» ha una storia. È idempotente: rilanciarlo non ne aggiunge.

La classifica della settimana è a **punti guadagnati**, col numero di cacate accanto
fra parentesi; e si punzecchia chi, pur attivo negli ultimi 30 giorni, questa settimana
non ha depositato nulla.
