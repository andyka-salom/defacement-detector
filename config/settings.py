"""
config/settings.py
Memuat seluruh konfigurasi dari file .env
Arsitektur: 1 VPS Ubuntu — Nginx + Python + PostgreSQL pada server yang sama.
Lokasi project: /var/www/defacement-detector
Log Nginx dibaca langsung dari sistem file lokal (tidak ada SSH).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Log Nginx (lokal, 1 server) ───────────────────────────────
LOG_PATH = os.getenv("LOG_PATH", "/var/log/nginx/hs_access.log")

# ── Target Website ────────────────────────────────────────────
TARGET_BASE_URL = os.getenv("TARGET_BASE_URL", "https://x.com")

# ── PostgreSQL ────────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = int(os.getenv("DB_PORT", 5432))
DB_NAME     = os.getenv("DB_NAME",     "defacement_db")
DB_USER     = os.getenv("DB_USER",     "deploy_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# ── Fonnte WhatsApp API ───────────────────────────────────────
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN", "")
WA_TARGET    = os.getenv("WA_TARGET", "")

# ── Deteksi ───────────────────────────────────────────────────
FLUSH_INTERVAL    = int(os.getenv("FLUSH_INTERVAL", 60))
CONTAMINATION     = float(os.getenv("CONTAMINATION", 0.10))
CONFIDENCE_MEDIUM = int(os.getenv("CONFIDENCE_MEDIUM", 50))
CONFIDENCE_HIGH   = int(os.getenv("CONFIDENCE_HIGH", 80))

# ── Flask Dashboard ───────────────────────────────────────────
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")
FLASK_HOST       = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT       = int(os.getenv("FLASK_PORT", 5000))
FLASK_DEBUG      = os.getenv("FLASK_DEBUG", "false").lower() == "true"

# ── Logging ───────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = os.getenv("LOG_FILE", "logs/system.log")
LOG_DIR   = "logs"

# ── Konstanta sistem ──────────────────────────────────────────
STATIC_EXT = (
    '.css', '.js', '.jpg', '.jpeg', '.png', '.gif',
    '.ico', '.woff', '.woff2', '.svg', '.pdf', '.zip',
    '.mp4', '.webp', '.ttf', '.eot', '.map',
)

BOT_KEYWORDS = [
    'googlebot', 'bingbot', 'duckduckbot', 'yandexbot',
    'baiduspider', 'facebookexternalhit', 'crawler',
    'spider', 'bot', 'slurp', 'teoma', 'archive.org_bot',
]

UA_NORMAL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

UA_BOT = "Googlebot/2.1 (+http://www.google.com/bot.html)"

DEFACEMENT_DICT = [
    "hacked", "defaced", "owned", "pwned", "r00ted", "h4ck3d",
    "hacker", "hacktivist", "greetz",
    "judi", "slot", "togel", "poker", "casino", "betting",
    "bandar", "taruhan", "gacor", "maxwin", "jackpot",
    "situs judi", "agen slot", "daftar slot",
    "pinjaman", "kredit cepat", "dana cepat",
    "viagra", "cialis", "obat kuat",
    "~~", "xXx", "l33t", "31337",
]

MODEL_DIR = "model"
DATA_DIR  = "data"
