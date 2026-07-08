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

# --- Riferimenti geografici ------------------------------------------------
ITALIAN_REGIONS = frozenset({
    "Valle d'Aosta", "Piemonte", "Lombardia", "Trentino-Alto Adige", "Veneto",
    "Friuli-Venezia Giulia", "Liguria", "Emilia-Romagna", "Toscana", "Umbria",
    "Marche", "Lazio", "Abruzzo", "Molise", "Campania", "Puglia", "Basilicata",
    "Calabria", "Sicilia", "Sardegna",
})
