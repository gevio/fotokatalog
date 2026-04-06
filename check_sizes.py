import sqlite3
conn = sqlite3.connect('fotokatalog.db')

print("=== BILDGROESSEN-ANALYSE ===\n")

# Groessen-Verteilung
for row in conn.execute('''
    SELECT width, height, COUNT(*) as cnt
    FROM photos
    WHERE width IS NOT NULL
    GROUP BY width, height
    ORDER BY cnt DESC
'''):
    w, h, cnt = row
    mp = round(w * h / 1_000_000, 1)
    # DPI-Berechnung fuer Druck
    a4_w_cm, a4_h_cm = 21, 29.7
    postkarte_w_cm, postkarte_h_cm = 14.8, 10.5
    dpi_a4 = round(min(w / (a4_w_cm / 2.54), h / (a4_h_cm / 2.54)))
    dpi_pk = round(min(w / (postkarte_w_cm / 2.54), h / (postkarte_h_cm / 2.54)))
    ok_a4 = "OK" if dpi_a4 >= 300 else ("grenzwertig" if dpi_a4 >= 200 else "zu klein")
    ok_pk = "OK" if dpi_pk >= 300 else ("grenzwertig" if dpi_pk >= 200 else "zu klein")
    print(f"  {w}x{h} ({mp} MP) - {cnt} Fotos")
    print(f"    A4-Druck:       {dpi_a4} DPI -> {ok_a4}")
    print(f"    Postkarte:      {dpi_pk} DPI -> {ok_pk}")
    print()

# Fotos ohne Groesse
no_size = conn.execute('SELECT COUNT(*) FROM photos WHERE width IS NULL').fetchone()[0]
if no_size:
    print(f"  {no_size} Fotos ohne Groessenangabe")

# Samsung S22 Ultra Originale = 12MP (4000x3000)
print("\n=== EMPFEHLUNG ===")
print("  Samsung S22 Ultra Originale: 4000x3000 (12 MP)")
print("    -> A4 Hochformat:  341 DPI = perfekt")
print("    -> A4 Querformat:  254 DPI = gut")
print("    -> Postkarte:      514 DPI = perfekt")
print()
print("  Snapseed-Exporte: siehe oben")
print("  Falls < 300 DPI fuer A4: Upscaling empfohlen")

conn.close()
