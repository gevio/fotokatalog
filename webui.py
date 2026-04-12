"""
FOTOKATALOG - Lokaler Web-Browser
Startet einen Webserver auf localhost:8080.

Nutzung:
    python webui.py
    python webui.py --db pfad/zur/fotokatalog.db
    python webui.py --port 9090
"""

import http.server
import json
import sqlite3
import os
import argparse
import urllib.parse
import urllib.request
import webbrowser

DB_PATH = "fotokatalog.db"
DB_BACKEND = "sqlite"
MARIADB_CONFIG = {}
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY = None


class DBRow(dict):
    """Dict row that also supports index-based access like sqlite3.Row."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class DBCursorProxy:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        return getattr(self._cursor, "lastrowid", None)

    @property
    def rowcount(self):
        return getattr(self._cursor, "rowcount", -1)

    def _convert_row(self, row):
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return DBRow({k: row[k] for k in row.keys()})
        if isinstance(row, dict):
            return DBRow(row)
        if isinstance(row, (list, tuple)):
            cols = [d[0] for d in (self._cursor.description or [])]
            return DBRow({cols[i]: row[i] for i in range(min(len(cols), len(row)))})
        return row

    def fetchone(self):
        return self._convert_row(self._cursor.fetchone())

    def fetchall(self):
        return [self._convert_row(r) for r in self._cursor.fetchall()]


class DBConnectionProxy:
    def __init__(self, connection):
        self._connection = connection

    def _convert_query(self, query):
        if DB_BACKEND != "mariadb":
            return query
        q = query.replace("INSERT OR IGNORE", "INSERT IGNORE")
        return q.replace("?", "%s")

    def execute(self, query, args=()):
        params = tuple(args) if isinstance(args, list) else (args or ())
        q = self._convert_query(query)
        if DB_BACKEND == "sqlite":
            cur = self._connection.execute(q, params)
        else:
            cur = self._connection.cursor()
            cur.execute(q, params)
        return DBCursorProxy(cur)

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()

def load_api_key():
    """Laedt ANTHROPIC_API_KEY aus .env Datei oder Umgebungsvariable."""
    global API_KEY
    # 1. Umgebungsvariable
    API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    if API_KEY:
        return
    # 2. .env Datei im Projektverzeichnis
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "ANTHROPIC_API_KEY" in line and "=" in line:
                    API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return

def get_db():
    if DB_BACKEND == "sqlite":
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return DBConnectionProxy(conn)

    try:
        import pymysql
    except ImportError as e:
        raise RuntimeError("MariaDB Backend verlangt 'pymysql' (pip install pymysql)") from e

    conn = pymysql.connect(
        host=MARIADB_CONFIG["host"],
        port=MARIADB_CONFIG["port"],
        user=MARIADB_CONFIG["user"],
        password=MARIADB_CONFIG["password"],
        database=MARIADB_CONFIG["database"],
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )
    return DBConnectionProxy(conn)

def load_db_config(args):
    """Laedt Datenbank-Konfiguration aus CLI/ENV mit sicherem Default auf SQLite."""
    global DB_BACKEND, DB_PATH, MARIADB_CONFIG

    backend_env = (os.environ.get("FOTOKATALOG_DB_BACKEND") or "sqlite").strip().lower()
    backend_cli = (args.db_backend or backend_env).strip().lower()
    DB_BACKEND = backend_cli if backend_cli in ("sqlite", "mariadb") else "sqlite"

    DB_PATH = args.db

    MARIADB_CONFIG = {
        "host": os.environ.get("FOTOKATALOG_DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("FOTOKATALOG_DB_PORT", "3306")),
        "database": os.environ.get("FOTOKATALOG_DB_NAME", "fotokatalog"),
        "user": os.environ.get("FOTOKATALOG_DB_USER", "fotokatalog"),
        "password": os.environ.get("FOTOKATALOG_DB_PASSWORD", ""),
    }

def ensure_db_columns():
    """Fuegt fehlende Spalten hinzu (Migration)."""
    conn = get_db()
    if DB_BACKEND == "sqlite":
        existing = [r["name"] for r in conn.execute("PRAGMA table_info(geo_data)").fetchall()]
    else:
        existing = [r["name"] for r in conn.execute(
            """
            SELECT COLUMN_NAME as name
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=? AND TABLE_NAME='geo_data'
            """,
            (MARIADB_CONFIG["database"],)
        ).fetchall()]
    for col in ["city_fr", "city_de", "city_en"]:
        if col not in existing:
            conn.execute(f"ALTER TABLE geo_data ADD COLUMN {col} TEXT")
            print(f"  DB-Migration: geo_data.{col} hinzugefuegt")
    conn.commit()
    conn.close()

def query_photos(params):
    conn = get_db()
    where = ["1=1"]
    args = []
    if params.get("tag"):
        where.append("p.id IN (SELECT pt.photo_id FROM photo_tags pt JOIN tags t ON pt.tag_id=t.id WHERE t.name=?)")
        args.append(params["tag"])
    if params.get("city"):
        where.append("g.city=?")
        args.append(params["city"])
    if params.get("rating_min"):
        where.append("p.rating>=?")
        args.append(int(params["rating_min"]))
    if params.get("favorite"):
        where.append("p.is_favorite=1")
    if params.get("print_cat"):
        where.append("pi.print_cat=?")
        args.append(params["print_cat"])
    if params.get("search"):
        where.append("(p.file_name LIKE ? OR p.notes LIKE ?)")
        q = "%" + params["search"] + "%"
        args.extend([q, q])
    if params.get("album"):
        where.append("p.id IN (SELECT photo_id FROM photo_albums WHERE album_id=?)")
        args.append(int(params["album"]))
    # Hidden filter: default = hide hidden, show_hidden=1 to include
    if params.get("show_hidden"):
        pass  # show all
    elif params.get("only_hidden"):
        where.append("p.is_hidden=1")
    else:
        where.append("(p.is_hidden=0 OR p.is_hidden IS NULL)")

    order = {
        "date_desc": "p.date_taken DESC",
        "date_asc": "p.date_taken ASC",
        "rating": "p.rating DESC, p.date_taken DESC",
        "name": "p.file_name ASC",
        "quality": "va.quality_score DESC, p.date_taken DESC",
        "postcard": "va.postcard_score DESC, p.date_taken DESC",
        "print": "va.print_score DESC, p.date_taken DESC",
    }.get(params.get("sort", "date_desc"), "p.date_taken DESC")

    cat_tags_expr = "GROUP_CONCAT(DISTINCT t.category || ':' || t.name) as cat_tags"
    if DB_BACKEND == "mariadb":
        cat_tags_expr = "GROUP_CONCAT(DISTINCT CONCAT(t.category, ':', t.name)) as cat_tags"

    sql = """
        SELECT p.id, p.file_name, p.date_taken, p.rating, p.is_favorite, p.is_hidden,
               p.width, p.height, p.notes,
               g.latitude, g.longitude, g.city, g.country, g.display_name, g.altitude,
               g.city_fr, g.city_de, g.city_en,
               e.camera_model, e.focal_length, e.aperture, e.iso, e.shutter_speed,
               pi.print_cat, pi.dpi_a4, pi.orientation as photo_orient, pi.megapixel,
               va.quality_score, va.postcard_score, va.print_score, va.mood, va.description, va.key_elements,
               va.gibran_de, va.gibran_fr, va.gibran_en, va.gibran_theme, va.gibran_ref,
               GROUP_CONCAT(DISTINCT t.name) as tag_list,
               """ + cat_tags_expr + """
        FROM photos p
        LEFT JOIN geo_data g ON p.id = g.photo_id
        LEFT JOIN exif_data e ON p.id = e.photo_id
        LEFT JOIN print_info pi ON p.id = pi.photo_id
        LEFT JOIN vision_analysis va ON p.id = va.photo_id
        LEFT JOIN photo_tags pt ON p.id = pt.photo_id
        LEFT JOIN tags t ON pt.tag_id = t.id
        WHERE """ + " AND ".join(where) + """
        GROUP BY p.id
        ORDER BY """ + order

    rows = conn.execute(sql, args).fetchall()
    result = [{k: r[k] for k in r.keys()} for r in rows]
    conn.close()
    return result

def get_stats():
    conn = get_db()
    s = {}
    s["total"] = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    s["with_gps"] = conn.execute("SELECT COUNT(*) FROM geo_data").fetchone()[0]
    s["rated"] = conn.execute("SELECT COUNT(*) FROM photos WHERE rating>0").fetchone()[0]
    s["favorites"] = conn.execute("SELECT COUNT(*) FROM photos WHERE is_favorite=1").fetchone()[0]
    s["hidden"] = conn.execute("SELECT COUNT(*) FROM photos WHERE is_hidden=1").fetchone()[0]
    s["cities"] = [dict(r) for r in conn.execute("SELECT * FROM v_location_stats LIMIT 50").fetchall()]
    s["tags"] = [dict(r) for r in conn.execute("""
        SELECT t.name, t.category, COUNT(pt.photo_id) as cnt
        FROM tags t JOIN photo_tags pt ON t.id=pt.tag_id
        GROUP BY t.id ORDER BY cnt DESC LIMIT 40
    """).fetchall()]
    try:
        s["print_cats"] = [dict(r) for r in conn.execute(
            "SELECT print_cat, COUNT(*) as cnt FROM print_info GROUP BY print_cat ORDER BY cnt DESC"
        ).fetchall()]
    except:
        s["print_cats"] = []
    try:
        s["albums"] = [dict(r) for r in conn.execute("""
            SELECT a.id, a.name, a.description, COUNT(pa.photo_id) as cnt
            FROM albums a LEFT JOIN photo_albums pa ON a.id = pa.album_id
            GROUP BY a.id ORDER BY a.sort_order, a.name
        """).fetchall()]
    except:
        s["albums"] = []
    conn.close()
    return s

def get_albums():
    conn = get_db()
    albums = [dict(r) for r in conn.execute("""
        SELECT a.id, a.name, a.description, COUNT(pa.photo_id) as cnt
        FROM albums a LEFT JOIN photo_albums pa ON a.id = pa.album_id
        GROUP BY a.id ORDER BY a.sort_order, a.name
    """).fetchall()]
    conn.close()
    return albums

def create_album(data):
    conn = get_db()
    cur = conn.execute("INSERT INTO albums (name, description) VALUES (?, ?)",
                       (data.get("name", "Neues Album"), data.get("description", "")))
    album_id = cur.lastrowid
    conn.commit()
    conn.close()
    return album_id

def add_to_album(album_id, photo_ids):
    conn = get_db()
    for pid in photo_ids:
        conn.execute("INSERT OR IGNORE INTO photo_albums (photo_id, album_id) VALUES (?, ?)",
                     (pid, album_id))
    conn.commit()
    conn.close()

def remove_from_album(album_id, photo_ids):
    conn = get_db()
    for pid in photo_ids:
        conn.execute("DELETE FROM photo_albums WHERE photo_id=? AND album_id=?", (pid, album_id))
    conn.commit()
    conn.close()

def delete_album(album_id):
    conn = get_db()
    conn.execute("DELETE FROM photo_albums WHERE album_id=?", (album_id,))
    conn.execute("DELETE FROM albums WHERE id=?", (album_id,))
    conn.commit()
    conn.close()

def update_photo(photo_id, data, session_id=None):
    conn = get_db()
    # MariaDB/Prod: rating+favorite gehen auf user_ratings (Admin-Werte bleiben)
    if DB_BACKEND == "mariadb" and session_id and ("rating" in data or "favorite" in data):
        upsert_user_rating(photo_id, session_id, data)
    else:
        # SQLite/Lokal: direkt auf photos (Admin-Modus)
        if "rating" in data:
            conn.execute("UPDATE photos SET rating=? WHERE id=?", (data["rating"], photo_id))
        if "favorite" in data:
            conn.execute("UPDATE photos SET is_favorite=? WHERE id=?", (1 if data["favorite"] else 0, photo_id))
    if "hidden" in data:
        conn.execute("UPDATE photos SET is_hidden=? WHERE id=?", (1 if data["hidden"] else 0, photo_id))
    if "notes" in data:
        conn.execute("UPDATE photos SET notes=? WHERE id=?", (data["notes"], photo_id))
    conn.commit()
    conn.close()


def upsert_user_rating(photo_id, session_id, data):
    """Speichert User-Bewertung in user_ratings (nur MariaDB/Prod)."""
    conn = get_db()
    rating = data.get("rating")
    fav = 1 if data.get("favorite") else 0 if "favorite" in data else None

    # UPSERT: existiert schon -> update, sonst insert
    if rating is not None and fav is not None:
        conn.execute(
            """INSERT INTO user_ratings (photo_id, session_id, rating, is_favorite)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE rating=VALUES(rating), is_favorite=VALUES(is_favorite)""",
            (photo_id, session_id, rating, fav))
    elif rating is not None:
        conn.execute(
            """INSERT INTO user_ratings (photo_id, session_id, rating)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE rating=VALUES(rating)""",
            (photo_id, session_id, rating))
    elif fav is not None:
        conn.execute(
            """INSERT INTO user_ratings (photo_id, session_id, is_favorite)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE is_favorite=VALUES(is_favorite)""",
            (photo_id, session_id, fav))
    conn.commit()
    conn.close()


def get_session_id(headers):
    """Extrahiert oder generiert eine Session-ID aus dem Cookie."""
    import hashlib
    cookie_header = headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("fk_session="):
            return part.split("=", 1)[1]
    # Fallback: IP + User-Agent Hash
    remote = headers.get("X-Forwarded-For", headers.get("Host", "unknown"))
    ua = headers.get("User-Agent", "")
    return hashlib.sha256((remote + ua).encode()).hexdigest()[:16]

def geocode_place(city, country=""):
    """Forward-Geocoding: Ortsname -> Koordinaten via Nominatim."""
    try:
        from geopy.geocoders import Nominatim
        geo = Nominatim(user_agent="fotokatalog/1.0", timeout=5)
        query = city
        if country:
            query += ", " + country
        location = geo.geocode(query)
        if location:
            return round(location.latitude, 6), round(location.longitude, 6)
    except Exception as e:
        print(f"  Geocoding-Fehler: {e}")
    return None, None


def translate_city(photo_id):
    """Uebersetzt city/country in alle 3 Sprachen via Claude API. Cached in DB."""
    if not API_KEY:
        return None

    conn = get_db()
    row = conn.execute("SELECT city, country, city_fr, city_de, city_en FROM geo_data WHERE photo_id=?",
                       (photo_id,)).fetchone()
    if not row or not row["city"]:
        conn.close()
        return None

    # Schon uebersetzt?
    if row["city_fr"] and row["city_de"] and row["city_en"]:
        conn.close()
        return {"fr": row["city_fr"], "de": row["city_de"], "en": row["city_en"]}

    city = row["city"]
    country = row["country"] or ""

    prompt = f"""Übersetze diesen Ortsnamen in 3 Sprachen: "{city}, {country}"

Kontext: Postkarten aus der Schweiz. Verwende die touristisch gebräuchliche, schöne Bezeichnung.
Regeln:
- Verwende Talnamen mit "Val" wenn üblich (Anniviers → Val d'Anniviers, Hérens → Val d'Hérens)
- Übersetze Kanton/Region korrekt (Wallis↔Valais, Schweiz↔Suisse↔Switzerland, Bern↔Berne)
- Städtenamen übersetzen wenn üblich (Sitten↔Sion, Genf↔Genève↔Geneva, Luzern↔Lucerne)
- Bei Orten ohne Übersetzung (Zermatt, Evolène, Grimentz) den Namen belassen
- Region/Kanton immer mit angeben
Beispiele: "Sion, Valais" (FR), "Sitten, Wallis" (DE), "Val d'Anniviers, Valais" (FR)

Antwort NUR als JSON:
{{"fr": "Sion, Valais", "de": "Sitten, Wallis", "en": "Sion, Valais"}}"""

    try:
        payload = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 150,
            "messages": [{"role": "user", "content": prompt}]
        }).encode("utf-8")

        req = urllib.request.Request("https://api.anthropic.com/v1/messages",
                                     data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-api-key", API_KEY)
        req.add_header("anthropic-version", "2023-06-01")

        with urllib.request.urlopen(req, timeout=10) as resp:
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

        translations = json.loads(text.strip())

        city_fr = translations.get("fr", city)
        city_de = translations.get("de", city)
        city_en = translations.get("en", city)

        # In DB cachen
        conn.execute("""UPDATE geo_data SET city_fr=?, city_de=?, city_en=?
                        WHERE photo_id=?""", (city_fr, city_de, city_en, photo_id))
        conn.commit()
        conn.close()

        print(f"  Uebersetzt: {city} -> FR:{city_fr} DE:{city_de} EN:{city_en}")
        return {"fr": city_fr, "de": city_de, "en": city_en}

    except Exception as e:
        print(f"  Uebersetzung-Fehler: {e}")
        conn.close()
        return None

def update_geo(photo_id, data):
    conn = get_db()
    city = data.get("city", "").strip()
    country = data.get("country", "").strip()

    # Forward-Geocoding: Koordinaten aus Ortsname ermitteln
    lat, lon = None, None
    if city:
        lat, lon = geocode_place(city, country)

    # Check if geo_data row exists
    row = conn.execute("SELECT photo_id, latitude, longitude FROM geo_data WHERE photo_id=?", (photo_id,)).fetchone()
    display = city
    if country:
        display = city + ", " + country if city else country

    if row:
        conn.execute("UPDATE geo_data SET city=?, country=?, display_name=? WHERE photo_id=?",
                     (city, country, display, photo_id))
        # Koordinaten nur updaten wenn wir neue haben UND die alten Platzhalter (0,0) waren
        if lat is not None and lon is not None:
            old_lat = row["latitude"] if row["latitude"] else 0
            old_lon = row["longitude"] if row["longitude"] else 0
            if old_lat == 0 and old_lon == 0:
                conn.execute("UPDATE geo_data SET latitude=?, longitude=? WHERE photo_id=?",
                             (lat, lon, photo_id))
    else:
        if lat is None:
            lat = 0
        if lon is None:
            lon = 0
        conn.execute("""INSERT INTO geo_data (photo_id, latitude, longitude, city, country, display_name)
                        VALUES (?, ?, ?, ?, ?, ?)""", (photo_id, lat, lon, city, country, display))
    conn.commit()
    conn.close()
    return {"lat": lat, "lon": lon}

def bulk_update(data):
    conn = get_db()
    ids = data.get("ids", [])
    if not ids:
        conn.close()
        return
    placeholders = ",".join(["?"] * len(ids))
    updated_total = 0
    if "hidden" in data:
        val = 1 if data["hidden"] else 0
        cur = conn.execute("UPDATE photos SET is_hidden=? WHERE id IN (" + placeholders + ")", [val] + ids)
        if cur.rowcount and cur.rowcount > 0:
            updated_total += cur.rowcount
    if "rating" in data:
        cur = conn.execute("UPDATE photos SET rating=? WHERE id IN (" + placeholders + ")", [data["rating"]] + ids)
        if cur.rowcount and cur.rowcount > 0:
            updated_total += cur.rowcount
    conn.commit()
    conn.close()
    return updated_total

def get_thumbnail(photo_id):
    conn = get_db()
    row = conn.execute("SELECT thumbnail FROM photos WHERE id=?", (photo_id,)).fetchone()
    conn.close()
    if row and row["thumbnail"]:
        return row["thumbnail"]
    return None

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = dict(urllib.parse.parse_qsl(parsed.query))

        if path == "/" or path == "/index.html":
            html_path = os.path.join(SCRIPT_DIR, "index.html")
            if os.path.exists(html_path):
                with open(html_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(content))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"index.html nicht gefunden!")
        elif path == "/api/stats":
            self.send_json(get_stats())
        elif path == "/api/photos":
            self.send_json(query_photos(params))
        elif path == "/api/albums":
            self.send_json(get_albums())
        elif path.startswith("/api/thumb/"):
            try:
                photo_id = int(path.split("/")[-1])
                thumb = get_thumbnail(photo_id)
                if thumb:
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    self.wfile.write(thumb)
                else:
                    self.send_response(404)
                    self.end_headers()
            except:
                self.send_response(404)
                self.end_headers()
        elif path.startswith("/api/full/"):
            try:
                photo_id = int(path.split("/")[-1])
                conn = get_db()
                row = conn.execute("SELECT file_path FROM photos WHERE id=?", (photo_id,)).fetchone()
                conn.close()
                if row and os.path.exists(row["file_path"]):
                    with open(row["file_path"], "rb") as f:
                        content = f.read()
                    ext = row["file_path"].lower()
                    ctype = "image/jpeg"
                    if ext.endswith(".png"): ctype = "image/png"
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "max-age=3600")
                    self.send_header("Content-Length", len(content))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self.send_response(404)
                    self.end_headers()
            except:
                self.send_response(404)
                self.end_headers()
        elif path.startswith("/api/preview/"):
            try:
                photo_id = int(path.split("/")[-1])
                preview_path = os.path.join(SCRIPT_DIR, "_previews", f"{photo_id}.jpg")
                if os.path.exists(preview_path):
                    with open(preview_path, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "max-age=86400")
                    self.send_header("Content-Length", len(content))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    # Fallback: Thumbnail-BLOB wenn kein Preview vorhanden
                    thumb = get_thumbnail(photo_id)
                    if thumb:
                        self.send_response(200)
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Cache-Control", "max-age=3600")
                        self.end_headers()
                        self.wfile.write(thumb)
                    else:
                        self.send_response(404)
                        self.end_headers()
            except:
                self.send_response(404)
                self.end_headers()
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif path.startswith("/api/translate-city/"):
            try:
                photo_id = int(path.split("/")[-1])
                result = translate_city(photo_id)
                if result:
                    self.send_json({"ok": True, **result})
                else:
                    self.send_json({"ok": False})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b""
        data = json.loads(raw) if raw else {}

        if parsed.path.startswith("/api/postcard/"):
            photo_id = int(parsed.path.split("/")[3])
            qparams = dict(urllib.parse.parse_qsl(parsed.query))
            lang = qparams.get("lang", "fr")
            front_style = qparams.get("front", "clean")
            try:
                from postcard_pdf import HAS_REPORTLAB, get_postcard_photos, create_postcard, register_fonts, FORMATS
                if not HAS_REPORTLAB:
                    self.send_json({"ok": False, "error": "reportlab nicht installiert (pip install reportlab)"})
                    return
                fonts = register_fonts()
                photos_list = get_postcard_photos(DB_PATH, lang=lang, photo_id=photo_id, min_score=0)
                if photos_list:
                    output_dir = os.path.join(SCRIPT_DIR, "_postkarten")
                    os.makedirs(output_dir, exist_ok=True)
                    pdf_path = create_postcard(photos_list[0], "auto", lang, "P. Kueck", output_dir, fonts, front_style)
                    if pdf_path:
                        self.send_json({"ok": True, "path": pdf_path})
                    else:
                        self.send_json({"ok": False, "error": "PDF-Erstellung fehlgeschlagen"})
                else:
                    self.send_json({"ok": False, "error": "Foto nicht gefunden oder kein Gibran-Text"})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"ok": False, "error": str(e)})
        elif parsed.path.startswith("/api/photo/"):
            photo_id = int(parsed.path.split("/")[-1])
            session_id = get_session_id(self.headers) if DB_BACKEND == "mariadb" else None
            update_photo(photo_id, data, session_id=session_id)
            self.send_json({"ok": True})
        elif parsed.path.startswith("/api/geo/"):
            photo_id = int(parsed.path.split("/")[-1])
            result = update_geo(photo_id, data)
            self.send_json({"ok": True, "lat": result.get("lat"), "lon": result.get("lon")})
        elif parsed.path.startswith("/api/vision/"):
            photo_id = int(parsed.path.split("/")[-1])
            field = data.get("field")
            value = data.get("value")
            allowed = {"quality_score", "postcard_score", "print_score"}
            if field in allowed:
                conn = get_db()
                conn.execute("UPDATE vision_analysis SET " + field + "=? WHERE photo_id=?", (value, photo_id))
                conn.commit()
                conn.close()
            self.send_json({"ok": True})
        elif parsed.path == "/api/bulk":
            cnt = bulk_update(data)
            self.send_json({"ok": True, "updated": cnt})
        elif parsed.path == "/api/albums/create":
            aid = create_album(data)
            self.send_json({"ok": True, "album_id": aid})
        elif parsed.path.startswith("/api/albums/") and parsed.path.endswith("/add"):
            album_id = int(parsed.path.split("/")[3])
            add_to_album(album_id, data.get("ids", []))
            self.send_json({"ok": True})
        elif parsed.path.startswith("/api/albums/") and parsed.path.endswith("/remove"):
            album_id = int(parsed.path.split("/")[3])
            remove_from_album(album_id, data.get("ids", []))
            self.send_json({"ok": True})
        elif parsed.path.startswith("/api/albums/") and parsed.path.endswith("/delete"):
            album_id = int(parsed.path.split("/")[3])
            delete_album(album_id)
            self.send_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fotokatalog Web-UI")
    parser.add_argument("--db", default="fotokatalog.db")
    parser.add_argument("--db-backend", default=None, choices=["sqlite", "mariadb"])
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    load_db_config(args)

    if DB_BACKEND == "sqlite":
        if not os.path.exists(DB_PATH):
            print("Datenbank nicht gefunden: " + DB_PATH)
            exit(1)
    else:
        try:
            test_conn = get_db()
            test_conn.close()
        except Exception as e:
            print("MariaDB-Verbindung fehlgeschlagen: " + str(e))
            exit(2)

    # DB-Migration und API-Key
    ensure_db_columns()
    load_api_key()

    server = http.server.HTTPServer(("127.0.0.1", args.port), Handler)
    url = "http://localhost:" + str(args.port)
    print("")
    print("  FOTOKATALOG - Web-UI")
    print("  " + url)
    print("  DB-Backend: " + DB_BACKEND)
    if DB_BACKEND == "sqlite":
        print("  Datenbank: " + DB_PATH)
    else:
        print("  MariaDB: {user}@{host}:{port}/{database}".format(**MARIADB_CONFIG))
    print("  API-Key: " + ("geladen" if API_KEY else "NICHT GEFUNDEN (.env oder $ANTHROPIC_API_KEY)"))
    print("  Beenden mit Ctrl+C")
    print("")

    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer beendet.")
