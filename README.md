<p align="center">
  <b>Conquisterco</b><br>
  <i>Il Cacasto — territory-control mondiale a base fecale.</i>
</p>

---

Un gruppo di amici documenta ogni deposito con un **pin GPS + selfie**. Conquisterco
trasforma quel flusso in un gioco di conquista: chi caga di più in un comune lo
**possiede**; i comuni si **rubano** superando l'owner. Sopra ci sono leaderboard
globali (comuni controllati e km²), record superlativi (più a nord, più in alto,
trasferta più lontana…) e achievement.

## Meccanica in una riga

> Owner = chi ha **strettamente** più depositi nel comune. Parità = comune conteso,
> vale zero. Rubi solo **superando** l'owner.

## Stato

**Fase 3 — Dashboard.** Sopra il motore di Fase 1 c'è una web app FastAPI +
Leaflet: mappa con modalità **Territori** (pin colorati per owner) e **Dump**
(pin dei singoli depositi con selfie / coniglio 🐰), pannello classifica
(comuni + km²), record superlativi, feed dei flip e profilo giocatore con
bacheca badge. Login minimale a password condivisa che fa da gate ai pin dump.
Ancora da fare: import storico (Fase 2), gestione utenti/admin (Fase 4), bot
Telegram (Fase 5), geocoder OSM reale.

- [`SPEC.md`](SPEC.md) — specifica completa
- [`schema.sql`](schema.sql) — schema DB (SQLite)
- [`docs/whatsapp-import.md`](docs/whatsapp-import.md) — formato import storico
- [`conquisterco/`](conquisterco/) — motore + `app/` (dashboard) · [`tests/`](tests/) — suite

## Come girare

```bash
uv run conquisterco-demo             # mondo fittizio + report su console
uv run --extra web conquisterco-serve   # dashboard su http://127.0.0.1:8077
uv run --extra dev pytest            # test
```

La dashboard, al primo avvio, semina un mondo demo (4 giocatori, scenario che
innesca conquiste/furti/badge). Password di default `cacca`
(`CONQUISTERCO_PASSWORD`), DB in `conquisterco.db` (`CONQUISTERCO_DB`).

## Stack previsto

FastAPI · SQLite · `shapely` (point-in-polygon su poligoni OSM) · Leaflet/MapLibre ·
bot Telegram (input di regime) · deploy su borant.

## Principio

Il `Deposit` è l'unico dato grezzo. Ownership, classifiche, record e badge sono tutti
**derivati e ricalcolabili**: cambiare le regole non tocca lo storico, rigira il motore.
