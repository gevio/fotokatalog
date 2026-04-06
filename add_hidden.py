"""
Fuegt die is_hidden Spalte zur photos-Tabelle hinzu.
Einmalig ausfuehren: python add_hidden.py
"""
import sqlite3
import argparse

def add_hidden(db_path="fotokatalog.db"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE photos ADD COLUMN is_hidden INTEGER DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_hidden ON photos(is_hidden)")
        conn.commit()
        print("is_hidden Spalte hinzugefuegt.")
    except Exception as e:
        if "duplicate column" in str(e).lower():
            print("is_hidden existiert bereits.")
        else:
            print("Fehler: " + str(e))
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fotokatalog.db")
    args = parser.parse_args()
    add_hidden(args.db)
