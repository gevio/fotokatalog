# VM Local Setup - Schritt fuer Schritt

Diese Anleitung bildet die lokale Prototyp-Umgebung auf der VMWare-VM ab.

## 0) Git-Remote auf Windows setzen (einmalig)

Wenn lokal noch kein `origin` gesetzt ist, zuerst auf Windows/PowerShell ausfuehren:

```powershell
git -C "E:\DCIM\03_Privat\Best of Valais\_fotokatalog" remote add origin https://github.com/gevio/fotokatalog.git
git -C "E:\DCIM\03_Privat\Best of Valais\_fotokatalog" branch -M main
git -C "E:\DCIM\03_Privat\Best of Valais\_fotokatalog" push -u origin main
```

Pruefen:

```powershell
git -C "E:\DCIM\03_Privat\Best of Valais\_fotokatalog" remote -v
```

## 1) SSH und Projektordner auf VM

Auf Windows/PowerShell:

```powershell
ssh vm-claude
```

Auf der VM:

```bash
sudo mkdir -p /srv/fotokatalog
sudo chown -R claude-code:www-data /srv/fotokatalog
sudo chmod -R 775 /srv/fotokatalog
cd /srv
git clone https://github.com/gevio/fotokatalog.git fotokatalog
```

## 2) Python Umgebung

Falls `ensurepip is not available` erscheint, zuerst als `root` ausfuehren:

```bash
apt update
apt install -y python3-venv python3-pip
```

```bash
cd /srv/fotokatalog
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install exifread geopy Pillow reportlab anthropic pymysql
```

## 3) MariaDB auf der VM

Hinweis: Die aktuelle `webui.py` nutzt weiterhin SQLite. MariaDB wird hier als Ziel-DB vorbereitet,
aber fuer den sofortigen Start der bestehenden WebUI wird zusaetzlich `/srv/fotokatalog/fotokatalog.db` benoetigt.

Installation (Debian/Ubuntu):

```bash
sudo apt update
sudo apt install -y mariadb-server
sudo systemctl enable mariadb
sudo systemctl start mariadb
```

DB/User anlegen:

```bash
sudo mysql < /srv/fotokatalog/ops/vm/mariadb/01_init_fotokatalog.sql
```

Dann Passwort hart setzen:

```bash
sudo mysql -e "ALTER USER 'fotokatalog'@'localhost' IDENTIFIED BY 'SET_STRONG_PASSWORD_HERE';"
```

Falls die SQLite-Datei auf der VM noch fehlt, minimal initialisieren:

```bash
cd /srv/fotokatalog
sqlite3 fotokatalog.db < schema.sql
```

## 4) App-Env Datei

```bash
sudo mkdir -p /etc/fotokatalog
sudo cp /srv/fotokatalog/ops/vm/env/fotokatalog.env.example /etc/fotokatalog/fotokatalog.env
sudo chown root:www-data /etc/fotokatalog/fotokatalog.env
sudo chmod 640 /etc/fotokatalog/fotokatalog.env
sudo nano /etc/fotokatalog/fotokatalog.env
```

Werte anpassen:
- FOTOKATALOG_DB_BACKEND=sqlite
- FOTOKATALOG_DB_PASSWORD
- ANTHROPIC_API_KEY

## 5) systemd Service

```bash
sudo cp /srv/fotokatalog/ops/vm/systemd/fotokatalog.service /etc/systemd/system/fotokatalog.service
sudo systemctl daemon-reload
sudo systemctl enable fotokatalog
sudo systemctl start fotokatalog
sudo systemctl status fotokatalog --no-pager
```

## 6) Nginx Reverse Proxy

```bash
sudo apt install -y nginx
sudo cp /srv/fotokatalog/ops/vm/nginx/fotokatalog.dev.local.conf /etc/nginx/sites-available/fotokatalog.dev.local
sudo ln -s /etc/nginx/sites-available/fotokatalog.dev.local /etc/nginx/sites-enabled/fotokatalog.dev.local
sudo nginx -t
sudo systemctl reload nginx
```

## 7) Windows hosts (bereits gesetzt)

`192.168.28.130 fotokatalog.dev.local`

Test:

```powershell
ping fotokatalog.dev.local
```

## 8) Zugriff pruefen

Im Browser auf Windows:
- http://fotokatalog.dev.local/

Hinweis zu `curl`-Tests:
- Bei `curl ... | head -n 5` oder `head -n 10` kann `curl: (23) Failure writing output to destination` erscheinen.
- Das ist in diesem Kontext normal, weil `head` die Pipe frueh schliesst. Kein Fehler der Anwendung.

Hinweis zum DB-Backend:
- `webui.py` startet standardmaessig mit SQLite (`--db-backend sqlite`).
- Der Schalter `--db-backend mariadb` ist jetzt als optionaler Testpfad verfuegbar (PyMySQL erforderlich).
- Dadurch bleibt der lokale Windows-Start unveraendert kompatibel.

Logs bei Problemen:

```bash
sudo journalctl -u fotokatalog -n 100 --no-pager
sudo tail -n 100 /var/log/nginx/fotokatalog_error.log
```

## 9) HeidiSQL via SSH Tunnel

HeidiSQL Session:
- Network type: MariaDB or MySQL (TCP/IP)
- Hostname/IP: 127.0.0.1
- Port: 3397 (entsprechend SSH LocalForward)
- User: fotokatalog
- Password: aus /etc/fotokatalog/fotokatalog.env

SSH:
- Host: 192.168.28.130
- User: claude-code
- Private key: ~/.ssh/claude_code_vm

Hinweis:
- Kein DB-Port in Firewall oeffnen.
- Zugriff nur via SSH Tunnel.
