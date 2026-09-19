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

Ordinata per **Punteggio**, con comuni e km² come colonne e tie-break:

1. **Punteggio** (metrica canonica di sintesi)
2. **N° comuni posseduti** (leggibile, primo tie-break)
3. **km² controllati** (secondo tie-break)

Popolazione esclusa. In classifica compare **chiunque abbia giocato** (≥1 deposito,
possiede un comune, o ha un badge): un giocatore non sparisce solo perché non controlla
territorio. Accanto al nome, la **bandiera** scelta dal giocatore.

### 4.1 Punteggio (somma pesata)

```
score = PT_COMUNE·comuni + PT_KM2·km² + punti dei badge (i segreti ×MULT)
```

Tutti i coefficienti in `config.py` (default: comune 10 · 100 km² = 1 pt · badge 10 ·
segreti ×2). km² scalato per non schiacciare comuni e badge. Interamente **derivato e
ricalcolabile**.

**I badge danno sempre punti, anche i ripetibili presi più volte** — con **peso
calante** e un **pavimento a metà**: la n-esima presa dello stesso badge vale
`punti · DECAY^(n-1)`, e mai meno di `punti/2`. Con `SCORE_BADGE_DECAY = 0.5` la curva è
**10, 5, 5, 5…** (e 20, 10, 10… per un segreto, dove il ×2 si applica al totale già
decaduto). Con un DECAY più alto la discesa dal pieno alla metà è più morbida (0.8
dà 10, 8, 6.4, 5.12, 5…): il parametro governa **la discesa**, non il valore finale.

Il pavimento toglie il tetto, ed è voluto. Senza, con DECAY=0.5 la quinta presa valeva
0,62 punti e la settantottesima zero: «danno sempre punti» era vero sulla carta e falso
in pratica, e le 78 conquiste di comuni vergini del giocatore più attivo rendevano 20
punti in tutto. Col pavimento ne rendono 395, e un ripetibile cresce senza limite di
mezzo punto-badge per volta.

Un badge può **dichiarare i suoi punti e il suo decadimento** nel registry
(`@achievement(..., points=..., decay=...)`), e la coppia finisce in colonna nella
tabella `achievements` a ogni `sync`. È la deroga che serve a un ripetibile a valore
fisso: **Gnnn!** vale `GNNN_POINTS` tondi a ogni cacata, `decay=1.0`, perché un handicap
che si sgonfia dopo tre giorni non è un handicap.

---

## 5. Leaderboard secondarie (record / superlativi)

Ognuna ha un singolo detentore, con storia dei sorpassi:

- 🧭 **Più a Nord / Sud / Est / Ovest** (estremi lat/lon)
- ⛰️ **Più in alto** / 🕳️ **Più in basso** (altitudine)
- 🗺️ **Esploratore** — più comuni distinti lifetime
- 💩 **Volume** — più depositi totali
- 🌍 **Cosmopolita** — più nazioni distinte (si chiamava *Passaporto*: rinominato il
  19 set 2026 perché collideva col badge omonimo, che è un'altra cosa — il badge è una
  soglia a 5 nazioni, il record è un primato)

> **Tolto il 19 set 2026: 📏 Trasferta più lontana** (distanza da `home_base`). Non era
> ridondante, era **morta**: `users.home_lat` non aveva UI né nel profilo né nell'admin,
> si scriveva solo da `add_user()` e in produzione era NULL per 26 utenti su 26. La riga
> mostrava un trattino da sempre. Le colonne restano nello schema, non scritte da nessuno.
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

### Espansione (luglio 2026)

Aggiunti 30 badge pubblici. La canonicalizzazione nazioni/regioni sta in
`geonames.py` (i nomi reali sono in lingua nativa: `Italia`, `Deutschland`,
`Schweiz/Suisse/Svizzera/Svizra`…), così le regole ragionano su codici ISO-2.

**Calendario / ora** (`turno_notte` 00–05, `alba_regno` 05–07, `natale_fecale`
25/12, `anno_bisesto` 29/02, `capodanno` prima cacca dell'anno, `ultima_chiamata`
ultima dell'anno). **Assiduità** (`orologio` streak 7, `metronomo` streak 30,
`pilastro` 50 giorni totali). **Selfie** (`gallerista` 50, `archivista` 100,
`museo_orrori` 200). **Luoghi** (`checkpoint_charlie` Berlino, `uranus`
Missouri, `middelfart` DK, `cavaliere_oscuro` Batman TR, `hell_and_back`,
`meta_cacca` nome scatologico, `d_day` Normandia, `vendicatore_fiume` Rijeka).
**Coordinate** (`precisino` incrocio meridiano×parallelo, `ultima_thule` oltre il
Circolo Polare Artico, `titicacca` presso il lago). **Sequenza** (`anschluss`
DE→AT stesso giorno). **Possesso** (`granduca_colon` ≥25 comuni insieme,
`colonialista_anale`/`imperialista_anale` owner-aggregato di ≥2/≥4 stati insieme).
**Flip nel tempo** (`campagna_elettorale` ≥3 cacate/settimana che strappano il
comune, `vendetta_fredda` riconquista dopo ≥30g, `avignone` Roma→persa→Avignone).

Soglie e finestre in `config.py`.

### Gnnn! — il badge degli stitici

Dal profilo ci si può **dichiarare stitici**. Da quel momento ogni cacata frutta un
**Gnnn!** (`GNNN_POINTS` punti, nessun decadimento). Non è un handicap ma un **incentivo**:
paga in proporzione a quante volte caghi, e va bene così perché lo scopo è far cagare di
più. Il valore è stato scelto simulando sulle 443 settimane di storico — a tre punti il
bonus ribaltava 5 settimane su 59 alla giocatrice piu' assidua fra le stitiche, a quattro
ne ribaltava 6 (il quarto punto non comprava niente), a cinque ne ribalta 9.

La dichiarazione **non è un booleano ma una storia**: `stitico_periods` tiene i periodi
in cui valeva, e Gnnn! premia i depositi caduti dentro. Serve perché il motore rivaluta
sempre tutto lo storico — un flag letto al presente regalerebbe un Gnnn! a ogni cacata
del 2018, e spegnendolo li toglierebbe tutti in blocco. Con i periodi si può smettere di
dichiararsi stitici senza perdere quello che si è guadagnato.

> È **autodichiarato** e nessuno lo verifica: chi vuole barare se lo spunta e prende 3
> punti a cacata. Scelta deliberata — il controllo sociale del gruppo costa meno di un
> motore anti-frode, e la data di dichiarazione è pubblica sul profilo.

### Badge segreti

Presenti nel motore e assegnati come gli altri, ma **nascosti dalla legenda** del
modale (colonna `secret` in `achievements`; restano visibili sul profilo di chi li
prende). Documentati qui e basta — la sorpresa è il punto.

| Code | Nome | Regola |
|---|---|---|
| `pellegrino` | **Il Pellegrino** | cacca in Vaticano |
| `serenissima` | **Serenissima Deposizione** | prima cacca a Venezia |
| `danzica_libera` | **Danzica Libera** | prima cacca a Gdańsk |
| `sudetenland` | **Sudetenland** | DE poi CZ lo stesso giorno |
| `barbarossa` | **Operazione Barbarossa** | DE poi RU entro 5 giorni |
| `fuck_brexit` | **Fuck Brexit** | UE → UK → UE entro 5 giorni |
| `neutralita_armata` | **Neutralità Armata** | CH dopo aver cacato in IT/DE/FR/AT |
| `cortina_igienica` | **La Cortina di Carta Igienica** | ex-Ovest & ex-Est entro 5 giorni |
| `incontro_teano` | **Incontro di Te-ano** | due giocatori stesso giorno stesso comune → conteso |

### Badge manuali ("li assegna il Sistema")

Alcuni riconoscimenti non derivano dai depositi: li **assegna a mano** l'admin. Poiché
gli award vengono azzerati e riderivati a ogni `finalize`, la fonte di verità sta in
una tabella persistente **`manual_awards`** (non toccata dal ricalcolo); una regola con
`manual=True` la rilegge e la trasforma in award, così sopravvive ai ricalcoli.
Assegnazione/revoca dal pannello admin ("Badge speciali"). Primo esemplare:
`gatto_sul_cesso` — **Gatto sul Cesso**, "solo per gatti molto speciali" (una gatta del
gruppo, colta sul cesso, ha un profilo a pieno titolo).

### Note su alcuni badge

- **`capodanno` / `ultima_chiamata`** sono **superlativi di gruppo**: la prima e
  l'ultima cacata dell'anno *tra tutti* (un detentore per anno), non per-utente.
  `ultima_chiamata` solo per anni conclusi (nell'anno in corso "l'ultima" si sposterebbe
  a ogni dump).
- **Badge-soglia** (`granduca_colon`, `colonialista_anale`, `imperialista_anale`,
  `spartizione_polonia`) sono datati al **primo superamento** della soglia (il replay
  registra il primo ts per conteggio): ts stabile → il bot non li riannuncia a ogni dump.

### Backlog badge — livelli amministrativi (futuri)

> Nota: `colonialista_anale` / `imperialista_anale` già coprono il **possesso di
> stati** (owner-aggregato). Restano i livelli intermedi.

Quando la mappa avrà gli aggregati (stato → regione → provincia, vedi §7), la
stessa logica abilita badge di livello superiore. Da valutare, non ancora
implementati:

- **Governatore** — possiedi un'intera provincia (tutti i suoi comuni).
- **Viceré** — possiedi un'intera regione.
- **Re della Padania** / titoli regionali — sei owner (per comuni controllati)
  di una regione-simbolo.
- **Guerra dei cent'anni** — strappi una regione al suo owner-aggregato
  precedente (flip a livello regione).
- **Cordone sanitario** — possiedi tutte le province confinanti con una che non
  è tua (richiede adiacenze, più avanti).

---

## 6bis. Settimane, e la faccia di merda

### La settimana

Il punteggio è una funzione dello stato, quindi «punti della settimana» non è un dato:
è un **delta** fra due istantanee (`weeks.score_snapshot`), ricostruite rileggendo
l'ownership dai flip e i badge dagli award datati.

**La settimana la chiude il recap.** Quando il bot manda il riepilogo della domenica, la
settimana finisce in quell'istante e il verdetto viene scritto in `weeks`. Da lì non si
ricalcola più: quello che il bot ha annunciato al gruppo **resta** il verdetto, anche se
lo storico viene ri-arricchito dopo. È lo stesso patto di `manual_awards` — dato grezzo,
non derivato, immune al `finalize`.

Le settimane tessellano senza buchi: ognuna comincia dove è finita la precedente, così
la cacata delle 21 di domenica (dopo il recap delle 20) cade nella settimana nuova e non
in un limbo. Quelle passate **senza** recap — tutto lo storico WhatsApp, e le domeniche
in cui il cron non è partito — si chiudono retroattivamente sulla griglia dei lunedì,
una volta sola. Due recap ravvicinati non fabbricano una settimana di due ore:
sotto `MIN_WEEK_DAYS` non si chiude niente.

**Vincitore = chi guadagna strettamente più punti. Parità = settimana contesa, non la
vince nessuno**: la stessa regola dei comuni (§2). Sui dati veri la parità non capita
quasi mai, perché i badge fanno divergere i decimali.

**Classifica per settimane vinte**: `vinte / giocate`, dove «giocata» è una settimana
chiusa in cui hai depositato almeno una volta. Chi non c'era non viene punito per le
settimane in cui non c'era; chi c'era e ha perso sì.

Sotto `WEEKS_MIN_PLAYED` settimane giocate si è **fuori graduatoria**: un rateo su una
settimana sola non è un rateo, 1/1 fa 1.00 e resterebbe in testa per sempre. Fuori
graduatoria **non vuol dire fuori dalla lista** — si compare in coda, con posizione e
rateo a trattino ma vinte e giocate vere, ordinati per quanto manca a entrarci. Il
principio è quello della classifica principale (§4): chi ha giocato compare. E la colonna
`giocate` resta **sempre** accanto al rateo, perché la soglia riduce il rumore, non lo
azzera: con `WEEKS_MIN_PLAYED = 8` entrano in graduatoria dodici giocatori su diciotto,
e il più leggero ci sta appena dentro.

### Faccia di merda della settimana

Il recap che chiude la settimana **apre il voto sui suoi selfie** e **proclama** quella
della settimana prima, il cui voto si chiude in quel momento. Un solo voto aperto alla
volta.

- Si vota dal sito, **dietro login** (i selfie sono dato sensibile e lo restano): il
  selfie a tutta cella e cinque 💩 in overlay, da 1 a 5. Un voto per votante per
  selfie, cambiabile, con **undo**.
- **Non si votano i propri selfie**: non compaiono nemmeno in gara.
- Vince la **somma** dei voti presi, non la media: chi raccoglie più merda vince, e tre
  persone che ti danno 2 battono una che ne dà 5. Parità in testa, o meno di
  `FACE_MIN_VOTERS` votanti nella settimana: **nessuna proclamazione**, ma il voto si
  chiude lo stesso — una settimana non resta aperta in eterno.
- La proclamazione vive in `weeks.face_deposit_id` ed è **dato grezzo**. Il badge
  ripetibile **Faccia di Merda** la rilegge, come i manuali rileggono `manual_awards`,
  ed è datato sul selfie perché stia nel punto giusto della storia.
- I voti stanno in `selfie_votes`, anche loro fuori dalla portata del `finalize`.

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

### 7.1 Aree, poligoni e Level-of-Detail

La mappa è una **coropletica**: le aree si riempiono del colore dell'owner, con la
**bandierina** del giocatore piantata al centroide sopra il poligono; contested =
grigio. (I marker ai centroidi della prima versione erano un segnaposto.)

A zoom largo un solo pin per comune è illeggibile, quindi si aggrega su **quattro
livelli amministrativi** con un Level-of-Detail:

- z ≤ 4 → **stati** · 5-6 → **regioni** · 7-8 → **province** · z ≥ 9 → **comuni**

**Ownership aggregata (logica A):** owner di provincia/regione/stato = chi vi
**controlla più comuni** (max stretto, parità = conteso), esattamente la regola dei
comuni un livello sopra. È **derivata** dai comuni, si rigenera; la leaderboard resta
sui comuni.

**Geocoding & geometrie (Nominatim pubblico + cache):**
- reverse-geocode di ogni punto a zoom 10/8/6/3 → osm_id di comune, provincia,
  regione, stato + gerarchia (nomi/ISO) + geometria (GeoJSON) di ciascun livello;
- si recuperano **solo le unità toccate** dai depositi (+ i loro antenati), e le
  **nuove** al volo quando compaiono; tutto **cachato** nel DB → l'egress verso OSM
  è una tantum e non si ripete;
- niente self-host (troppo oneroso); geometrie semplificate per tenere leggere le
  aree grandi (stati). Backend dietro interfaccia: un domani si può puntare a un
  Nominatim proprio cambiando URL.

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
- **Storage:** **SQLite**.
- **Geo:** **Nominatim** (reverse-geocoding: comune, gerarchia e geometria GeoJSON;
  cachato in DB, egress una tantum — §7.1); quota da **open-meteo** (DEM); area km²
  con formula sferica (niente shapely).
- **Frontend:** web dashboard, **Leaflet** (renderer canvas) per la coropletica.
- **Tooling:** `uv` (pyproject.toml + lock).
- **Deploy:** **Docker + Caddy** su borant; DB e selfie su volume `/data` fuori da git
  (vedi `DEPLOY.md`).

**Pipeline dati (idempotente, ri-eseguibile end-to-end):**

```
raw (whatsapp / telegram / map)
  → parse            → Deposit normalizzato
  → geo-enrich       → territory_osm_id (reverse-geocode Nominatim) + altitude (DEM)
  → recompute        → standings + ownership + flips + aggregati
  → evaluate         → awards (motore achievement)
```

**Motore achievement:** ogni regola è una funzione registrata con un decoratore in un
registry. L'evaluator scorre i depositi in ordine temporale, mantiene lo stato derivato
(ownership corrente, conteggi, streak) ed emette `Award`. One-shot vs ripetibile è un
attributo della regola. Nuovo badge = nuova funzione + riga in `achievements`.

Schema DB completo in [`schema.sql`](schema.sql).

---

## 12. Roadmap — tutte le fasi FATTE ✅

1. **Fase 0 — Spec** ✅ (questo documento)
2. **Fase 1 — Modello & motore** ✅ schema DB, ingestion normalizzata, geo-enrich,
   recompute standings/ownership/flips + aggregati, evaluator achievement.
3. **Fase 2 — Import storico** ✅ parser export WhatsApp + pairing selfie (`importers/`).
4. **Fase 3 — Dashboard** ✅ mappa coropletica (LOD) + dump, leaderboard, record, feed,
   profili, badge, galleria.
5. **Fase 4 — Auth & admin** ✅ login per-utente, ruoli, gestione utenti + merge.
6. **Fase 5 — Bot Telegram** ✅ webhook, account provvisori + deep-link, annunci sassy,
   recap settimanale.

**Oltre le fasi:** geocoding reale via Nominatim + cache (non self-host) con quota da
open-meteo (§7.1); i18n IT/EN; deploy Docker + Caddy (`DEPLOY.md`); dati veri su volume
fuori da git.

**Espansione (settembre 2026):** i **badge danno sempre punti**, anche i ripetibili, con
peso calante e deroga per badge (§4.1); **Gnnn!**, l'handicap autodichiarato degli
stitici, con la dichiarazione tenuta a periodi e non a booleano (§6); le **settimane**
come oggetto di gioco — chiuse dal recap, vinte a punti guadagnati e non a numero di
cacate, con classifica per **vinte/giocate** (§6bis); la **faccia di merda della
settimana**, votata a cinque 💩 dal sito e proclamata dal recap successivo (§6bis).

**Espansione (luglio 2026):** **punteggio** combinato che ordina la classifica (§4.1);
oltre 50 achievement (30 pubblici + segreti + **manuali**, §6); **bandiere** in
classifica; galleria coi selfie in **modale** (foto/video) + numero progressivo, quota,
"vedi sulla mappa"; **video** nel popup dei dump + **spiderfy** dei pin sovrapposti;
modali "chi l'ha preso" / "come si prende"; punteggio + rank e badge cliccabili nel
profilo; admin: **messaggi liberi al gruppo** e **badge speciali** assegnabili a mano;
bot con **notifica speciale per i segreti**, **podio a punti** nel recap, e ~50 **trigger
testuali** a parole chiave (`triggers.py`, frequenza via `CONQUISTERCO_TRIGGER_CHANCE`).

**Aperti / idee:** badge a livello aggregato (§6, "Governatore/Viceré…"); geocoder
offline opzionale; rifinitura km² per unità estere sovradimensionate; eventuale "albo
d'oro per anno" per i superlativi annuali (Capodanno/Ultima Chiamata).
