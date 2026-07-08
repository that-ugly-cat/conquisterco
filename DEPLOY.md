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

## Variabili (in `docker-compose.yml`)

| var | |
|---|---|
| `CONQUISTERCO_SECRET` | **obbligatoria**: secret di sessione fisso |
| `CONQUISTERCO_DEMO` | `0` in produzione (niente auto-seed) |
| `CONQUISTERCO_DB` | `/data/conquisterco.db` |
| `CONQUISTERCO_MEDIA` | `/data/media` |
