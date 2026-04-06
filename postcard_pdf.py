"""
FOTOKATALOG - Postkarten PDF Generator
========================================
Generiert druckfertige PDFs fuer Postkarten:
- Vorderseite: Foto (randabfallend)
- Rueckseite: Gibran-Text, Ortsname, Fotograf

Formate:
- DIN lang: 210 x 105 mm (+ 3mm Beschnitt = 216 x 111 mm)
- A6: 148 x 105 mm (+ 3mm Beschnitt = 154 x 111 mm)  [spaeter]

Nutzung:
    python postcard_pdf.py                         # alle mit Gibran-Text
    python postcard_pdf.py --limit 5               # nur 5
    python postcard_pdf.py --photo-id 42           # einzelnes Foto
    python postcard_pdf.py --format a6             # A6 statt DIN lang
    python postcard_pdf.py --lang de               # Deutsch statt FR
"""

import sqlite3
import os
import sys
import argparse
from pathlib import Path

try:
    from reportlab.lib.pagesizes import mm
    from reportlab.lib.colors import Color, black, white, HexColor
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

DB_PATH = "fotokatalog.db"
OUTPUT_DIR = "_postkarten"

# Formate in mm
FORMATS = {
    "dinlang": {"name": "DIN lang", "w": 210, "h": 105},
    "a6":      {"name": "A6",       "w": 148, "h": 105},
    "a6hoch":  {"name": "A6 hoch", "w": 105, "h": 148},
}

BLEED = 3  # mm Beschnitt
SAFE_MARGIN = 8  # mm Sicherheitsabstand fuer Text


def detect_format(photo):
    """Erkennt das beste Kartenformat anhand des Bildseitenverhältnisses."""
    fpath = photo.get("file_path", "")
    try:
        img = Image.open(fpath) if HAS_PIL else None
        if img:
            iw, ih = img.size
        else:
            iw = photo.get("width") or 4
            ih = photo.get("height") or 3
    except:
        iw = photo.get("width") or 4
        ih = photo.get("height") or 3

    ratio = iw / ih if ih > 0 else 1.5

    if ratio >= 1.7:
        return "dinlang"    # Breit-Panorama -> DIN lang (210x105, 2:1)
    elif ratio >= 1.0:
        return "a6"         # Normal quer (4:3, 3:2) -> A6 quer (148x105)
    else:
        return "a6hoch"     # Hochformat -> A6 hoch (105x148)

# Farben
DARK_GRAY = HexColor("#2c2c2a")
MID_GRAY = HexColor("#6b6a66")
LIGHT_GRAY = HexColor("#9c9a92")
ACCENT = HexColor("#2563eb")


def register_fonts():
    """Versucht elegante Schriften zu laden."""
    font_paths = {
        "Garamond": [
            "C:/Windows/Fonts/garamond.ttf",
            "C:/Windows/Fonts/GARA.TTF",
            "C:/Windows/Fonts/EBGaramond-Regular.ttf",
        ],
        "GaramondItalic": [
            "C:/Windows/Fonts/garamonditalic.ttf",
            "C:/Windows/Fonts/GARAIT.TTF",
            "C:/Windows/Fonts/EBGaramond-Italic.ttf",
        ],
        "Calibri": [
            "C:/Windows/Fonts/calibri.ttf",
        ],
        "CalibriBold": [
            "C:/Windows/Fonts/calibrib.ttf",
        ],
        "CalibriLight": [
            "C:/Windows/Fonts/calibril.ttf",
        ],
    }

    registered = {}
    for name, paths in font_paths.items():
        for fp in paths:
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont(name, fp))
                    registered[name] = True
                    break
                except:
                    pass

    # Fallbacks
    if "Garamond" not in registered:
        # Try Georgia as fallback serif
        for fp in ["C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/times.ttf"]:
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont("Garamond", fp))
                    registered["Garamond"] = True
                    break
                except:
                    pass

    if "GaramondItalic" not in registered:
        for fp in ["C:/Windows/Fonts/georgiai.ttf", "C:/Windows/Fonts/timesi.ttf"]:
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont("GaramondItalic", fp))
                    registered["GaramondItalic"] = True
                    break
                except:
                    pass

    return registered


def get_postcard_photos(db_path, lang="fr", limit=None, photo_id=None, min_score=4):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    gibran_col = {"fr": "gibran_fr", "de": "gibran_de", "en": "gibran_en"}.get(lang, "gibran_fr")

    if photo_id:
        sql = """
            SELECT p.id, p.file_path, p.file_name, p.width, p.height,
                   g.city, g.country, g.altitude,
                   g.city_fr, g.city_de, g.city_en,
                   va.gibran_de, va.gibran_fr, va.gibran_en, va.gibran_theme, va.gibran_ref,
                   va.postcard_score, va.mood
            FROM photos p
            LEFT JOIN geo_data g ON p.id = g.photo_id
            JOIN vision_analysis va ON p.id = va.photo_id
            WHERE p.id = ?
        """
        rows = conn.execute(sql, (photo_id,)).fetchall()
    else:
        sql = """
            SELECT p.id, p.file_path, p.file_name, p.width, p.height,
                   g.city, g.country, g.altitude,
                   g.city_fr, g.city_de, g.city_en,
                   va.gibran_de, va.gibran_fr, va.gibran_en, va.gibran_theme, va.gibran_ref,
                   va.postcard_score, va.mood
            FROM photos p
            LEFT JOIN geo_data g ON p.id = g.photo_id
            JOIN vision_analysis va ON p.id = va.photo_id
            WHERE (p.is_hidden=0 OR p.is_hidden IS NULL)
              AND va.""" + gibran_col + """ IS NOT NULL
              AND va.""" + gibran_col + """ != ''
              AND va.postcard_score >= ?
            ORDER BY va.postcard_score DESC, p.date_taken DESC
        """
        args = [min_score]
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        rows = conn.execute(sql, args).fetchall()

    result = [dict(r) for r in rows]
    conn.close()
    return result


def create_front_page(c, photo, fmt, bleed, front_style="clean", lang="fr", fonts=None):
    """Zeichnet die Vorderseite.
    front_style: 'clean' (nur Bild), 'location' (Bild + Ort), 'text' (Bild + Gibran-Spruch)
    """
    page_w = (fmt["w"] + 2 * bleed) * mm
    page_h = (fmt["h"] + 2 * bleed) * mm

    c.setPageSize((page_w, page_h))

    fpath = photo["file_path"]
    if not os.path.exists(fpath):
        print(f"  Datei nicht gefunden: {fpath}")
        return False

    if fonts is None:
        fonts = {}

    try:
        img = ImageReader(fpath)
        iw, ih = img.getSize()

        # Weisser Hintergrund
        c.setFillColor(white)
        c.rect(0, 0, page_w, page_h, fill=True, stroke=False)

        card_w = fmt["w"] * mm
        card_h = fmt["h"] * mm
        bx = bleed * mm
        by = bleed * mm

        if front_style == "clean":
            # Contain: Bild zentriert im Druckbereich
            scale_w = card_w / iw
            scale_h = card_h / ih
            scale = min(scale_w, scale_h)
            draw_w = iw * scale
            draw_h = ih * scale
            x = bx + (card_w - draw_w) / 2
            y = by + (card_h - draw_h) / 2
            c.drawImage(img, x, y, draw_w, draw_h)
        else:
            # location/text: Bild contain-zentriert, unterer Rand fuer Text

            scale_w = card_w / iw
            scale_h = card_h / ih
            scale = min(scale_w, scale_h)
            draw_w = iw * scale
            draw_h = ih * scale

            # Vertikaler Freiraum verteilen: 1/3 oben, 2/3 unten (fuer Text)
            total_gap = card_h - draw_h
            gap_top = total_gap / 3
            gap_bottom = total_gap * 2 / 3

            # Mindesthoehe unten fuer Text: 7mm
            if gap_bottom < 7 * mm:
                draw_h = card_h - 7 * mm
                scale = draw_h / ih
                draw_w = iw * scale
                gap_top = 0
                gap_bottom = 7 * mm

            x = bx + (card_w - draw_w) / 2
            y = by + gap_bottom

            c.drawImage(img, x, y, draw_w, draw_h)

            # Weisser Streifen unten
            text_area_h = gap_bottom
            text_area_top = by + text_area_h  # Oberkante des weissen Streifens
            safe = SAFE_MARGIN * mm

            sans_font = "CalibriLight" if "CalibriLight" in fonts else "Calibri" if "Calibri" in fonts else "Helvetica"
            serif_font = "GaramondItalic" if "GaramondItalic" in fonts else "Garamond" if "Garamond" in fonts else "Helvetica"

            if front_style == "location":
                # Ort in Versalien, zentriert — sprachspezifisch
                city_col = {"fr": "city_fr", "de": "city_de", "en": "city_en"}.get(lang, "city_fr")
                loc_text = photo.get(city_col) or ""
                if not loc_text:
                    # Fallback: Original city + country
                    city = photo.get("city") or ""
                    if city:
                        country = photo.get("country") or ""
                        loc_text = city + (", " + country if country else "")
                if loc_text:
                    loc_text = loc_text.upper()

                    c.setFillColor(MID_GRAY)
                    font_size = 10
                    # Sicherstellen dass es in den Streifen passt
                    if font_size * 1.3 > text_area_h * 0.85:
                        font_size = (text_area_h * 0.85) / 1.3
                    font_size = max(7, font_size)
                    c.setFont(sans_font, font_size)

                    # Gesperrte Schrift
                    spacing = 2.0
                    spaced_w = c.stringWidth(loc_text, sans_font, font_size) + spacing * (len(loc_text) - 1)
                    tx = bx + (card_w - spaced_w) / 2
                    ty = by + text_area_h / 2 - font_size * 0.35

                    # Buchstabe fuer Buchstabe mit Abstand zeichnen
                    cx = tx
                    for ch in loc_text:
                        c.drawString(cx, ty, ch)
                        cx += c.stringWidth(ch, sans_font, font_size) + spacing

            elif front_style == "text":
                # Gibran-Spruch, Garamond Italic, zentriert
                gibran_col = {"fr": "gibran_fr", "de": "gibran_de", "en": "gibran_en"}.get(lang, "gibran_fr")
                gibran_text = photo.get(gibran_col, "") or ""

                # Alle moeglichen Newline-Varianten normalisieren
                # 1. Literale Zeichenfolge backslash+n (aus JSON oder DB)
                gibran_text = gibran_text.replace("\\n", "\n")
                # 2. Windows-Zeilenenden
                gibran_text = gibran_text.replace("\r\n", "\n")
                # 3. Alte Mac-Zeilenenden
                gibran_text = gibran_text.replace("\r", "\n")

                if gibran_text:
                    # Gesamten Text zu einem Fliesstext zusammenfuegen
                    full_text = " ".join(l.strip() for l in gibran_text.strip().split("\n") if l.strip())

                    # Volle Kartenbreite nutzen
                    max_tw = card_w - 6 * mm

                    # Immer 1 Zeile: starte bei 11pt, reduziere bis Text passt
                    font_size = 11
                    while font_size >= 6:
                        c.setFont(serif_font, font_size)
                        tw = c.stringWidth(full_text, serif_font, font_size)
                        if tw <= max_tw:
                            break
                        font_size -= 0.5

                    # Falls bei 6pt immer noch zu lang: kuerzen mit "..."
                    display_text = full_text
                    if c.stringWidth(display_text, serif_font, font_size) > max_tw:
                        while len(display_text) > 10 and c.stringWidth(display_text + " ...", serif_font, font_size) > max_tw:
                            display_text = display_text[:-1]
                        display_text = display_text.rstrip(",. ") + " ..."

                    # Schrift nicht groesser als der Streifen erlaubt
                    line_height = font_size * 1.45
                    if line_height > text_area_h * 0.8:
                        font_size = (text_area_h * 0.8) / 1.45
                        line_height = font_size * 1.45

                    c.setFillColor(MID_GRAY)
                    c.setFont(serif_font, font_size)

                    # Vertikal zentriert im weissen Streifen
                    tw = c.stringWidth(display_text, serif_font, font_size)
                    sx = bx + (card_w - tw) / 2
                    sy = by + text_area_h / 2 - font_size * 0.35

                    c.drawString(sx, sy, display_text)

        # Beschnittmarken
        c.setStrokeColor(Color(0, 0, 0, 0.6))
        c.setLineWidth(0.3)
        mark_len = 4 * mm
        mark_gap = 1 * mm
        bx, by = bleed * mm, bleed * mm
        bw, bh = fmt["w"] * mm, fmt["h"] * mm

        c.line(bx - mark_gap - mark_len, by, bx - mark_gap, by)
        c.line(bx, by - mark_gap - mark_len, bx, by - mark_gap)
        c.line(bx + bw + mark_gap, by, bx + bw + mark_gap + mark_len, by)
        c.line(bx + bw, by - mark_gap - mark_len, bx + bw, by - mark_gap)
        c.line(bx - mark_gap - mark_len, by + bh, bx - mark_gap, by + bh)
        c.line(bx, by + bh + mark_gap, bx, by + bh + mark_gap + mark_len)
        c.line(bx + bw + mark_gap, by + bh, bx + bw + mark_gap + mark_len, by + bh)
        c.line(bx + bw, by + bh + mark_gap, bx + bw, by + bh + mark_gap + mark_len)

        return True
    except Exception as e:
        print(f"  Bild-Fehler: {e}")
        return False


def create_back_page(c, photo, fmt, bleed, lang, photographer, fonts):
    """Zeichnet die Rueckseite: Gibran-Text, Ort, Fotograf."""
    page_w = (fmt["w"] + 2 * bleed) * mm
    page_h = (fmt["h"] + 2 * bleed) * mm
    c.setPageSize((page_w, page_h))

    bx = bleed * mm
    by = bleed * mm
    card_w = fmt["w"] * mm
    card_h = fmt["h"] * mm
    safe = SAFE_MARGIN * mm

    # Weisser Hintergrund (ganzes Blatt inkl. Beschnitt)
    c.setFillColor(white)
    c.rect(0, 0, page_w, page_h, fill=True, stroke=False)

    # Beschnittmarken (Fadenkreuze mit Abstand)
    c.setStrokeColor(Color(0, 0, 0, 0.6))
    c.setLineWidth(0.3)
    mark_len = 4 * mm
    mark_gap = 1 * mm

    # Unten links
    c.line(bx - mark_gap - mark_len, by, bx - mark_gap, by)
    c.line(bx, by - mark_gap - mark_len, bx, by - mark_gap)
    # Unten rechts
    c.line(bx + card_w + mark_gap, by, bx + card_w + mark_gap + mark_len, by)
    c.line(bx + card_w, by - mark_gap - mark_len, bx + card_w, by - mark_gap)
    # Oben links
    c.line(bx - mark_gap - mark_len, by + card_h, bx - mark_gap, by + card_h)
    c.line(bx, by + card_h + mark_gap, bx, by + card_h + mark_gap + mark_len)
    # Oben rechts
    c.line(bx + card_w + mark_gap, by + card_h, bx + card_w + mark_gap + mark_len, by + card_h)
    c.line(bx + card_w, by + card_h + mark_gap, bx + card_w, by + card_h + mark_gap + mark_len)

    # Layout: Linke Haelfte = Text, Rechte Haelfte = Adressfeld
    mid_x = bx + card_w / 2
    text_left = bx + safe
    text_right = mid_x - safe / 2
    text_w = text_right - text_left

    addr_left = mid_x + safe / 2
    addr_right = bx + card_w - safe

    # Trennlinie (vertikal, Mitte)
    c.setStrokeColor(LIGHT_GRAY)
    c.setLineWidth(0.4)
    c.line(mid_x, by + safe, mid_x, by + card_h - safe)

    # Briefmarkenfeld (oben rechts)
    stamp_size = 18 * mm
    stamp_x = bx + card_w - safe - stamp_size
    stamp_y = by + card_h - safe - stamp_size
    c.setStrokeColor(LIGHT_GRAY)
    c.setLineWidth(0.3)
    c.setDash(2, 2)
    c.rect(stamp_x, stamp_y, stamp_size, stamp_size, fill=False, stroke=True)
    c.setDash()

    # Adresslinien
    c.setStrokeColor(LIGHT_GRAY)
    c.setLineWidth(0.3)
    line_y_start = by + card_h * 0.45
    for i in range(4):
        ly = line_y_start - i * 10 * mm
        c.line(addr_left, ly, bx + card_w - safe, ly)

    # ── Gibran-Text (linke Seite) ──────────────────────
    gibran_col = {"fr": "gibran_fr", "de": "gibran_de", "en": "gibran_en"}.get(lang, "gibran_fr")
    gibran_text = photo.get(gibran_col, "") or ""
    gibran_text = gibran_text.replace("\\n", "\n")

    # Serif-Schrift fuer den Gibran-Text
    serif_font = "GaramondItalic" if "GaramondItalic" in fonts else "Garamond" if "Garamond" in fonts else "Helvetica"
    sans_font = "CalibriLight" if "CalibriLight" in fonts else "Calibri" if "Calibri" in fonts else "Helvetica"
    sans_bold = "CalibriBold" if "CalibriBold" in fonts else "Calibri" if "Calibri" in fonts else "Helvetica-Bold"

    # Gibran-Text zeichnen
    if gibran_text:
        c.setFillColor(DARK_GRAY)
        c.setFont(serif_font, 9.5)

        lines = gibran_text.strip().split("\n")
        text_y = by + card_h - safe - 4 * mm

        for line in lines:
            line = line.strip()
            if not line:
                text_y -= 4 * mm
                continue

            # Zeilenumbruch wenn zu lang
            words = line.split()
            current_line = ""
            for word in words:
                test = current_line + (" " if current_line else "") + word
                tw = c.stringWidth(test, serif_font, 9.5)
                if tw > text_w and current_line:
                    c.drawString(text_left, text_y, current_line)
                    text_y -= 13
                    current_line = word
                else:
                    current_line = test

            if current_line:
                c.drawString(text_left, text_y, current_line)
                text_y -= 13

    # ── Ortsname (sprachspezifisch) ──────────────────
    city_col = {"fr": "city_fr", "de": "city_de", "en": "city_en"}.get(lang, "city_fr")
    country_text = photo.get(city_col) or ""
    if not country_text:
        # Fallback: Original city + country
        city = photo.get("city") or ""
        if city:
            country = photo.get("country") or ""
            country_text = city + (", " + country if country else "")

    # Ort und Fotograf unten links
    bottom_y = by + safe

    if country_text:
        c.setFillColor(MID_GRAY)
        c.setFont(sans_font, 7.5)
        c.drawString(text_left, bottom_y + 10, country_text)

    # Fotograf
    c.setFillColor(LIGHT_GRAY)
    c.setFont(sans_font, 6.5)
    c.drawString(text_left, bottom_y, "Fotografie: P. Kueck")

    # Gibran-Referenz (ganz klein, unter dem Text)
    ref = photo.get("gibran_ref", "")
    if ref and gibran_text:
        c.setFillColor(LIGHT_GRAY)
        c.setFont(sans_font, 5.5)
        inspired_labels = {
            "fr": "Inspir\u00e9 par Khalil Gibran, Le Proph\u00e8te",
            "de": "Inspiriert von Khalil Gibran, Der Prophet",
            "en": "Inspired by Khalil Gibran, The Prophet",
        }
        c.drawString(text_left, bottom_y + 22, inspired_labels.get(lang, inspired_labels["fr"]))

    return True


def create_postcard(photo, fmt_key, lang, photographer, output_dir, fonts, front_style="clean"):
    """Erstellt ein druckfertiges PDF fuer eine Postkarte."""
    # Auto-Format: bestes Format anhand Bildseitenverhaeltnis
    if fmt_key == "auto":
        fmt_key = detect_format(photo)
    fmt = FORMATS[fmt_key]
    bleed = BLEED

    fname = os.path.splitext(photo["file_name"])[0]
    style_suffix = "" if front_style == "clean" else f"_{front_style}"
    pdf_path = os.path.join(output_dir, f"{fname}_postcard_{lang}{style_suffix}.pdf")

    c = canvas.Canvas(pdf_path)

    # Seite 1: Vorderseite (Foto)
    ok = create_front_page(c, photo, fmt, bleed, front_style, lang, fonts)
    if not ok:
        return None

    c.showPage()

    # Seite 2: Rueckseite (Text)
    create_back_page(c, photo, fmt, bleed, lang, photographer, fonts)

    c.showPage()
    c.save()

    return pdf_path


def main():
    if not HAS_REPORTLAB:
        print("FEHLER: reportlab nicht installiert!")
        print("  pip install reportlab")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Fotokatalog - Postkarten PDF Generator")
    parser.add_argument("--db", default="fotokatalog.db")
    parser.add_argument("--format", choices=["auto", "dinlang", "a6", "a6hoch"], default="auto", help="Kartenformat (auto=nach Bildverhaeltnis)")
    parser.add_argument("--lang", choices=["fr", "de", "en"], default="fr", help="Sprache Rueckseite")
    parser.add_argument("--limit", type=int, help="Max. Anzahl")
    parser.add_argument("--photo-id", type=int, help="Einzelnes Foto")
    parser.add_argument("--min-score", type=int, default=4, help="Min. postcard_score")
    parser.add_argument("--output", default=OUTPUT_DIR, help="Ausgabe-Ordner")
    parser.add_argument("--photographer", default="P. Kueck", help="Fotografen-Name")
    parser.add_argument("--front", choices=["clean", "location", "text"], default="clean",
                        help="Vorderseite: clean (nur Bild), location (Bild+Ort), text (Bild+Spruch)")
    args = parser.parse_args()

    # Schriften registrieren
    fonts = register_fonts()
    print(f"  Schriften: {', '.join(fonts.keys()) if fonts else 'nur Standard'}")

    # Fotos laden
    photos = get_postcard_photos(args.db, lang=args.lang, limit=args.limit,
                                  photo_id=args.photo_id, min_score=args.min_score)

    if not photos:
        print("Keine Postkarten-Kandidaten gefunden!")
        return

    fmt = FORMATS[args.format]
    lang_labels = {"fr": "Francais", "de": "Deutsch", "en": "English"}

    print("")
    print("  FOTOKATALOG - Postkarten PDF")
    print("  =============================")
    print(f"  Fotos:     {len(photos)}")
    print(f"  Format:    {fmt['name']} ({fmt['w']}x{fmt['h']}mm)")
    print(f"  Beschnitt: {BLEED}mm")
    print(f"  Sprache:   {lang_labels.get(args.lang, args.lang)}")
    print(f"  Ausgabe:   {os.path.abspath(args.output)}")
    print("")

    os.makedirs(args.output, exist_ok=True)

    success = 0
    errors = 0

    for i, photo in enumerate(photos, 1):
        fname = photo["file_name"]
        city = photo.get("city", "")
        score = photo.get("postcard_score", "?")

        print(f"[{i}/{len(photos)}] {fname}  PK:{score}  {city}")

        pdf_path = create_postcard(photo, args.format, args.lang,
                                    args.photographer, args.output, fonts, args.front)
        if pdf_path:
            print(f"  -> {pdf_path}")
            success += 1
        else:
            errors += 1

    print("")
    print("  =============================")
    print(f"  Erstellt: {success} PDFs")
    print(f"  Fehler:   {errors}")
    print(f"  Ordner:   {os.path.abspath(args.output)}")
    print("")


if __name__ == "__main__":
    main()
