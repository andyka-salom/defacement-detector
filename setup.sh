#!/bin/bash
# setup.sh — Setup otomatis sistem deteksi web defacement
# Lokasi project: /var/www/defacement-detector
# User: deploy_user | Log: /var/log/nginx/hs_access.log
# Jalankan: bash setup.sh

set -e

PROJ_DIR="/var/www/defacement-detector"
LOG_FILE="/var/log/nginx/hs_access.log"
DB_USER="deploy_user"
DB_NAME="defacement_db"

echo "╔══════════════════════════════════════════════════════╗"
echo "║   SETUP SISTEM DETEKSI WEB DEFACEMENT                ║"
echo "║   /var/www/defacement-detector                       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 1. Cek Python
echo "[1/8] Mengecek Python..."
python3 --version || { echo "ERROR: Python 3 tidak ditemukan"; exit 1; }

# 2. Buat virtualenv
echo "[2/8] Membuat virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
echo "[3/8] Menginstall dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "      ✓ Dependencies terinstall"

# 4. Buat folder yang diperlukan
echo "[4/8] Membuat folder..."
mkdir -p data model logs
echo "      ✓ Folder data/, model/, logs/ siap"

# 5. Izin baca log Nginx hs_access.log
echo "[5/8] Mengatur izin baca file log Nginx..."
CURRENT_USER=$(whoami)
if groups "$CURRENT_USER" | grep -q '\badm\b'; then
    echo "      ✓ User '$CURRENT_USER' sudah ada di grup 'adm'"
else
    echo "      ⚠️  Menambahkan user '$CURRENT_USER' ke grup 'adm'..."
    sudo usermod -aG adm "$CURRENT_USER"
    echo "      ✓ Selesai. PENTING: Re-login agar grup berlaku (newgrp adm)"
fi

# Verifikasi file log ada dan bisa dibaca
if [ -f "$LOG_FILE" ]; then
    echo "      ✓ File log ditemukan: $LOG_FILE"
else
    echo "      ⚠️  File log belum ada: $LOG_FILE"
    echo "         Pastikan Nginx sudah berjalan dan log dikonfigurasi dengan nama hs_access.log"
fi

# 6. Cek PostgreSQL
echo "[6/8] Mengecek PostgreSQL..."
if ! command -v psql &> /dev/null; then
    echo "      ⚠️  psql tidak ditemukan. Install: sudo apt install postgresql postgresql-client"
else
    echo "      ✓ PostgreSQL client tersedia"
    # Cek apakah user deploy_user dan database sudah ada
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
        echo "      ✓ PostgreSQL user '$DB_USER' sudah ada"
    else
        echo "      ⚠️  User '$DB_USER' belum ada — buat manual (lihat instruksi di bawah)"
    fi
fi

# 7. Salin .env
echo "[7/8] Menyiapkan konfigurasi..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "      ✓ File .env dibuat dari .env.example"
    echo "      ⚠️  PENTING: Edit file .env sebelum menjalankan sistem!"
    echo "         nano .env"
else
    echo "      ✓ File .env sudah ada"
fi

# 8. Generate data sintetis
echo "[8/8] Generate data sintetis untuk pengujian awal..."
python3 scripts/generate_synthetic_log.py

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   SETUP SELESAI                                      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Langkah selanjutnya:"
echo ""
echo "  1. Setup PostgreSQL (jika belum):"
echo "     sudo -u postgres psql"
echo "     CREATE USER deploy_user WITH PASSWORD 'password_anda_170401@';"
echo "     CREATE DATABASE defacement_db OWNER deploy_user;"
echo "     GRANT ALL PRIVILEGES ON DATABASE defacement_db TO deploy_user;"
echo "     \q"
echo ""
echo "  2. Edit file .env (isi FONNTE_TOKEN, WA_TARGET, FLASK_SECRET_KEY):"
echo "     nano .env"
echo ""
echo "  3. Salin log Nginx historis untuk training:"
echo "     sudo cp /var/log/nginx/hs_access.log data/"
echo "     sudo chmod 644 data/hs_access.log"
echo "     mv data/hs_access.log data/access.log"
echo ""
echo "  4. Latih model Isolation Forest:"
echo "     source venv/bin/activate"
echo "     python main.py --train"
echo ""
echo "  5. Uji notifikasi WhatsApp:"
echo "     python main.py --test-alert"
echo ""
echo "  6. Jalankan sistem (stream + dashboard):"
echo "     python main.py --all"
echo ""
echo "  7. Pasang sebagai systemd service:"
echo "     sudo cp defacement-detector.service /etc/systemd/system/"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable --now defacement-detector"
echo "     sudo systemctl status defacement-detector"
echo ""
echo "  8. Akses dashboard:"
echo "     http://IP_VPS_ANDA:5000"
echo ""
