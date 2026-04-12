# ============================================================
# FOTOKATALOG - MariaDB Schema
# Konvertiert aus schema.sql (SQLite) für VM/Prod
# ============================================================

USE fotokatalog;

# ────────────────────────────────────────────────────────────
# 1. HAUPTTABELLE: Fotos & Videos
# ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS photos (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    file_path       VARCHAR(512) NOT NULL UNIQUE,
    file_name       VARCHAR(255) NOT NULL,
    file_size       INT,
    file_hash       VARCHAR(64),
    media_type      ENUM('photo','video') DEFAULT 'photo',
    width           INT,
    height          INT,
    date_taken      VARCHAR(32),
    date_imported   DATETIME DEFAULT CURRENT_TIMESTAMP,
    rating          TINYINT DEFAULT 0 CHECK(rating BETWEEN 0 AND 5),
    is_favorite     TINYINT DEFAULT 0,
    is_hidden       TINYINT DEFAULT 0,
    notes           TEXT,
    thumbnail       MEDIUMBLOB
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# ────────────────────────────────────────────────────────────
# 2. EXIF / TECHNISCHE METADATEN
# ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS exif_data (
    photo_id        INT PRIMARY KEY,
    camera_make     VARCHAR(128),
    camera_model    VARCHAR(128),
    lens_model      VARCHAR(128),
    focal_length    DOUBLE,
    aperture        DOUBLE,
    shutter_speed   VARCHAR(32),
    iso             INT,
    flash_fired     TINYINT,
    orientation     TINYINT,
    software        VARCHAR(128),
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# ────────────────────────────────────────────────────────────
# 3. GEODATEN
# ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS geo_data (
    photo_id        INT PRIMARY KEY,
    latitude        DOUBLE NOT NULL,
    longitude       DOUBLE NOT NULL,
    altitude        DOUBLE,
    country         VARCHAR(128),
    country_code    VARCHAR(8),
    state           VARCHAR(128),
    city            VARCHAR(128),
    district        VARCHAR(128),
    street          VARCHAR(255),
    display_name    VARCHAR(512),
    geohash         VARCHAR(16),
    city_fr         VARCHAR(128),
    city_de         VARCHAR(128),
    city_en         VARCHAR(128),
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# ────────────────────────────────────────────────────────────
# 4. TAGS / SCHLAGWÖRTER
# ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tags (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    category        ENUM('motiv','stimmung','technik','jahreszeit','tageszeit','farbe','custom') DEFAULT 'custom',
    auto_generated  TINYINT DEFAULT 0,
    UNIQUE KEY uq_tag_name_cat (name, category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS photo_tags (
    photo_id        INT NOT NULL,
    tag_id          INT NOT NULL,
    confidence      DOUBLE DEFAULT 1.0,
    PRIMARY KEY (photo_id, tag_id),
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# ────────────────────────────────────────────────────────────
# 5. ALBEN / SAMMLUNGEN
# ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS albums (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    cover_photo_id  INT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    sort_order      INT DEFAULT 0,
    FOREIGN KEY (cover_photo_id) REFERENCES photos(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS photo_albums (
    photo_id        INT NOT NULL,
    album_id        INT NOT NULL,
    position        INT DEFAULT 0,
    PRIMARY KEY (photo_id, album_id),
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE,
    FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# ────────────────────────────────────────────────────────────
# 6. DRUCKINFO
# ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS print_info (
    photo_id        INT PRIMARY KEY,
    megapixel       DOUBLE,
    aspect_ratio    VARCHAR(16),
    orientation     ENUM('landscape','portrait','square','panorama'),
    dpi_a4          INT,
    dpi_postkarte   INT,
    print_cat       ENUM('a4_ready','a4_upscale','postkarte_only','too_small'),
    needs_upscale   TINYINT DEFAULT 0,
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# ────────────────────────────────────────────────────────────
# 7. KI-ANALYSE (Claude Vision)
# ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vision_analysis (
    photo_id        INT PRIMARY KEY,
    quality_score   TINYINT,
    postcard_score  TINYINT,
    print_score     TINYINT,
    mood            VARCHAR(64),
    description     TEXT,
    key_elements    TEXT,
    analyzed_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    gibran_de       TEXT,
    gibran_fr       TEXT,
    gibran_en       TEXT,
    gibran_theme    VARCHAR(128),
    gibran_ref      VARCHAR(255),
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# ────────────────────────────────────────────────────────────
# 8. GIPFEL-ANNOTATIONEN (Peak Overlay)
# ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS peak_annotations (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    photo_id        INT NOT NULL,
    peak_name       VARCHAR(128),
    elevation       INT,
    x_percent       DOUBLE,
    y_percent       DOUBLE,
    confidence      VARCHAR(16),
    UNIQUE KEY uq_peak (photo_id, peak_name),
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# ────────────────────────────────────────────────────────────
# 9. USER-BEWERTUNGEN (nur Prod, nicht in SQLite)
#    Admin-Ratings bleiben in photos.rating / photos.is_favorite
#    User-Interaktionen landen hier separat
# ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_ratings (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    photo_id        INT NOT NULL,
    session_id      VARCHAR(64) NOT NULL,          # anonymer Cookie-Hash
    rating          TINYINT CHECK(rating BETWEEN 1 AND 5),
    is_favorite     TINYINT DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_photo (photo_id, session_id),
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# Aggregierte User-Statistik als View (performant abfragbar)
CREATE OR REPLACE VIEW v_user_rating_stats AS
SELECT
    photo_id,
    COUNT(*) as total_votes,
    ROUND(AVG(rating), 1) as avg_rating,
    SUM(is_favorite) as favorite_count
FROM user_ratings
WHERE rating IS NOT NULL
GROUP BY photo_id;

# ────────────────────────────────────────────────────────────
# 10. INDIZES
# ────────────────────────────────────────────────────────────
CREATE INDEX idx_geo_coords ON geo_data(latitude, longitude);
CREATE INDEX idx_geo_country ON geo_data(country);
CREATE INDEX idx_geo_city ON geo_data(city);
CREATE INDEX idx_geo_geohash ON geo_data(geohash);

CREATE INDEX idx_photos_date ON photos(date_taken);
CREATE INDEX idx_photos_rating ON photos(rating);
CREATE INDEX idx_photos_favorite ON photos(is_favorite);
CREATE INDEX idx_photos_type ON photos(media_type);
CREATE INDEX idx_photos_hash ON photos(file_hash);
CREATE INDEX idx_photos_hidden ON photos(is_hidden);

CREATE INDEX idx_print_cat ON print_info(print_cat);
CREATE INDEX idx_tags_category ON tags(category);
CREATE INDEX idx_tags_name ON tags(name);

# ────────────────────────────────────────────────────────────
# 11. VIEWS
# ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_photos_with_location AS
SELECT
    p.id, p.file_name, p.date_taken, p.rating, p.is_favorite,
    g.latitude, g.longitude, g.country, g.city, g.district, g.display_name
FROM photos p
JOIN geo_data g ON p.id = g.photo_id;

CREATE OR REPLACE VIEW v_location_stats AS
SELECT
    g.country, g.city,
    COUNT(*) as photo_count,
    MIN(p.date_taken) as first_visit,
    MAX(p.date_taken) as last_visit
FROM photos p
JOIN geo_data g ON p.id = g.photo_id
GROUP BY g.country, g.city
ORDER BY photo_count DESC;

CREATE OR REPLACE VIEW v_top_rated AS
SELECT
    p.*, g.city, g.country
FROM photos p
LEFT JOIN geo_data g ON p.id = g.photo_id
WHERE p.rating >= 4
ORDER BY p.rating DESC, p.date_taken DESC;
