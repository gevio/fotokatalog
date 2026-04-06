#!/usr/bin/env python3
"""
FOTOKATALOG - Import & Verschlagwortungs-Engine
================================================
Liest Fotos/Videos ein, extrahiert EXIF+GPS, löst Orte auf,
und speichert alles in einer SQLite-Datenbank.

Nutzung:
    python3 katalog.py /pfad/zu/fotos
    python3 katalog.py /pfad/zu/fotos --db mein_katalog.db
    python3 katalog.py /pfad/zu/fotos --no-geocode   (ohne Reverse Geocoding)
"""

import sqlite3
import hashlib
import json
import os
import sys
import time
import struct
import logging
from pathlib import Path
from datetime import datetime
from io import BytesIO
from typing import Optional

# ── Abhängigkeiten ──────────────────────────────────────────
try:
    from PIL import Image, ExifTags
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("⚠  Pillow nicht installiert – Thumbnails deaktiviert")

try:
    import exifread
    HAS_EXIFREAD = True
except ImportError:
    HAS_EXIFREAD = False
    print("⚠  exifread nicht installiert – pip install exifread")

try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    HAS_GEOPY = True
except ImportError:
    HAS_GEOPY = False
    print("⚠  geopy nicht installiert – Reverse Geocoding deaktiviert")


# ── Konfiguration ───────────────────────────────────────────
PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.heic', '.heif', '.webp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.mts', '.m4v'}
THUMBNAIL_SIZE = (320, 320)
GEOCODE_DELAY = 1.1          # Nominatim: max 1 Request/Sekunde
GEOHASH_PRECISION = 7

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('fotokatalog')


# ── Geohash-Berechnung ─────────────────────────────────────
def encode_geohash(lat: float, lon: float, precision: int = 7) -> str:
    """Einfache Geohash-Implementierung für Clustering."""
    BASE32 = '0123456789bcdefghjkmnpqrstuvwxyz'
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    geohash = []
    bits = [16, 8, 4, 2, 1]
    bit = 0
    ch = 0
    even = True
    while len(geohash) < precision:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if lon > mid:
                ch |= bits[bit]
                lon_range[0] = mid
            else:
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat > mid:
                ch |= bits[bit]
                lat_range[0] = mid
            else:
                lat_range[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            geohash.append(BASE32[ch])
            bit = 0
            ch = 0
    return ''.join(geohash)


# ── EXIF-Extraktion ────────────────────────────────────────
def _dms_to_decimal(dms_tuple, ref: str) -> Optional[float]:
    """Konvertiert GPS DMS (Grad/Min/Sek) Tuple in Dezimalgrad.
    Funktioniert sowohl mit Pillow-Tupeln als auch exifread-Werten."""
    if not dms_tuple or not ref:
        return None
    try:
        # Pillow gibt Tupel zurück: (46.0, 26.0, 14.15292)
        if isinstance(dms_tuple, (tuple, list)):
            d, m, s = float(dms_tuple[0]), float(dms_tuple[1]), float(dms_tuple[2])
        else:
            # exifread gibt IfdTag-Objekte zurück
            values = dms_tuple.values
            d = float(values[0].num) / float(values[0].den)
            m = float(values[1].num) / float(values[1].den)
            s = float(values[2].num) / float(values[2].den)
        decimal = d + m / 60 + s / 3600
        if ref in ('S', 'W'):
            decimal = -decimal
        return round(decimal, 7)
    except (AttributeError, IndexError, ZeroDivisionError, TypeError, ValueError):
        return None


def extract_exif(file_path: str) -> dict:
    """Extrahiert alle relevanten EXIF-Daten aus einer Bilddatei.
    Nutzt Pillow als primäre Quelle (liest Samsung GPS korrekt),
    mit exifread als Ergänzung für Belichtungsdaten."""
    result = {
        'camera_make': None, 'camera_model': None, 'lens_model': None,
        'focal_length': None, 'aperture': None, 'shutter_speed': None,
        'iso': None, 'flash_fired': None, 'orientation': None,
        'software': None, 'date_taken': None, 'width': None, 'height': None,
        'latitude': None, 'longitude': None, 'altitude': None
    }

    # ── Pillow: Hauptquelle (besonders für GPS + Basisdaten) ──
    if HAS_PIL:
        try:
            from PIL.ExifTags import TAGS, IFD, GPSTAGS
            img = Image.open(file_path)
            exif = img.getexif()

            if exif:
                # Basisdaten direkt aus dem Root-IFD
                result['camera_make'] = exif.get(0x010F)  # Make
                result['camera_model'] = exif.get(0x0110)  # Model
                result['software'] = exif.get(0x0131)  # Software
                result['orientation'] = exif.get(0x0112)  # Orientation
                result['width'] = exif.get(0x0100)  # ImageWidth
                result['height'] = exif.get(0x0101)  # ImageLength

                # Datum
                dt_str = exif.get(0x0132)  # DateTime
                if dt_str:
                    try:
                        result['date_taken'] = datetime.strptime(
                            str(dt_str), '%Y:%m:%d %H:%M:%S').isoformat()
                    except ValueError:
                        pass

                # EXIF Sub-IFD (Belichtung etc.)
                try:
                    exif_ifd = exif.get_ifd(IFD.Exif)
                    if exif_ifd:
                        # DateTimeOriginal (bevorzugt)
                        dto = exif_ifd.get(0x9003)
                        if dto:
                            try:
                                result['date_taken'] = datetime.strptime(
                                    str(dto), '%Y:%m:%d %H:%M:%S').isoformat()
                            except ValueError:
                                pass

                        # Belichtungsdaten
                        fn = exif_ifd.get(0x829D)  # FNumber
                        if fn:
                            result['aperture'] = round(float(fn), 1)

                        et = exif_ifd.get(0x829A)  # ExposureTime
                        if et:
                            if isinstance(et, (int, float)):
                                result['shutter_speed'] = str(et)
                            else:
                                result['shutter_speed'] = str(et)

                        iso_val = exif_ifd.get(0x8827)  # ISOSpeedRatings
                        if iso_val:
                            result['iso'] = int(iso_val) if not isinstance(iso_val, tuple) else int(iso_val[0])

                        fl_val = exif_ifd.get(0x920A)  # FocalLength
                        if fl_val:
                            result['focal_length'] = round(float(fl_val), 1)

                        flash_val = exif_ifd.get(0x9209)  # Flash
                        if flash_val is not None:
                            result['flash_fired'] = 1 if (int(flash_val) & 1) else 0

                        lens = exif_ifd.get(0xA434)  # LensModel
                        if lens:
                            result['lens_model'] = str(lens)

                        # Bildgröße aus EXIF (genauer)
                        ew = exif_ifd.get(0xA002)  # ExifImageWidth
                        eh = exif_ifd.get(0xA003)  # ExifImageLength
                        if ew:
                            result['width'] = int(ew)
                        if eh:
                            result['height'] = int(eh)
                except Exception:
                    pass

                # GPS Sub-IFD
                try:
                    gps_ifd = exif.get_ifd(IFD.GPSInfo)
                    if gps_ifd:
                        lat_ref = gps_ifd.get(1)   # GPSLatitudeRef
                        lat_dms = gps_ifd.get(2)   # GPSLatitude
                        lon_ref = gps_ifd.get(3)   # GPSLongitudeRef
                        lon_dms = gps_ifd.get(4)   # GPSLongitude

                        result['latitude'] = _dms_to_decimal(lat_dms, lat_ref)
                        result['longitude'] = _dms_to_decimal(lon_dms, lon_ref)

                        alt = gps_ifd.get(6)  # GPSAltitude
                        if alt is not None:
                            result['altitude'] = float(alt)
                except Exception:
                    pass

            img.close()
        except Exception as e:
            log.warning(f"  PIL EXIF-Fehler bei {file_path}: {e}")

    # ── exifread: Ergänzung (falls Pillow Felder verpasst) ────
    if HAS_EXIFREAD:
        try:
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)

            # Nur leere Felder auffüllen
            if not result['camera_make']:
                result['camera_make'] = str(tags.get('Image Make', '')).strip() or None
            if not result['camera_model']:
                result['camera_model'] = str(tags.get('Image Model', '')).strip() or None
            if not result['lens_model']:
                result['lens_model'] = str(tags.get('EXIF LensModel', '')).strip() or None

            if not result['date_taken']:
                for tag_name in ['EXIF DateTimeOriginal', 'EXIF DateTimeDigitized', 'Image DateTime']:
                    dt = tags.get(tag_name)
                    if dt:
                        try:
                            result['date_taken'] = datetime.strptime(
                                str(dt), '%Y:%m:%d %H:%M:%S').isoformat()
                            break
                        except ValueError:
                            pass

            if not result['aperture']:
                ap = tags.get('EXIF FNumber')
                if ap:
                    try:
                        result['aperture'] = round(float(ap.values[0].num) / float(ap.values[0].den), 1)
                    except: pass

            if not result['shutter_speed']:
                ss = tags.get('EXIF ExposureTime')
                if ss:
                    result['shutter_speed'] = str(ss)

            if not result['iso']:
                iso = tags.get('EXIF ISOSpeedRatings')
                if iso:
                    try: result['iso'] = int(str(iso))
                    except: pass

            if not result['focal_length']:
                fl = tags.get('EXIF FocalLength')
                if fl:
                    try:
                        result['focal_length'] = float(fl.values[0].num) / float(fl.values[0].den)
                    except: pass

        except Exception as e:
            log.warning(f"  exifread-Fehler bei {file_path}: {e}")

    # Strings bereinigen
    for key in ('camera_make', 'camera_model', 'lens_model', 'software'):
        if result[key]:
            result[key] = str(result[key]).strip() or None

    return result


# ── Bildgröße (Fallback über PIL) ──────────────────────────
def get_dimensions(file_path: str) -> tuple:
    """Gibt (width, height) zurück, falls PIL verfügbar."""
    if not HAS_PIL:
        return None, None
    try:
        with Image.open(file_path) as img:
            return img.size
    except:
        return None, None


# ── Thumbnail erzeugen ─────────────────────────────────────
def create_thumbnail(file_path: str) -> Optional[bytes]:
    """Erzeugt ein JPEG-Thumbnail als Bytes."""
    if not HAS_PIL:
        return None
    try:
        with Image.open(file_path) as img:
            img.thumbnail(THUMBNAIL_SIZE)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            buf = BytesIO()
            img.save(buf, format='JPEG', quality=75)
            return buf.getvalue()
    except Exception:
        return None


# ── Datei-Hash ─────────────────────────────────────────────
def file_sha256(file_path: str, chunk_size: int = 65536) -> str:
    """Berechnet SHA-256 Hash einer Datei."""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ── Automatische Tags ─────────────────────────────────────
def auto_tags_from_exif(exif: dict, date_taken: str) -> list:
    """Generiert automatische Tags aus EXIF und Datum."""
    tags = []

    # Tageszeit
    if date_taken:
        try:
            dt = datetime.fromisoformat(date_taken)
            hour = dt.hour
            if 5 <= hour < 7:
                tags.append(('Blaue Stunde (morgens)', 'tageszeit'))
            elif 7 <= hour < 9:
                tags.append(('Goldene Stunde (morgens)', 'tageszeit'))
            elif 9 <= hour < 17:
                tags.append(('Tageslicht', 'tageszeit'))
            elif 17 <= hour < 19:
                tags.append(('Goldene Stunde (abends)', 'tageszeit'))
            elif 19 <= hour < 21:
                tags.append(('Blaue Stunde (abends)', 'tageszeit'))
            else:
                tags.append(('Nacht', 'tageszeit'))

            # Jahreszeit (Nordhalbkugel)
            month = dt.month
            if month in (3, 4, 5):
                tags.append(('Frühling', 'jahreszeit'))
            elif month in (6, 7, 8):
                tags.append(('Sommer', 'jahreszeit'))
            elif month in (9, 10, 11):
                tags.append(('Herbst', 'jahreszeit'))
            else:
                tags.append(('Winter', 'jahreszeit'))
        except:
            pass

    # Technische Tags
    if exif.get('iso') and exif['iso'] >= 3200:
        tags.append(('High ISO', 'technik'))
    if exif.get('shutter_speed'):
        ss = str(exif['shutter_speed'])
        if '/' not in ss:
            try:
                if float(ss) >= 1:
                    tags.append(('Langzeitbelichtung', 'technik'))
            except:
                pass
    if exif.get('focal_length'):
        fl = exif['focal_length']
        if fl <= 24:
            tags.append(('Weitwinkel', 'technik'))
        elif fl >= 200:
            tags.append(('Tele', 'technik'))
        elif fl <= 60 and fl >= 35:
            tags.append(('Normalbrennweite', 'technik'))

    return tags


# ── Reverse Geocoding ──────────────────────────────────────
class GeoResolver:
    """Löst GPS-Koordinaten in Ortsnamen auf (mit Cache)."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and HAS_GEOPY
        self._cache = {}
        if self.enabled:
            self.geolocator = Nominatim(
                user_agent="fotokatalog/1.0",
                timeout=10
            )

    def resolve(self, lat: float, lon: float) -> dict:
        """Gibt Ortsinformationen für Koordinaten zurück."""
        result = {
            'country': None, 'country_code': None, 'state': None,
            'city': None, 'district': None, 'street': None,
            'display_name': None, 'geohash': None
        }

        result['geohash'] = encode_geohash(lat, lon, GEOHASH_PRECISION)

        if not self.enabled:
            return result

        # Cache-Key: auf 3 Dezimalstellen gerundet (~111m Genauigkeit)
        cache_key = f"{round(lat, 3)},{round(lon, 3)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            time.sleep(GEOCODE_DELAY)
            location = self.geolocator.reverse(
                f"{lat},{lon}",
                language='de',
                exactly_one=True
            )
            if location and location.raw.get('address'):
                addr = location.raw['address']
                result['country'] = addr.get('country')
                result['country_code'] = addr.get('country_code', '').upper()
                result['state'] = addr.get('state')
                result['city'] = (addr.get('city') or addr.get('town')
                                  or addr.get('village') or addr.get('municipality'))
                result['district'] = addr.get('suburb') or addr.get('district')
                result['street'] = addr.get('road')
                result['display_name'] = location.address

            self._cache[cache_key] = result
            log.info(f"    📍 {result['city']}, {result['country']}")

        except (GeocoderTimedOut, GeocoderServiceError) as e:
            log.warning(f"    Geocoding-Fehler: {e}")
        except Exception as e:
            log.warning(f"    Geocoding-Fehler: {e}")

        return result


# ── Datenbank-Manager ──────────────────────────────────────
class FotokatalogDB:
    """Verwaltet die SQLite-Datenbank."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Erstellt die Tabellenstruktur."""
        schema_path = Path(__file__).parent / 'schema.sql'
        if schema_path.exists():
            with open(schema_path) as f:
                self.conn.executescript(f.read())
        log.info(f"✅ Datenbank initialisiert: {self.db_path}")

    def photo_exists(self, file_hash: str) -> bool:
        """Prüft ob ein Foto bereits importiert wurde (Duplikaterkennung)."""
        row = self.conn.execute(
            "SELECT id FROM photos WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        return row is not None

    def insert_photo(self, photo_data: dict) -> int:
        """Fügt ein Foto in die Datenbank ein."""
        cur = self.conn.execute("""
            INSERT INTO photos (file_path, file_name, file_size, file_hash,
                              media_type, width, height, date_taken, thumbnail)
            VALUES (:file_path, :file_name, :file_size, :file_hash,
                    :media_type, :width, :height, :date_taken, :thumbnail)
        """, photo_data)
        return cur.lastrowid

    def insert_exif(self, photo_id: int, exif: dict):
        """Speichert EXIF-Daten."""
        self.conn.execute("""
            INSERT OR REPLACE INTO exif_data
            (photo_id, camera_make, camera_model, lens_model, focal_length,
             aperture, shutter_speed, iso, flash_fired, orientation, software)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (photo_id, exif.get('camera_make'), exif.get('camera_model'),
              exif.get('lens_model'), exif.get('focal_length'),
              exif.get('aperture'), exif.get('shutter_speed'),
              exif.get('iso'), exif.get('flash_fired'),
              exif.get('orientation'), exif.get('software')))

    def insert_geodata(self, photo_id: int, lat: float, lon: float,
                       alt: float, geo_info: dict):
        """Speichert Geodaten."""
        self.conn.execute("""
            INSERT OR REPLACE INTO geo_data
            (photo_id, latitude, longitude, altitude, country, country_code,
             state, city, district, street, display_name, geohash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (photo_id, lat, lon, alt,
              geo_info.get('country'), geo_info.get('country_code'),
              geo_info.get('state'), geo_info.get('city'),
              geo_info.get('district'), geo_info.get('street'),
              geo_info.get('display_name'), geo_info.get('geohash')))

    def get_or_create_tag(self, name: str, category: str, auto: bool = False) -> int:
        """Holt oder erstellt einen Tag."""
        row = self.conn.execute(
            "SELECT id FROM tags WHERE name = ? AND category = ?",
            (name, category)
        ).fetchone()
        if row:
            return row['id']
        cur = self.conn.execute(
            "INSERT INTO tags (name, category, auto_generated) VALUES (?, ?, ?)",
            (name, category, 1 if auto else 0)
        )
        return cur.lastrowid

    def tag_photo(self, photo_id: int, tag_id: int, confidence: float = 1.0):
        """Verknüpft ein Foto mit einem Tag."""
        self.conn.execute(
            "INSERT OR IGNORE INTO photo_tags (photo_id, tag_id, confidence) VALUES (?, ?, ?)",
            (photo_id, tag_id, confidence)
        )

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ── Abfrage-Methoden ────────────────────────────────────
    def search_by_location(self, country=None, city=None, radius_km=None,
                           lat=None, lon=None) -> list:
        """Sucht Fotos nach Ort."""
        if radius_km and lat and lon:
            # Umkreissuche mit Haversine-Approximation
            # 1 Grad ≈ 111 km
            delta = radius_km / 111.0
            return self.conn.execute("""
                SELECT p.*, g.city, g.country, g.display_name
                FROM photos p JOIN geo_data g ON p.id = g.photo_id
                WHERE g.latitude BETWEEN ? AND ?
                  AND g.longitude BETWEEN ? AND ?
                ORDER BY p.date_taken
            """, (lat - delta, lat + delta, lon - delta, lon + delta)).fetchall()
        elif city:
            return self.conn.execute("""
                SELECT p.*, g.city, g.country
                FROM photos p JOIN geo_data g ON p.id = g.photo_id
                WHERE g.city LIKE ?
                ORDER BY p.date_taken
            """, (f"%{city}%",)).fetchall()
        elif country:
            return self.conn.execute("""
                SELECT p.*, g.city, g.country
                FROM photos p JOIN geo_data g ON p.id = g.photo_id
                WHERE g.country LIKE ?
                ORDER BY p.date_taken
            """, (f"%{country}%",)).fetchall()
        return []

    def get_stats(self) -> dict:
        """Gibt Statistiken über den Katalog zurück."""
        stats = {}
        stats['total_photos'] = self.conn.execute(
            "SELECT COUNT(*) FROM photos WHERE media_type='photo'").fetchone()[0]
        stats['total_videos'] = self.conn.execute(
            "SELECT COUNT(*) FROM photos WHERE media_type='video'").fetchone()[0]
        stats['with_gps'] = self.conn.execute(
            "SELECT COUNT(*) FROM geo_data").fetchone()[0]
        stats['countries'] = self.conn.execute(
            "SELECT COUNT(DISTINCT country) FROM geo_data WHERE country IS NOT NULL"
        ).fetchone()[0]
        stats['cities'] = self.conn.execute(
            "SELECT COUNT(DISTINCT city) FROM geo_data WHERE city IS NOT NULL"
        ).fetchone()[0]
        stats['cameras'] = [
            dict(row) for row in self.conn.execute(
                "SELECT camera_model, COUNT(*) as cnt FROM exif_data "
                "WHERE camera_model IS NOT NULL GROUP BY camera_model ORDER BY cnt DESC"
            ).fetchall()
        ]
        return stats


# ── Import-Engine ──────────────────────────────────────────
def scan_directory(root_path: str) -> list:
    """Scannt ein Verzeichnis rekursiv nach Medien-Dateien."""
    all_extensions = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS
    files = []
    for dirpath, _, filenames in os.walk(root_path):
        for fname in sorted(filenames):
            ext = Path(fname).suffix.lower()
            if ext in all_extensions:
                files.append(os.path.join(dirpath, fname))
    return files


def import_photos(source_dir: str, db_path: str = "fotokatalog.db",
                  geocode: bool = True):
    """Hauptfunktion: Importiert alle Fotos aus einem Verzeichnis."""

    log.info(f"🔍 Scanne {source_dir} ...")
    files = scan_directory(source_dir)
    log.info(f"📂 {len(files)} Mediendateien gefunden")

    if not files:
        log.warning("Keine Mediendateien gefunden!")
        return

    db = FotokatalogDB(db_path)
    geo = GeoResolver(enabled=geocode)

    imported = 0
    skipped = 0
    errors = 0
    geo_count = 0

    for i, fpath in enumerate(files, 1):
        fname = os.path.basename(fpath)
        ext = Path(fpath).suffix.lower()
        is_video = ext in VIDEO_EXTENSIONS

        log.info(f"[{i}/{len(files)}] {fname}")

        try:
            # 1. Hash berechnen & Duplikat prüfen
            fhash = file_sha256(fpath)
            if db.photo_exists(fhash):
                log.info(f"  ⏭  Duplikat – übersprungen")
                skipped += 1
                continue

            # 2. EXIF auslesen (nur für Bilder)
            exif = extract_exif(fpath) if not is_video else {}

            # 2b. Datum-Fallback: aus Dateinamen parsen (z.B. 20211223_164541)
            date_taken = exif.get('date_taken')
            if not date_taken:
                import re
                m = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', fname)
                if m:
                    y, mo, d, h, mi, s = m.groups()
                    date_taken = f'{y}-{mo}-{d}T{h}:{mi}:{s}'
                    log.info(f"  📅 Datum aus Dateinamen: {date_taken}")

            # 3. Bildgröße (Fallback)
            width = exif.get('width')
            height = exif.get('height')
            if not width and not is_video:
                width, height = get_dimensions(fpath)

            # 4. Thumbnail erzeugen
            thumb = create_thumbnail(fpath) if not is_video else None

            # 5. In DB einfügen
            photo_id = db.insert_photo({
                'file_path': os.path.abspath(fpath),
                'file_name': fname,
                'file_size': os.path.getsize(fpath),
                'file_hash': fhash,
                'media_type': 'video' if is_video else 'photo',
                'width': width,
                'height': height,
                'date_taken': date_taken,
                'thumbnail': thumb
            })

            # 6. EXIF-Daten speichern
            if exif and any(v for k, v in exif.items() if k not in
                          ('date_taken', 'width', 'height', 'latitude', 'longitude', 'altitude')):
                db.insert_exif(photo_id, exif)

            # 7. Geodaten verarbeiten
            lat = exif.get('latitude')
            lon = exif.get('longitude')
            if lat and lon:
                geo_info = geo.resolve(lat, lon)
                db.insert_geodata(photo_id, lat, lon, exif.get('altitude'), geo_info)
                geo_count += 1

            # 8. Auto-Tags
            auto_tags = auto_tags_from_exif(exif, date_taken)
            for tag_name, tag_cat in auto_tags:
                tag_id = db.get_or_create_tag(tag_name, tag_cat, auto=True)
                db.tag_photo(photo_id, tag_id)

            imported += 1

            # Regelmäßig committen
            if imported % 50 == 0:
                db.commit()

        except Exception as e:
            log.error(f"  ❌ Fehler: {e}")
            errors += 1

    db.commit()

    # ── Statistik ausgeben ──────────────────────────────────
    stats = db.get_stats()
    log.info("\n" + "=" * 50)
    log.info("📊 IMPORT ABGESCHLOSSEN")
    log.info("=" * 50)
    log.info(f"  Importiert:    {imported}")
    log.info(f"  Duplikate:     {skipped}")
    log.info(f"  Fehler:        {errors}")
    log.info(f"  Mit GPS:       {geo_count}")
    log.info(f"  Länder:        {stats['countries']}")
    log.info(f"  Städte:        {stats['cities']}")
    if stats['cameras']:
        log.info(f"  Kameras:")
        for cam in stats['cameras'][:5]:
            log.info(f"    • {cam['camera_model']}: {cam['cnt']} Aufnahmen")
    log.info(f"\n  Datenbank: {db.db_path}")

    db.close()


# ── EXIF-Übertragung: Originale → Snapseed ────────────────
def extract_timestamp_prefix(filename: str) -> Optional[str]:
    """Extrahiert den Timestamp-Prefix aus einem Dateinamen.
    z.B. '20211223_164541-01.jpeg' → '20211223_164541'
         '20211223_164541.jpg'     → '20211223_164541'
    """
    import re
    m = re.search(r'(\d{8}_\d{6})', filename)
    return m.group(1) if m else None


def build_exif_lookup(originals_dir: str) -> tuple:
    """Scannt den Originale-Ordner und baut zwei Lookup-Tabellen:
    1. timestamp_prefix → exif_data (für Timestamp-Dateinamen)
    2. date_str → [(timestamp_prefix, exif_data), ...] (für numerische Dateinamen)
    """
    log.info(f"🔍 Scanne Originale in {originals_dir} ...")
    files = scan_directory(originals_dir)
    log.info(f"📂 {len(files)} Originale gefunden")

    lookup = {}          # prefix → exif
    date_index = {}      # "20260224" → [(prefix, exif, datetime), ...]

    for i, fpath in enumerate(files, 1):
        fname = os.path.basename(fpath)
        prefix = extract_timestamp_prefix(fname)
        if not prefix:
            continue

        exif = extract_exif(fpath)

        # Nur speichern wenn es nützliche Daten gibt
        has_gps = exif.get('latitude') is not None and exif.get('longitude') is not None
        has_camera = exif.get('camera_model') is not None
        has_date = exif.get('date_taken') is not None

        if has_gps or has_camera or has_date:
            lookup[prefix] = exif
            gps_str = f"📍 GPS" if has_gps else "  ---"
            log.info(f"  [{i}/{len(files)}] {fname}  {gps_str}  {exif.get('camera_model', '')}")

            # Date-Index aufbauen: "20260224" → Liste von Originalen an diesem Tag
            date_str = prefix[:8]  # "20260224" aus "20260224_175846"
            if date_str not in date_index:
                date_index[date_str] = []
            # Zeitstempel für zeitliche Sortierung
            try:
                from datetime import datetime as dt_class
                ts = dt_class.strptime(prefix, '%Y%m%d_%H%M%S')
            except:
                ts = None
            date_index[date_str].append((prefix, exif, ts))

    # Sortiere Date-Index nach Zeit
    for date_str in date_index:
        date_index[date_str].sort(key=lambda x: x[2] or datetime.min)

    log.info(f"✅ {len(lookup)} Originale mit nutzbaren Metadaten")
    gps_count = sum(1 for e in lookup.values() if e.get('latitude'))
    log.info(f"   davon {gps_count} mit GPS-Koordinaten")
    log.info(f"   {len(date_index)} verschiedene Tage im Date-Index")

    return lookup, date_index


def match_numeric_filename(fpath: str, date_index: dict) -> tuple:
    """Versucht ein numerisches Snapseed-Foto über LastWriteTime
    dem zeitlich nächsten Original zuzuordnen.
    Gibt (original_exif, match_info) zurück oder (None, None).
    """
    try:
        # LastWriteTime der Snapseed-Datei auslesen
        mtime = os.path.getmtime(fpath)
        file_dt = datetime.fromtimestamp(mtime)
        date_str = file_dt.strftime('%Y%m%d')

        # Suche Originale vom selben Tag
        candidates = date_index.get(date_str, [])

        if not candidates:
            # Auch Tag davor/danach prüfen
            from datetime import timedelta
            for delta in [timedelta(days=-1), timedelta(days=1)]:
                alt_date = (file_dt + delta).strftime('%Y%m%d')
                candidates = date_index.get(alt_date, [])
                if candidates:
                    break

        if not candidates:
            return None, None

        # Zeitlich nächstes Original finden
        best = None
        best_diff = None
        for prefix, exif, ts in candidates:
            if ts:
                diff = abs((file_dt - ts).total_seconds())
                if best_diff is None or diff < best_diff:
                    best = exif
                    best_diff = diff
                    best_prefix = prefix

        if best:
            return best, f"~{best_prefix} (Datum-Match, {int(best_diff)}s Differenz)"
        else:
            # Kein Zeitstempel, nehme erstes vom Tag
            return candidates[0][1], f"~{candidates[0][0]} (Datum-Match, erstes vom Tag)"

    except Exception as e:
        log.warning(f"  Numerisches Matching fehlgeschlagen: {e}")
        return None, None


def import_snapseed(snapseed_dir: str, originals_dir: str,
                    db_path: str = "fotokatalog.db", geocode: bool = True):
    """Zwei-Pass-Import: Snapseed-Bilder mit EXIF von Originalen.

    1. Scanne Originale → baue Metadaten-Lookup (nach Timestamp)
    2. Importiere Snapseed-Bilder als Hauptbilder
    3. Übertrage GPS + EXIF vom Original via Timestamp-Matching
    """

    # ── Pass 1: Originale scannen ───────────────────────────
    log.info("=" * 50)
    log.info("PASS 1: Originale scannen (Metadaten sammeln)")
    log.info("=" * 50)
    exif_lookup, date_index = build_exif_lookup(originals_dir)

    if not exif_lookup:
        log.warning("⚠  Keine nutzbaren Metadaten in Originalen gefunden!")
        log.info("   Fahre trotzdem fort (nur Dateinamen-Daten)")

    # ── Pass 2: Snapseed-Bilder importieren ─────────────────
    log.info("")
    log.info("=" * 50)
    log.info("PASS 2: Snapseed-Bilder importieren")
    log.info("=" * 50)

    files = scan_directory(snapseed_dir)
    log.info(f"📂 {len(files)} Snapseed-Bilder gefunden")

    if not files:
        log.warning("Keine Mediendateien gefunden!")
        return

    db = FotokatalogDB(db_path)
    geo = GeoResolver(enabled=geocode)

    imported = 0
    matched = 0
    skipped = 0
    errors = 0
    geo_count = 0

    for i, fpath in enumerate(files, 1):
        fname = os.path.basename(fpath)
        ext = Path(fpath).suffix.lower()
        is_video = ext in VIDEO_EXTENSIONS

        log.info(f"[{i}/{len(files)}] {fname}")

        try:
            # 1. Duplikat prüfen
            fhash = file_sha256(fpath)
            if db.photo_exists(fhash):
                log.info(f"  ⏭  Duplikat – übersprungen")
                skipped += 1
                continue

            # 2. Timestamp-Matching: Metadaten vom Original holen
            prefix = extract_timestamp_prefix(fname)
            original_exif = exif_lookup.get(prefix, {}) if prefix else {}
            match_method = "timestamp"

            # 2b. Fallback: numerische Dateinamen über LastWriteTime matchen
            if not original_exif and not prefix:
                import re
                if re.match(r'^\d{7,}\.', fname):
                    original_exif, match_info = match_numeric_filename(fpath, date_index)
                    if original_exif:
                        match_method = "datum"
                        log.info(f"  🔗 Datum-Match → {match_info}")
                    else:
                        original_exif = {}

            if original_exif and match_method == "timestamp":
                matched += 1
                cam = original_exif.get('camera_model', '?')
                has_gps = '📍' if original_exif.get('latitude') else ''
                log.info(f"  🔗 Match → {cam} {has_gps}")
            elif original_exif and match_method == "datum":
                matched += 1

            # 3. Datum: Original-EXIF > Dateiname-Fallback > LastWriteTime
            date_taken = original_exif.get('date_taken') if original_exif else None
            if not date_taken and prefix:
                import re
                m = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', prefix)
                if m:
                    y, mo, d, h, mi, s = m.groups()
                    date_taken = f'{y}-{mo}-{d}T{h}:{mi}:{s}'
            if not date_taken:
                # Letzter Fallback: Datei-Änderungsdatum
                try:
                    mtime = os.path.getmtime(fpath)
                    date_taken = datetime.fromtimestamp(mtime).isoformat()
                    log.info(f"  📅 Datum aus Dateidatum: {date_taken[:10]}")
                except:
                    pass

            # 4. Bildgröße
            width, height = None, None
            if not is_video:
                width, height = get_dimensions(fpath)

            # 5. Thumbnail
            thumb = create_thumbnail(fpath) if not is_video else None

            # 6. In DB einfügen
            photo_id = db.insert_photo({
                'file_path': os.path.abspath(fpath),
                'file_name': fname,
                'file_size': os.path.getsize(fpath),
                'file_hash': fhash,
                'media_type': 'video' if is_video else 'photo',
                'width': width,
                'height': height,
                'date_taken': date_taken,
                'thumbnail': thumb
            })

            # 7. EXIF vom Original speichern
            if original_exif and any(v for k, v in original_exif.items()
                                     if k not in ('date_taken', 'width', 'height',
                                                  'latitude', 'longitude', 'altitude')):
                db.insert_exif(photo_id, original_exif)

            # 8. Geodaten vom Original
            lat = original_exif.get('latitude')
            lon = original_exif.get('longitude')
            if lat and lon:
                geo_info = geo.resolve(lat, lon)
                db.insert_geodata(photo_id, lat, lon,
                                  original_exif.get('altitude'), geo_info)
                geo_count += 1

            # 9. Auto-Tags
            auto_tags = auto_tags_from_exif(original_exif, date_taken)
            for tag_name, tag_cat in auto_tags:
                tag_id = db.get_or_create_tag(tag_name, tag_cat, auto=True)
                db.tag_photo(photo_id, tag_id)

            imported += 1

            if imported % 50 == 0:
                db.commit()

        except Exception as e:
            log.error(f"  ❌ Fehler: {e}")
            errors += 1

    db.commit()

    # ── Statistik ───────────────────────────────────────────
    stats = db.get_stats()
    log.info("\n" + "=" * 50)
    log.info("📊 SNAPSEED-IMPORT ABGESCHLOSSEN")
    log.info("=" * 50)
    log.info(f"  Snapseed-Bilder: {imported}")
    log.info(f"  Matched:         {matched} / {imported} ({round(matched/max(imported,1)*100)}% mit Original-EXIF)")
    log.info(f"  Duplikate:       {skipped}")
    log.info(f"  Fehler:          {errors}")
    log.info(f"  Mit GPS:         {geo_count}")
    log.info(f"  Länder:          {stats['countries']}")
    log.info(f"  Städte:          {stats['cities']}")
    if stats['cameras']:
        log.info(f"  Kameras:")
        for cam in stats['cameras'][:5]:
            log.info(f"    • {cam['camera_model']}: {cam['cnt']} Aufnahmen")
    log.info(f"\n  Datenbank: {db.db_path}")

    db.close()


# ── CLI ────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description='Fotokatalog – Import & Verschlagwortung',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  # Normaler Import (Fotos mit EXIF):
  python katalog.py "E:\\DCIM\\Fotos"

  # Snapseed-Import (Metadaten von Originalen übernehmen):
  python katalog.py "E:\\DCIM\\Snapseed" --originals "E:\\DCIM\\Originale"

  # Schneller Import ohne Geocoding:
  python katalog.py "E:\\DCIM\\Snapseed" --originals "E:\\DCIM\\Originale" --no-geocode
        """)
    parser.add_argument('source', help='Quellverzeichnis mit Fotos (bzw. Snapseed-Bilder)')
    parser.add_argument('--originals', help='Ordner mit Originalfotos (für EXIF-Übertragung auf Snapseed-Bilder)')
    parser.add_argument('--db', default='fotokatalog.db', help='Pfad zur Datenbank')
    parser.add_argument('--no-geocode', action='store_true', help='Reverse Geocoding deaktivieren')
    args = parser.parse_args()

    if not os.path.isdir(args.source):
        print(f"❌ Verzeichnis nicht gefunden: {args.source}")
        sys.exit(1)

    if args.originals:
        if not os.path.isdir(args.originals):
            print(f"❌ Originale-Verzeichnis nicht gefunden: {args.originals}")
            sys.exit(1)
        import_snapseed(args.source, args.originals,
                        args.db, geocode=not args.no_geocode)
    else:
        import_photos(args.source, args.db, geocode=not args.no_geocode)
