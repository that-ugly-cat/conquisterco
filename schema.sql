-- Conquisterco — schema DB (SQLite)
-- Il Deposit è l'unico dato grezzo. Tutto il resto (standings, ownership,
-- flips, awards) è DERIVATO e ricalcolabile: le tabelle marcate "[derivata]"
-- si possono droppare e rigenerare dal flusso dei depositi.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Anagrafiche
-- ---------------------------------------------------------------------------

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    display_name  TEXT    NOT NULL UNIQUE,       -- username di login (unico)
    public_name   TEXT,                          -- nome mostrato su mappe/classifiche (fallback: display_name)
    color         TEXT,                         -- tinta sulla mappa
    wa_handle     TEXT,                         -- matching import storico WhatsApp
    telegram_id   TEXT,                         -- @username Telegram (match iniziale)
    telegram_user_id INTEGER UNIQUE,            -- id numerico Telegram (chiave stabile)
    provisional   INTEGER NOT NULL DEFAULT 0,   -- account creato dal bot, da reclamare
    avatar_ref    TEXT,                         -- immagine profilo
    flag_ref      TEXT,                         -- bandierina piantata sui comuni
    home_lat      REAL,                         -- home base (record "trasferta")
    home_lon      REAL,
    no_selfie     INTEGER NOT NULL DEFAULT 0,    -- preferenza: il bot non salva i selfie
    role          TEXT    NOT NULL DEFAULT 'user'
                          CHECK (role IN ('user', 'admin')),
    password_hash TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE territories (
    osm_id            INTEGER PRIMARY KEY,       -- identità globale uniforme (comune)
    name              TEXT    NOT NULL,
    admin_level       INTEGER,                   -- livello OSM del comune
    country           TEXT,
    region            TEXT,
    province          TEXT,
    -- catena amministrativa: link agli aggregati (per la logica A e il LOD)
    province_osm_id   INTEGER,
    region_osm_id     INTEGER,
    country_osm_id    INTEGER,
    area_km2          REAL,                      -- leaderboard km²
    centroid_lat      REAL,                      -- dove piantare la bandierina
    centroid_lon      REAL,
    geometry_geojson  TEXT                       -- poligono comune (coropletica)
);

-- ---------------------------------------------------------------------------
-- Dato grezzo
-- ---------------------------------------------------------------------------

CREATE TABLE deposits (
    id                INTEGER PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    ts                TEXT    NOT NULL,                 -- timestamp evento
    lat               REAL    NOT NULL,
    lon               REAL    NOT NULL,
    altitude          REAL,                             -- stimata da DEM
    alt_source        TEXT    CHECK (alt_source IN ('dem', 'device', NULL)),
    photo_ref         TEXT,                             -- NULL → placeholder coniglio
    territory_osm_id  INTEGER REFERENCES territories(osm_id),  -- [derivato] geo-enrich
    source            TEXT    NOT NULL
                              CHECK (source IN ('whatsapp_import', 'telegram', 'map_manual')),
    raw_ref           TEXT,                             -- puntatore al messaggio originale (audit)
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_deposits_user      ON deposits(user_id);
CREATE INDEX idx_deposits_territory ON deposits(territory_osm_id);
CREATE INDEX idx_deposits_ts        ON deposits(ts);
-- dedup ingestion: stesso utente, stesso pin, stesso minuto
CREATE UNIQUE INDEX idx_deposits_dedup
    ON deposits(user_id, lat, lon, substr(ts, 1, 16));

-- ---------------------------------------------------------------------------
-- Stato derivato (rigenerabile dal recompute)
-- ---------------------------------------------------------------------------

-- Conteggio depositi per (territorio, utente).            [derivata]
CREATE TABLE standings (
    territory_osm_id  INTEGER NOT NULL REFERENCES territories(osm_id),
    user_id           INTEGER NOT NULL REFERENCES users(id),
    deposit_count     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (territory_osm_id, user_id)
);

-- Owner corrente per territorio.                          [derivata]
CREATE TABLE territory_ownership (
    territory_osm_id  INTEGER PRIMARY KEY REFERENCES territories(osm_id),
    owner_user_id     INTEGER REFERENCES users(id),   -- NULL se contested
    is_contested      INTEGER NOT NULL DEFAULT 0,
    top_count         INTEGER NOT NULL DEFAULT 0,
    last_flip_ts      TEXT
);

-- Storia dei cambi di owner: alimenta feed + achievement.  [derivata]
CREATE TABLE flips (
    id                 INTEGER PRIMARY KEY,
    territory_osm_id   INTEGER NOT NULL REFERENCES territories(osm_id),
    ts                 TEXT    NOT NULL,
    deposit_id         INTEGER REFERENCES deposits(id),
    prev_owner_user_id INTEGER REFERENCES users(id),  -- NULL se prima conquista
    new_owner_user_id  INTEGER REFERENCES users(id)   -- NULL se → contested
);

CREATE INDEX idx_flips_territory ON flips(territory_osm_id);
CREATE INDEX idx_flips_ts        ON flips(ts);

-- ---------------------------------------------------------------------------
-- Achievement (registry flessibile)
-- ---------------------------------------------------------------------------

-- Metadati di visualizzazione. La REGOLA vive nel codice (registry).
CREATE TABLE achievements (
    id           INTEGER PRIMARY KEY,
    code         TEXT    NOT NULL UNIQUE,       -- match con la funzione registrata
    name         TEXT    NOT NULL,
    description  TEXT,
    type         TEXT    NOT NULL CHECK (type IN ('one_shot', 'repeatable')),
    icon_ref     TEXT,
    secret       INTEGER NOT NULL DEFAULT 0,   -- nascosto dalla legenda (assegnato comunque)
    active       INTEGER NOT NULL DEFAULT 1
);

-- Badge assegnati.                                         [derivata]
CREATE TABLE awards (
    id              INTEGER PRIMARY KEY,
    achievement_id  INTEGER NOT NULL REFERENCES achievements(id),
    user_id         INTEGER NOT NULL REFERENCES users(id),
    ts_earned       TEXT    NOT NULL,
    context         TEXT                        -- es. comune/nazione che l'ha scatenato
);

CREATE INDEX idx_awards_user ON awards(user_id);

-- Assegnazioni MANUALI ("lo assegna il Sistema"): non derivano dai depositi e
-- NON vengono azzerate dal finalize. Le regole-badge manuali le rileggono da qui
-- e le trasformano in `awards`, così sopravvivono ai ricalcoli.
CREATE TABLE manual_awards (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code     TEXT    NOT NULL,
    ts       TEXT    NOT NULL,
    context  TEXT,
    PRIMARY KEY (user_id, code)
);
-- one-shot: un solo award per (achievement, utente). Ripetibili: gestiti in codice
-- differenziando via context; questo indice resta parziale sui one-shot lato app.

-- ---------------------------------------------------------------------------
-- Livelli amministrativi aggregati + geocoding (mappa coropletica / LOD)
-- ---------------------------------------------------------------------------

-- Unità aggregate (provincia / regione / stato) con geometria, per il LOD.
-- I comuni stanno in `territories`; qui i loro antenati.
CREATE TABLE admin_units (
    osm_id            INTEGER PRIMARY KEY,
    kind              TEXT    NOT NULL CHECK (kind IN ('province', 'region', 'country')),
    name              TEXT    NOT NULL,
    parent_osm_id     INTEGER,                   -- antenato immediato (region→country, ...)
    centroid_lat      REAL,
    centroid_lon      REAL,
    geometry_geojson  TEXT
);

-- Ownership aggregata (logica A: owner = chi controlla più comuni).  [derivata]
CREATE TABLE aggregate_ownership (
    unit_osm_id    INTEGER PRIMARY KEY REFERENCES admin_units(osm_id),
    owner_user_id  INTEGER REFERENCES users(id),   -- NULL se conteso
    is_contested   INTEGER NOT NULL DEFAULT 0,
    comuni_owned   INTEGER NOT NULL DEFAULT 0      -- comuni dell'owner nell'unità
);

-- Cache del reverse-geocoding: coordinata → catena amministrativa risolta.
-- Rende l'enrich idempotente e l'egress verso OSM una tantum. Le geometrie
-- vivono in territories/admin_units (una per unità), qui solo la mappatura.
CREATE TABLE geocode_cache (
    lat            REAL NOT NULL,
    lon            REAL NOT NULL,
    comune_osm_id  INTEGER,                        -- NULL = fuori copertura / mare
    payload_json   TEXT NOT NULL,                  -- catena risolta (osm_id per livello)
    geocoded_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (lat, lon)
);

-- ---------------------------------------------------------------------------
-- Bot Telegram
-- ---------------------------------------------------------------------------

-- Token monouso per il deep-link di collegamento (profilo web → account Telegram).
CREATE TABLE tg_link_tokens (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Foto arrivata prima del pin: tenuta in sospeso per agganciarla al pin successivo.
CREATE TABLE tg_pending_photo (
    telegram_user_id INTEGER PRIMARY KEY,
    file_id          TEXT NOT NULL,
    ts               TEXT NOT NULL
);
