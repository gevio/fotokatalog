"""
Fuegt Gibran-Zitat-Felder zur vision_analysis Tabelle hinzu.
Einmalig ausfuehren: python add_gibran.py
"""
import sqlite3
import argparse

def add_gibran(db_path="fotokatalog.db"):
    conn = sqlite3.connect(db_path)
    cols = {"gibran_de": "TEXT", "gibran_fr": "TEXT", "gibran_en": "TEXT", "gibran_theme": "TEXT", "gibran_ref": "TEXT"}
    for col, typ in cols.items():
        try:
            conn.execute(f"ALTER TABLE vision_analysis ADD COLUMN {col} {typ}")
            print(f"  {col} hinzugefuegt")
        except Exception as e:
            if "duplicate" in str(e).lower():
                print(f"  {col} existiert bereits")
            else:
                print(f"  Fehler bei {col}: {e}")
    conn.commit()
    conn.close()
    print("Fertig.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fotokatalog.db")
    args = parser.parse_args()
    add_gibran(args.db)
