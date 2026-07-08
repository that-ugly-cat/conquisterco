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

**Fase 0 — Spec.** Nessun codice ancora. Il design vive in:

- [`SPEC.md`](SPEC.md) — specifica completa
- [`schema.sql`](schema.sql) — schema DB (SQLite)
- [`docs/whatsapp-import.md`](docs/whatsapp-import.md) — formato import storico

## Stack previsto

FastAPI · SQLite · `shapely` (point-in-polygon su poligoni OSM) · Leaflet/MapLibre ·
bot Telegram (input di regime) · deploy su borant.

## Principio

Il `Deposit` è l'unico dato grezzo. Ownership, classifiche, record e badge sono tutti
**derivati e ricalcolabili**: cambiare le regole non tocca lo storico, rigira il motore.
