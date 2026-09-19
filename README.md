<p align="center">
  <b>Conquisterco</b><br>
  <i>la mappa del cacasto fecale — territory-control mondiale a base fecale.</i>
</p>

---

Un gruppo di amici documenta ogni deposito con un **pin GPS + selfie**. Conquisterco
trasforma quel flusso in un gioco di conquista: chi caga di più in un comune lo
**possiede**; i comuni si **rubano** superando l'owner. Sopra ci sono un **punteggio**
combinato, leaderboard (comuni controllati e km²), record superlativi (più a nord, più
in alto, trasferta più lontana…), oltre 50 achievement, e una mappa coropletica del mondo.

## Meccanica in una riga

> Owner = chi ha **strettamente** più depositi nel comune. Parità = comune conteso,
> vale zero. Rubi solo **superando** l'owner. Gli aggregati (provincia/regione/stato)
> ereditano la stessa regola: comanda chi controlla più comuni.

## Cosa c'è

- **Mappa coropletica** con Level-of-Detail sullo zoom: stato → regione → provincia →
  comune, aree tinte col colore dell'owner + bandierina; robusta anche ai paesi con
  gerarchie piatte (un "rappresentante" per comune non fa sparire nulla).
- **Modalità Dump** (dietro login): i pin dei singoli depositi con selfie/video o
  coniglio 🐰; i pin densi si aggregano e si aprono a **ventaglio** (spiderfy) al
  passaggio del mouse.
- **Punteggio** combinato (comuni · km² · badge, badge segreti ×2 — pesi in `config.py`)
  che ordina la **classifica**; colonna comuni/km² come tie-break. In classifica compare
  chiunque abbia giocato, con la **bandiera** del giocatore accanto al nome. I badge
  danno **sempre** punti, anche i ripetibili presi più volte: il valore cala a ogni
  ripetizione ma non scende mai sotto metà del punteggio pieno.
- **Settimane**: il recap della domenica chiude la settimana e ne scrive il verdetto, che
  poi non si ricalcola più. La vince chi ha guadagnato più **punti**, non chi ha cagato
  di più; parità = settimana contesa. Da lì una seconda classifica: **settimane vinte su
  settimane giocate**, con due soglie per entrare in graduatoria — un
  minimo di settimane giocate e un minimo di cacate recenti, così conta esserci adesso e
  non solo esserci stati. Chi non ci arriva compare comunque, in coda.
- **Faccia di merda della settimana**: il recap apre il voto sui selfie appena chiusi —
  si vota dal sito con cinque 💩 in overlay (con undo, e non sui propri) — e il recap
  dopo proclama chi ha raccolto più merda, che si becca un badge.
- **Cacca Nautica**: una cacata in acqua non ha un comune, quindi per il motore non
  esiste — non conquista niente e non fa punteggio. Questo badge è l'unica cosa che la
  vede.
- **Gnnn!**: chi si dichiara stitico prende un badge a punti fissi a ogni cacata. La
  dichiarazione è tenuta a periodi, così toglierla non cancella quello che hai già preso.
- **Record** superlativi, **feed** dei flip, **badge** (>50) con legenda: la scritta
  "N l'hanno preso" apre chi ce l'ha, il nome-badge apre "come si prende". **Galleria**
  per utente: i selfie si aprono in un **modale** (foto o video) con comune, data,
  numero progressivo, quota e bottone "vedi sulla mappa".
- **Visibilità dei selfie** a tre livelli: pubblici, **ristretti** (io, gli admin e una
  lista che scelgo — e in cambio si esce dal voto della faccia di merda), oppure non
  salvati affatto. Il controllo sta in un posto solo, perché un selfie esce da cinque.
- **Profilo**: rank e punteggio, bacheca badge cliccabili, nome pubblico (≠ username),
  bandiera, handle Telegram, "non salvare i selfie", cancella-solo-selfie e cancella-tutto.
- **Admin**: crea utenti, reset password, ruoli, **merge** account, **messaggi liberi
  al gruppo** via bot, e **assegnazione/revoca di badge speciali** ("li dà il Sistema").
- **i18n IT/EN** con selettore in topbar; pagina **privacy**; layout responsive.
- **Bot Telegram**: ogni pin è un dump (foto/video opzionale, anche prima del pin),
  account provvisori reclamabili via deep-link, annunci sassy distinti (conquista/furto/
  pareggio a N, badge — con **notifica speciale per i segreti** —, record, sempre coi
  nomi), **recap settimanale** col **podio a punti**, e ~50 **trigger testuali** che
  rispondono a parole chiave in chat.

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
