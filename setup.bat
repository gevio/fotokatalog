@echo off
REM ============================================================
REM FOTOKATALOG - Windows Setup & Start
REM ============================================================
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║       FOTOKATALOG - Setup                ║
echo  ╚══════════════════════════════════════════╝
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ❌ Python nicht gefunden!
    echo     Bitte installiere Python 3 von https://python.org
    pause
    exit /b 1
)

echo  ✅ Python gefunden
python --version

REM Install dependencies
echo.
echo  📦 Installiere Abhängigkeiten...
pip install exifread geopy Pillow --quiet
if errorlevel 1 (
    echo  ⚠  Fehler bei der Installation. Versuche mit --user...
    pip install exifread geopy Pillow --user --quiet
)

echo  ✅ Abhängigkeiten installiert
echo.
echo  ════════════════════════════════════════════
echo  Setup abgeschlossen!
echo.
echo  SNAPSEED-IMPORT (empfohlen):
echo    python katalog.py "E:\DCIM\03_Privat\Best of Valais\Snapseed" --originals "E:\DCIM\03_Privat\Best of Valais\Originale"
echo.
echo  NORMALER IMPORT (Fotos mit EXIF):
echo    python katalog.py "E:\DCIM\03_Privat"
echo.
echo  Optionen:
echo    --originals PFAD   Originale-Ordner (EXIF-Uebertragung)
echo    --db PFAD          Datenbank-Pfad (Standard: fotokatalog.db)
echo    --no-geocode       Ohne Reverse Geocoding (schneller)
echo  ════════════════════════════════════════════
pause
