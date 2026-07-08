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

**Fase 1 — Motore di dominio.** Il cuore gira e ha i test verdi: ingestione
normalizzata, geo-enrich pluggable, recompute (standings/ownership/flips),
motore achievement a registry, leaderboard. Ancora niente dashboard/auth/bot
(Fasi 3-5). Gira su sola stdlib.

- [`SPEC.md`](SPEC.md) — specifica completa
- [`schema.sql`](schema.sql) — schema DB (SQLite)
- [`docs/whatsapp-import.md`](docs/whatsapp-import.md) — formato import storico
- [`conquisterco/`](conquisterco/) — il motore · [`tests/`](tests/) — la suite

## Come girare

```bash
uv run conquisterco-demo      # mondo fittizio + report end-to-end
uv run --extra dev pytest     # test
```

Il demo semina 4 giocatori e uno scenario che innesca conquiste, furti e la
gran parte dei badge, poi stampa classifica, record, feed dei flip e bacheca.

## Stack previsto

FastAPI · SQLite · `shapely` (point-in-polygon su poligoni OSM) · Leaflet/MapLibre ·
bot Telegram (input di regime) · deploy su borant.

## Principio

Il `Deposit` è l'unico dato grezzo. Ownership, classifiche, record e badge sono tutti
**derivati e ricalcolabili**: cambiare le regole non tocca lo storico, rigira il motore.
