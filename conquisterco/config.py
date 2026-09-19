"""Soglie e costanti di gioco. Un solo posto da toccare per bilanciare."""

# --- Achievement: finestre e soglie ---------------------------------------
BLITZ_COUNT = 3           # comuni distinti...
BLITZ_WINDOW_H = 24       # ...entro N ore

PENDOLARE_COUNT = 5       # comuni distinti...
PENDOLARE_WINDOW_DAYS = 7  # ...entro N giorni

PASSAPORTO_NATIONS = 5    # nazioni distinte (one-shot)

POLONIA_COMUNI = 3        # comuni polacchi posseduti in contemporanea
WATERLOO_COMUNI = 3       # comuni francesi distinti in cui hai depositato

SCALATORE_M = 2000.0      # quota sopra la quale scatta Scalatore
BATISFERA_M = -5.0        # sotto questa quota scatta Batisfera. NON zero: il DEM
                          # sbaglia di un metro su una spiaggia, e il 19 set 2026 il
                          # badge e il record "piu' in basso" erano entrambi appesi a
                          # due depositi a -1 m a Jesolo. Cinque metri e' rumore di DEM,
                          # -5 no.

TELETRASPORTO_KMH = 900.0  # velocità implicita oltre cui il salto è "sospetto"

# --- Ownership simultanea --------------------------------------------------
GRANDUCA_COMUNI = 25       # comuni posseduti in contemporanea (Granduca del Colon)
COLONIALISTA_STATES = 2    # stati owner-aggregato in contemporanea
IMPERIALISTA_STATES = 4    # idem, soglia superiore

# --- Streak / assiduità ----------------------------------------------------
OROLOGIO_STREAK = 7        # giorni consecutivi con ≥1 deposito (Regolare come un Orologio)
METRONOMO_STREAK = 30      # idem, soglia superiore (Metronomo Intestinale)
PILASTRO_DAYS = 50         # giorni DISTINTI totali con ≥1 deposito (non consecutivi)

# --- Ora del giorno (h locale del deposito) --------------------------------
NIGHT_END_H = 5            # Turno di Notte: deposito con ora in [0, 5)
DAWN_START_H, DAWN_END_H = 5, 7   # L'Alba del Nuovo Regno: ora in [5, 7)

# --- Selfie caricati -------------------------------------------------------
GALLERISTA_SELFIE = 50
ARCHIVISTA_SELFIE = 100
MUSEO_SELFIE = 200

# --- Flip / conquista temporale --------------------------------------------
VENDETTA_DAYS = 30         # riconquisti un comune perso da almeno N giorni
CAMPAGNA_COUNT = 3         # cacate nello stesso comune...
CAMPAGNA_WINDOW_DAYS = 7   # ...entro N giorni, che strappano il comune a un altro

# --- Precisione / geometria ------------------------------------------------
PRECISINO_TOL_DEG = 0.03   # tolleranza (~3.3 km) dall'incrocio meridiano×parallelo
TITICACA_RADIUS_KM = 80.0  # raggio entro cui scatta Titicacca

# --- Finestra "viaggio" (sequenze internazionali) --------------------------
TRIP_WINDOW_DAYS = 5       # Fuck Brexit / Barbarossa / Cortina di carta igienica

# --- Punteggio (somma pesata, tutto ritarabile qui) ------------------------
# score = PT_COMUNE·comuni + PT_KM2·km² + punti dei badge (i segreti ×MULT).
# km² scalato così non schiaccia comuni e badge.
#
# I badge danno SEMPRE punti, anche i ripetibili presi più volte — con peso
# calante, ma con un **pavimento a metà**: la n-esima presa vale
# `punti · DECAY^(n-1)`, e mai meno di `punti/2`. Con DECAY=0.5 la curva è
# 10, 5, 5, 5… (e 20, 10, 10… per un segreto); con un DECAY più alto la
# discesa dal pieno alla metà è più morbida (0.8 → 10, 8, 6.4, 5.12, 5…).
# Il pavimento toglie il tetto: un ripetibile cresce senza limite, mezzo
# punto-badge per volta. È deliberato — senza, dalla quinta presa in poi
# «danno sempre punti» era vero solo sulla carta.
# Un badge può dichiarare i suoi punti e il suo decadimento nel registry
# (`@achievement(..., points=…, decay=…)`): è così che Gnnn! vale punti tondi
# a ogni cacata, senza decadere.
SCORE_PT_COMUNE = 10.0     # punti per comune posseduto
SCORE_PT_KM2 = 0.01        # punti per km² (→ 100 km² = 1 punto)
SCORE_PT_BADGE = 10.0      # punti del badge, default se non lo dichiara
SCORE_BADGE_DECAY = 0.5    # ratio di decadimento fra una presa e la successiva
SCORE_SECRET_MULT = 2      # i badge segreti valgono doppio

# --- Stitici ---------------------------------------------------------------
# Cinque e non tre: simulato il 19 set 2026 sulle 443 settimane di storico, con
# tre punti il bonus ribaltava 5 settimane su 59 ad Angela_B e con quattro ne
# ribaltava 6 — il quarto punto non comprava niente. A cinque diventano 9.
# Non e' un handicap ma un incentivo (decisione di Spit): premia la frequenza, e
# va bene così, perche' lo scopo dichiarato e' far cagare di piu'.
GNNN_POINTS = 5.0          # punti di ogni Gnnn! (niente decadimento)

# --- Settimane -------------------------------------------------------------
# La settimana la chiude il recap. Sotto questa durata non si chiude niente:
# due `conquisterco-recap` nello stesso giorno non devono fabbricare una
# settimana di due ore e regalarla a chi ha cagato in quelle due ore.
MIN_WEEK_DAYS = 3

# Settimane giocate sotto le quali non si entra in graduatoria. Un rateo su una
# sola settimana non e' un rateo: 1/1 fa 1.00 e starebbe in testa per sempre.
# Chi non ci arriva NON sparisce, compare sotto la tabella: la classifica
# principale include deliberatamente chiunque abbia giocato (SS4), e nasconderli
# qui la contraddirebbe.
WEEKS_MIN_PLAYED = 8

# Seconda condizione, di recenza: per stare in graduatoria non basta avere una
# storia, bisogna esserci adesso. Attenzione, questa rende la classifica
# **dipendente dall'ora in cui la guardi**: un giocatore ne esce da solo
# smettendo di cagare, senza che cambi un dato. E' voluto.
WEEKS_ACTIVE_WINDOW = 8    # settimane della finestra di attivita'
WEEKS_ACTIVE_DUMPS = 8     # cacate che servono dentro la finestra

# --- Faccia di merda della settimana ---------------------------------------
# Un selfie vale la SOMMA dei voti presi, non la media: vince chi raccoglie piu'
# merda. Parita' in testa = nessuna proclamazione, come per i comuni.
FACE_MAX_VOTE = 5          # quante emoji cacca in overlay (voto da 1 a 5)
FACE_MIN_VOTERS = 2        # votanti distinti sotto i quali la settimana non elegge
FACE_SELF_VOTE = False     # si possono votare i propri selfie?

# --- Riferimenti geografici ------------------------------------------------
ITALIAN_REGIONS = frozenset({
    "Valle d'Aosta", "Piemonte", "Lombardia", "Trentino-Alto Adige", "Veneto",
    "Friuli-Venezia Giulia", "Liguria", "Emilia-Romagna", "Toscana", "Umbria",
    "Marche", "Lazio", "Abruzzo", "Molise", "Campania", "Puglia", "Basilicata",
    "Calabria", "Sicilia", "Sardegna",
})
