"""
main.py
Entry point utama sistem deteksi web defacement.
Arsitektur: 1 VPS Ubuntu — Nginx + Python + PostgreSQL (log dibaca lokal).

Penggunaan:
  python main.py --train        # Latih model dari data historis
  python main.py --stream       # Streaming log real-time (daemon)
  python main.py --dashboard    # Jalankan dashboard saja
  python main.py --all          # Stream + dashboard (production)
  python main.py --test-alert   # Uji pengiriman notifikasi WhatsApp
"""
import argparse
import threading
import sys
import os
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.logger import get_logger
from core.storage import init_db, close_pool

logger = get_logger("main")


def _on_shutdown(signum, frame):
    logger.info("Sinyal shutdown diterima, menutup koneksi database...")
    close_pool()
    sys.exit(0)


signal.signal(signal.SIGTERM, _on_shutdown)
signal.signal(signal.SIGINT,  _on_shutdown)


def cmd_train():
    """Latih model Isolation Forest dari data historis (Nginx access.log)."""
    import glob
    from core.parser import parse_log, engineer_features
    from core.detector import train
    import pandas as pd

    log_files = glob.glob("data/*.log") + glob.glob("data/access.log")
    if not log_files:
        logger.error("Tidak ada file .log di folder data/")
        logger.info(
            "Letakkan file Nginx access.log di folder data/ lalu jalankan ulang.\n"
            "Contoh: sudo cp /var/log/nginx/access.log data/"
        )
        sys.exit(1)

    dfs = []
    for f in log_files:
        logger.info(f"Membaca: {f}")
        dfs.append(parse_log(f))

    df_raw  = pd.concat(dfs, ignore_index=True)
    df_feat = engineer_features(df_raw)

    if df_feat.empty:
        logger.error("Tidak cukup data untuk melatih model (perlu akses normal & bot)")
        sys.exit(1)

    model, scaler = train(df_feat)
    logger.info(f"✓ Model berhasil dilatih dari {len(df_feat)} URL")
    logger.info("Jalankan 'python main.py --stream' untuk memulai monitoring")


def cmd_stream():
    """Jalankan streaming log real-time dari Nginx access.log lokal."""
    from core.streamer import start
    logger.info("Memulai streaming log Nginx (lokal)...")
    logger.info("Tekan Ctrl+C untuk menghentikan")
    start()


def cmd_dashboard():
    """Jalankan dashboard Flask saja."""
    from dashboard.app import run_dashboard
    from config.settings import FLASK_HOST, FLASK_PORT
    logger.info(f"Dashboard berjalan di http://{FLASK_HOST}:{FLASK_PORT}")
    run_dashboard()


def cmd_all():
    """Jalankan streaming + dashboard secara bersamaan (production)."""
    from core.streamer import start as start_stream
    from dashboard.app import run_dashboard
    from config.settings import FLASK_HOST, FLASK_PORT

    t_dash = threading.Thread(
        target=run_dashboard,
        daemon=True,
        name="dashboard",
    )
    t_dash.start()
    logger.info(f"Dashboard aktif di http://{FLASK_HOST}:{FLASK_PORT}")

    logger.info("Streaming log Nginx dimulai...")
    start_stream()


def cmd_test_alert():
    """Kirim pesan WhatsApp uji coba ke nomor yang dikonfigurasi."""
    from core.alerter import send_whatsapp
    logger.info("Mengirim test alert ke WhatsApp...")
    result = send_whatsapp(
        url           = "/test-halaman",
        confidence    = 75,
        level         = "MEDIUM",
        anomaly_score = -0.62,
        size_normal   = 25000,
        size_bot      = 45000,
        size_diff_pct = 80.0,
        cosine_sim    = 0.65,
        dict_hits     = ["hacked", "judi", "slot"],
    )
    if result:
        logger.info("✓ Test alert berhasil dikirim!")
    else:
        logger.error("✗ Gagal kirim alert. Periksa FONNTE_TOKEN dan WA_TARGET di .env")


def main():
    parser = argparse.ArgumentParser(
        description="Sistem Deteksi Dini Web Defacement — 1 VPS Ubuntu (Nginx + PostgreSQL)"
    )
    parser.add_argument("--train",      action="store_true", help="Latih model dari data historis")
    parser.add_argument("--stream",     action="store_true", help="Streaming log Nginx real-time")
    parser.add_argument("--dashboard",  action="store_true", help="Jalankan dashboard saja")
    parser.add_argument("--all",        action="store_true", help="Stream + dashboard (production)")
    parser.add_argument("--test-alert", action="store_true", help="Uji notifikasi WhatsApp")
    args = parser.parse_args()

    init_db()

    if   args.train:      cmd_train()
    elif args.stream:     cmd_stream()
    elif args.dashboard:  cmd_dashboard()
    elif args.all:        cmd_all()
    elif args.test_alert: cmd_test_alert()
    else:
        parser.print_help()
        print("\n💡 Untuk memulai: python main.py --all")

    close_pool()


if __name__ == "__main__":
    main()
