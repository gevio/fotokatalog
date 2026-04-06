"""
FOTOKATALOG - Claude Vision Tagging
====================================
Sendet ausgewaehlte Fotos an Claude Vision API fuer:
- Qualitaetsbewertung (1-5)
- Postkarten-Eignung (1-5)
- Grossformat-Druck-Eignung (1-5)
- Stimmung
- Beschreibung
- Tags

Nutzung:
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    python vision_tags.py                         # alle 5-Sterne Fotos
    python vision_tags.py --stars 4               # alle 4+ Sterne
    python vision_tags.py --limit 20              # nur erste 20
    python vision_tags.py --all                   # alle nicht-versteckten
    python vision_tags.py --db pfad/zur/db.db
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
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

DB_PATH = "fotokatalog.db"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """Du bist ein Experte fuer Landschaftsfotografie, Bildanalyse und Alpentopografie.
Analysiere das Foto und gib eine JSON-Antwort zurueck. NUR JSON, kein anderer Text.

{
  "quality_score": 4,
  "postcard_score": 5,
  "print_score": 3,
  "mood": "dramatisch",
  "description": "Sonnenuntergang ueber verschneiten Alpengipfeln mit warmem Gegenlicht und Foehwolken",
  "key_elements": "Starker Vordergrund mit Holzzaun, goldenes Licht, klare Bergsilhouette",
  "tags": ["Sonnenuntergang", "Alpenpanorama", "Winterlandschaft", "Gegenlicht", "Foehwolken"],
  "peaks": ["Weisshorn", "Bietschhorn"]
}

Bewertungskriterien:
- quality_score (1-5): Gesamteindruck, Komposition, Licht, Schaerfe, Bildwirkung
- postcard_score (1-5): Eignung als Postkarte - klarer Blickfang, kraeftige Farben, ikonisches Motiv, ausgewogene Komposition
- print_score (1-5): Eignung fuer Grossformat A4-Druck - Detailreichtum, Tiefenwirkung, keine stoerenden Elemente, clean
- mood: Ein Wort - dramatisch, friedlich, mystisch, majestaetisch, intim, wild, warm, kalt, melancholisch
- description: 1-2 Saetze, was das Bild zeigt und was es besonders macht
- key_elements: Was macht das Bild stark oder schwach
- tags: 3-7 spezifische Tags (deutsch), z.B. Bergpanorama, Spiegelung, Nebelmeer, Chalet, Matterhorn, Laerchen, Gletschersee
- peaks: Liste erkennbarer Berggipfel. WICHTIG: Identifiziere NUR Gipfel die du tatsaechlich ALS GIPFELFORM IM BILD SIEHST — nicht Gipfel die einfach in der Naehe des Standorts liegen! Die GPS-Koordinaten helfen dir einzugrenzen welche Gipfel es sein KOENNTEN, aber du musst die Gipfelsilhouette im Foto erkennen. Gipfel die sich hinter dem Fotografen befinden oder durch Wolken/Vordergrund verdeckt sind, gehoeren NICHT in die Liste. Leeres Array [] wenn du keine Gipfel sicher im Bild erkennen kannst. Lieber leer als falsch.

Sei ehrlich bei der Bewertung. Nicht jedes Foto ist eine 5."""


def get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("FEHLER: ANTHROPIC_API_KEY nicht gesetzt!")
        print("")
        print("Setze den Key so:")
        print('  $env:ANTHROPIC_API_KEY = "sk-ant-..."')
        print("")
        print("Dann nochmal ausfuehren:")
        print("  python vision_tags.py")
        sys.exit(1)
    return key


def get_photos(db_path, min_stars=5, limit=None, all_photos=False, skip_analyzed=False):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    where = "(p.is_hidden=0 OR p.is_hidden IS NULL)"
    args = []

    if not all_photos:
        where += " AND p.rating>=?"
        args.append(min_stars)

    if skip_analyzed:
        where += " AND p.id NOT IN (SELECT photo_id FROM vision_analysis)"

    sql = """SELECT p.id, p.file_path, p.file_name, p.rating,
                    g.latitude, g.longitude, g.altitude, g.city, g.country
             FROM photos p
             LEFT JOIN geo_data g ON p.id = g.photo_id
             WHERE """ + where + " ORDER BY p.rating DESC, p.date_taken DESC"
    if limit:
        sql += " LIMIT ?"
        args.append(limit)

    rows = conn.execute(sql, args).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def make_thumbnail_base64(file_path, max_size=512):
    """Erstellt ein verkleinertes JPEG und gibt Base64 zurueck."""
    if not HAS_PIL:
        # Fallback: ganzes Bild lesen
        with open(file_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8"), "image/jpeg"

    try:
        img = Image.open(file_path)
        img.thumbnail((max_size, max_size))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        return b64, "image/jpeg"
    except Exception as e:
        print(f"  Bild-Fehler: {e}")
        return None, None


def call_vision_api(api_key, image_b64, media_type, geo_info=None):
    """Sendet ein Bild an Claude Vision und gibt die Analyse zurueck."""
    user_text = "Analysiere dieses Landschaftsfoto."
    if geo_info:
        user_text += "\n" + geo_info

    payload = {
        "model": MODEL,
        "max_tokens": 600,
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
                        "text": user_text
                    }
                ]
            }
        ],
        "system": SYSTEM_PROMPT
    }

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(API_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        # Antwort-Text extrahieren
        text = ""
        for block in result.get("content", []):
            if block.get("type") == "text":
                text += block["text"]

        # JSON parsen (evtl. mit Backticks)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        analysis = json.loads(text)

        # Usage fuer Kostenberechnung
        usage = result.get("usage", {})
        return analysis, usage

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"  API-Fehler {e.code}: {body[:200]}")
        return None, None
    except json.JSONDecodeError as e:
        print(f"  JSON-Parse-Fehler: {e}")
        print(f"  Antwort: {text[:200]}")
        return None, None
    except Exception as e:
        print(f"  Fehler: {e}")
        return None, None


def save_analysis(db_path, photo_id, analysis):
    """Speichert die Vision-Analyse in der Datenbank."""
    conn = sqlite3.connect(db_path)

    # Vision-Ergebnisse in eine eigene Tabelle
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS vision_analysis (
            photo_id        INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
            quality_score   INTEGER,
            postcard_score  INTEGER,
            print_score     INTEGER,
            mood            TEXT,
            description     TEXT,
            key_elements    TEXT,
            analyzed_at     TEXT DEFAULT (datetime('now'))
        );
    """)

    conn.execute("""
        INSERT OR REPLACE INTO vision_analysis
        (photo_id, quality_score, postcard_score, print_score, mood, description, key_elements)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        photo_id,
        analysis.get("quality_score"),
        analysis.get("postcard_score"),
        analysis.get("print_score"),
        analysis.get("mood"),
        analysis.get("description"),
        analysis.get("key_elements")
    ))

    # Tags hinzufuegen
    for tag_name in analysis.get("tags", []):
        tag_name = tag_name.strip()
        if not tag_name:
            continue
        row = conn.execute(
            "SELECT id FROM tags WHERE name=? AND category='motiv'", (tag_name,)
        ).fetchone()
        if row:
            tag_id = row[0]
        else:
            cur = conn.execute(
                "INSERT INTO tags (name, category, auto_generated) VALUES (?, 'motiv', 1)",
                (tag_name,)
            )
            tag_id = cur.lastrowid
        conn.execute(
            "INSERT OR IGNORE INTO photo_tags (photo_id, tag_id, confidence) VALUES (?, ?, 0.9)",
            (photo_id, tag_id)
        )

    # Gipfel als Tags hinzufuegen (eigene Kategorie 'custom' fuer Gipfelnamen)
    for peak_name in analysis.get("peaks", []):
        peak_name = peak_name.strip()
        if not peak_name:
            continue
        row = conn.execute(
            "SELECT id FROM tags WHERE name=?", (peak_name,)
        ).fetchone()
        if row:
            tag_id = row[0]
        else:
            cur = conn.execute(
                "INSERT INTO tags (name, category, auto_generated) VALUES (?, 'motiv', 1)",
                (peak_name,)
            )
            tag_id = cur.lastrowid
        conn.execute(
            "INSERT OR IGNORE INTO photo_tags (photo_id, tag_id, confidence) VALUES (?, ?, 0.85)",
            (photo_id, tag_id)
        )

    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Fotokatalog - Claude Vision Tagging")
    parser.add_argument("--db", default="fotokatalog.db")
    parser.add_argument("--stars", type=int, default=5, help="Minimum Sterne (Standard: 5)")
    parser.add_argument("--limit", type=int, help="Max. Anzahl Fotos")
    parser.add_argument("--all", action="store_true", help="Alle nicht-versteckten Fotos")
    parser.add_argument("--skip-analyzed", action="store_true", help="Bereits analysierte ueberspringen")
    parser.add_argument("--thumb-size", type=int, default=512, help="Thumbnail-Groesse in Pixel")
    parser.add_argument("--delay", type=float, default=1.0, help="Pause zwischen API-Calls in Sekunden")
    args = parser.parse_args()

    api_key = get_api_key()

    # Fotos laden
    photos = get_photos(args.db, min_stars=args.stars, limit=args.limit,
                        all_photos=args.all, skip_analyzed=args.skip_analyzed)

    if not photos:
        print("Keine Fotos gefunden!")
        if not args.all:
            print(f"  (Filter: {args.stars}+ Sterne, nicht versteckt)")
            print(f"  Tipp: --stars 4 oder --all")
        return

    print("")
    print("  FOTOKATALOG - Claude Vision Tagging")
    print("  ====================================")
    print(f"  Fotos:     {len(photos)}")
    print(f"  Modell:    {MODEL}")
    print(f"  Thumbnail: {args.thumb_size}px")
    print(f"  Geschaetzte Kosten: ~${len(photos) * 0.005:.2f}")
    print("")

    # Bestaetigung
    answer = input(f"  {len(photos)} Fotos analysieren? (j/n): ").strip().lower()
    if answer not in ("j", "ja", "y", "yes"):
        print("  Abgebrochen.")
        return

    print("")

    total_input = 0
    total_output = 0
    success = 0
    errors = 0

    for i, photo in enumerate(photos, 1):
        fpath = photo["file_path"]
        fname = photo["file_name"]

        print(f"[{i}/{len(photos)}] {fname} ({'*' * photo['rating']})")

        # Datei pruefen
        if not os.path.exists(fpath):
            print(f"  Datei nicht gefunden: {fpath}")
            errors += 1
            continue

        # Thumbnail erstellen
        b64, mtype = make_thumbnail_base64(fpath, args.thumb_size)
        if not b64:
            errors += 1
            continue

        # API aufrufen (mit GPS-Kontext wenn vorhanden)
        geo_info = None
        lat = photo.get("latitude")
        lon = photo.get("longitude")
        alt = photo.get("altitude")
        city = photo.get("city")
        if lat and lon:
            geo_info = f"Aufnahmestandort: {lat:.5f}N, {lon:.5f}E"
            if alt:
                geo_info += f", Hoehe: {int(alt)}m"
            if city:
                geo_info += f", Ort: {city}, {photo.get('country', '')}"

        analysis, usage = call_vision_api(api_key, b64, mtype, geo_info)

        if analysis:
            save_analysis(args.db, photo["id"], analysis)
            q = analysis.get("quality_score", "?")
            pk = analysis.get("postcard_score", "?")
            pr = analysis.get("print_score", "?")
            mood = analysis.get("mood", "?")
            tags = ", ".join(analysis.get("tags", []))
            peaks = analysis.get("peaks", [])
            print(f"  Qualitaet: {q}/5  Postkarte: {pk}/5  Druck: {pr}/5  Stimmung: {mood}")
            print(f"  Tags: {tags}")
            if peaks:
                print(f"  Gipfel: {', '.join(peaks)}")
            print(f"  {analysis.get('description', '')}")
            success += 1

            if usage:
                total_input += usage.get("input_tokens", 0)
                total_output += usage.get("output_tokens", 0)
        else:
            errors += 1

        # Pause zwischen Calls
        if i < len(photos):
            time.sleep(args.delay)

    # Zusammenfassung
    cost_input = total_input * 3 / 1_000_000
    cost_output = total_output * 15 / 1_000_000
    total_cost = cost_input + cost_output

    print("")
    print("  ====================================")
    print("  ERGEBNIS")
    print("  ====================================")
    print(f"  Erfolgreich: {success}")
    print(f"  Fehler:      {errors}")
    print(f"  Tokens:      {total_input:,} Input + {total_output:,} Output")
    print(f"  Kosten:      ~${total_cost:.3f}")
    print("")
    print("  Ergebnisse in der DB gespeichert.")
    print("  Starte webui.py um sie zu sehen.")


if __name__ == "__main__":
    main()
