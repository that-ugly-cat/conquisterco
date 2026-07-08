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

Ogni pin nel gruppo = un dump; la foto (entro 5 min, anche prima del pin) fa da
selfie. Chi non è agganciato ottiene un account provvisorio, reclamabile dal
profilo con **Collega Telegram** (deep-link).
