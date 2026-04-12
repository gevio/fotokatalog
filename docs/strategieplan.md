# Fotokatalog → Postkarten-Business: Strategieplan

*Stand: 7. April 2026*

## Context

Du hast einen funktionierenden lokalen Foto-Katalog (~2500 Walliser Landschaftsfotos, 866 KI-analysiert, 364 mit Gibran-Texten, PDF-Generierung). Ziel: daraus ein vollständiges Business machen — Web-Galerie, Multi-Tenant-Plattform für Shops/Cabanes, QR-Code-Bestellungen, Druck über flexible Partner (Flyeralarm, Printzessin, oder andere).

### Paperclip.ing — Einordnung

**Paperclip.ing ist KEINE E-Commerce-Plattform.** Es ist eine Open-Source-Plattform zur Orchestrierung von KI-Agenten als "virtuelle Mitarbeiter" (Org-Charts, Budget-Kontrolle, Task-Management für AI-Agents). Für den Shop/Storefront/Payment-Teil ist es ungeeignet.

**Wo Paperclip.ing Sinn macht (Phase 3):**
- Agent 1: **Foto-Onboarding** — neue Fotos automatisch analysieren (Vision + Gibran), Previews generieren, Tenant-Zuordnung vorschlagen
- Agent 2: **Order-Monitor** — Bestellstatus prüfen, Versand-Benachrichtigungen senden, feststeckende Bestellungen flaggen
- Agent 3: **Analytics-Digest** — Wöchentlich: Umsatzreport, Top-Fotos, Tenant-Performance
- Agent 4: **Kundenservice** — FAQ beantworten, komplexe Anfragen eskalieren

**Ehrliche Einschätzung:** Bei den zu erwartenden Volumina im ersten Jahr (Hunderte, nicht Tausende Bestellungen) ist manueller Betrieb machbar. Paperclip.ing wird wertvoll, wenn mehrere Collections und dutzende Tenants operativen Overhead erzeugen.

---

## Phase 1: Web-Ready Gallery (Preview-Only)

**Ziel:** Wassergezeichnete Vorschaubilder online, Originale bleiben lokal. Öffentliche Galerie + Admin-Bereich.

### 1.1 Preview-Pipeline

Neues Script `generate_previews.py`:
- Alle nicht-versteckten Fotos verarbeiten
- Lange Kante max 1200px (ausreichend für Web, unbrauchbar für Qualitätsdruck)
- Dezentes diagonales Wasserzeichen ("© P. Kueck") via Pillow
- Output: `_previews/{photo_id}.jpg` (JPEG 82%, ~80-150KB pro Bild)
- Geschätzt: ~864 sichtbare Fotos × ~120KB = **~100MB** (trivial deploybar)

```sql
ALTER TABLE photos ADD COLUMN preview_path TEXT;
```

### 1.2 Flask-Migration

`http.server` → **Flask**. Gründe: leichtestes echtes Framework, Blueprints für Multi-Tenant, Middleware-Support, trotzdem Python.

```
_fotokatalog/
  app/
    __init__.py              # Flask App Factory
    config.py                # DB-Pfad, Secrets, Modes
    routes_public.py         # Öffentliche Galerie: /api/photos, /api/preview/{id}
    routes_admin.py          # Admin: Rating, Tagging, PDF (bestehende Logik aus webui.py)
    auth.py                  # Session-Auth (Admin-Login)
    templates/
      gallery.html           # Öffentliche Galerie (read-only, nur Previews)
      admin.html             # Bestehende UI (refactored aus index.html)
    static/                  # CSS, JS (extrahiert aus index.html)
  generate_previews.py       # Batch Preview-Generator
```

**URL-Struktur:**
- `/` — Öffentliche Galerie (kein Auth, nur Previews)
- `/admin` — Bestehende vollständige UI hinter Login
- `/api/preview/{id}` — Wassergezeichnete Vorschau (öffentlich)
- `/api/full/{id}` — Nur Admin, nie öffentlich

### 1.3 Auth & Rollen

**Rollenmodell (alle Phasen):**

| Feature | Public | Reviewer | Admin | Tenant |
|---------|:------:|:--------:|:-----:|:------:|
| Fotos anschauen (Previews) | ✅ | ✅ | ✅ | ✅ (nur seine Collection) |
| Karte | ✅ | ✅ | ✅ | ✅ (nur seine Fotos) |
| Filter (Ort, Tag) | ✅ | ✅ | ✅ | eingeschränkt |
| ★ Rating abgeben | ❌ | ✅ → `user_ratings` | ✅ → `photos.rating` | ✅ → `user_ratings` |
| ❤ Favorit/Merkliste | ❌ | ✅ → `user_ratings` | ✅ → `photos.is_favorite` | ✅ → `user_ratings` |
| QS/PKS/DRS Scores sehen | ❌ | ❌ | ✅ | ✅ (read-only) |
| Alben verwalten | ❌ | ❌ | ✅ | ✅ (nur seine Collection) |
| Gibran-Texte sehen | ✅ (lesen) | ✅ | ✅ (editieren) | ✅ (lesen) |
| Notizen bearbeiten | ❌ | ❌ | ✅ | ❌ |
| Hidden/Versteckte | ❌ | ❌ | ✅ | ❌ |
| Postkarten-PDF generieren | ❌ | ❌ | ✅ | ❌ |
| EXIF/Druckinfo | ❌ | ❌ | ✅ | ❌ |

**Zugangsmodell:**
- **Public** → kein Login, sieht nur Gallery + Previews
- **Reviewer** → Link mit Token (`?token=abc123`), kann ★ + ❤, Token = `session_id`
- **Admin** → Login (username/password), volle UI
- **Tenant** → Login oder Token, sieht nur seine Collection

**Admin-Bewertung vs User-Bewertung:**
- `photos.rating` / `photos.is_favorite` = Admin-Werte (lokal gepflegt, bei Deploy überschrieben)
- `user_ratings` = Reviewer/Tenant-Bewertungen (nur in MariaDB/Prod, bleibt erhalten)
- UI zeigt bei Admin: direkt editierbar. Bei allen anderen: eigene ★ über `user_ratings`

### 1.3.1 Collection-Flow (Wie kommt ein Tenant zu seinen Fotos?)

```
Admin (lokal, SQLite)                    Prod (MariaDB)
┌────────────────────────────┐           ┌─────────────────────────┐
│ 1. Fotos kuratieren        │           │                         │
│    (Rating, Tags, Alben)   │           │                         │
│                            │           │                         │
│ 2. Collection erstellen:   │           │                         │
│    "Grimentz Winter 2026"  │           │                         │
│    → Album mit best-of     │           │                         │
│                            │           │                         │
│ 3. Tenant anlegen:         │──deploy──→│ tenant: dorfladen-grim. │
│    slug: dorfladen-grim.   │           │ collection_id: 7        │
│    collection_id: Album 7  │           │ → sieht nur Album 7    │
│                            │           │                         │
│ 4. Export: SQLite→MariaDB  │──export──→│ photos + tenant_photos  │
└────────────────────────────┘           └─────────────────────────┘
```

**Ablauf im Detail:**
1. Admin erstellt Alben als "Collections" (z.B. "Grimentz Auswahl", "Anniviers Best-Of")
2. Admin weist Fotos den Alben zu (bestehendes Album-Feature)
3. In `tenants`-Tabelle: `collection_id` verweist auf ein Album
4. Alternativ: `tenant_photos` für freie Zuordnung ohne Album
5. Export-Script überträgt alles nach MariaDB
6. Tenant-Login zeigt nur Fotos aus seiner `collection_id` / `tenant_photos`

**Ergebnis:** Tenant "Dorfladen Grimentz" öffnet `fotokatalog.dev.local/t/dorfladen-grimentz`
→ sieht 30 kuratierte Winterfotos aus dem Anniviers
→ kann ★ bewerten + ❤ merken (→ `user_ratings`)
→ sieht QS/PKS/DRS Scores (read-only)
→ kann eigene Alben innerhalb seiner Collection verwalten

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT DEFAULT 'admin',
    tenant_id     INTEGER REFERENCES tenants(id),   -- NULL=Admin, sonst Tenant-Zuordnung
    created_at    TEXT DEFAULT (datetime('now'))
);
```

### 1.4 Deployment

- **Hetzner Cloud CPX11** (~4 EUR/Monat) oder Railway/Render zum Prototyping
- Flask + Gunicorn + Caddy (Auto-HTTPS)
- Upload: `_previews/` + `fotokatalog.db` + App-Code. Originale bleiben lokal.
- SQLite reicht für diese Phase (read-heavy, ein Admin-Writer)

### 1.5 Aufwand Phase 1: ~16-20 Stunden

| Task | Aufwand |
|------|---------|
| `generate_previews.py` (Wasserzeichen + Resize) | 3-4h |
| Flask-Scaffold + Routes aus `webui.py` migrieren | 4-6h |
| JS/CSS aus `index.html` extrahieren | 2-3h |
| Öffentliche Galerie-Template | 3-4h |
| Auth (Admin-Login) | 2h |
| Server-Setup + Deployment | 2-3h |

---

## Phase 2: Multi-Tenant Business-Plattform

**Ziel:** Shops/Cabanes zeigen kuratierte Foto-Auswahl, QR-Bestellung, Zahlung, Druck-Fulfillment.

### 2.1 Neue Datenbank-Tabellen

**Tenants** (Shops, Cabanes, Hotels):
```sql
CREATE TABLE IF NOT EXISTS tenants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT NOT NULL UNIQUE,        -- "dorfladen-grimentz"
    name            TEXT NOT NULL,
    type            TEXT CHECK(type IN ('shop','cabane','hotel','online')),
    contact_email   TEXT,
    address         TEXT,
    latitude        REAL,
    longitude       REAL,
    theme_color     TEXT DEFAULT '#2563eb',
    commission_pct  REAL DEFAULT 15.0,
    collection_id   INTEGER REFERENCES collections(id),
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tenant_photos (
    tenant_id   INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    photo_id    INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    sort_order  INTEGER DEFAULT 0,
    is_featured INTEGER DEFAULT 0,
    PRIMARY KEY (tenant_id, photo_id)
);
```

**Produkte, Bestellungen, QR-Codes:**
```sql
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,               -- "Postkarte DIN lang"
    type            TEXT,                        -- 'postcard_dinlang', 'print_a4', etc.
    base_price_chf  REAL NOT NULL,
    retail_price_chf REAL NOT NULL,
    provider_sku    TEXT,                        -- SKU beim jeweiligen Druckpartner
    is_active       INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_ref       TEXT NOT NULL UNIQUE,        -- "VPC-20260407-001"
    tenant_id       INTEGER REFERENCES tenants(id),
    status          TEXT DEFAULT 'pending',
    customer_email  TEXT,
    shipping_address TEXT,                       -- JSON
    total_chf       REAL,
    vat_chf         REAL,
    vat_rate        REAL DEFAULT 2.6,           -- Reduzierter Satz für Druckerzeugnisse
    payment_method  TEXT,                        -- 'stripe', 'twint'
    payment_id      TEXT,
    print_provider  TEXT,                        -- 'flyeralarm', 'gelato', 'printzessin', 'manual'
    print_order_id  TEXT,                        -- Bestell-ID beim Druckpartner
    created_at      TEXT DEFAULT (datetime('now')),
    paid_at         TEXT,
    shipped_at      TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER REFERENCES orders(id) ON DELETE CASCADE,
    photo_id    INTEGER REFERENCES photos(id),
    product_id  INTEGER REFERENCES products(id),
    quantity    INTEGER DEFAULT 1,
    unit_price_chf REAL,
    front_style TEXT DEFAULT 'location',
    lang        TEXT DEFAULT 'fr'
);

CREATE TABLE IF NOT EXISTS qr_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    code        TEXT NOT NULL UNIQUE,
    label       TEXT,                           -- "Schaufenster", "Tisch 3"
    scan_count  INTEGER DEFAULT 0,
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);
```

### 2.2 QR → Storefront → Bestellung (Kundenflow)

```
QR-Code im Shop (z.B. neben Postkarten-Ständer)
  ↓
https://postkarten.valais.ch/dorfladen-grimentz?qr=ABC123
  ↓
Mobile-optimierter Storefront (Tenant-spezifisch)
  ↓
Foto auswählen → Format/Sprache/Stil wählen → Live-Vorschau
  ↓
Warenkorb → Checkout (Stripe: Kreditkarte + TWINT)
  ↓
Bezahlt → Print-PDF generiert → An Druckpartner übermittelt
  ↓
Druckerei druckt + versendet → Kunde erhält Tracking-Email
```

**URL-Struktur Storefront:**
- `/{slug}` — Tenant-Landingpage (Fotoraster)
- `/{slug}/photo/{id}` — Foto-Detail + Produktoptionen
- `/{slug}/cart` — Warenkorb (Session-basiert)
- `/{slug}/checkout` — Bezahlvorgang
- `/{slug}/order/{ref}` — Bestellstatus

### 2.3 Payment: Stripe + TWINT

- **Stripe Checkout Session** für Kartenzahlung + TWINT
- TWINT ist seit 2023 als Zahlungsmethode in Stripe verfügbar (Schweiz)
- Webhook `/webhooks/stripe` für Zahlungsbestätigung
- MwSt: **2.6%** (reduzierter Satz für Druckerzeugnisse in der Schweiz)

### 2.4 Druck-Fulfillment (druckerunabhängig)

Die Architektur soll **nicht an einen Druckpartner gebunden** sein. Stattdessen: eine abstrakte Fulfillment-Schicht, die verschiedene Druckereien unterstützt.

#### Recherchierte Druckpartner

| Druckerei | API? | Min. Stück | Stückpreis | Lieferung CH | Besonderheit |
|-----------|------|-----------|------------|-------------|-------------|
| **Flyeralarm** | REST Reseller-API | k.A. (anfragen) | Bulk günstig | ab CHF 17.90 | Grösste Auswahl, API-fähig |
| **Printzessin** (Belp) | Nein (Web-Upload) | 20 | ab 7.8 Rp/Stk (1000er) | Express 2 Tage | Schweizer Qualität, lokal |
| **Gelato** | REST API | 1 | ~15-30 Rp/Stk | EU-Fulfillment | Echtes POD, kein Lager nötig |
| **be.print** | be.open API | variiert | variiert | Schweizer Druckernetzwerk | Hub zu CH-Druckereien |

#### Hybrid-Modell (empfohlen)

**Zwei Fulfillment-Wege parallel:**

1. **Bulk für Shops** (Flyeralarm / Printzessin):
   - Bestseller-Motive in 100er/500er-Chargen vordrucken
   - Shops werden direkt beliefert und verkaufen an Laufkundschaft
   - Höhere Marge (~60-70%), aber Lagerrisiko
   - Nachbestellung wenn Bestand niedrig (Tenant-Admin meldet)

2. **Einzelbestellung Online** (Gelato / Flyeralarm-API):
   - Kunde bestellt via QR/Web → Zahlung → API-Auftrag → Druckerei versendet
   - Kein Lager, aber geringere Marge (~40-50%)
   - Ideal für: Direktverkauf, Custom-Bestellungen, Testphase

#### Technische Umsetzung

Neues Modul `print_fulfillment.py` mit abstraktem Interface:

```python
class PrintProvider:
    """Abstrakte Basis — jede Druckerei implementiert diese Methoden"""
    def submit_order(self, print_pdf_url, quantity, shipping_address): ...
    def get_order_status(self, order_id): ...
    def get_pricing(self, product_type, quantity): ...

class FlyeralarmProvider(PrintProvider): ...   # REST API
class GelatoProvider(PrintProvider): ...       # REST API
class ManualProvider(PrintProvider): ...       # Email/CSV-Export für Printzessin etc.
```

**Flow:**
1. Bestellung bezahlt (Stripe-Webhook bestätigt)
2. System generiert druckfertiges PDF via bestehendem `postcard_pdf.py`
3. PDF zu Cloud-Storage (Cloudflare R2) hochgeladen
4. Je nach Konfiguration: API-Auftrag ODER Admin-Benachrichtigung für manuellen Upload
5. Status-Tracking in `orders`-Tabelle

**Wichtig:** Print-PDFs werden lokal generiert (brauchen Originale), nur die fertigen PDFs gehen in die Cloud. Originale verlassen nie den lokalen Rechner.

### 2.5 Neue Dateistruktur Phase 2

```
app/
  routes_storefront.py       # Tenant-Storefronts (Mobile-first)
  routes_tenant_admin.py     # Tenant-Manager-Dashboard
  routes_payment.py          # Stripe Checkout + Webhooks
  print_fulfillment.py       # Abstrakte Druckpartner-Schicht (Flyeralarm, Gelato, manuell)
  qr_generator.py            # QR-Code-Generierung
  email_service.py           # Bestellbestätigungen
  templates/
    storefront/              # Mobile-first Kunden-Templates
      landing.html
      photo_detail.html
      cart.html
      checkout.html
      order_status.html
    tenant_admin/
      dashboard.html
```

### 2.6 Aufwand Phase 2: ~65-90 Stunden

| Task | Aufwand |
|------|---------|
| DB-Schema + Migrationen | 3-4h |
| Tenant-CRUD + Admin-UI | 6-8h |
| Mobile Storefront (Templates + JS) | 12-16h |
| Warenkorb + Checkout-Flow | 8-10h |
| Stripe-Integration (Checkout + Webhooks) | 6-8h |
| Druck-Fulfillment (abstrakte Schicht + 1. Provider) | 8-10h |
| QR-Code-Generierung + Verwaltung | 3-4h |
| Bestellverwaltung + Status-Tracking | 6-8h |
| Email-Benachrichtigungen | 3-4h |
| Tenant-Admin-Dashboard | 4-6h |
| Testing + Edge-Cases | 8-10h |

---

## Phase 3: Skalierung & Multi-Theme

**Ziel:** Weitere Regionen/Themen, KI-Automatisierung, Analytics.

### 3.1 Collections-Architektur

```sql
CREATE TABLE IF NOT EXISTS collections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,           -- "valais", "berner-oberland", "tessin"
    name        TEXT NOT NULL,
    description TEXT,
    theme_config TEXT,                          -- JSON: Farben, Fonts, Branding
    is_active   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS collection_photos (
    collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
    photo_id    INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    PRIMARY KEY (collection_id, photo_id)
);
```

Jede Collection hat eigene visuelle Identität, Preisgestaltung, Produktkatalog. "Wallis" ist die erste; weitere kommen durch neue Foto-Imports.

### 3.2 Paperclip.ing-Integration (AI-Agenten)

| Agent | Trigger | Aufgabe |
|-------|---------|---------|
| Foto-Onboarding | Neuer Import | Vision-Analyse, Gibran-Texte, Previews, Tenant-Vorschläge |
| Order-Monitor | Stündlich | Druckpartner-Status prüfen, Versandmails, Stuck-Orders flaggen |
| Analytics-Digest | Wöchentlich | Umsatzreport, Top-Fotos, Tenant-Performance |
| Kundenservice | Eingehende Anfrage | FAQs beantworten, komplexe Fälle eskalieren |

Paperclip-Agents rufen Flask-API-Endpoints auf oder nutzen die bestehenden Python-Scripts als Tools.

### 3.3 White-Label

Die Collection + Tenant-Architektur unterstützt natürlich White-Labeling:
- Hotel-Ketten: `postkarten.hotel-brand.ch` → ihre Collection
- Custom CSS via `theme_config` JSON
- Tenant-spezifische Domains via Caddy Reverse Proxy

### 3.4 Aufwand Phase 3: ~30-45 Stunden

---

## Geschäftsmodell

### Revenue Streams
1. **Produktmarge:** Retail-Preis minus Druckkosten minus Versand.
   - Bulk (Flyeralarm/Printzessin): ~60-70% Marge bei 500er-Chargen
   - Einzelbestellung (Gelato/API): ~40-50% Marge
2. **Tenant-Kommission:** 15% auf Verkäufe über Tenant-QR-Codes (konfigurierbar pro Tenant)
3. **Lizenzgebühr (optional):** CHF 99-299/Monat pro Tenant für Premium-Features

### Swiss-Spezifisches
- **MwSt:** 2.6% für Druckerzeugnisse (reduzierter Satz)
- **Zahlung:** Stripe (Kreditkarten + TWINT)
- **Druck:** Flexibel — Schweizer Druckereien (Printzessin) für Qualität, Flyeralarm für Volumen, Gelato für Einzelbestellungen
- **Recht:** Einzelfirma oder GmbH, CHE-Nummer, Impressum, AGB, nDSG-konform

---

## Empfohlene Reihenfolge

1. **Phase 1a:** `generate_previews.py` schreiben + testen
2. **Phase 1b:** Flask-App aufsetzen, Routes aus `webui.py` migrieren
3. **Phase 1c:** Auth + öffentliche Galerie. Deploy auf Testserver.
4. **Phase 2a:** Tenant/Produkt/Order-Schema. Erster Storefront.
5. **Phase 2b:** Stripe-Checkout (Testmodus). End-to-End-Test.
6. **Phase 2c:** Druck-Fulfillment (Testbestellung bei gewähltem Partner).
7. **Phase 2d:** QR-Generierung, Tenant-Admin. Pilot mit einem echten Shop.
8. **Phase 3:** Wächst mit dem Business.

## Verifikation

- **Phase 1:** Öffentliche Galerie aufrufen → Fotos mit Wasserzeichen sichtbar, Originale nicht erreichbar. Admin-Login funktioniert.
- **Phase 2:** QR-Code scannen → Storefront → Foto wählen → Checkout (Stripe Testmodus) → Druckauftrag (Test) → Status-Update
- **Phase 3:** Neue Collection anlegen → Fotos zuordnen → Tenant erstellen → Storefront zeigt nur zugeordnete Fotos

## Risiken

| Risiko | Mitigation |
|--------|-----------|
| SQLite Write-Contention bei vielen Orders | Bei <100 Orders/Tag OK. PostgreSQL-Migration als Phase-3-Option. |
| Druckqualität variiert je Partner | Testbestellungen bei jedem Partner vor Go-Live. Mehrere Partner = Fallback. |
| Druckereien ohne API (z.B. Printzessin) | ManualProvider: generiert PDF-Paket + CSV, Admin lädt manuell hoch |
| TWINT via Stripe nicht verfügbar | Fallback: Datatrans (Schweizer PSP) |
| Print-PDFs brauchen Originale | PDFs lokal generieren, nur fertige PDFs zu Cloud hochladen |
| Rechtliches (GmbH, AGB, nDSG) | Anwalt für Schweizer E-Commerce konsultieren vor Go-Live |
