# Fotokatalog Projekt - Umfassende Analyse

## Projekt-Kontext
- **Ort**: `e:\DCIM\03_Privat\Best of Valais\_fotokatalog`
- **Art**: Foto-Katalogisierung → E-Commerce (Postkarten)
- **Status**: Lokales Tool, funktionierend. Produktionsbereit für Phase 1 nicht vorhanden.
- **Daten**: ~2500 Wallis-Fotos, 866 KI-analysiert, 364 mit Gibran-Texten

## Gefundene Infrastruktur-Komponenten

### Existierend (funktionierend lokal)
- **Katalog-Engine**: katalog.py (EXIF/GPS/Geohash, SQLite WAL-Mode)
- **DB-Schema**: schema.sql (Fotos, EXIF, Geo, Tags, Alben, Vision-Analysis, Print-Info)
- **Web-UI**: webui.py (http.server lokal, kein Framework, auth-less)
- **AI-Integration**: gibran_tags.py (Claude Vision/Text), vision_tags.py, peak_overlay.py
- **PDF-Generator**: postcard_pdf.py (reportlab, DIN-lang/A6-Formate)
- **Database**: fotokatalog.db (SQLite + WAL, Duplikaterkennung via Hash)

### Fehlend (produktives Deployment)
- **Framework**: `http.server` statt Flask/FastAPI
- **Auth**: Keine Session-Verwaltung
- **Preview-Generierung**: Kein generate_previews.py
- **Reverse Proxy**: Keine Caddy/Nginx-Konfiguration
- **Environment**: .env nur für ANTHROPIC_API_KEY
- **.env Handling**: Manuell (nicht in production-ready config.py)
- **Database-Migration**: `ensure_db_columns()` in webui.py (ad-hoc, nicht strukturell)
- **Service Scripts**: Keine Systemd/Supervisor-Scripts
- **Docker**: Kein Dockerfile/docker-compose.yml
- **Deployment-Secrets**: .env im Git (⚠️ SICHERHEITSRISIKO!)
- **Datenbank-Pfad**: Hardcoded `fotokatalog.db` im lokalen Verzeichnis

## .gitignore-Analyse
✅ .env ist excluded, aber in Repo vorhanden (Sicherheitsleck!)
✅ fotokatalog.db + WAL-Dateien excluded
✅ _postkarten/, _annotated/ excluded
✅ __pycache__/ excluded

## Abhängigkeiten (aus setup.bat)
```
exifread
geopy
Pillow
```

Implizite weitere (aus code):
```
reportlab (postcard_pdf.py)
anthropic (gibran_tags.py, vision_tags.py, peak_overlay.py)
sqlite3 (all)
```

## Zwei Deploymentszenarien

### Option A: SSH-VM bei Originalbildern auf ext. Festplatte
- **Pro**: Schnelles Iterieren, volle Kontrolle, Originalbilder lokal sicher
- **Con**: VM-Verwaltung, Bandbreite für Bild-Upload über SSH
- **Infra-Anforderung**: Python 3.9+, SQLite, ~500MB SSD, ~2TB ext. HDD-Zugang

### Option B: VPS mit bestehendem Setup (aus anderem Projekt)
- **Pro**: Production-ready, Skalierung, Backup-Strategien existent
- **Con**: Abhängigkeit von externem Projekt-Setup, Migrationscomplexität
- **Infra-Anforderung**: Python 3.9+, PostgreSQL (wahrscheinlich), 2+ CPU, 4GB RAM, Nginx/Caddy

## Strategisches Ziel (aus strategieplan.md)
Phase 1 (6-8 Wochen):
1. generate_previews.py (Wasserzeichen, 1200px, ~100MB total)
2. Flask-Migration (Blueprint-Struktur für Multi-Tenant)
3. Auth-System (Flask-Login, 1 Admin-User)
4. Öffentliche Galerie (nur Previews) + Admin-Bereich (bestehende UI)

Phase 2 (Tenants, QR-Codes, Stripe, Druck-Fulfillment)
Phase 3 (Collections, Paperclip.ing-Agenten, White-Label)

## Kritische Blockers für Production
1. .env mit Secrets im Repo
2. Keine Config-Abstraction (DB-Pfad, Port etc. hardcoded)
3. Keine Datenbank-Migrations-Framework
4. Keine Preview-Pipeline
5. `http.server` nicht skalierbar
6. Keine CI/CD-Pipeline
7. Keine Monitoring/Logging
8. Originale auf lokaler Festplatte (Backup-Strategie unklar)

# Update 12.04.2026: Local-First Umsetzung

## Entscheidungsstand
- DNS steht: `fotokatalog.gevio.cloud` zeigt auf `72.62.42.124`.
- Zielbetrieb bleibt VPS (Nginx + systemd), aber Implementierung startet lokal auf VM.
- Datenbankstrategie: MariaDB ist Pflicht in Phase 1.
- Sicherheitsstatus: Anthropic-Key ist rotiert.

## Lokale Entwicklungsumgebung (VMWare) - verbindlich
- Windows hosts ist gesetzt: `192.168.28.130 fotokatalog.dev.local`.
- Ping-Test erfolgreich auf `fotokatalog.dev.local`.
- SSH-Hosts vorhanden:
	- `vm-local-wwwdata` (Runtime/Rechte-Checks)
	- `vm-claude` (primäre Entwicklungsumgebung)

## Warum Git auf der VM sinnvoll ist
- Ja, Quellen sollen in der VM liegen.
- Grund: Nginx/Gunicorn/systemd/MariaDB laufen dort zusammen und müssen in derselben Umgebung getestet werden.
- Betriebsweg:
	1. Code in eigenem VM-Projektverzeichnis klonen.
	2. Dort entwickeln und testen.
	3. Später identischen Ablauf für VPS-Deploy nutzen.

## Zugriff auf Originale
- Originale bleiben auf externer Festplatte am Windows-Host.
- VM greift kontrolliert darauf zu, bevorzugt read-only via SMB-Mount.
- Alternative: regelmäßiger Sync in einen VM-Arbeitsordner.

## Nginx auf der VM - konkretes Zielbild
- Domain lokal: `fotokatalog.dev.local`
- Nginx als Reverse Proxy vor Gunicorn
- App-Prozess als systemd-Service
- MariaDB lokal auf VM (keine externe DB-Freigabe nötig)

## Nächste Umsetzungsschritte
1. Neues Projektverzeichnis auf `vm-claude` anlegen und Repo klonen.
2. Python venv + Basis-Abhängigkeiten installieren.
3. MariaDB DB/User/Rechte für `fotokatalog` anlegen.
4. Nginx Server-Block für `fotokatalog.dev.local` einrichten.
5. Gunicorn als systemd-Service konfigurieren.
6. End-to-End-Test über Browser und DB-Verbindung.

## Bereits angelegte Implementierungsartefakte
- VM Runbook: `docs/vm-local-setup.md`
- Nginx Server-Block: `ops/vm/nginx/fotokatalog.dev.local.conf`
- systemd Service (aktueller webui.py Stand): `ops/vm/systemd/fotokatalog.service`
- systemd Service (spätere Flask/Gunicorn Migration): `ops/vm/systemd/fotokatalog-gunicorn.future.service`
- MariaDB Init-SQL: `ops/vm/mariadb/01_init_fotokatalog.sql`
- Environment-Vorlage: `ops/vm/env/fotokatalog.env.example`