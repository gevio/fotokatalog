"""
Druckkategorien zur Fotokatalog-DB hinzufügen.

Nutzung:
    python add_print_info.py
    python add_print_info.py --db pfad/zur/fotokatalog.db
"""
import sqlite3
import argparse
import math

def add_print_info(db_path="fotokatalog.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Tabelle für Druckinfo
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS print_info (
            photo_id      INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
            megapixel     REAL,
            aspect_ratio  TEXT,
            orientation   TEXT CHECK(orientation IN ('landscape','portrait','square','panorama')),
            dpi_a4        INTEGER,
            dpi_postkarte INTEGER,
            print_cat     TEXT CHECK(print_cat IN ('a4_ready','a4_upscale','postkarte_only','too_small')),
            needs_upscale INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_print_cat ON print_info(print_cat);
    """)

    A4_W_CM, A4_H_CM = 21.0, 29.7
    PK_W_CM, PK_H_CM = 14.8, 10.5

    updated = 0
    for row in conn.execute("SELECT id, width, height FROM photos WHERE width IS NOT NULL AND height IS NOT NULL"):
        pid, w, h = row["id"], row["width"], row["height"]
        if w == 0 or h == 0:
            continue

        mp = round(w * h / 1_000_000, 1)

        # Orientation
        ratio = max(w, h) / min(w, h)
        if ratio > 2.2:
            orient = "panorama"
        elif abs(w - h) < 50:
            orient = "square"
        elif w > h:
            orient = "landscape"
        else:
            orient = "portrait"

        # Aspect ratio (vereinfacht)
        g = math.gcd(w, h)
        ar_w, ar_h = w // g, h // g
        # Auf gängige Formate runden
        if orient == "landscape":
            aspect = f"{ar_w}:{ar_h}"
        else:
            aspect = f"{ar_w}:{ar_h}"

        # DPI für A4 (Querformat = Foto-Breite / A4-Höhe, Hochformat = Foto-Breite / A4-Breite)
        if orient in ("landscape", "panorama"):
            dpi_a4 = round(min(w / (A4_H_CM / 2.54), h / (A4_W_CM / 2.54)))
        elif orient == "portrait":
            dpi_a4 = round(min(w / (A4_W_CM / 2.54), h / (A4_H_CM / 2.54)))
        else:
            dpi_a4 = round(min(w / (A4_W_CM / 2.54), h / (A4_W_CM / 2.54)))

        # DPI für Postkarte (immer Querformat)
        dpi_pk = round(min(max(w, h) / (PK_W_CM / 2.54), min(w, h) / (PK_H_CM / 2.54)))

        # Kategorie
        if dpi_a4 >= 300:
            cat = "a4_ready"
        elif dpi_a4 >= 200:
            cat = "a4_upscale"
        elif dpi_pk >= 300:
            cat = "postkarte_only"
        else:
            cat = "too_small"

        conn.execute("""
            INSERT OR REPLACE INTO print_info
            (photo_id, megapixel, aspect_ratio, orientation, dpi_a4, dpi_postkarte, print_cat, needs_upscale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, mp, aspect, orient, dpi_a4, dpi_pk, cat, 1 if cat == "a4_upscale" else 0))
        updated += 1

    conn.commit()

    # Statistik
    print("=" * 50)
    print("DRUCKKATEGORIEN HINZUGEFUEGT")
    print("=" * 50)
    for row in conn.execute("""
        SELECT print_cat, COUNT(*) as cnt,
               MIN(dpi_a4) as min_dpi, MAX(dpi_a4) as max_dpi
        FROM print_info GROUP BY print_cat ORDER BY cnt DESC
    """):
        label = {
            "a4_ready": "A4 direkt druckbar",
            "a4_upscale": "A4 mit Upscaling",
            "postkarte_only": "Nur Postkarte",
            "too_small": "Zu klein"
        }.get(row["print_cat"], row["print_cat"])
        print(f"  {label:25s}  {row['cnt']:5d} Fotos  ({row['min_dpi']}-{row['max_dpi']} DPI)")

    print(f"\n  Orientierung:")
    for row in conn.execute("SELECT orientation, COUNT(*) as cnt FROM print_info GROUP BY orientation ORDER BY cnt DESC"):
        print(f"    {row['orientation']:12s}  {row['cnt']} Fotos")

    print(f"\n  {updated} Fotos analysiert")
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fotokatalog.db")
    args = parser.parse_args()
    add_print_info(args.db)
