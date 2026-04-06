"""
FOTOKATALOG - Gibran Postkarten-Texte
======================================
Generiert poetische Postkartentexte auf DE/FR/EN
inspiriert von Khalil Gibrans "The Prophet".

Nutzt die bereits vorhandene Vision-Analyse (description, mood)
aus der DB - schickt KEINE Bilder an die API, nur Text.

Nutzung:
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    python gibran_tags.py                      # postcard_score >= 4
    python gibran_tags.py --min-score 3        # postcard_score >= 3
    python gibran_tags.py --limit 10           # nur 10 testen
    python gibran_tags.py --skip-existing      # bereits generierte ueberspringen
"""

import sqlite3
import json
import os
import sys
import time
import argparse
import urllib.request
import urllib.error

DB_PATH = "fotokatalog.db"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

# Gibran-Referenzpassagen (Auswahl der staerksten fuer Landschaft/Natur)
GIBRAN_EXCERPTS = """
Ausgewaehlte Passagen aus "The Prophet" von Khalil Gibran (1923, gemeinfrei):

ON LOVE: "When love beckons to you, follow him, though his ways are hard and steep."
ON JOY AND SORROW: "Your joy is your sorrow unmasked. The deeper that sorrow carves into your being, the more joy you can contain."
ON FREEDOM: "You shall be free indeed when your days are not without a care nor your nights without a want and a grief, but rather when these things girdle your life and yet you rise above them naked and unbound."
ON BEAUTY: "Beauty is life when life unveils her holy face. Beauty is eternity gazing at itself in a mirror."
ON DEATH: "For what is it to die but to stand naked in the wind and to melt into the sun? Only when you drink from the river of silence shall you indeed sing. And when you have reached the mountain top, then you shall begin to climb."
ON SELF-KNOWLEDGE: "Your hearts know in silence the secrets of the days and the nights. The soul unfolds itself, like a lotus of countless petals."
ON TIME: "The timeless in you is aware of life's timelessness, and knows that yesterday is but today's memory and tomorrow is today's dream."
ON FRIENDSHIP: "For that which you love most in him may be clearer in his absence, as the mountain to the climber is clearer from the plain."
ON GIVING: "You give but little when you give of your possessions. It is when you give of yourself that you truly give."
ON PAIN: "Your pain is the breaking of the shell that encloses your understanding. Even as the stone of the fruit must break, that its heart may stand in the sun, so must you know pain."
ON PLEASURE: "And forget not that the earth delights to feel your bare feet and the winds long to play with your hair."
ON HOUSES: "Your house shall be not an anchor but a mast."
ON WORK: "Work is love made visible."
ON CHILDREN: "You are the bows from which your children as living arrows are sent forth."
ON TALKING: "For thought is a bird of space, that in a cage of words may indeed unfold its wings but cannot fly."
ON GOOD AND EVIL: "You are good when you are one with yourself."
ON REASON AND PASSION: "Your reason and your passion are the rudder and the sails of your seafaring soul."
THE FAREWELL: "A little while, a moment of rest upon the wind, and another woman shall bear me."
THE FAREWELL: "These mountains and plains are a cradle and a stepping-stone."
THE FAREWELL: "I mirrored the summits in you and the bending slopes, and even the passing flocks of your thoughts and your desires."
"""

SYSTEM_PROMPT = """Du bist ein poetischer Texter fuer Reise-Postkarten.
Du erhaeltst eine Bildbeschreibung und Stimmung eines Landschaftsfotos.
Deine Aufgabe: Erzeuge drei eigenstaendige Postkartenruecktexte - DE, FR und EN.

Inspirationsquelle ist "The Prophet" von Khalil Gibran (1923).
Die Texte sollen von Gibrans Geist inspiriert sein, aber eigenstaendig.

""" + GIBRAN_EXCERPTS + """

Antworte NUR mit JSON:
{
  "gibran_de": "Hier oben h\u00f6rt man,\\nwie die Stille atmet.\\nUnd man versteht pl\u00f6tzlich,\\nwarum manche Menschen\\nimmer wiederkommen.",
  "gibran_fr": "Il y a des endroits\\no\u00f9 le silence a une couleur.\\nC'est ici que tu comprends\\npourquoi certains ne redescendent jamais vraiment.",
  "gibran_en": "Up here you can hear\\nthe silence breathing.\\nAnd suddenly you understand\\nwhy some people\\nalways come back.",
  "gibran_theme": "Stille und Wiederkehr",
  "gibran_ref": "The deeper that sorrow carves into your being, the more joy you can contain."
}

STILREGELN:
- 2-5 Zeilen pro Sprache, getrennt durch \\n
- Warm, zeitlos, leicht poetisch - nie kitschig, nie akademisch
- Spricht den Betrachter/Empfaenger an - direkt oder indirekt einladend
- Keine Ortsnennung im Text (Ort ist auf der Bildseite)
- Keine Reime ausser sie entstehen organisch
- Keine Klischees wie "Die Natur ist wunderschoen" oder "Geniesse den Moment"
- Jede Sprachversion ist eigenstaendig, NICHT uebersetzt
- Deutsch: Klar, fliessend, leicht literarisch - eher Peter Handke als Werbetext
- Franzoesisch: Leuchtend, praezise, Hauch Poesie - eher Saint-Exupery als Tourismusprospekt
- Englisch: Simple, evocative, rhythmic - eher Mary Oliver als greeting card
- gibran_ref: Die Gibran-Passage die als Inspiration diente (englisches Original)
- gibran_theme: 1-3 Worte zum Thema (deutsch)
- WICHTIG: Verwende IMMER korrekte Unicode-Zeichen! Deutsche Umlaute: \u00e4 \u00f6 \u00fc \u00c4 \u00d6 \u00dc \u00df. Franzoesische Akzente: \u00e9 \u00e8 \u00ea \u00e0 \u00e2 \u00f4 \u00ee \u00e7. NIEMALS ae oe ue statt \u00e4 \u00f6 \u00fc schreiben!"""


def get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("FEHLER: ANTHROPIC_API_KEY nicht gesetzt!")
        print('  $env:ANTHROPIC_API_KEY = "sk-ant-..."')
        sys.exit(1)
    return key


def get_postcard_photos(db_path, min_score=4, limit=None, skip_existing=False):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    where = "va.postcard_score >= ? AND (p.is_hidden=0 OR p.is_hidden IS NULL)"
    args = [min_score]

    if skip_existing:
        where += " AND (va.gibran_de IS NULL OR va.gibran_de = '')"

    sql = """
        SELECT p.id, p.file_name, va.description, va.mood, va.quality_score,
               va.postcard_score, va.print_score, va.key_elements,
               g.city, g.country, g.altitude
        FROM photos p
        JOIN vision_analysis va ON p.id = va.photo_id
        LEFT JOIN geo_data g ON p.id = g.photo_id
        WHERE """ + where + """
        ORDER BY va.postcard_score DESC, va.quality_score DESC
    """
    if limit:
        sql += " LIMIT ?"
        args.append(limit)

    rows = conn.execute(sql, args).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def call_gibran_api(api_key, photo):
    context = f"Bildbeschreibung: {photo['description']}"
    context += f"\nStimmung: {photo['mood']}"
    if photo.get('key_elements'):
        context += f"\nBildstaerken: {photo['key_elements']}"
    if photo.get('city'):
        context += f"\nRegion: {photo['city']}, {photo.get('country', '')}"
    if photo.get('altitude'):
        context += f"\nHoehe: {int(photo['altitude'])}m"

    payload = {
        "model": MODEL,
        "max_tokens": 500,
        "messages": [
            {
                "role": "user",
                "content": context
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


def save_gibran(db_path, photo_id, gibran):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        UPDATE vision_analysis
        SET gibran_de = ?, gibran_fr = ?, gibran_en = ?,
            gibran_theme = ?, gibran_ref = ?
        WHERE photo_id = ?
    """, (
        gibran.get("gibran_de"),
        gibran.get("gibran_fr"),
        gibran.get("gibran_en"),
        gibran.get("gibran_theme"),
        gibran.get("gibran_ref"),
        photo_id
    ))
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Fotokatalog - Gibran Postkarten-Texte")
    parser.add_argument("--db", default="fotokatalog.db")
    parser.add_argument("--min-score", type=int, default=4, help="Minimum postcard_score (Standard: 4)")
    parser.add_argument("--limit", type=int, help="Max. Anzahl Fotos")
    parser.add_argument("--skip-existing", action="store_true", help="Bereits generierte ueberspringen")
    parser.add_argument("--delay", type=float, default=0.5, help="Pause zwischen API-Calls")
    args = parser.parse_args()

    api_key = get_api_key()
    photos = get_postcard_photos(args.db, min_score=args.min_score,
                                 limit=args.limit, skip_existing=args.skip_existing)

    if not photos:
        print("Keine Postkarten-Kandidaten gefunden!")
        return

    # Kosten: nur Text, kein Bild = sehr guenstig
    est_cost = len(photos) * 0.002
    print("")
    print("  FOTOKATALOG - Gibran Postkarten-Texte")
    print("  ======================================")
    print(f"  Fotos:     {len(photos)} (postcard_score >= {args.min_score})")
    print(f"  Modell:    {MODEL}")
    print(f"  Kosten:    ~${est_cost:.2f} (nur Text, keine Bilder)")
    print("")

    answer = input(f"  {len(photos)} Texte generieren? (j/n): ").strip().lower()
    if answer not in ("j", "ja", "y", "yes"):
        print("  Abgebrochen.")
        return

    print("")

    total_input = 0
    total_output = 0
    success = 0
    errors = 0

    for i, photo in enumerate(photos, 1):
        fname = photo["file_name"]
        mood = photo.get("mood", "?")
        pk = photo.get("postcard_score", "?")
        city = photo.get("city", "")

        print(f"[{i}/{len(photos)}] {fname}  PK:{pk}  {mood}  {city}")

        result, usage = call_gibran_api(api_key, photo)

        if result:
            save_gibran(args.db, photo["id"], result)

            # Vorschau
            de_preview = (result.get("gibran_de", "") or "").split("\\n")[0]
            theme = result.get("gibran_theme", "")
            print(f"  Thema: {theme}")
            print(f"  DE: {de_preview}")
            success += 1

            if usage:
                total_input += usage.get("input_tokens", 0)
                total_output += usage.get("output_tokens", 0)
        else:
            errors += 1

        if i < len(photos):
            time.sleep(args.delay)

    cost_input = total_input * 3 / 1_000_000
    cost_output = total_output * 15 / 1_000_000
    total_cost = cost_input + cost_output

    print("")
    print("  ======================================")
    print("  ERGEBNIS")
    print("  ======================================")
    print(f"  Erfolgreich: {success}")
    print(f"  Fehler:      {errors}")
    print(f"  Tokens:      {total_input:,} Input + {total_output:,} Output")
    print(f"  Kosten:      ~${total_cost:.3f}")
    print("")


if __name__ == "__main__":
    main()
