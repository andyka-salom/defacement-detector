"""core/parser.py — Parsing Nginx access.log + analitik lengkap"""
import re
from datetime import datetime
from collections import defaultdict
import pandas as pd
from config.settings import STATIC_EXT, BOT_KEYWORDS
from config.logger import get_logger

logger = get_logger("parser")

LOG_PATTERN = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<url>\S+) \S+" '
    r'(?P<status>\d{3}) (?P<size>\S+) '
    r'"(?P<referrer>[^"]*)" "(?P<useragent>[^"]*)"'
)

def is_bot(ua: str) -> bool:
    ua_lower = ua.lower()
    return any(k in ua_lower for k in BOT_KEYWORDS)

def is_static(url: str) -> bool:
    return any(url.lower().split("?")[0].endswith(e) for e in STATIC_EXT)

def parse_time(time_str: str):
    try:
        return datetime.strptime(time_str.split()[0], "%d/%b/%Y:%H:%M:%S")
    except:
        return None

def parse_line(line: str) -> dict | None:
    m = LOG_PATTERN.match(line.strip())
    if not m: return None
    size = m.group("size")
    dt   = parse_time(m.group("time"))
    ua   = m.group("useragent")
    return {
        "ip":        m.group("ip"),
        "time":      dt,
        "time_str":  m.group("time").split()[0],
        "method":    m.group("method"),
        "url":       m.group("url").split("?")[0].rstrip("/") or "/",
        "url_full":  m.group("url"),
        "status":    int(m.group("status")),
        "size":      int(size) if size.isdigit() else 0,
        "referrer":  m.group("referrer"),
        "useragent": ua,
        "is_bot":    is_bot(ua),
        "is_static": is_static(m.group("url")),
    }

def parse_log(filepath: str) -> pd.DataFrame:
    records, errors = [], 0
    try:
        with open(filepath, errors="ignore") as f:
            for line in f:
                p = parse_line(line)
                if p: records.append(p)
                else: errors += 1
    except FileNotFoundError:
        logger.error(f"File log tidak ditemukan: {filepath}")
        return pd.DataFrame()
    df = pd.DataFrame(records)
    logger.info(f"Parse selesai: {len(df):,} entri valid, {errors:,} gagal")
    return df

def get_log_analytics(filepath: str) -> dict:
    """Hitung statistik lengkap dari file log untuk dashboard."""
    df = parse_log(filepath)
    if df.empty:
        return {"error": "Log kosong atau tidak ditemukan", "total": 0}

    total = len(df)
    # Hitung status code
    status_counts = df["status"].value_counts().to_dict()
    status_2xx = sum(v for k,v in status_counts.items() if 200 <= k < 300)
    status_3xx = sum(v for k,v in status_counts.items() if 300 <= k < 400)
    status_4xx = sum(v for k,v in status_counts.items() if 400 <= k < 500)
    status_5xx = sum(v for k,v in status_counts.items() if k >= 500)

    # Top URLs
    top_urls = (df[~df["is_static"]]["url"]
                .value_counts().head(10).reset_index()
                .rename(columns={"index":"url","url":"url","count":"count"})
                .to_dict("records"))
    # pandas 2.x value_counts returns Series with name=url
    top_urls = df[~df["is_static"]]["url"].value_counts().head(10)
    top_urls = [{"url": k, "count": int(v)} for k,v in top_urls.items()]

    # Top IPs
    top_ips = df["ip"].value_counts().head(10)
    top_ips = [{"ip": k, "count": int(v)} for k,v in top_ips.items()]

    # Bot vs normal
    bot_count    = int(df["is_bot"].sum())
    normal_count = total - bot_count

    # Traffic per hour (last 24h jika ada timestamp)
    hourly = {}
    if "time" in df.columns and df["time"].notna().any():
        df_t = df[df["time"].notna()].copy()
        df_t["hour"] = df_t["time"].dt.strftime("%H:00")
        hourly = df_t.groupby("hour").size().to_dict()

    # Top User Agents (non-bot singkat)
    ua_counts = df["useragent"].apply(lambda x: x[:60]).value_counts().head(5)
    top_ua = [{"ua": k[:60], "count": int(v)} for k,v in ua_counts.items()]

    # Bytes transferred
    total_bytes = int(df["size"].sum())

    # Recent entries (last 50)
    recent = df.tail(50)[["time_str","ip","method","url","status","size","useragent","is_bot"]].copy()
    recent["useragent"] = recent["useragent"].str[:80]
    recent = recent.fillna("-").to_dict("records")

    # Status breakdown
    status_detail = {}
    for code, cnt in status_counts.items():
        status_detail[str(code)] = int(cnt)

    # Methods
    method_counts = df["method"].value_counts().to_dict()
    method_counts = {k: int(v) for k,v in method_counts.items()}

    # Suspicious IPs (many 404/403)
    suspicious = (df[df["status"].isin([404,403,400,500])]
                  .groupby("ip").size()
                  .sort_values(ascending=False)
                  .head(5))
    suspicious_ips = [{"ip": k, "count": int(v)} for k,v in suspicious.items()]

    return {
        "total":          total,
        "status_2xx":     status_2xx,
        "status_3xx":     status_3xx,
        "status_4xx":     status_4xx,
        "status_5xx":     status_5xx,
        "bot_count":      bot_count,
        "normal_count":   normal_count,
        "total_bytes":    total_bytes,
        "total_mb":       round(total_bytes / 1024 / 1024, 2),
        "top_urls":       top_urls,
        "top_ips":        top_ips,
        "top_ua":         top_ua,
        "hourly":         hourly,
        "status_detail":  status_detail,
        "method_counts":  method_counts,
        "suspicious_ips": suspicious_ips,
        "recent":         recent,
        "error":          None,
    }

def engineer_features(df: pd.DataFrame, min_normal: int = 1, min_bot: int = 1) -> pd.DataFrame:
    df = df[(df["status"] == 200) & (~df["url"].apply(is_static))].copy()
    normal = (df[~df["is_bot"]].groupby("url")["size"]
              .agg(size_normal_mean="mean", size_normal_std="std", count_normal="count").reset_index())
    bot    = (df[df["is_bot"]].groupby("url")["size"]
              .agg(size_bot_mean="mean", size_bot_std="std", count_bot="count").reset_index())
    merged = pd.merge(normal, bot, on="url").fillna(0)
    merged = merged[(merged["count_normal"] >= min_normal) & (merged["count_bot"] >= min_bot)].copy()
    if merged.empty:
        return merged
    denom = merged["size_normal_mean"].replace(0, 1)
    merged["size_diff_abs"] = abs(merged["size_normal_mean"] - merged["size_bot_mean"])
    merged["size_ratio"]    = (merged["size_bot_mean"] / denom).round(4)
    merged["size_diff_pct"] = (merged["size_diff_abs"] / denom * 100).round(2)
    logger.info(f"Fitur dihasilkan untuk {len(merged)} URL")
    return merged
