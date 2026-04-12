#!/usr/bin/env python3
"""
FOTOKATALOG - SQLite -> MariaDB Export
=======================================
Exportiert Foto-Metadaten (ohne Originale/Thumbnails) aus der
lokalen SQLite-DB in die MariaDB auf VM/Prod.

Nutzung:
    python export_to_mariadb.py
    python export_to_mariadb.py --sqlite fotokatalog.db
    python export_to_mariadb.py --dry-run
"""

import sqlite3
import argparse
import os
import sys

try:
    import pymysql
except ImportError:
    print("FEHLER: pymysql nicht installiert (pip install pymysql)")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Tabellen-Definitionen fuer Export ───────────────────────
# Reihenfolge wichtig wegen Foreign Keys
TABLES = [
    {
        "name": "photos",
        "select": """SELECT id, file_path, file_name, file_size, file_hash,
                     media_type, width, height, date_taken, date_imported,
                     rating, is_favorite, is_hidden, notes
                     FROM photos""",
        # Kein thumbnail - zu gross, nicht noetig auf Prod
        "insert": """INSERT INTO photos (id, file_path, file_name, file_size, file_hash,
                     media_type, width, height, date_taken, date_imported,
                     rating, is_favorite, is_hidden, notes)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE
                     file_name=VALUES(file_name), file_size=VALUES(file_size),
                     file_hash=VALUES(file_hash), media_type=VALUES(media_type),
                     width=VALUES(width), height=VALUES(height),
                     date_taken=VALUES(date_taken), rating=VALUES(rating),
                     is_favorite=VALUES(is_favorite), is_hidden=VALUES(is_hidden),
                     notes=VALUES(notes)""",
    },
    {
        "name": "exif_data",
        "select": "SELECT * FROM exif_data",
        "insert": """INSERT INTO exif_data (photo_id, camera_make, camera_model, lens_model,
                     focal_length, aperture, shutter_speed, iso, flash_fired, orientation, software)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE
                     camera_make=VALUES(camera_make), camera_model=VALUES(camera_model),
                     lens_model=VALUES(lens_model), focal_length=VALUES(focal_length),
                     aperture=VALUES(aperture), shutter_speed=VALUES(shutter_speed),
                     iso=VALUES(iso)""",
    },
    {
        "name": "geo_data",
        "select": "SELECT * FROM geo_data",
        "insert": """INSERT INTO geo_data (photo_id, latitude, longitude, altitude,
                     country, country_code, state, city, district, street,
                     display_name, geohash, city_fr, city_de, city_en)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE
                     latitude=VALUES(latitude), longitude=VALUES(longitude),
                     city=VALUES(city), country=VALUES(country),
                     display_name=VALUES(display_name),
                     city_fr=VALUES(city_fr), city_de=VALUES(city_de), city_en=VALUES(city_en)""",
    },
    {
        "name": "tags",
        "select": "SELECT * FROM tags",
        "insert": """INSERT INTO tags (id, name, category, auto_generated)
                     VALUES (%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE name=VALUES(name)""",
    },
    {
        "name": "photo_tags",
        "select": "SELECT * FROM photo_tags",
        "insert": """INSERT INTO photo_tags (photo_id, tag_id, confidence)
                     VALUES (%s,%s,%s)
                     ON DUPLICATE KEY UPDATE confidence=VALUES(confidence)""",
    },
    {
        "name": "albums",
        "select": "SELECT * FROM albums",
        "insert": """INSERT INTO albums (id, name, description, cover_photo_id, created_at, sort_order)
                     VALUES (%s,%s,%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE name=VALUES(name), description=VALUES(description)""",
    },
    {
        "name": "photo_albums",
        "select": "SELECT * FROM photo_albums",
        "insert": """INSERT INTO photo_albums (photo_id, album_id, position)
                     VALUES (%s,%s,%s)
                     ON DUPLICATE KEY UPDATE position=VALUES(position)""",
    },
    {
        "name": "print_info",
        "select": "SELECT * FROM print_info",
        "insert": """INSERT INTO print_info (photo_id, megapixel, aspect_ratio, orientation,
                     dpi_a4, dpi_postkarte, print_cat, needs_upscale)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE
                     print_cat=VALUES(print_cat), megapixel=VALUES(megapixel)""",
    },
    {
        "name": "vision_analysis",
        "select": "SELECT * FROM vision_analysis",
        "insert": """INSERT INTO vision_analysis (photo_id, quality_score, postcard_score, print_score,
                     mood, description, key_elements, analyzed_at,
                     gibran_de, gibran_fr, gibran_en, gibran_theme, gibran_ref)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE
                     quality_score=VALUES(quality_score), postcard_score=VALUES(postcard_score),
                     description=VALUES(description),
                     gibran_de=VALUES(gibran_de), gibran_fr=VALUES(gibran_fr),
                     gibran_en=VALUES(gibran_en)""",
    },
    {
        "name": "peak_annotations",
        "select": "SELECT * FROM peak_annotations",
        "insert": """INSERT INTO peak_annotations (id, photo_id, peak_name, elevation,
                     x_percent, y_percent, confidence)
                     VALUES (%s,%s,%s,%s,%s,%s,%s)
                     ON DUPLICATE KEY UPDATE
                     elevation=VALUES(elevation), x_percent=VALUES(x_percent),
                     y_percent=VALUES(y_percent)""",
    },
]


def load_mariadb_config():
    """Laedt MariaDB-Verbindung aus ENV oder .env Datei."""
    # .env Datei lesen falls vorhanden
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

    return {
        "host": os.environ.get("FOTOKATALOG_DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("FOTOKATALOG_DB_PORT", "3306")),
        "database": os.environ.get("FOTOKATALOG_DB_NAME", "fotokatalog"),
        "user": os.environ.get("FOTOKATALOG_DB_USER", "fotokatalog"),
        "password": os.environ.get("FOTOKATALOG_DB_PASSWORD", ""),
    }


def export(sqlite_path, maria_config, dry_run=False, only_visible=True):
    """Exportiert alle Tabellen von SQLite nach MariaDB."""

    if not os.path.exists(sqlite_path):
        print(f"FEHLER: SQLite-DB nicht gefunden: {sqlite_path}")
        sys.exit(1)

    # SQLite oeffnen
    sconn = sqlite3.connect(sqlite_path)
    sconn.row_factory = sqlite3.Row

    # MariaDB oeffnen
    if not dry_run:
        mconn = pymysql.connect(
            **maria_config,
            charset="utf8mb4",
            autocommit=False,
        )
        mcur = mconn.cursor()
        # FK-Checks temporaer deaktivieren fuer sauberen Import
        mcur.execute("SET FOREIGN_KEY_CHECKS=0")

    total_rows = 0

    for tbl in TABLES:
        name = tbl["name"]
        select_sql = tbl["select"]

        # Optional: nur sichtbare Fotos exportieren
        if only_visible and name == "photos":
            select_sql += " WHERE (is_hidden=0 OR is_hidden IS NULL)"

        rows = sconn.execute(select_sql).fetchall()

        if not rows:
            print(f"  {name}: 0 Zeilen (uebersprungen)")
            continue

        if dry_run:
            print(f"  {name}: {len(rows)} Zeilen (dry-run)")
            total_rows += len(rows)
            continue

        count = 0
        for row in rows:
            values = tuple(row)
            try:
                mcur.execute(tbl["insert"], values)
                count += 1
            except pymysql.err.IntegrityError as e:
                # FK-Fehler bei geloeschten Referenzen ignorieren
                if e.args[0] == 1452:
                    continue
                raise
            except Exception as e:
                print(f"  FEHLER in {name} (row {count}): {e}")
                print(f"    values: {values[:3]}...")
                continue

        print(f"  {name}: {count}/{len(rows)} Zeilen importiert")
        total_rows += count

    if not dry_run:
        mcur.execute("SET FOREIGN_KEY_CHECKS=1")
        mconn.commit()
        mconn.close()

    sconn.close()
    print(f"\nGesamt: {total_rows} Zeilen exportiert" + (" (dry-run)" if dry_run else ""))


def main():
    parser = argparse.ArgumentParser(description="SQLite -> MariaDB Export")
    parser.add_argument("--sqlite", default=os.path.join(SCRIPT_DIR, "fotokatalog.db"),
                        help="Pfad zur SQLite-DB (default: fotokatalog.db)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Nur zaehlen, nichts schreiben")
    parser.add_argument("--include-hidden", action="store_true",
                        help="Auch hidden Fotos exportieren")

    # MariaDB-Verbindung via ENV oder direkte CLI-Optionen
    parser.add_argument("--db-host", help="MariaDB Host (oder FOTOKATALOG_DB_HOST)")
    parser.add_argument("--db-port", type=int, help="MariaDB Port (oder FOTOKATALOG_DB_PORT)")
    parser.add_argument("--db-name", help="MariaDB Database (oder FOTOKATALOG_DB_NAME)")
    parser.add_argument("--db-user", help="MariaDB User (oder FOTOKATALOG_DB_USER)")
    parser.add_argument("--db-password", help="MariaDB Password (oder FOTOKATALOG_DB_PASSWORD)")

    args = parser.parse_args()

    maria_config = load_mariadb_config()

    # CLI-Optionen ueberschreiben ENV
    if args.db_host: maria_config["host"] = args.db_host
    if args.db_port: maria_config["port"] = args.db_port
    if args.db_name: maria_config["database"] = args.db_name
    if args.db_user: maria_config["user"] = args.db_user
    if args.db_password: maria_config["password"] = args.db_password

    print("=" * 50)
    print("FOTOKATALOG: SQLite -> MariaDB Export")
    print("=" * 50)
    print(f"  SQLite:  {args.sqlite}")
    print(f"  MariaDB: {maria_config['user']}@{maria_config['host']}:{maria_config['port']}/{maria_config['database']}")
    print(f"  Hidden:  {'ja' if args.include_hidden else 'nein (nur sichtbare)'}")
    print(f"  Modus:   {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()

    export(args.sqlite, maria_config, dry_run=args.dry_run, only_visible=not args.include_hidden)


if __name__ == "__main__":
    main()
