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

### 3bis. L'orologio

**Ogni timestamp in tabella è ora locale italiana, senza fuso scritto.** Lo erano già
i 599 depositi importati da WhatsApp, che portano l'ora com'era battuta in chat, e un
badge che dice «fra mezzanotte e le 5» parla dell'orologio in bagno, non di un istante
assoluto sulla linea del tempo.

Il fuso sta scritto **nel codice** (`util.ROME`) e non nell'ambiente. Non è pignoleria:
se il significato di un dato già salvato dipende da una variabile d'ambiente, un
redeploy che la perde cambia il senso di ottomila righe senza che niente segnali un
errore. `TZ=Europe/Rome` c'è lo stesso nel compose, ma serve ai log e ai `DEFAULT
(datetime('now'))` rimasti nel DDL, non al gioco.

Tre regole operative:

- **Mai `datetime.now()` nudo**: segue il fuso del processo. Si usa `util.now_local()`.
- **Mai il `datetime('now')` di SQLite** dove il valore si confronterà con un
  `deposits.ts`: quello è UTC sempre, in qualunque container. Si passa `util.ts_now()`
  dal Python. Restano DDL con quel default sulle colonne di solo audit (`created_at`,
  `geocoded_at`), dove un'ora di scarto non decide niente.
- **I secondi Unix di Telegram sono un istante assoluto** e vanno convertiti a Roma
  esplicitamente (`util.local_from_epoch`), non con `fromtimestamp()` nudo.

> **Come si è scoperto, il 21 set 2026.** Il container girava senza `TZ`, quindi in UTC,
> e `_msg_ts` del bot convertiva con `fromtimestamp()` nudo: **809 depositi salvati due
> ore indietro**, più della metà del database. Non l'ha segnalato nessun errore, l'ha
> detto l'istogramma delle ore: in otto anni di WhatsApp ci sono **2** cacate fra le 4 e
> le 6 del mattino, nei due mesi e mezzo del bot ce n'erano **172**. Le due curve hanno la
> stessa forma, traslata. Danno collaterale: **133 "Alba del Nuovo Regno" su 135** erano
> andate a gente che cagava alle 7 passate, e il recap della domenica partiva alle 22:00
> per il gruppo perché il cron leggeva le 20:00 di Greenwich. Il cron adesso tenta a
> entrambe le ore UTC in cui a Roma può essere l'ora giusta, con una guardia che lascia
> passare solo quella, e **non** con `CRON_TZ`: quello è di cronie, e questo cron
> (Debian vixie) **non lo onora**. Provato con una sonda che non scattava mentre il
> controllo senza `CRON_TZ` scattava. L'alternativa era cambiare il fuso della macchina,
> che avrebbe spostato anche i quattro job di borant-backup nello stesso crontab.

---

## 4. Leaderboard principale — controllo territori

> **Nomi in interfaccia (19 set 2026):** in dashboard questa è la tab **Punti**, seconda;
> la prima si chiama **Classifica** ed è quella per settimane vinte (§6bis). L'ordine dice
> qual è il piatto forte: vincere settimane, non accumulare punteggio.

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
tabella `achievements` a ogni `sync`. **Gnnn!** dichiara i punti (`GNNN_POINTS`, 5) e
basta: decade come tutti, quindi 5 la prima volta e 2,5 per sempre dopo.

> **La deroga sul decadimento è caduta il 21 set 2026.** Gnnn! aveva `decay=1.0`,
> motivato con «un handicap che si sgonfia dopo tre giorni non è un handicap» — ma
> Gnnn! è un **incentivo**, non un handicap, e caduta la premessa restava l'unico
> ripetibile trattato diversamente dagli altri senza una ragione. Misurato sul cacasto
> vero prima di toccarlo: a punti fissi valeva **un badge ordinario pieno a ogni
> cacata** (simularlo come badge da 10 a decadimento normale dava lo stesso totale a
> meno di 5 punti), cioè raddoppiava il valore di una cacata rispetto ai 6,0 punti di
> media del gruppo, e faceva il **48%** del punteggio di chi lo prendeva. Nessun altro
> ripetibile paga senza un evento sotto: un comune nuovo, un turno di notte, una
> nazione nuova. Ora ne vale metà, che è la taglia giusta per «hai fatto la cosa che il
> gioco già premia».

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

### Cacca Nautica — l'unico badge che guarda fuori dai comuni

Un deposito che il geocoder non riesce ad attribuire a nessun comune — in pratica **una
cacata in acqua** — è invisibile a tutto il motore: `EvalContext` carica solo i depositi
con `territory_osm_id`, quindi quella cacata non conquista, non contende, non fa
punteggio e non concorre a nessun altro badge. Sulla mappa in modalità Dump il pin però
si vede, perché `dumps_geo` non filtra: era una cacata **visibile e muta**.

**Cacca Nautica** (ripetibile, 🌊) legge quei depositi da una lista `ctx.deposits_nautici`
tenuta **separata** di proposito: infilarli fra gli altri farebbe ragionare ogni regola su
un territorio `None`. Dal 19 set li legge anche **Gnnn!** (§sotto), e sono le uniche due
regole a farlo: se l'incentivo è che cagare vale, vale anche dove non c'è un comune da
conquistare.

> Al 19 set 2026 i depositi senza comune dell'intero cacasto sono **tre**, tutti dello
> stesso giocatore e tutti in mare: Golfo di Napoli, Eolie, largo dell'Elba — le cacate
> in traghetto, lasciate in acqua di proposito quando si è ripulito il dato.

### Gnnn! — il badge degli stitici

Dal profilo ci si può **dichiarare stitici**. Da quel momento ogni cacata frutta un
**Gnnn!**: `GNNN_POINTS` (5) la prima volta, **2,5 tutte le altre**, perché decade come
ogni altro ripetibile (§4). Non è un handicap ma un **incentivo**: paga in proporzione a
quante volte caghi, e va bene così perché lo scopo è far cagare di più.

Il valore è tarato sulle 444 settimane di storico, e la taratura dice una cosa sola:
**fra 2, 2,5 e 3 punti a regime i verdetti settimanali sono identici** (18 settimane
vinte dalla stitica più assidua, gli stessi 4 verdetti diversi da quelli a 5). Dentro
quella banda si sceglie guardando la classifica lifetime, non il gioco settimanale. A 5
secchi erano 21, e il 20 set 2026 il bonus ha vinto la **prima settimana mai annunciata
al gruppo** con 5 cacate contro le 13 del secondo: 40,0 punti contro 37,1, di cui 25 di
solo Gnnn!. Quel verdetto **resta** — è annunciato, e un verdetto annunciato non si
ricalcola (§8) — ma è il caso che ha fatto cadere la deroga.

La dichiarazione **non è un booleano ma una storia**: `stitico_periods` tiene i periodi
in cui valeva, e Gnnn! premia i depositi caduti dentro. Serve perché il motore rivaluta
sempre tutto lo storico — un flag letto al presente regalerebbe un Gnnn! a ogni cacata
del 2018, e spegnendolo li toglierebbe tutti in blocco. Con i periodi si può smettere di
dichiararsi stitici senza perdere quello che si è guadagnato.

> È **autodichiarato** e nessuno lo verifica: chi vuole barare se lo spunta e prende
> 2,5 punti a cacata. Scelta deliberata — il controllo sociale del gruppo costa meno di
> un motore anti-frode, e la data di dichiarazione è pubblica sul profilo.

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

Le settimane tessellano senza buchi: ognuna comincia dove è finita la precedente, così la
cacata di mezzanotte di domenica (dopo il recap delle **21:30**) cade nella settimana nuova
e non in un limbo. Quelle passate **senza** recap — tutto lo storico WhatsApp, e le domeniche
in cui il cron non è partito — si chiudono retroattivamente sulla griglia dei lunedì,
una volta sola. Due recap ravvicinati non fabbricano una settimana di due ore:
sotto `MIN_WEEK_DAYS` non si chiude niente.

**Vincitore = chi guadagna strettamente più punti. Parità = settimana contesa, non la
vince nessuno**: la stessa regola dei comuni (§2). Sui dati veri la parità non capita
quasi mai, perché i badge fanno divergere i decimali.

**Classifica per settimane vinte**: `vinte / giocate`, dove «giocata» è una settimana
chiusa in cui hai depositato almeno una volta. Chi non c'era non viene punito per le
settimane in cui non c'era; chi c'era e ha perso sì.

Per stare **in graduatoria** servono due cose insieme:

- almeno `WEEKS_MIN_PLAYED` **settimane giocate** — un rateo su una settimana sola non è
  un rateo, 1/1 fa 1.00 e resterebbe in testa per sempre;
- almeno `WEEKS_ACTIVE_DUMPS` **cacate nelle ultime `WEEKS_ACTIVE_WINDOW` settimane** —
  la storia non basta, bisogna esserci adesso.

Entrambe valgono **4**: chi arriva nel gruppo entra in classifica dopo un mese. A 8 e 8 un
nuovo aspettava due mesi, e i due giocatori più attivi in assoluto restavano fuori per una
settimana di anzianità mancante — il contrario di quello che la soglia doveva fare.

La seconda condizione rende questa classifica **dipendente dall'istante in cui la si
guarda**: è l'unica cosa nel gioco che cambia senza che cambi un dato, e un giocatore ne
esce da solo smettendo di cagare. È voluto — premia chi c'è — ma va saputo, perché
significa che il rateo storico da solo non garantisce un posto.

Fuori graduatoria **non vuol dire fuori dalla lista**: si compare in coda, con posizione e
rateo a trattino ma vinte, giocate e cacate recenti vere, ordinati per quanto manca a
entrarci. Il principio è quello della classifica principale (§4): chi ha giocato compare.
E `giocate` e `ultime N` stanno **sempre** accanto al rateo, perché le soglie riducono il
rumore ma non lo azzerano.

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
- Il recap **manda anche il selfie vincitore**, come messaggio a parte e non come
  didascalia del recap: la didascalia di Telegram si ferma a 1024 caratteri e il recap ne
  fa mille abbondanti. Se l'invio della foto fallisce il verdetto è già stato annunciato a
  parole. I byte vengono caricati (`sendPhoto`/`sendVideo` in multipart) invece di riusare
  il `file_id` di Telegram: il file_id ci sarebbe, perché i selfie del bot sono salvati
  col file_id come nome, ma non ce l'hanno quelli importati da WhatsApp.
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
- **Pagina di login** su `/login`. Una pagina chiesta senza sessione non risponde con
  un errore: rimanda li' con `next`, e dopo la password si torna dove si stava andando.
  Vale per le pagine e non per `/api/`, dove un 401 deve restare un 401 in JSON, e
  `next` viene accettato solo se e' un path interno (altrimenti e' un redirect aperto).
  Serve perche' il link del voto arriva su Telegram e si apre dal telefono, dove la
  sessione spesso non c'e'.

---

## 9bis. Visibilità dei selfie

Il selfie è **l'unico dato del cacasto che riguarda una persona e non un territorio**,
quindi è l'unico che ha bisogno di un permesso: pin, conquiste e punteggi sono pubblici
per costruzione. Tre livelli, dichiarati dal proprietario nel profilo:

| livello | il bot salva | chi vede sul sito |
|---|---|---|
| `pubblico` | sì | chiunque abbia un account |
| `ristretto` | sì | il proprietario, gli admin, e una lista che sceglie |
| `niente` | **no** | nessuno |

`niente` prende il posto del vecchio flag `no_selfie`, che era la stessa domanda fatta
due volte; la migrazione lo travasa e la colonna resta solo per non fare un `ALTER`
distruttivo.

**Il controllo sta in `visibilita.py` e in nessun altro posto**, perché un selfie esce da
cinque superfici: la rotta che serve i byte, la galleria, i pin della mappa, i candidati
al voto e la foto che il recap manda in chat. Sparpagliare la regola vuol dire
dimenticarne una, e dimenticarne una qui significa pubblicare la foto di chi aveva
chiesto di no. Il permesso **fallisce chiuso**: senza uno spettatore noto non si mostra
niente.

Due conseguenze volute, non effetti collaterali:

- **Chi sta in `ristretto` è fuori dal voto della faccia di merda** (§6bis). Un selfie
  ristretto messo ai voti sarebbe mostrato a tutti, e il vincitore verrebbe pure
  ripubblicato in chat: la mezza misura qui non esiste. È il prezzo, ed è scritto
  nell'interfaccia accanto alla scelta.
- **Il pin resta visibile, sparisce solo la foto**, che diventa il coniglio 🐰 già usato
  per i dump senza selfie. La posizione non è il dato protetto.

### Pulizia della chat

Manopola **separata** dal livello (`users.pulisci_chat`), perché sono due domande diverse:
«chi può vedere la foto sul sito» e «cosa resta nella cronologia del gruppo». Accesa, il
bot **cancella dalla chat sia la foto sia il pin** appena registrati — di quel dump resta
in chat solo l'annuncio del bot.

Si accende **da sé quando si passa a `ristretto`**, lato javascript e anche lato server per
chi non ce l'ha: senza, la foto resterebbe in cronologia e ristretto sarebbe teatro. Ma la
può accendere anche chi resta pubblico e vuole solo la chat pulita, e si può spegnere a
mano una volta dentro.

Vincoli tecnici che ne determinano la forma:

- serve che il bot sia **amministratore del gruppo con `can_delete_messages`** (promosso il
  19 set 2026): l'API non lascia cancellare messaggi altrui a un bot semplice;
- **prima si scarica, poi si cancella**, sempre. Nel caso della foto-prima-del-pin la
  cancellazione aspetta che il pin la consumi, perché solo allora il file è sul volume;
- una foto mandata e mai diventata un dump **resta in chat**: il bot cancella ciò che
  registra, non tutto quello che passa;
- una cancellazione fallita non ferma l'ingestione. Al peggio il messaggio resta, che è lo
  stato di prima.

> **Cancellare dalla chat non è privacy, e va detto al gruppo.** Fra l'invio e la
> cancellazione passano secondi in cui la notifica è già arrivata sui telefoni; i client
> Telegram fanno cache; e il file resta sui server di Telegram comunque. La promessa
> onesta è «non resta nella cronologia», non «nessuno l'ha vista».

> **Cosa NON copre, e va detto a chi lo usa.** I file stanno in chiaro sul volume `/data`,
> finiscono nel backup off-site, e un admin del sito li vede tutti. «Ristretto» vuol dire
> ristretto **fra i giocatori**, non cifrato. Chi ha bisogno che una foto non esista deve
> usare `niente`. L'avviso è scritto sotto la scelta nel profilo, non solo qui.

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
