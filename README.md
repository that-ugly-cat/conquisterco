<p align="center">
  <b>Conquisterco</b><br>
  <i>la mappa del cacasto fecale — territory-control mondiale a base fecale.</i>
</p>

---

Un gruppo di amici documenta ogni deposito con un **pin GPS + selfie**. Conquisterco
trasforma quel flusso in un gioco di conquista: chi caga di più in un comune lo
**possiede**; i comuni si **rubano** superando l'owner. Sopra ci sono leaderboard
(comuni controllati e km²), record superlativi (più a nord, più in alto, trasferta
più lontana…), achievement, e una mappa coropletica del mondo.

## Meccanica in una riga

> Owner = chi ha **strettamente** più depositi nel comune. Parità = comune conteso,
> vale zero. Rubi solo **superando** l'owner. Gli aggregati (provincia/regione/stato)
> ereditano la stessa regola: comanda chi controlla più comuni.

## Cosa c'è

- **Mappa coropletica** con Level-of-Detail sullo zoom: stato → regione → provincia →
  comune, aree tinte col colore dell'owner + bandierina; robusta anche ai paesi con
  gerarchie piatte (un "rappresentante" per comune non fa sparire nulla).
- **Modalità Dump** (dietro login): i pin dei singoli depositi, con selfie o coniglio 🐰.
- **Classifica** (comuni + km²), **record** superlativi, **feed** dei flip, **badge**
  con legenda, e una **galleria** per utente (griglia 3, più recenti in alto).
- **Profilo**: nome pubblico (≠ username), bandiera, handle Telegram, "non salvare i
  selfie", cancella-solo-selfie e cancella-tutto.
- **Admin**: crea utenti, reset password, ruoli, e **merge** account (assorbi un
  provvisorio del bot nell'account reale).
- **i18n IT/EN** con selettore in topbar; pagina **privacy**; layout responsive.
- **Bot Telegram**: ogni pin è un dump (foto opzionale, anche prima del pin), account
  provvisori reclamabili via deep-link, annunci sassy distinti (conquista/furto/pareggio
  a N, badge, record — sempre coi nomi), e **recap settimanale**.

Il motore, l'import storico e il bot sono coperti da test (`uv run --extra dev pytest`).

## Come girare (locale)

```bash
uv run conquisterco-demo                 # mondo fittizio + report su console
uv run --extra web conquisterco-serve    # dashboard su http://127.0.0.1:8077
uv run --extra dev pytest                # test
```

La dashboard, al primo avvio senza dati, semina un mondo demo. L'auth è **per
utente** (niente password condivisa): crea un admin con
`uv run conquisterco-admin <nome> --password <pw> --role admin`.

CLI: `conquisterco-serve` (web) · `conquisterco-demo` · `conquisterco-import <dir>`
(export WhatsApp) · `conquisterco-admin` · `conquisterco-recap` (recap settimanale).

## Deploy

Docker + Caddy, DB e selfie su volume `/data` (fuori dall'immagine, mai su git).
Vedi **[`DEPLOY.md`](DEPLOY.md)** (build, dati veri via `scp`, bot Telegram, cron del
recap).

## Stack

FastAPI · SQLite · `uv` · Leaflet (renderer canvas) · **Nominatim** (reverse-geocoding
comune/gerarchia/geometria, cachato) · **open-meteo** (quota da DEM) · area km² con
formula sferica (niente shapely). Deploy su borant.

## Principio

Il `Deposit` è l'unico dato grezzo. Ownership, classifiche, record, aggregati e badge
sono tutti **derivati e ricalcolabili**: cambiare le regole non tocca lo storico,
rigira il motore.

Design completo in **[`SPEC.md`](SPEC.md)**; formato import storico in
[`docs/whatsapp-import.md`](docs/whatsapp-import.md).
