# Conquisterco — Spec

*Il Cacasto: territory-control mondiale a base fecale.*

*Versione: 1.0 (finalizzata) — luglio 2026*

---

## 0. Premessa

Un gruppo di amici documenta ogni deposito con un **pin GPS + selfie**. Conquisterco
trasforma quel flusso in un gioco di conquista territoriale: chi caga di più in un
comune lo **possiede**; i comuni si **rubano** superando l'owner. Sopra ci sono
leaderboard globali, record superlativi e achievement.

**Principio guida:** il `Deposit` è l'unico dato grezzo. Ownership, classifiche,
record e badge sono tutti **derivati e ricalcolabili**. Se cambiamo le regole non
tocchiamo lo storico: rigiriamo il motore.

---

## 1. Concetti core

| Termine | Significato |
|---|---|
| **Deposito** (dump) | Evento atomico: un utente, un istante, una coordinata, un selfie. L'unica cosa che i giocatori producono davvero. |
| **Territorio** | Unità amministrativa possedibile. Sempre il **comune**, identificato da `osm_id`. |
| **Owner** | Utente con **strettamente** più depositi nel territorio. |
| **Contested** | Territorio in parità: nessun owner, grigio, vale zero finché la parità non si rompe. |
| **Flip** | Cambio di owner (o da neutro a posseduto). Unità narrativa del feed. |

---

## 2. Regole di ownership

- **Owner = conteggio massimo in modo stretto.** 3 vs 3 = contested.
- **Rubare = superare.** Se l'owner ha 3, per prendere il comune ne servono 4.
- **Prima mossa conta:** i comuni sono "appiccicosi". È voluto.
- **Parità = contested (grigio), vale 0.**
- Depositi multipli nello stesso comune lo stesso giorno: contano tutti.

---

## 3. Ambito e geografia

- **Mondiale.** Territorio = comune ovunque, identità = **`osm_id`** (niente ISTAT,
  uniformità globale).
- Point-in-polygon **offline con `shapely`** su poligoni **OSM**. Nominatim solo
  come fallback.
- **Altitudine stimata** da DEM (SRTM / open-elevation) a partire da lat/lon, con
  `alt_source='dem'`. Il pin non porta quota; siamo onesti sul fatto che sia derivata.

---

## 4. Leaderboard principale — controllo territori

Doppio valore, entrambi mostrati:

1. **N° comuni posseduti** (metrica canonica, leggibile)
2. **km² controllati** (tie-break e board parallela)

Popolazione esclusa.

---

## 5. Leaderboard secondarie (record / superlativi)

Ognuna ha un singolo detentore, con storia dei sorpassi:

- 🧭 **Più a Nord / Sud / Est / Ovest** (estremi lat/lon)
- ⛰️ **Più in alto** / 🕳️ **Più in basso** (altitudine)
- 📏 **Trasferta più lontana** (distanza da `home_base`)
- 🗺️ **Esploratore** — più comuni distinti lifetime
- 💩 **Volume** — più depositi totali
- 🌍 **Passaporto** — più nazioni distinte
- 🔥 **Streak** — giorni consecutivi con ≥1 deposito
- 👑 **Latifondista** — record di comuni posseduti in contemporanea

---

## 6. Achievement

Sistema a **registry flessibile**: ogni achievement è una regola (funzione) che gira
sul flusso ordinato dei depositi + stato derivato e produce `Award`. La riga in
`achievements` porta solo i metadati di visualizzazione. **Aggiungere un badge =
aggiungere una funzione + una riga**, senza migrazioni né tocchi ai dati grezzi.
Rivalutabile a ritroso su tutto lo storico. (Dettaglio tecnico in §11.)

Set iniziale:

| Code | Nome | Tipo | Regola |
|---|---|---|---|
| `blitz` | **Blitz** | ripetibile | 3 comuni distinti in 24h |
| `colonizzatore` | **Colonizzatore** | ripetibile | primo del gruppo *in assoluto* in un comune |
| `conquistador` | **Conquistador** | ripetibile | flip attivo (rubi un comune) |
| `regicidio` | **Regicidio** | ripetibile | rubi un comune al leader di classifica |
| `scalatore` | **Scalatore** | ripetibile | deposito sopra quota X m |
| `batisfera` | **Batisfera** | ripetibile | deposito sotto il livello del mare |
| `grand_tour` | **Grand Tour** | one-shot | un deposito in ogni regione italiana |
| `passaporto` | **Passaporto** | one-shot | depositi in **≥5 nazioni** |
| `pendolare` | **Pendolare** | ripetibile | 5 comuni in una settimana |
| `teletrasporto` | **Teletrasporto sospetto** | ripetibile | salto spazio-tempo fisicamente impossibile (ironico, nessuna penalità) |
| `guardiano` | **Guardiano** | ripetibile | ripristini il tuo vantaggio dopo un pareggio subìto |
| `spartizione_polonia` | **Spartizione della Polonia** 🇵🇱 | ripetibile | possiedi ≥3 comuni in Polonia contemporaneamente |
| `waterloo` | **Waterloo** 🇫🇷 | one-shot | depositi in ≥3 comuni francesi distinti |

Il set crescerà: l'architettura è progettata per aggiunte a basso costo.

### Backlog badge — livelli amministrativi (futuri)

Quando la mappa avrà gli aggregati (stato → regione → provincia, vedi §7), la
stessa logica abilita badge di livello superiore. Da valutare, non ancora
implementati:

- **Governatore** — possiedi un'intera provincia (tutti i suoi comuni).
- **Viceré** — possiedi un'intera regione.
- **Re della Padania** / titoli regionali — sei owner (per comuni controllati)
  di una regione-simbolo.
- **Anschluss** — diventi owner-aggregato di un intero stato.
- **Guerra dei cent'anni** — strappi una regione al suo owner-aggregato
  precedente (flip a livello regione).
- **Cordone sanitario** — possiedi tutte le province confinanti con una che non
  è tua (richiede adiacenze, più avanti).

---

## 7. Mappa & dashboard

Due modalità sulla stessa mappa (Leaflet / MapLibre):

**Modalità Territori** (default)
- Comuni conquistati = **marroni** 💩, con la **bandierina del giocatore** piantata
  sopra (immagine definita dall'utente nel profilo).
- Contested = grigio / tratteggiato.
- Click comune → classifica depositi nel comune + storico flip.

**Modalità Dump**
- Mostra i **singoli pin** dei depositi.
- Click pin → dati del deposito (chi, quando, quota) + **selfie** (o placeholder
  coniglio 🐰 se mancante).
- Visibile **solo da utenti loggati** (dato sensibile).

Contorno: pannello leaderboard (principale + secondarie a tab), feed flip, profilo
giocatore con bacheca badge.

---

## 8. Input

Tre sorgenti confluiscono nello **stesso record `Deposit` normalizzato**; il resto
della pipeline non sa da dove arriva il dato.

**Storico → parsing chat WhatsApp** (`source='whatsapp_import'`)
Export `.txt` + media. Ogni messaggio location porta `maps.google.com/?q=lat,lon`;
si accoppia col selfie dello stesso mittente più vicino nel tempo. Un deposito = una
location (+ selfie appaiato). Deduplica su `pin + minuto`. Idempotente e
ri-eseguibile. Formato dettagliato in [`docs/whatsapp-import.md`](docs/whatsapp-import.md).

**Futuro → bot Telegram** (`source='telegram'`)
Bot dedicato: mandi posizione + foto, il bot crea il `Deposit` mappando `telegram_id`
→ user. Dato strutturato all'origine, niente parsing fragile. È la strada di regime
post-sviluppo.

**Inserimento diretto da mappa** (`source='map_manual'`)
Utente loggato: click sulla mappa → piazza pin → carica selfie. Per recuperi manuali
o quando il bot non c'è.

---

## 9. Utenti / visibilità

| Livello | Mappa territori + leaderboard | Pin dump + selfie | Feature giocatore | Gestione utenti |
|---|:--:|:--:|:--:|:--:|
| **Anonimo** (no login) | ✅ | ❌ | ❌ | ❌ |
| **User** | ✅ | ✅ | ✅ profilo, bandierina, avatar, home base, inserimento da mappa | ❌ |
| **Admin** | ✅ | ✅ | ✅ | ✅ crea / modifica / reset password |

- Auth a **password** (serve il reset da admin), sessione / JWT.
- Il pubblico ha **solo lettura** di mappa + classifiche coi display name scelti dagli
  utenti. Pin, foto e profili restano dietro login.
- Nessuna self-registration prevista: gli utenti li crea l'admin.

---

## 10. Casi limite / anti-cheat

Contesto: amici, fiducia di base. Niente sistemi polizieschi.

- **Duplicati** (stesso pin + stesso minuto): deduplica in ingestion.
- **Spoofing GPS / teletrasporto:** non si punisce, si *deride* → badge
  "Teletrasporto sospetto".
- **Selfie mancante** (storico vecchio): il deposito conta lo stesso, `photo_ref=null`,
  placeholder = coniglio. Eventuale filtro "solo verificati".

---

## 11. Stack & architettura

Allineato all'ecosistema (borant VPS, come RoomPulse):

- **Backend:** Python / **FastAPI**.
- **Storage:** **SQLite** (eventuale SpatiaLite per la geometria).
- **Geo:** `shapely` per point-in-polygon offline; poligoni OSM; DEM per la quota.
- **Frontend:** web dashboard, **Leaflet / MapLibre** per la coropletica.
- **Tooling:** `uv` (pyproject.toml + lock).
- **Deploy:** borant, come gli altri tool.

**Pipeline dati (idempotente, ri-eseguibile end-to-end):**

```
raw (whatsapp / telegram / map)
  → parse            → Deposit normalizzato
  → geo-enrich       → territory_osm_id (point-in-polygon) + altitude (DEM)
  → recompute        → standings + ownership + flips
  → evaluate         → awards (motore achievement)
```

**Motore achievement:** ogni regola è una funzione registrata con un decoratore in un
registry. L'evaluator scorre i depositi in ordine temporale, mantiene lo stato derivato
(ownership corrente, conteggi, streak) ed emette `Award`. One-shot vs ripetibile è un
attributo della regola. Nuovo badge = nuova funzione + riga in `achievements`.

Schema DB completo in [`schema.sql`](schema.sql).

---

## 12. Roadmap indicativa

1. **Fase 0 — Spec** ✅ (questo documento)
2. **Fase 1 — Modello & motore:** schema DB, ingestion normalizzata, geo-enrich,
   recompute standings/flips, evaluator achievement. Testabile con dati fittizi.
3. **Fase 2 — Import storico:** parser export WhatsApp + pairing selfie.
4. **Fase 3 — Dashboard:** mappa (territori + dump), leaderboard, profili, feed.
5. **Fase 4 — Auth & admin:** login, ruoli, gestione utenti.
6. **Fase 5 — Bot Telegram:** input di regime.
