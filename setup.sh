#!/bin/bash
# setup.sh — Setup otomatis sistem deteksi web defacement
# Arsitektur: 1 VPS Ubuntu — Nginx + Python + PostgreSQL
# Jalankan: bash setup.sh

set -e

echo "╔══════════════════════════════════════════════════════╗"
echo "║   SETUP SISTEM DETEKSI WEB DEFACEMENT                ║"
echo "║   1 VPS Ubuntu — Nginx + Python + PostgreSQL         ║"
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
echo "      ✓ Dependencies terinstall (termasuk psycopg2-binary)"

# 4. Buat folder yang diperlukan
echo "[4/8] Membuat folder..."
mkdir -p data model logs
echo "      ✓ Folder data/, model/, logs/ siap"

# 5. Izin baca Nginx access.log
echo "[5/8] Mengatur izin baca file log Nginx..."
CURRENT_USER=$(whoami)
if groups "$CURRENT_USER" | grep -q '\badm\b'; then
    echo "      ✓ User '$CURRENT_USER' sudah ada di grup 'adm'"
else
    echo "      ⚠️  Menambahkan user '$CURRENT_USER' ke grup 'adm'..."
    sudo usermod -aG adm "$CURRENT_USER"
    echo "      ✓ Selesai. PENTING: Re-login agar grup berlaku (atau: newgrp adm)"
fi

# 6. Cek & setup PostgreSQL
echo "[6/8] Mengecek PostgreSQL..."
if ! command -v psql &> /dev/null; then
    echo "      ⚠️  psql tidak ditemukan. Install: sudo apt install postgresql postgresql-client"
else
    echo "      ✓ PostgreSQL client tersedia"
fi

# 7. Salin .env
echo "[7/8] Menyiapkan konfigurasi..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "      ✓ File .env dibuat dari .env.example"
    echo "      ⚠️  PENTING: Edit file .env sebelum menjalankan sistem!"
    echo "        nano .env"
else
    echo "      ✓ File .env sudah ada"
fi

# 8. Generate data sintetis
echo "[8/8] Generate data sintetis untuk pengujian..."
python3 scripts/generate_synthetic_log.py

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   SETUP SELESAI                                      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Langkah selanjutnya:"
echo ""
echo "  1. Buat database PostgreSQL:"
echo "     sudo -u postgres createdb defacement_db"
echo "     sudo -u postgres psql -c \"ALTER USER postgres PASSWORD 'password_anda';\""
echo ""
echo "  2. Edit file .env:"
echo "     nano .env"
echo "     (isi DB_PASSWORD, FONNTE_TOKEN, WA_TARGET, TARGET_BASE_URL)"
echo ""
echo "  3. Latih model dari data historis Nginx:"
echo "     sudo cp /var/log/nginx/access.log data/"
echo "     source venv/bin/activate"
echo "     python main.py --train"
echo ""
echo "  4. Uji notifikasi WhatsApp:"
echo "     python main.py --test-alert"
echo ""
echo "  5. Jalankan sistem (stream + dashboard):"
echo "     python main.py --all"
echo ""
echo "  6. Atau pasang sebagai systemd service (production):"
echo "     sudo cp defacement-detector.service /etc/systemd/system/"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable --now defacement-detector"
echo "     sudo systemctl status defacement-detector"
echo ""
echo "  7. Akses dashboard di:"
echo "     http://IP_VPS_ANDA:5000"
echo ""
