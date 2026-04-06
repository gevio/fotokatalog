# Fotokatalog — Schnellstart (Windows)

## Was ist das?
Ein lokales Tool das deine Fotos automatisch katalogisiert:
- **EXIF-Daten** auslesen (Kamera, Objektiv, ISO, Blende...)
- **GPS → Ortsname** auflösen (Land, Stadt, Bezirk)
- **Automatische Tags** (Tageszeit, Jahreszeit, Technik)
- **Datum aus Dateinamen** als Fallback (z.B. `20211223_164541`)
- **Duplikaterkennung** über SHA-256 Hash
- Alles in einer portablen **SQLite-Datenbank**

## Installation

### 1. Setup ausführen
Doppelklick auf `setup.bat` — installiert die Python-Abhängigkeiten.

### 2. Import starten
Öffne eine Eingabeaufforderung (cmd) im Projektordner und führe aus:

```
python katalog.py "E:\DCIM\03_Privat\Best of Valais\Originale"
```

### Optionen
```
python katalog.py "E:\DCIM\03_Privat" --db mein_katalog.db
python katalog.py "E:\DCIM\03_Privat" --no-geocode
```

- `--db PFAD` — Eigener Datenbank-Pfad (Standard: fotokatalog.db)
- `--no-geocode` — Ohne Reverse Geocoding (viel schneller, GPS bleibt als Koordinaten)

## Empfohlene Ordnerstruktur
```
E:\DCIM\03_Privat\
├── Best of Valais\
│   ├── Originale\        ← Originalfotos MIT EXIF/GPS
│   └── Snapseed\         ← Bearbeitete Fotos (OHNE EXIF)
└── _fotokatalog\         ← Diesen Ordner hierhin kopieren
    ├── fotokatalog.db    ← Wird beim ersten Import erstellt
    ├── katalog.py
    ├── schema.sql
    └── setup.bat
```

## Nach dem Import

Die SQLite-Datenbank kannst du mit jedem SQLite-Browser öffnen,
z.B. [DB Browser for SQLite](https://sqlitebrowser.org/).

Nützliche Abfragen:

```sql
-- Alle Fotos aus einem bestimmten Land
SELECT * FROM v_photos_with_location WHERE country = 'Schweiz';

-- Fotos pro Stadt
SELECT * FROM v_location_stats;

-- Top-bewertete Fotos
SELECT * FROM v_top_rated;

-- Alle Fotos mit einem bestimmten Tag
SELECT p.file_name, t.name, t.category
FROM photos p
JOIN photo_tags pt ON p.id = pt.photo_id
JOIN tags t ON pt.tag_id = t.id
WHERE t.name = 'Sonnenuntergang';

-- Fotos in einem Umkreis von 10km um einen Punkt
SELECT p.*, g.city, g.country
FROM photos p JOIN geo_data g ON p.id = g.photo_id
WHERE g.latitude BETWEEN 46.2 AND 46.4
  AND g.longitude BETWEEN 7.3 AND 7.5;
```

## Hinweis zu Snapseed
Snapseed entfernt beim Export alle EXIF-Daten. Das Script parst
in diesem Fall das Aufnahmedatum aus dem Dateinamen (Format: YYYYMMDD_HHMMSS).
GPS-Daten gehen dabei leider verloren — importiere daher immer auch
die Originale, um die vollen Metadaten zu erhalten.
