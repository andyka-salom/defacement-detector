"""
core/alerter.py
Confidence scoring dan pengiriman notifikasi WhatsApp via Fonnte API.
"""
import requests
from datetime import datetime
from config.settings import (
    FONNTE_TOKEN, WA_TARGET,
    CONFIDENCE_MEDIUM, CONFIDENCE_HIGH,
    TARGET_BASE_URL,
)
from config.logger import get_logger

logger = get_logger("alerter")

FONNTE_URL = "https://api.fonnte.com/send"


# ── Confidence Scoring ────────────────────────────────────────

def compute_confidence(
    anomaly_score: float,
    size_diff_pct: float,
    size_ratio: float,
    cosine_sim: float = 1.0,
    dict_hits: int = 0,
) -> tuple[int, str]:
    """
    Hitung confidence score (0–100) dan level (LOW/MEDIUM/HIGH)
    berdasarkan 5 indikator.

    Returns: (score, level)
    """
    score = 0

    # Indikator 1: Isolation Forest anomaly score
    if   anomaly_score < -0.15: score += 40
    elif anomaly_score < -0.05: score += 20

    # Indikator 2: Persentase perbedaan response size
    if   size_diff_pct > 80: score += 40
    elif size_diff_pct > 40: score += 20
    elif size_diff_pct > 20: score += 10

    # Indikator 3: Rasio size bot/normal
    if   size_ratio > 2.5 or size_ratio < 0.40: score += 20
    elif size_ratio > 1.8 or size_ratio < 0.60: score += 10

    # Indikator 4: Cosine similarity konten HTML
    if   cosine_sim < 0.70: score += 40
    elif cosine_sim < 0.85: score += 20

    # Indikator 5: Dictionary defacement hit
    if   dict_hits >= 3: score += 20
    elif dict_hits >= 1: score += 10

    score = min(score, 100)

    if   score >= CONFIDENCE_HIGH:   level = "HIGH"
    elif score >= CONFIDENCE_MEDIUM: level = "MEDIUM"
    else:                            level = "LOW"

    return score, level


# ── WhatsApp Notification ─────────────────────────────────────

def _build_message(
    url: str,
    confidence: int,
    level: str,
    anomaly_score: float,
    size_normal: int,
    size_bot: int,
    size_diff_pct: float,
    cosine_sim: float,
    dict_hits: list,
) -> str:
    emoji   = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(level, "⚪")
    now     = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    base    = TARGET_BASE_URL.rstrip("/")
    hits_str = (
        ", ".join(dict_hits[:5]) + ("..." if len(dict_hits) > 5 else "")
    ) if dict_hits else "Tidak ada"

    return (
        f"{emoji} *ALERT WEB DEFACEMENT*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Waktu  : {now}\n"
        f"🌐 URL    : {base}{url}\n"
        f"⚠️  Level  : *{level}* ({confidence}/100)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Indikator Deteksi:*\n"
        f"• IF Anomaly Score : {anomaly_score:.4f}\n"
        f"• Size Normal      : {size_normal:,} byte\n"
        f"• Size Bot         : {size_bot:,} byte\n"
        f"• Selisih Size     : {size_diff_pct:.1f}%\n"
        f"• Cosine Similarity: {cosine_sim:.4f}\n"
        f"• Dictionary Hits  : {hits_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Segera periksa halaman web!"
    )


def send_whatsapp(
    url: str,
    confidence: int,
    level: str,
    anomaly_score: float,
    size_normal: int,
    size_bot: int,
    size_diff_pct: float,
    cosine_sim: float = 1.0,
    dict_hits: list = None,
) -> bool:
    """
    Kirim notifikasi WhatsApp via Fonnte API.
    Return True jika berhasil.
    """
    if not FONNTE_TOKEN or not WA_TARGET:
        logger.warning("FONNTE_TOKEN atau WA_TARGET belum dikonfigurasi di .env")
        return False

    message = _build_message(
        url=url, confidence=confidence, level=level,
        anomaly_score=anomaly_score,
        size_normal=size_normal, size_bot=size_bot,
        size_diff_pct=size_diff_pct, cosine_sim=cosine_sim,
        dict_hits=dict_hits or [],
    )

    try:
        resp = requests.post(
            FONNTE_URL,
            headers={"Authorization": FONNTE_TOKEN},
            data={"target": WA_TARGET, "message": message},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info(f"Notifikasi WA terkirim → {WA_TARGET} | {url} [{level}]")
            return True
        else:
            logger.error(f"Fonnte error {resp.status_code}: {resp.text[:200]}")
            return False
    except requests.RequestException as e:
        logger.error(f"Gagal kirim notifikasi WA: {e}")
        return False


def should_alert(level: str) -> bool:
    """Apakah level ini perlu dikirim notifikasi?"""
    return level in ("MEDIUM", "HIGH")
