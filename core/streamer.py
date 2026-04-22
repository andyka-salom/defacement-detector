"""
core/streamer.py
Streaming real-time log Nginx access.log secara lokal.

Arsitektur 1 VPS: Nginx dan sistem deteksi berjalan pada server
yang sama, sehingga log dibaca langsung dari sistem file lokal
menggunakan mekanisme tail -f (subprocess non-blocking).
Tidak ada SSH, tidak ada Paramiko.
"""
import os
import time
import subprocess
import threading
import pandas as pd
from collections import defaultdict
from config.settings import (
    LOG_PATH,
    FLUSH_INTERVAL,
    CONTAMINATION,
)
from config.logger import get_logger
from core.parser import parse_line, is_static
from core.detector import load_model, predict, train, FEATURES
from core.html_checker import check_similarity
from core.alerter import compute_confidence, send_whatsapp, should_alert
from core.storage import save_detection, init_db

logger = get_logger("streamer")

# Buffer global: url → list of {size, is_bot}
url_buffer: dict  = defaultdict(list)
buffer_lock       = threading.Lock()

# Status daemon
_running = False
_proc: subprocess.Popen | None = None
_stats = {
    "total_lines":    0,
    "total_analyzed": 0,
    "total_anomaly":  0,
    "total_alerts":   0,
    "last_flush":     "-",
}


# ── Flush & Analisis ──────────────────────────────────────────

def _flush_and_analyze():
    """
    Dipanggil setiap FLUSH_INTERVAL detik oleh background thread.
    Analisis buffer → Isolation Forest → confidence scoring → alert.
    """
    global _stats

    while _running:
        time.sleep(FLUSH_INTERVAL)
        if not _running:
            break

        with buffer_lock:
            snapshot = dict(url_buffer)
            url_buffer.clear()

        if not snapshot:
            logger.debug("Buffer kosong, skip flush")
            continue

        # Bangun DataFrame fitur dari buffer
        rows = []
        for url, entries in snapshot.items():
            if is_static(url):
                continue
            normal = [e["size"] for e in entries if not e["is_bot"]]
            bot    = [e["size"] for e in entries if     e["is_bot"]]
            if len(normal) < 1 or len(bot) < 1:
                continue

            n_mean = sum(normal) / len(normal)
            b_mean = sum(bot)    / len(bot)
            n_std  = pd.Series(normal).std() or 0
            b_std  = pd.Series(bot).std()    or 0
            diff   = abs(n_mean - b_mean)
            ratio  = b_mean / n_mean if n_mean > 0 else 1.0
            pct    = diff / n_mean * 100 if n_mean > 0 else 0

            rows.append({
                "url":              url,
                "size_normal_mean": n_mean,
                "size_bot_mean":    b_mean,
                "size_normal_std":  n_std,
                "size_bot_std":     b_std,
                "size_diff_abs":    diff,
                "size_ratio":       round(ratio, 4),
                "size_diff_pct":    round(pct, 2),
                "count_normal":     len(normal),
                "count_bot":        len(bot),
            })

        if not rows:
            continue

        df = pd.DataFrame(rows)
        _stats["total_analyzed"] += len(df)
        _stats["last_flush"] = pd.Timestamp.now().strftime("%H:%M:%S")

        # Load atau latih model
        try:
            model, scaler = load_model()
        except FileNotFoundError:
            logger.info("Model belum ada, latih dengan data buffer saat ini...")
            model, scaler = train(df, contamination=CONTAMINATION)

        df_result = predict(df, model, scaler)
        anomalies  = df_result[df_result["is_anomaly"]]
        _stats["total_anomaly"] += len(anomalies)

        logger.info(
            f"[FLUSH] {len(df)} URL dianalisis → {len(anomalies)} anomali"
        )

        # Proses setiap anomali
        for _, row in anomalies.iterrows():
            url_path = row["url"]

            # Analisis konten HTML (konfirmasi tambahan)
            html_detail = check_similarity(url_path)

            confidence, level = compute_confidence(
                anomaly_score = row["anomaly_score"],
                size_diff_pct = row["size_diff_pct"],
                size_ratio    = row["size_ratio"],
                cosine_sim    = html_detail["cosine_similarity"],
                dict_hits     = html_detail["dict_hit_count"],
            )

            notified = False
            if should_alert(level):
                notified = send_whatsapp(
                    url           = url_path,
                    confidence    = confidence,
                    level         = level,
                    anomaly_score = row["anomaly_score"],
                    size_normal   = html_detail["size_normal"],
                    size_bot      = html_detail["size_bot"],
                    size_diff_pct = html_detail["size_diff_pct"],
                    cosine_sim    = html_detail["cosine_similarity"],
                    dict_hits     = html_detail["dict_hits"],
                )
                if notified:
                    _stats["total_alerts"] += 1

            # Simpan ke database
            save_detection({
                **html_detail,
                "anomaly_score": row["anomaly_score"],
                "size_ratio":    row["size_ratio"],
                "confidence":    confidence,
                "level":         level,
                "notified":      notified,
            })

            logger.warning(
                f"[{level}] {url_path} | "
                f"IF={row['anomaly_score']:.4f} | "
                f"diff={row['size_diff_pct']:.1f}% | "
                f"cosine={html_detail['cosine_similarity']:.4f} | "
                f"conf={confidence} | alert={'✓' if notified else '✗'}"
            )


# ── Local File Streaming ──────────────────────────────────────

def _wait_for_log(path: str, timeout: int = 60) -> bool:
    """Tunggu hingga file log tersedia (Nginx mungkin belum buat file)."""
    waited = 0
    while not os.path.exists(path):
        if waited == 0:
            logger.warning(f"File log tidak ditemukan: {path} — menunggu...")
        time.sleep(5)
        waited += 5
        if waited >= timeout:
            logger.error(f"File log tidak muncul dalam {timeout}s: {path}")
            return False
    return True


def _stream_log():
    """
    Baca Nginx access.log lokal secara real-time menggunakan tail -f.
    Karena sistem berjalan di VPS yang sama dengan Nginx,
    tidak diperlukan koneksi jaringan atau library eksternal.
    """
    global _proc

    if not _wait_for_log(LOG_PATH):
        return

    logger.info(f"Membaca log lokal: {LOG_PATH}")

    # Pastikan user punya izin baca file log
    if not os.access(LOG_PATH, os.R_OK):
        logger.error(
            f"Tidak ada izin baca: {LOG_PATH}\n"
            "Solusi: sudo usermod -aG adm $USER  atau  "
            "sudo setfacl -m u:$USER:r /var/log/nginx/access.log"
        )
        return

    _proc = subprocess.Popen(
        ["tail", "-n", "0", "-F", LOG_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,          # line-buffered
    )
    logger.info(f"tail -F dimulai (PID {_proc.pid})")

    try:
        for raw_line in _proc.stdout:
            if not _running:
                break
            line = raw_line.strip()
            if not line:
                continue

            _stats["total_lines"] += 1
            parsed = parse_line(line)
            if not parsed or parsed["status"] != 200:
                continue

            with buffer_lock:
                url_buffer[parsed["url"]].append({
                    "size":   parsed["size"],
                    "is_bot": parsed["is_bot"],
                })
    finally:
        if _proc and _proc.poll() is None:
            _proc.terminate()
        _proc = None
        logger.info("Proses tail dihentikan")


# ── Public API ────────────────────────────────────────────────

def start():
    """Jalankan daemon streamer (blocking, dengan auto-restart)."""
    global _running
    _running = True

    init_db()

    # Background thread untuk analisis berkala
    flush_thread = threading.Thread(
        target=_flush_and_analyze, daemon=True, name="flush-analyzer"
    )
    flush_thread.start()
    logger.info(f"Flush analyzer dimulai (interval: {FLUSH_INTERVAL}s)")

    # Main loop dengan auto-restart jika tail gagal
    while _running:
        try:
            _stream_log()
        except KeyboardInterrupt:
            logger.info("Dihentikan oleh pengguna")
            break
        except Exception as e:
            logger.error(f"Error streaming log: {e}")
            logger.info("Restart dalam 15 detik...")
            time.sleep(15)

    _running = False
    logger.info("Streamer dihentikan")


def stop():
    """Hentikan daemon streamer."""
    global _running, _proc
    _running = False
    if _proc and _proc.poll() is None:
        _proc.terminate()


def get_stats() -> dict:
    """Return statistik runtime streamer."""
    return dict(_stats)
