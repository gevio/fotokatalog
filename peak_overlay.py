"""
FOTOKATALOG - Gipfel-Erkennung & Overlay
==========================================
Sendet Fotos MIT GPS-Koordinaten an Claude Vision.
Claude identifiziert sichtbare Berggipfel.
Erstellt annotierte Kopien mit Gipfelmarkierungen.

Nutzung:
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    python peak_overlay.py                     # alle 5-Sterne mit GPS
    python peak_overlay.py --stars 4           # 4+ Sterne
    python peak_overlay.py --limit 5           # nur 5 Fotos testen
    python peak_overlay.py --photo-id 42       # einzelnes Foto
"""

import sqlite3
import base64
import json
import os
import sys
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("FEHLER: Pillow nicht installiert!")
    print("  pip install Pillow")
    sys.exit(1)

DB_PATH = "fotokatalog.db"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"
OUTPUT_DIR = "_annotated"

PEAK_SYSTEM_PROMPT = """Du bist ein Experte fuer Alpentopografie und Bergidentifikation.

Du erhaeltst ein Landschaftsfoto zusammen mit den GPS-Koordinaten des Aufnahmestandorts und der Hoehe.
Identifiziere die sichtbaren Berggipfel im Bild.

Antworte NUR mit JSON, kein anderer Text:

{
  "peaks": [
    {
      "name": "Bietschhorn",
      "elevation": 3934,
      "x_percent": 35,
      "y_percent": 20,
      "confidence": "hoch"
    },
    {
      "name": "Weisshorn", 
      "elevation": 4506,
      "x_percent": 65,
      "y_percent": 15,
      "confidence": "mittel"
    }
  ],
  "view_direction": "Suedwest",
  "notes": "Blick ins Rhonetal, Walliser Alpen im Hintergrund"
}

Regeln:
- x_percent: horizontale Position des Gipfels im Bild (0=links, 100=rechts)
- y_percent: vertikale Position des Gipfels im Bild (0=oben, 100=unten)
- Platziere die Markierung GENAU auf der Gipfelspitze
- confidence: "hoch" (sicher erkannt), "mittel" (wahrscheinlich), "niedrig" (unsicher)
- Nur Gipfel angeben die du wirklich im Bild siehst
- Elevation in Metern
- Lieber weniger Gipfel mit hoher Konfidenz als viele unsichere
- Beruecksichtige den Aufnahmestandort um die Blickrichtung zu bestimmen
- Bekannte Gipfel der Schweizer Alpen: Matterhorn, Weisshorn, Bietschhorn, Dents du Midi, Grand Combin, Mont Blanc, Diablerets, Wildhorn, Wildstrubel, Rinderhorn, Balmhorn, Doldenhorn, etc."""


def get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("FEHLER: ANTHROPIC_API_KEY nicht gesetzt!")
        print('  $env:ANTHROPIC_API_KEY = "sk-ant-..."')
        sys.exit(1)
    return key


def get_photos(db_path, min_stars=5, limit=None, photo_id=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if photo_id:
        rows = conn.execute("""
            SELECT p.id, p.file_path, p.file_name, p.rating,
                   g.latitude, g.longitude, g.altitude, g.city
            FROM photos p
            JOIN geo_data g ON p.id = g.photo_id
            WHERE p.id = ?
        """, (photo_id,)).fetchall()
    else:
        sql = """
            SELECT p.id, p.file_path, p.file_name, p.rating,
                   g.latitude, g.longitude, g.altitude, g.city
            FROM photos p
            JOIN geo_data g ON p.id = g.photo_id
            WHERE (p.is_hidden=0 OR p.is_hidden IS NULL)
              AND p.rating >= ?
              AND g.latitude IS NOT NULL
            ORDER BY p.rating DESC, p.date_taken DESC
        """
        args = [min_stars]
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        rows = conn.execute(sql, args).fetchall()

    result = [dict(r) for r in rows]
    conn.close()
    return result


def make_thumbnail_base64(file_path, max_size=768):
    try:
        img = Image.open(file_path)
        img.thumbnail((max_size, max_size))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"
    except Exception as e:
        print(f"  Bild-Fehler: {e}")
        return None, None


def call_peak_api(api_key, image_b64, media_type, lat, lon, alt, city):
    location_info = f"Aufnahmestandort: {lat:.5f}N, {lon:.5f}E"
    if alt:
        location_info += f", Hoehe: {int(alt)}m"
    if city:
        location_info += f", Ort: {city}"

    payload = {
        "model": MODEL,
        "max_tokens": 800,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64
                        }
                    },
                    {
                        "type": "text",
                        "text": f"Identifiziere die sichtbaren Berggipfel in diesem Foto.\n{location_info}"
                    }
                ]
            }
        ],
        "system": PEAK_SYSTEM_PROMPT
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        text = ""
        for block in result.get("content", []):
            if block.get("type") == "text":
                text += block["text"]

        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        analysis = json.loads(text)
        usage = result.get("usage", {})
        return analysis, usage

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"  API-Fehler {e.code}: {body[:200]}")
        return None, None
    except json.JSONDecodeError as e:
        print(f"  JSON-Parse-Fehler: {e}")
        print(f"  Antwort: {text[:300]}")
        return None, None
    except Exception as e:
        print(f"  Fehler: {e}")
        return None, None


def get_font(size):
    """Versucht eine gute Schrift zu laden, Fallback auf Default."""
    font_paths = [
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except:
                pass
    return ImageFont.load_default()


def create_overlay(original_path, peaks_data, output_path):
    """Erstellt eine annotierte Kopie des Fotos mit Gipfelmarkierungen."""
    img = Image.open(original_path).copy()
    if img.mode != "RGB":
        img = img.convert("RGB")

    draw = ImageDraw.Draw(img)
    w, h = img.size

    # Schriftgroessen relativ zur Bildbreite
    name_size = max(int(w * 0.018), 14)
    elev_size = max(int(w * 0.013), 11)
    font_name = get_font(name_size)
    font_elev = get_font(elev_size)

    peaks = peaks_data.get("peaks", [])

    for peak in peaks:
        name = peak.get("name", "?")
        elevation = peak.get("elevation", 0)
        x_pct = peak.get("x_percent", 50)
        y_pct = peak.get("y_percent", 30)
        confidence = peak.get("confidence", "mittel")

        # Position berechnen
        px = int(w * x_pct / 100)
        py = int(h * y_pct / 100)

        # Farben nach Konfidenz
        if confidence == "hoch":
            color = (255, 255, 255)
            shadow = (0, 0, 0)
            line_color = (255, 255, 255, 200)
        elif confidence == "mittel":
            color = (255, 255, 200)
            shadow = (0, 0, 0)
            line_color = (255, 255, 200, 180)
        else:
            color = (200, 200, 200)
            shadow = (0, 0, 0)
            line_color = (200, 200, 200, 150)

        # Markierungspunkt (kleiner Kreis auf dem Gipfel)
        dot_r = max(int(w * 0.003), 3)
        draw.ellipse([px - dot_r, py - dot_r, px + dot_r, py + dot_r],
                     fill=color, outline=shadow, width=1)

        # Linie nach oben zum Label
        line_len = max(int(h * 0.06), 30)
        label_y = py - line_len
        draw.line([(px, py - dot_r), (px, label_y)], fill=color, width=1)

        # Label-Text
        label = f"{name}"
        elev_text = f"{elevation} m" if elevation else ""

        # Text mit Schatten fuer Lesbarkeit
        for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1), (-2, 0), (2, 0), (0, -2), (0, 2)]:
            draw.text((px + dx, label_y - name_size - 2 + dy), label,
                     font=font_name, fill=shadow, anchor="mb")
            if elev_text:
                draw.text((px + dx, label_y + dy), elev_text,
                         font=font_elev, fill=shadow, anchor="mt")

        # Haupttext
        draw.text((px, label_y - name_size - 2), label,
                 font=font_name, fill=color, anchor="mb")
        if elev_text:
            draw.text((px, label_y), elev_text,
                     font=font_elev, fill=color, anchor="mt")

    # Info-Zeile unten
    view_dir = peaks_data.get("view_direction", "")
    notes = peaks_data.get("notes", "")
    if view_dir or notes:
        info = ""
        if view_dir:
            info += f"Blickrichtung: {view_dir}"
        if notes:
            info += f"  |  {notes}" if info else notes
        info_font = get_font(max(int(w * 0.011), 10))
        # Halbtransparenter Balken unten
        bar_h = max(int(h * 0.035), 24)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle([(0, h - bar_h), (w, h)], fill=(0, 0, 0, 120))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw.text((10, h - bar_h + 4), info, font=info_font, fill=(255, 255, 255))

    # Speichern
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "JPEG", quality=92)
    return True


def save_peaks_to_db(db_path, photo_id, peaks_data):
    """Speichert Gipfeldaten in der DB."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS peak_annotations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id    INTEGER REFERENCES photos(id) ON DELETE CASCADE,
            peak_name   TEXT,
            elevation   INTEGER,
            x_percent   REAL,
            y_percent   REAL,
            confidence  TEXT,
            UNIQUE(photo_id, peak_name)
        );
    """)

    for peak in peaks_data.get("peaks", []):
        conn.execute("""
            INSERT OR REPLACE INTO peak_annotations
            (photo_id, peak_name, elevation, x_percent, y_percent, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            photo_id,
            peak.get("name"),
            peak.get("elevation"),
            peak.get("x_percent"),
            peak.get("y_percent"),
            peak.get("confidence")
        ))

        # Auch als Tag
        tag_name = peak.get("name", "")
        if tag_name:
            row = conn.execute("SELECT id FROM tags WHERE name=? AND category='motiv'", (tag_name,)).fetchone()
            if row:
                tag_id = row[0]
            else:
                cur = conn.execute("INSERT INTO tags (name, category, auto_generated) VALUES (?, 'motiv', 1)", (tag_name,))
                tag_id = cur.lastrowid
            conf = {"hoch": 0.95, "mittel": 0.7, "niedrig": 0.4}.get(peak.get("confidence", ""), 0.7)
            conn.execute("INSERT OR IGNORE INTO photo_tags (photo_id, tag_id, confidence) VALUES (?, ?, ?)",
                        (photo_id, tag_id, conf))

    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Fotokatalog - Gipfel-Erkennung & Overlay")
    parser.add_argument("--db", default="fotokatalog.db")
    parser.add_argument("--stars", type=int, default=5, help="Minimum Sterne (Standard: 5)")
    parser.add_argument("--limit", type=int, help="Max. Anzahl Fotos")
    parser.add_argument("--photo-id", type=int, help="Einzelnes Foto per ID")
    parser.add_argument("--output", default=OUTPUT_DIR, help="Ausgabe-Ordner")
    parser.add_argument("--delay", type=float, default=1.5, help="Pause zwischen API-Calls")
    args = parser.parse_args()

    api_key = get_api_key()
    photos = get_photos(args.db, min_stars=args.stars, limit=args.limit, photo_id=args.photo_id)

    if not photos:
        print("Keine Fotos mit GPS-Daten gefunden!")
        return

    gps_count = sum(1 for p in photos if p.get("latitude"))
    print("")
    print("  FOTOKATALOG - Gipfel-Erkennung")
    print("  ================================")
    print(f"  Fotos mit GPS: {gps_count}")
    print(f"  Ausgabe:       {os.path.abspath(args.output)}")
    print(f"  Geschaetzte Kosten: ~${gps_count * 0.008:.2f}")
    print("")

    answer = input(f"  {gps_count} Fotos analysieren? (j/n): ").strip().lower()
    if answer not in ("j", "ja", "y", "yes"):
        print("  Abgebrochen.")
        return

    print("")
    os.makedirs(args.output, exist_ok=True)

    success = 0
    errors = 0
    total_peaks = 0

    for i, photo in enumerate(photos, 1):
        fpath = photo["file_path"]
        fname = photo["file_name"]
        lat = photo["latitude"]
        lon = photo["longitude"]
        alt = photo.get("altitude")
        city = photo.get("city")

        print(f"[{i}/{len(photos)}] {fname}  ({city or '?'}, {int(alt or 0)}m)")

        if not os.path.exists(fpath):
            print(f"  Datei nicht gefunden: {fpath}")
            errors += 1
            continue

        # Thumbnail fuer API (etwas groesser fuer Gipfelerkennung)
        b64, mtype = make_thumbnail_base64(fpath, 768)
        if not b64:
            errors += 1
            continue

        # API aufrufen
        peaks_data, usage = call_peak_api(api_key, b64, mtype, lat, lon, alt, city)

        if peaks_data and peaks_data.get("peaks"):
            n_peaks = len(peaks_data["peaks"])
            total_peaks += n_peaks

            # Gipfel anzeigen
            for pk in peaks_data["peaks"]:
                conf_icon = {"hoch": "+", "mittel": "~", "niedrig": "?"}.get(pk.get("confidence", ""), "?")
                print(f"  {conf_icon} {pk['name']} ({pk.get('elevation', '?')}m) [{pk.get('confidence')}]")

            if peaks_data.get("view_direction"):
                print(f"  Blick: {peaks_data['view_direction']}")

            # Overlay erstellen
            out_path = os.path.join(args.output, fname)
            try:
                create_overlay(fpath, peaks_data, out_path)
                print(f"  -> {out_path}")
            except Exception as e:
                print(f"  Overlay-Fehler: {e}")

            # In DB speichern
            save_peaks_to_db(args.db, photo["id"], peaks_data)
            success += 1
        elif peaks_data:
            print(f"  Keine Gipfel erkannt")
            success += 1
        else:
            errors += 1

        if i < len(photos):
            time.sleep(args.delay)

    print("")
    print("  ================================")
    print("  ERGEBNIS")
    print("  ================================")
    print(f"  Fotos analysiert: {success}")
    print(f"  Gipfel erkannt:   {total_peaks}")
    print(f"  Fehler:           {errors}")
    print(f"  Annotierte Fotos: {args.output}/")
    print("")


if __name__ == "__main__":
    main()
