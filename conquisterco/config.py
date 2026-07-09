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
BATISFERA_M = 0.0         # sotto questa quota (livello del mare) scatta Batisfera

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

# --- Riferimenti geografici ------------------------------------------------
ITALIAN_REGIONS = frozenset({
    "Valle d'Aosta", "Piemonte", "Lombardia", "Trentino-Alto Adige", "Veneto",
    "Friuli-Venezia Giulia", "Liguria", "Emilia-Romagna", "Toscana", "Umbria",
    "Marche", "Lazio", "Abruzzo", "Molise", "Campania", "Puglia", "Basilicata",
    "Calabria", "Sicilia", "Sardegna",
})
