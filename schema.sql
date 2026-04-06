-- ============================================================
-- FOTOKATALOG - SQLite Datenbankschema
-- Optimiert für: Ortsbasierte Suche > Alben > Motiverkennung
-- ============================================================

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ────────────────────────────────────────────────────────────
-- 1. HAUPTTABELLE: Fotos & Videos
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS photos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path       TEXT    NOT NULL UNIQUE,
    file_name       TEXT    NOT NULL,
    file_size       INTEGER,
    file_hash       TEXT,                          -- SHA-256 zur Duplikaterkennung
    media_type      TEXT    CHECK(media_type IN ('photo','video')) DEFAULT 'photo',
    width           INTEGER,
    height          INTEGER,
    date_taken      TEXT,                          -- ISO 8601
    date_imported   TEXT    DEFAULT (datetime('now')),
    rating          INTEGER CHECK(rating BETWEEN 0 AND 5) DEFAULT 0,
    is_favorite     INTEGER DEFAULT 0,
    is_hidden       INTEGER DEFAULT 0,
    notes           TEXT,
    -- Thumbnail als BLOB (klein, für schnelle Vorschau in UI)
    thumbnail       BLOB
);

-- ────────────────────────────────────────────────────────────
-- 2. EXIF / TECHNISCHE METADATEN
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS exif_data (
    photo_id        INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    camera_make     TEXT,
    camera_model    TEXT,
    lens_model      TEXT,
    focal_length    REAL,                          -- in mm
    aperture        REAL,                          -- f-Nummer
    shutter_speed   TEXT,                          -- z.B. "1/250"
    iso             INTEGER,
    flash_fired     INTEGER,
    orientation     INTEGER,
    software        TEXT
);

-- ────────────────────────────────────────────────────────────
-- 3. GEODATEN (Priorität #1!)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS geo_data (
    photo_id        INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    latitude        REAL    NOT NULL,
    longitude       REAL    NOT NULL,
    altitude        REAL,
    -- Aufgelöste Ortsinformationen (Reverse Geocoding)
    country         TEXT,
    country_code    TEXT,
    state           TEXT,                          -- Bundesland / Region
    city            TEXT,
    district        TEXT,                          -- Stadtteil
    street          TEXT,
    display_name    TEXT,                          -- Vollständige Adresse
    -- Für schnelle Umkreissuche
    geohash         TEXT,                          -- Geohash für Clustering
    -- Übersetzte Ortsnamen (via Claude API)
    city_fr         TEXT,
    city_de         TEXT,
    city_en         TEXT
);

-- ────────────────────────────────────────────────────────────
-- 4. TAGS / SCHLAGWÖRTER
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    category        TEXT    CHECK(category IN (
                        'motiv',        -- Landschaft, Porträt, Architektur...
                        'stimmung',     -- Dramatisch, Friedlich, Lebhaft...
                        'technik',      -- Langzeitbelichtung, HDR, Panorama...
                        'jahreszeit',   -- Frühling, Sommer, Herbst, Winter
                        'tageszeit',    -- Goldene Stunde, Blaue Stunde, Nacht
                        'farbe',        -- Dominante Farben
                        'custom'        -- Eigene Tags
                    )) DEFAULT 'custom',
    auto_generated  INTEGER DEFAULT 0,             -- 1 = KI-generiert
    UNIQUE(name, category)
);

CREATE TABLE IF NOT EXISTS photo_tags (
    photo_id        INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    tag_id          INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    confidence      REAL    DEFAULT 1.0,           -- KI-Konfidenz (0-1)
    PRIMARY KEY (photo_id, tag_id)
);

-- ────────────────────────────────────────────────────────────
-- 5. ALBEN / SAMMLUNGEN (Priorität #2!)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS albums (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    description     TEXT,
    cover_photo_id  INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    created_at      TEXT    DEFAULT (datetime('now')),
    sort_order      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS photo_albums (
    photo_id        INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    album_id        INTEGER REFERENCES albums(id) ON DELETE CASCADE,
    position        INTEGER DEFAULT 0,             -- Reihenfolge im Album
    PRIMARY KEY (photo_id, album_id)
);

-- ────────────────────────────────────────────────────────────
-- 6. DRUCKINFO
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS print_info (
    photo_id        INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    megapixel       REAL,
    aspect_ratio    TEXT,
    orientation     TEXT    CHECK(orientation IN ('landscape','portrait','square','panorama')),
    dpi_a4          INTEGER,
    dpi_postkarte   INTEGER,
    print_cat       TEXT    CHECK(print_cat IN ('a4_ready','a4_upscale','postkarte_only','too_small')),
    needs_upscale   INTEGER DEFAULT 0
);

-- ────────────────────────────────────────────────────────────
-- 7. KI-ANALYSE (Claude Vision)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vision_analysis (
    photo_id        INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    quality_score   INTEGER,                       -- 1-5
    postcard_score  INTEGER,                       -- 1-5
    print_score     INTEGER,                       -- 1-5
    mood            TEXT,                          -- z.B. "dramatisch", "friedlich"
    description     TEXT,                          -- 1-2 Sätze
    key_elements    TEXT,
    analyzed_at     TEXT DEFAULT (datetime('now')),
    -- Gibran-Postkartentexte
    gibran_de       TEXT,
    gibran_fr       TEXT,
    gibran_en       TEXT,
    gibran_theme    TEXT,
    gibran_ref      TEXT                           -- Gibran-Zitat-Referenz
);

-- ────────────────────────────────────────────────────────────
-- 8. GIPFEL-ANNOTATIONEN (Peak Overlay)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS peak_annotations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id        INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    peak_name       TEXT,
    elevation       INTEGER,
    x_percent       REAL,                          -- 0-100, Position im Bild
    y_percent       REAL,                          -- 0-100, Position im Bild
    confidence      TEXT,                          -- hoch/mittel/niedrig
    UNIQUE(photo_id, peak_name)
);

-- ────────────────────────────────────────────────────────────
-- 9. INDIZES (Performance!)
-- ────────────────────────────────────────────────────────────

-- Geo-Suche: Schnelle Umkreissuche
CREATE INDEX IF NOT EXISTS idx_geo_coords ON geo_data(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_geo_country ON geo_data(country);
CREATE INDEX IF NOT EXISTS idx_geo_city ON geo_data(city);
CREATE INDEX IF NOT EXISTS idx_geo_geohash ON geo_data(geohash);

-- Zeitliche Suche
CREATE INDEX IF NOT EXISTS idx_photos_date ON photos(date_taken);
CREATE INDEX IF NOT EXISTS idx_photos_rating ON photos(rating);
CREATE INDEX IF NOT EXISTS idx_photos_favorite ON photos(is_favorite);
CREATE INDEX IF NOT EXISTS idx_photos_type ON photos(media_type);

-- Duplikaterkennung
CREATE INDEX IF NOT EXISTS idx_photos_hash ON photos(file_hash);

-- Hidden
CREATE INDEX IF NOT EXISTS idx_photos_hidden ON photos(is_hidden);

-- Druckkategorie
CREATE INDEX IF NOT EXISTS idx_print_cat ON print_info(print_cat);

-- Tags
CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(category);
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);

-- ────────────────────────────────────────────────────────────
-- 10. VIEWS (Komfort-Abfragen)
-- ────────────────────────────────────────────────────────────

-- Alle Fotos mit Ort
CREATE VIEW IF NOT EXISTS v_photos_with_location AS
SELECT
    p.id, p.file_name, p.date_taken, p.rating, p.is_favorite,
    g.latitude, g.longitude, g.country, g.city, g.district, g.display_name
FROM photos p
JOIN geo_data g ON p.id = g.photo_id;

-- Fotos pro Land/Stadt (für Statistik)
CREATE VIEW IF NOT EXISTS v_location_stats AS
SELECT
    g.country, g.city,
    COUNT(*) as photo_count,
    MIN(p.date_taken) as first_visit,
    MAX(p.date_taken) as last_visit
FROM photos p
JOIN geo_data g ON p.id = g.photo_id
GROUP BY g.country, g.city
ORDER BY photo_count DESC;

-- Top-bewertete Fotos
CREATE VIEW IF NOT EXISTS v_top_rated AS
SELECT
    p.*, g.city, g.country
FROM photos p
LEFT JOIN geo_data g ON p.id = g.photo_id
WHERE p.rating >= 4
ORDER BY p.rating DESC, p.date_taken DESC;
