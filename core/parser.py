"""
core/parser.py
Parser Nginx access.log dengan analitik komprehensif:
- Parsing Combined Log Format
- Klasifikasi bot, scanner, crawler
- Threat scoring per IP
- Tren trafik per jam
- Top referrers, status distribution
"""
import re
import os
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
from config.settings import STATIC_EXT, BOT_KEYWORDS
from config.logger import get_logger

logger = get_logger("parser")

# ── Regex Pattern ─────────────────────────────────────────────
LOG_PATTERN = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<url>\S+) \S+" '
    r'(?P<status>\d{3}) (?P<size>\S+) '
    r'"(?P<referrer>[^"]*)" "(?P<useragent>[^"]*)"'
)

# ── Klasifikasi ───────────────────────────────────────────────
SCANNER_PATTERNS = [
    'sqlmap', 'nikto', 'nmap', 'masscan', 'zgrab', 'nuclei',
    'acunetix', 'nessus', 'openvas', 'burpsuite', 'metasploit',
    'dirbuster', 'gobuster', 'wfuzz', 'hydra', 'medusa',
]

SUSPICIOUS_PATHS = [
    '/.env', '/.git', '/wp-admin', '/wp-login', '/xmlrpc',
    '/admin', '/phpmyadmin', '/shell', '/backdoor', '/cmd',
    '/config', '/setup.php', '/install.php', '/eval',
    '/../', '/etc/passwd', '/proc/self', '/bin/sh',
]

SEARCH_BOTS = ['googlebot', 'bingbot', 'duckduckbot', 'yandexbot',
               'baiduspider', 'facebookexternalhit', 'twitterbot',
               'linkedinbot', 'applebot', 'sogou']

MONITOR_BOTS = ['uptimerobot', 'pingdom', 'statuscake', 'freshping',
                'hetrixtools', 'monitis', 'site24x7']


def classify_agent(ua: str) -> str:
    """Klasifikasi user agent: human | search_bot | monitor | scanner | crawler"""
    ua_low = ua.lower()
    if any(s in ua_low for s in SCANNER_PATTERNS):
        return 'scanner'
    if any(b in ua_low for b in SEARCH_BOTS):
        return 'search_bot'
    if any(m in ua_low for m in MONITOR_BOTS):
        return 'monitor'
    if any(k in ua_low for k in ['bot', 'crawler', 'spider', 'scraper', 'fetch']):
        return 'crawler'
    return 'human'


def is_bot(ua: str) -> bool:
    ua_lower = ua.lower()
    return any(k in ua_lower for k in BOT_KEYWORDS)


def is_static(url: str) -> bool:
    return any(url.lower().split("?")[0].endswith(e) for e in STATIC_EXT)


def is_suspicious_path(url: str) -> bool:
    url_low = url.lower()
    return any(p in url_low for p in SUSPICIOUS_PATHS)


def parse_time(time_str: str) -> datetime | None:
    try:
        return datetime.strptime(time_str.split()[0], "%d/%b/%Y:%H:%M:%S")
    except Exception:
        return None


def parse_line(line: str) -> dict | None:
    m = LOG_PATTERN.match(line.strip())
    if not m:
        return None
    size   = m.group("size")
    ua     = m.group("useragent")
    url    = m.group("url")
    url_clean = url.split("?")[0].rstrip("/") or "/"
    dt     = parse_time(m.group("time"))
    agent_type = classify_agent(ua)
    return {
        "ip":         m.group("ip"),
        "time":       dt,
        "time_str":   m.group("time").split()[0],
        "method":     m.group("method"),
        "url":        url_clean,
        "url_full":   url,
        "status":     int(m.group("status")),
        "size":       int(size) if size.isdigit() else 0,
        "referrer":   m.group("referrer"),
        "useragent":  ua,
        "is_bot":     is_bot(ua),
        "is_static":  is_static(url),
        "agent_type": agent_type,
        "suspicious": is_suspicious_path(url_clean),
    }


def parse_log(filepath: str) -> pd.DataFrame:
    records, errors = [], 0
    try:
        with open(filepath, errors="ignore") as f:
            for line in f:
                p = parse_line(line)
                if p:
                    records.append(p)
                else:
                    errors += 1
    except FileNotFoundError:
        logger.error(f"File log tidak ditemukan: {filepath}")
        return pd.DataFrame()
    except PermissionError:
        logger.error(f"Tidak ada izin baca file: {filepath}")
        return pd.DataFrame()

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    logger.info(f"Parse selesai: {len(df):,} entri valid, {errors:,} gagal")
    return df


def get_log_analytics(filepath: str) -> dict:
    """
    Analitik lengkap dari Nginx access.log.
    Mencakup: traffic stats, top URLs/IPs, bot analysis,
    hourly trends, threat scoring, suspicious activity.
    """
    if not os.path.exists(filepath):
        return {"error": f"File tidak ditemukan: {filepath}", "total": 0}

    df = parse_log(filepath)
    if df.empty:
        return {"error": "Log kosong atau tidak dapat dibaca", "total": 0}

    total = len(df)

    # ── Status codes ──────────────────────────────────────────
    status_counts = df["status"].value_counts().to_dict()
    status_2xx = sum(v for k, v in status_counts.items() if 200 <= k < 300)
    status_3xx = sum(v for k, v in status_counts.items() if 300 <= k < 400)
    status_4xx = sum(v for k, v in status_counts.items() if 400 <= k < 500)
    status_5xx = sum(v for k, v in status_counts.items() if k >= 500)
    status_detail = {str(k): int(v) for k, v in sorted(status_counts.items())}

    # ── Traffic volumes ───────────────────────────────────────
    total_bytes   = int(df["size"].sum())
    dynamic_df    = df[~df["is_static"]]
    static_df     = df[df["is_static"]]

    # ── Agent types ───────────────────────────────────────────
    agent_counts  = df["agent_type"].value_counts().to_dict()
    bot_count     = int(df["is_bot"].sum())
    human_count   = total - bot_count
    scanner_count = int((df["agent_type"] == "scanner").sum())

    # ── Top URLs (dynamic only) ───────────────────────────────
    top_urls = [{"url": k, "count": int(v)}
                for k, v in dynamic_df["url"].value_counts().head(15).items()]

    # ── Top static resources ──────────────────────────────────
    top_static = [{"url": k, "count": int(v)}
                  for k, v in static_df["url"].value_counts().head(10).items()]

    # ── Top IPs with threat score ─────────────────────────────
    ip_stats = df.groupby("ip").agg(
        total     =("ip",       "count"),
        errors    =("status",   lambda x: (x >= 400).sum()),
        suspicious=("suspicious","sum"),
        scanners  =("agent_type", lambda x: (x == "scanner").sum()),
        bots      =("is_bot",  "sum"),
        bytes_sent=("size",    "sum"),
    ).reset_index()

    def threat_score(row):
        score = 0
        if row["errors"] / max(row["total"], 1) > 0.5:   score += 40
        elif row["errors"] / max(row["total"], 1) > 0.2: score += 20
        if row["suspicious"] > 5:  score += 30
        elif row["suspicious"] > 0: score += 15
        if row["scanners"] > 0:     score += 30
        if row["bots"] > 0 and row["total"] > 100: score += 10
        return min(score, 100)

    ip_stats["threat"] = ip_stats.apply(threat_score, axis=1)
    ip_stats = ip_stats.sort_values("total", ascending=False)

    top_ips = ip_stats.head(15).apply(lambda r: {
        "ip":       r["ip"],
        "count":    int(r["total"]),
        "errors":   int(r["errors"]),
        "threat":   int(r["threat"]),
        "suspicious": int(r["suspicious"]),
        "bytes":    int(r["bytes_sent"]),
    }, axis=1).tolist()

    # High-threat IPs
    threat_ips = ip_stats[ip_stats["threat"] >= 40].sort_values("threat", ascending=False).head(10)
    threat_ips_list = threat_ips.apply(lambda r: {
        "ip":       r["ip"],
        "count":    int(r["total"]),
        "errors":   int(r["errors"]),
        "threat":   int(r["threat"]),
        "suspicious": int(r["suspicious"]),
    }, axis=1).tolist()

    # ── Hourly traffic ────────────────────────────────────────
    hourly_data = {}
    if df["time"].notna().any():
        df_t = df[df["time"].notna()].copy()
        df_t["hour"] = df_t["time"].dt.hour
        hourly_raw = df_t.groupby("hour").agg(
            requests=("ip", "count"),
            errors  =("status", lambda x: (x >= 400).sum()),
            bots    =("is_bot", "sum"),
        ).reset_index()
        for _, row in hourly_raw.iterrows():
            hourly_data[int(row["hour"])] = {
                "requests": int(row["requests"]),
                "errors":   int(row["errors"]),
                "bots":     int(row["bots"]),
            }

    # ── HTTP Methods ──────────────────────────────────────────
    method_counts = {k: int(v) for k, v in df["method"].value_counts().items()}

    # ── Top referrers ─────────────────────────────────────────
    refs = df[(df["referrer"] != "-") & (df["referrer"] != "")]
    top_referrers = [{"url": k[:100], "count": int(v)}
                     for k, v in refs["referrer"].value_counts().head(10).items()]

    # ── User agents ───────────────────────────────────────────
    top_ua = [{"ua": k[:80], "count": int(v)}
              for k, v in df["useragent"].value_counts().head(10).items()]

    # ── Suspicious activity ───────────────────────────────────
    scan_attempts = df[df["suspicious"]].copy()
    scan_list = []
    if not scan_attempts.empty:
        for _, row in scan_attempts.groupby("ip").apply(
            lambda g: g.sort_values("time").head(5)
        ).reset_index(drop=True).head(30).iterrows():
            scan_list.append({
                "ip":      row["ip"],
                "url":     row["url"],
                "status":  int(row["status"]),
                "time":    str(row["time_str"]),
                "agent":   str(row["useragent"])[:60],
            })

    # ── Error analysis ────────────────────────────────────────
    error_df   = df[df["status"] >= 400]
    top_errors = [{"url": k, "count": int(v), "status": int(k.split("|")[1]) if "|" in k else 0}
                  for k, v in (error_df["url"] + "|" + error_df["status"].astype(str))
                  .value_counts().head(10).items()]
    # Simplify
    top_errors_clean = []
    for item in df[df["status"] >= 400].groupby(["url", "status"]).size().reset_index(name="count").sort_values("count", ascending=False).head(10).itertuples():
        top_errors_clean.append({"url": item.url, "status": int(item.status), "count": int(item.count)})

    # ── Response time proxy (size as indicator) ───────────────
    avg_size     = round(float(df["size"].mean()), 2)
    median_size  = round(float(df["size"].median()), 2)

    # ── Recent log entries ────────────────────────────────────
    recent_cols = ["time_str", "ip", "method", "url", "status",
                   "size", "useragent", "is_bot", "agent_type", "suspicious"]
    recent_df   = df.tail(100)[recent_cols].copy()
    recent_df["useragent"] = recent_df["useragent"].str[:80]
    recent      = recent_df.fillna("-").to_dict("records")

    # ── Uptime proxy: 5xx rate ────────────────────────────────
    error_rate   = round(status_5xx / max(total, 1) * 100, 2)
    uptime_proxy = round(100 - error_rate, 2)

    # ── Log file info ─────────────────────────────────────────
    try:
        log_size_mb = round(os.path.getsize(filepath) / 1024 / 1024, 2)
    except Exception:
        log_size_mb = 0

    # ── First & last entry time ───────────────────────────────
    first_time = last_time = None
    valid_times = df[df["time"].notna()]["time"]
    if not valid_times.empty:
        first_time = str(valid_times.min())[:19]
        last_time  = str(valid_times.max())[:19]

    return {
        "error":           None,
        "total":           total,
        "total_dynamic":   int(len(dynamic_df)),
        "total_static":    int(len(static_df)),
        "status_2xx":      status_2xx,
        "status_3xx":      status_3xx,
        "status_4xx":      status_4xx,
        "status_5xx":      status_5xx,
        "status_detail":   status_detail,
        "total_bytes":     total_bytes,
        "avg_size":        avg_size,
        "median_size":     median_size,
        "bot_count":       bot_count,
        "human_count":     human_count,
        "scanner_count":   scanner_count,
        "agent_counts":    agent_counts,
        "method_counts":   method_counts,
        "top_urls":        top_urls,
        "top_static":      top_static,
        "top_ips":         top_ips,
        "threat_ips":      threat_ips_list,
        "top_referrers":   top_referrers,
        "top_ua":          top_ua,
        "hourly":          hourly_data,
        "scan_attempts":   scan_list,
        "top_errors":      top_errors_clean,
        "error_rate":      error_rate,
        "uptime_proxy":    uptime_proxy,
        "log_size_mb":     log_size_mb,
        "first_entry":     first_time,
        "last_entry":      last_time,
        "recent":          recent,
    }


def engineer_features(df: pd.DataFrame, min_normal: int = 1, min_bot: int = 1) -> pd.DataFrame:
    df = df[(df["status"] == 200) & (~df["url"].apply(is_static))].copy()
    normal = (df[~df["is_bot"]].groupby("url")["size"]
              .agg(size_normal_mean="mean", size_normal_std="std", count_normal="count")
              .reset_index())
    bot = (df[df["is_bot"]].groupby("url")["size"]
           .agg(size_bot_mean="mean", size_bot_std="std", count_bot="count")
           .reset_index())
    merged = pd.merge(normal, bot, on="url").fillna(0)
    merged = merged[(merged["count_normal"] >= min_normal) &
                    (merged["count_bot"]    >= min_bot)].copy()
    if merged.empty:
        logger.warning("Tidak ada URL yang memenuhi syarat minimum akses normal & bot")
        return merged
    denom = merged["size_normal_mean"].replace(0, 1)
    merged["size_diff_abs"] = abs(merged["size_normal_mean"] - merged["size_bot_mean"])
    merged["size_ratio"]    = (merged["size_bot_mean"] / denom).round(4)
    merged["size_diff_pct"] = (merged["size_diff_abs"] / denom * 100).round(2)
    logger.info(f"Fitur dihasilkan untuk {len(merged)} URL")
    return merged
