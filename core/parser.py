"""
core/parser.py
Parsing Nginx access.log (Combined Log Format) dan rekayasa fitur
berbasis perbedaan response size antara akses normal dan bot.

Format log Nginx (Combined):
  $remote_addr - $remote_user [$time_local] "$request"
  $status $body_bytes_sent "$http_referer" "$http_user_agent"
"""
import re
import pandas as pd
import numpy as np
from config.settings import STATIC_EXT, BOT_KEYWORDS
from config.logger import get_logger

logger = get_logger("parser")

# Pola regex Combined Log Format — identik antara Nginx dan Apache CLF
LOG_PATTERN = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<url>\S+) \S+" '
    r'(?P<status>\d{3}) (?P<size>\S+) '
    r'"(?P<referrer>[^"]*)" "(?P<useragent>[^"]*)"'
)


def is_bot(ua: str) -> bool:
    """Deteksi apakah user-agent adalah bot mesin pencari."""
    ua_lower = ua.lower()
    return any(k in ua_lower for k in BOT_KEYWORDS)


def is_static(url: str) -> bool:
    """Filter URL resource statis yang tidak relevan dianalisis."""
    return any(url.lower().split("?")[0].endswith(e) for e in STATIC_EXT)


def parse_line(line: str) -> dict | None:
    """
    Parse satu baris log Nginx → dict atribut.
    Return None jika format tidak cocok.
    """
    m = LOG_PATTERN.match(line.strip())
    if not m:
        return None
    size = m.group("size")
    return {
        "ip":        m.group("ip"),
        "url":       m.group("url").split("?")[0].rstrip("/") or "/",
        "status":    int(m.group("status")),
        "size":      int(size) if size.isdigit() else 0,
        "useragent": m.group("useragent"),
        "is_bot":    is_bot(m.group("useragent")),
    }


def parse_log(filepath: str) -> pd.DataFrame:
    """
    Parse seluruh file Nginx access.log → DataFrame.
    Digunakan untuk training model dari data historis.
    """
    records = []
    errors  = 0
    with open(filepath, errors="ignore") as f:
        for line in f:
            parsed = parse_line(line)
            if parsed:
                records.append(parsed)
            else:
                errors += 1

    df = pd.DataFrame(records)
    logger.info(f"Parse selesai: {len(df):,} entri valid, {errors:,} baris gagal")
    return df


def engineer_features(df: pd.DataFrame, min_normal: int = 3, min_bot: int = 2) -> pd.DataFrame:
    """
    Rekayasa fitur utama:
    Hitung perbedaan response size antara akses normal dan bot per URL.

    Fitur yang dihasilkan:
    - size_diff_abs  : selisih absolut rata-rata response size (byte)
    - size_ratio     : rasio size_bot / size_normal
    - size_diff_pct  : persentase selisih terhadap size_normal
    - size_normal_std: standar deviasi size akses normal
    - size_bot_std   : standar deviasi size akses bot
    """
    # Filter: status 200, bukan resource statis
    df = df[(df["status"] == 200) & (~df["url"].apply(is_static))].copy()

    # Agregasi per URL
    normal = (
        df[~df["is_bot"]]
        .groupby("url")["size"]
        .agg(size_normal_mean="mean", size_normal_std="std", count_normal="count")
        .reset_index()
    )
    bot = (
        df[df["is_bot"]]
        .groupby("url")["size"]
        .agg(size_bot_mean="mean", size_bot_std="std", count_bot="count")
        .reset_index()
    )

    merged = pd.merge(normal, bot, on="url").fillna(0)
    # Hanya URL dengan data yang representatif
    merged = merged[
        (merged["count_normal"] >= min_normal) &
        (merged["count_bot"]    >= min_bot)
    ].copy()

    if merged.empty:
        logger.warning("Tidak ada URL yang memenuhi syarat minimum akses normal & bot")
        return merged

    # Fitur turunan
    denom = merged["size_normal_mean"].replace(0, 1)
    merged["size_diff_abs"] = abs(merged["size_normal_mean"] - merged["size_bot_mean"])
    merged["size_ratio"]    = (merged["size_bot_mean"] / denom).round(4)
    merged["size_diff_pct"] = (merged["size_diff_abs"] / denom * 100).round(2)

    logger.info(f"Fitur dihasilkan untuk {len(merged)} URL")
    return merged
