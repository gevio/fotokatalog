"""
Fixe Umlaute in gibran_de Texten.
Ersetzt ae/oe/ue nur wo es echte Umlaute sind.

python fix_umlauts.py
python fix_umlauts.py --dry-run   (nur anzeigen, nichts aendern)
"""
import sqlite3
import re
import argparse

# Woerter die NICHT ersetzt werden duerfen (ue ist kein Umlaut)
EXCEPTIONS = {
    'abenteuer', 'abenteuerlich', 'ungeheuer', 'geheuer',
    'feuer', 'scheuer', 'teuer', 'steuer', 'heuer',
    'treue', 'reue', 'neue', 'neues', 'neuem', 'neuen', 'neuer',
    'freue', 'freuen', 'freund', 'freunde',
    'kreuz', 'kreuze', 'deuten', 'bedeuten', 'bedeutung',
    'leuchten', 'leuchtend', 'leuchtende',
    'zeugen', 'zeuge', 'erzeugen',
    'beuel', 'meuel',
}

def fix_umlauts(text):
    """Ersetzt ae/oe/ue durch echte Umlaute, mit Ausnahmeliste.
    Erhaelt Zeilenumbrueche (sowohl echte als auch \\n escaped)."""
    if not text:
        return text

    # oe -> ö und ae -> ä sind fast immer korrekt
    result = text.replace('oe', '\u00f6').replace('Oe', '\u00d6')
    result = result.replace('ae', '\u00e4').replace('Ae', '\u00c4')

    # ue -> ü nur wenn nicht in Ausnahmewort
    # Regex: finde ue/Ue das NICHT Teil eines Ausnahmeworts ist
    def replace_ue(match):
        # Hole das ganze Wort um den Match herum
        start = match.start()
        end = match.end()
        # Wort-Grenzen finden
        s = start
        while s > 0 and result[s-1].isalpha():
            s -= 1
        e = end
        while e < len(result) and result[e].isalpha():
            e += 1
        word = result[s:e].lower()
        for exc in EXCEPTIONS:
            if exc in word:
                return match.group(0)  # Nicht ersetzen
        return '\u00fc' if match.group(0) == 'ue' else '\u00dc'

    result = re.sub(r'[Uu]e', replace_ue, result)

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fotokatalog.db")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT photo_id, gibran_de FROM vision_analysis
        WHERE gibran_de IS NOT NULL AND gibran_de != ''
    """).fetchall()

    changed = 0
    for row in rows:
        pid = row["photo_id"]
        original = row["gibran_de"]
        fixed = fix_umlauts(original)

        if fixed != original:
            changed += 1
            # Zeige nur die geaenderten Stellen
            print(f"  Foto #{pid}:")
            orig_short = original[:120].replace('\n', '|')
            fix_short = fixed[:120].replace('\n', '|')
            print(f"    - {orig_short}")
            print(f"    + {fix_short}")

            if not args.dry_run:
                conn.execute("UPDATE vision_analysis SET gibran_de = ? WHERE photo_id = ?",
                           (fixed, pid))

    if not args.dry_run:
        conn.commit()

    print(f"\n{'Wuerde aendern' if args.dry_run else 'Geaendert'}: {changed} von {len(rows)} Texten")
    conn.close()


if __name__ == "__main__":
    main()
