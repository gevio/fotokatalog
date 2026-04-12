#!/usr/bin/env python3
"""
FOTOKATALOG - Preview-Pipeline
================================
Generiert wassergezeichnete Vorschaubilder fuer Web/Prod.
Originale bleiben lokal, nur Previews werden deployed.

Nutzung:
    python generate_previews.py
    python generate_previews.py --db fotokatalog.db
    python generate_previews.py --force              # alle neu generieren
    python generate_previews.py --ids 1,2,42         # nur bestimmte IDs
    python generate_previews.py --dry-run            # nur zaehlen
"""

import sqlite3
import argparse
import os
import sys
import math

try:
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(SCRIPT_DIR, "fotokatalog.db")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "_previews")

# ── Konfiguration ──────────────────────────────────────────
MAX_LONG_EDGE = 1200       # px, ausreichend fuer Web, unbrauchbar fuer Druck
JPEG_QUALITY = 82          # guter Kompromiss Qualitaet/Groesse
WATERMARK_TEXT = "\u00a9 P. Kueck"
WATERMARK_OPACITY = 35     # 0-255, dezent
WATERMARK_REPEAT = 5       # Anzahl diagonaler Wiederholungen


def get_font(size):
    """Versucht eine passende Schrift zu laden."""
    font_candidates = [
        "arial.ttf",
        "Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for font_path in font_candidates:
        try:
            return ImageFont.truetype(font_path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def add_watermark(img):
    """Fuegt dezentes diagonales Wasserzeichen hinzu."""
    # Overlay erstellen (RGBA)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Schriftgroesse relativ zur Bildgroesse
    font_size = max(16, min(img.width, img.height) // 25)
    font = get_font(font_size)

    # Text-Bounding-Box messen
    bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Diagonale Wiederholungen
    diag = math.sqrt(img.width ** 2 + img.height ** 2)
    spacing = diag / (WATERMARK_REPEAT + 1)

    for i in range(1, WATERMARK_REPEAT + 1):
        # Position entlang der Diagonale
        frac = i / (WATERMARK_REPEAT + 1)
        cx = img.width * frac
        cy = img.height * frac
        x = int(cx - text_w / 2)
        y = int(cy - text_h / 2)
        draw.text((x, y), WATERMARK_TEXT, font=font,
                  fill=(255, 255, 255, WATERMARK_OPACITY))

    # Overlay auf Bild legen
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    watermarked = Image.alpha_composite(img, overlay)
    return watermarked.convert("RGB")


def resize_image(img, max_edge=MAX_LONG_EDGE):
    """Skaliert auf max max_edge, behaelt Seitenverhaeltnis."""
    w, h = img.size
    if max(w, h) <= max_edge:
        return img
    if w >= h:
        new_w = max_edge
        new_h = int(h * max_edge / w)
    else:
        new_h = max_edge
        new_w = int(w * max_edge / h)
    return img.resize((new_w, new_h), Image.LANCZOS)


def generate_preview(file_path, output_path, max_edge=MAX_LONG_EDGE, quality=JPEG_QUALITY):
    """Generiert ein einzelnes Preview-Bild."""
    img = Image.open(file_path)

    # EXIF-Rotation beruecksichtigen
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    img = resize_image(img, max_edge)
    img = add_watermark(img)
    img.save(output_path, "JPEG", quality=quality, optimize=True)
    return os.path.getsize(output_path)


def main():
    if not HAS_PIL:
        print("FEHLER: Pillow nicht installiert (pip install Pillow)")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Fotokatalog Preview-Generator")
    parser.add_argument("--db", default=DEFAULT_DB, help="Pfad zur SQLite-DB")
    parser.add_argument("--output", default=OUTPUT_DIR, help="Ausgabe-Verzeichnis")
    parser.add_argument("--force", action="store_true", help="Alle Previews neu generieren")
    parser.add_argument("--ids", help="Nur bestimmte Photo-IDs (kommasepariert)")
    parser.add_argument("--dry-run", action="store_true", help="Nur zaehlen")
    parser.add_argument("--max-edge", type=int, default=MAX_LONG_EDGE, help="Max lange Kante in px")
    parser.add_argument("--quality", type=int, default=JPEG_QUALITY, help="JPEG-Qualitaet (1-100)")
    args = parser.parse_args()

    max_edge = args.max_edge
    quality = args.quality

    if not os.path.exists(args.db):
        print(f"FEHLER: Datenbank nicht gefunden: {args.db}")
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Fotos abfragen (nur sichtbare)
    sql = """SELECT id, file_path, file_name FROM photos
             WHERE (is_hidden=0 OR is_hidden IS NULL)"""
    params = []

    if args.ids:
        id_list = [int(x.strip()) for x in args.ids.split(",")]
        placeholders = ",".join("?" * len(id_list))
        sql += f" AND id IN ({placeholders})"
        params.extend(id_list)

    sql += " ORDER BY id"
    photos = conn.execute(sql, params).fetchall()

    print("=" * 50)
    print("FOTOKATALOG: Preview-Generator")
    print("=" * 50)
    print(f"  DB:       {args.db}")
    print(f"  Output:   {args.output}")
    print(f"  Fotos:    {len(photos)} sichtbare")
    print(f"  Max Edge: {max_edge}px")
    print(f"  Quality:  {quality}%")
    print(f"  Force:    {'ja' if args.force else 'nein'}")
    print(f"  Modus:    {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()

    generated = 0
    skipped = 0
    errors = 0
    total_size = 0

    for photo in photos:
        pid = photo["id"]
        fpath = photo["file_path"]
        fname = photo["file_name"]
        out_path = os.path.join(args.output, f"{pid}.jpg")

        # Skip wenn schon vorhanden und nicht --force
        if os.path.exists(out_path) and not args.force:
            skipped += 1
            continue

        if args.dry_run:
            if os.path.exists(fpath):
                generated += 1
            else:
                print(f"  FEHLT: {fname} ({fpath})")
                errors += 1
            continue

        # Original vorhanden?
        if not os.path.exists(fpath):
            print(f"  FEHLT: {fname} ({fpath})")
            errors += 1
            continue

        try:
            size = generate_preview(fpath, out_path, max_edge, quality)
            total_size += size
            generated += 1
            if generated % 50 == 0:
                print(f"  ... {generated} generiert ({total_size / 1024 / 1024:.1f} MB)")
        except Exception as e:
            print(f"  FEHLER bei {fname}: {e}")
            errors += 1

    conn.close()

    print()
    print(f"Ergebnis:")
    print(f"  Generiert:   {generated}")
    print(f"  Uebersprungen: {skipped} (existieren bereits)")
    print(f"  Fehler:      {errors}")
    if total_size > 0:
        print(f"  Gesamtgroesse: {total_size / 1024 / 1024:.1f} MB")
        if generated > 0:
            print(f"  Durchschnitt:  {total_size / generated / 1024:.0f} KB/Bild")
    if args.dry_run:
        print("  (dry-run, nichts geschrieben)")


if __name__ == "__main__":
    main()
