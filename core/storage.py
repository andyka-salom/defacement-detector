"""
core/storage.py
Penyimpanan riwayat deteksi menggunakan PostgreSQL.
Menggunakan psycopg2 dengan connection pooling (ThreadedConnectionPool)
agar aman diakses oleh streamer thread dan Flask thread secara bersamaan.
"""
import json
from datetime import datetime
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from config.settings import (
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
)
from config.logger import get_logger

logger = get_logger("storage")

# Connection pool: min 2, max 10 koneksi
_pool: pool.ThreadedConnectionPool | None = None


def _get_pool() -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=10,
        )
        logger.debug("Connection pool PostgreSQL dibuat")
    return _pool


@contextmanager
def _conn():
    """Context manager: ambil koneksi dari pool, kembalikan setelah selesai."""
    p = _get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


# ── DDL ──────────────────────────────────────────────────────

def init_db():
    """Buat tabel jika belum ada (idempotent)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS detections (
                    id              SERIAL PRIMARY KEY,
                    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    url             TEXT        NOT NULL,
                    anomaly_score   DOUBLE PRECISION,
                    size_normal     INTEGER,
                    size_bot        INTEGER,
                    size_diff_pct   DOUBLE PRECISION,
                    size_ratio      DOUBLE PRECISION,
                    cosine_sim      DOUBLE PRECISION,
                    dict_hits       JSONB,
                    dict_hit_count  INTEGER,
                    confidence      INTEGER,
                    level           TEXT,
                    notified        BOOLEAN     DEFAULT FALSE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS system_stats (
                    id            SERIAL PRIMARY KEY,
                    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    total_parsed  INTEGER,
                    total_anomaly INTEGER,
                    model_version TEXT
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_detections_detected_at
                ON detections (detected_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_detections_level
                ON detections (level)
            """)
    logger.info("Database PostgreSQL diinisialisasi")


# ── DML ──────────────────────────────────────────────────────

def save_detection(data: dict) -> int:
    """Simpan satu hasil deteksi ke PostgreSQL. Return ID record."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO detections
                    (detected_at, url, anomaly_score, size_normal, size_bot,
                     size_diff_pct, size_ratio, cosine_sim, dict_hits,
                     dict_hit_count, confidence, level, notified)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                datetime.now(),
                data.get("url", ""),
                data.get("anomaly_score", 0),
                data.get("size_normal", 0),
                data.get("size_bot", 0),
                data.get("size_diff_pct", 0),
                data.get("size_ratio", 0),
                data.get("cosine_sim", 1.0),
                json.dumps(data.get("dict_hits", [])),
                data.get("dict_hit_count", 0),
                data.get("confidence", 0),
                data.get("level", "LOW"),
                bool(data.get("notified", False)),
            ))
            row_id = cur.fetchone()[0]
    logger.debug(f"Deteksi disimpan: id={row_id} url={data.get('url')} level={data.get('level')}")
    return row_id


def get_recent_detections(limit: int = 100) -> list:
    """Ambil riwayat deteksi terbaru."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    id, detected_at, url, anomaly_score,
                    size_normal, size_bot, size_diff_pct, size_ratio,
                    cosine_sim, dict_hits, dict_hit_count,
                    confidence, level, notified
                FROM detections
                ORDER BY detected_at DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

    result = []
    for r in rows:
        row = dict(r)
        if isinstance(row.get("dict_hits"), str):
            try:
                row["dict_hits"] = json.loads(row["dict_hits"])
            except Exception:
                row["dict_hits"] = []
        row["dict_hits"] = row["dict_hits"] or []
        if hasattr(row["detected_at"], "strftime"):
            row["detected_at"] = row["detected_at"].strftime("%Y-%m-%d %H:%M:%S")
        result.append(row)
    return result


def get_stats() -> dict:
    """Ambil statistik ringkasan dari database."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM detections")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM detections WHERE level = 'HIGH'")
            high = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM detections WHERE level = 'MEDIUM'")
            medium = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM detections WHERE level = 'LOW'")
            low = cur.fetchone()[0]
            cur.execute(
                "SELECT detected_at FROM detections ORDER BY detected_at DESC LIMIT 1"
            )
            last = cur.fetchone()

    last_str = "-"
    if last:
        last_str = (
            last[0].strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(last[0], "strftime")
            else str(last[0])
        )

    return {
        "total":          total,
        "high":           high,
        "medium":         medium,
        "low":            low,
        "last_detection": last_str,
    }


def close_pool():
    """Tutup semua koneksi pool (panggil saat shutdown)."""
    global _pool
    if _pool and not _pool.closed:
        _pool.closeall()
        logger.info("Connection pool PostgreSQL ditutup")
