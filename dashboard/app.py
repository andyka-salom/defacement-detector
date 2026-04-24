"""
dashboard/app.py
Backend dashboard monitoring lengkap dengan:
- Log analytics API
- Website monitoring (uptime, SSL, response time)
- SSE live log streaming
- Deteksi anomali stats
"""
import os, subprocess, json, time, threading
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, Response, request
import requests as req_lib

from config.settings import (FLASK_SECRET_KEY, FLASK_HOST, FLASK_PORT,
                              FLASK_DEBUG, LOG_PATH, TARGET_BASE_URL)
from core.storage  import get_recent_detections, get_stats, init_db
from core.streamer import get_stats as get_streamer_stats
from core.parser   import get_log_analytics, parse_line
from config.logger import get_logger

logger = get_logger("dashboard")

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = FLASK_SECRET_KEY

# ── Website Monitor Cache ─────────────────────────────────────
_monitor_cache = {}
_monitor_lock  = threading.Lock()
UA_NORMAL = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_BOT    = "Googlebot/2.1 (+http://www.google.com/bot.html)"


def _check_website(url: str, ua: str = UA_NORMAL) -> dict:
    """Cek ketersediaan dan response time suatu URL."""
    start = time.time()
    try:
        r = req_lib.get(url, headers={"User-Agent": ua},
                        timeout=10, allow_redirects=True,
                        verify=True)
        elapsed = round((time.time() - start) * 1000, 1)
        html_size = len(r.content)
        return {
            "url":         url,
            "status":      r.status_code,
            "ok":          r.status_code < 400,
            "response_ms": elapsed,
            "size_bytes":  html_size,
            "final_url":   r.url,
            "error":       None,
            "checked_at":  datetime.now().strftime("%H:%M:%S"),
        }
    except req_lib.exceptions.SSLError as e:
        return {"url": url, "status": 0, "ok": False,
                "response_ms": 0, "error": "SSL Error: "+str(e)[:60],
                "checked_at": datetime.now().strftime("%H:%M:%S")}
    except req_lib.exceptions.ConnectionError:
        return {"url": url, "status": 0, "ok": False,
                "response_ms": 0, "error": "Connection refused",
                "checked_at": datetime.now().strftime("%H:%M:%S")}
    except req_lib.exceptions.Timeout:
        elapsed = round((time.time() - start) * 1000, 1)
        return {"url": url, "status": 0, "ok": False,
                "response_ms": elapsed, "error": "Timeout (>10s)",
                "checked_at": datetime.now().strftime("%H:%M:%S")}
    except Exception as e:
        return {"url": url, "status": 0, "ok": False,
                "response_ms": 0, "error": str(e)[:80],
                "checked_at": datetime.now().strftime("%H:%M:%S")}


# ── Routes ────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html",
                           target_url=TARGET_BASE_URL,
                           log_path=LOG_PATH)


@app.route("/api/log-stats")
def api_log_stats():
    try:
        data = get_log_analytics(LOG_PATH)
        return jsonify(data)
    except Exception as e:
        logger.error(f"log-stats error: {e}")
        return jsonify({"error": str(e), "total": 0})


@app.route("/api/stats")
def api_stats():
    try:
        db  = get_stats()
        stm = get_streamer_stats()
        return jsonify({**db, **stm})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/detections")
def api_detections():
    limit = min(int(request.args.get("limit", 100)), 500)
    return jsonify(get_recent_detections(limit=limit))


@app.route("/api/live-log")
def api_live_log():
    """SSE: stream baris baru log Nginx secara real-time."""
    def generate():
        if not os.path.exists(LOG_PATH):
            yield f"data: {json.dumps({'error': f'File tidak ditemukan: {LOG_PATH}'})}\n\n"
            return
        if not os.access(LOG_PATH, os.R_OK):
            yield f"data: {json.dumps({'error': 'Tidak ada izin baca file log'})}\n\n"
            return

        proc = subprocess.Popen(
            ["tail", "-n", "30", "-F", LOG_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                p = parse_line(line)
                payload = {
                    "raw":        line[:250],
                    "ip":         p["ip"]         if p else "-",
                    "method":     p["method"]      if p else "-",
                    "url":        p["url"]         if p else line[:60],
                    "status":     p["status"]      if p else 0,
                    "size":       p["size"]        if p else 0,
                    "is_bot":     p["is_bot"]      if p else False,
                    "agent_type": p["agent_type"]  if p else "unknown",
                    "suspicious": p["suspicious"]  if p else False,
                    "time_str":   p["time_str"]    if p else "-",
                    "useragent":  (p["useragent"][:80] if p else "-"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
        except GeneratorExit:
            pass
        finally:
            if proc.poll() is None:
                proc.terminate()

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


@app.route("/api/tail-log")
def api_tail_log():
    n = min(int(request.args.get("n", 50)), 500)
    if not os.path.exists(LOG_PATH):
        return jsonify({"lines": [], "error": f"File tidak ditemukan: {LOG_PATH}"})
    try:
        result = subprocess.run(["tail", "-n", str(n), LOG_PATH],
                                capture_output=True, text=True, timeout=5)
        lines = []
        for raw in result.stdout.strip().split("\n"):
            if not raw:
                continue
            p = parse_line(raw)
            lines.append({
                "raw":        raw[:200],
                "ip":         p["ip"]         if p else "-",
                "method":     p["method"]      if p else "-",
                "url":        p["url"]         if p else "-",
                "status":     p["status"]      if p else 0,
                "size":       p["size"]        if p else 0,
                "is_bot":     p["is_bot"]      if p else False,
                "agent_type": p["agent_type"]  if p else "unknown",
                "suspicious": p["suspicious"]  if p else False,
                "time_str":   p["time_str"]    if p else "-",
                "useragent":  (p["useragent"][:80] if p else "-"),
            })
        return jsonify({"lines": list(reversed(lines)), "error": None})
    except Exception as e:
        return jsonify({"lines": [], "error": str(e)})


@app.route("/api/monitor")
def api_monitor():
    """Cek ketersediaan website target (normal + bot UA)."""
    url = request.args.get("url", TARGET_BASE_URL)
    normal = _check_website(url, UA_NORMAL)
    bot    = _check_website(url, UA_BOT)

    # Hitung size diff jika keduanya berhasil
    size_diff_pct = 0
    if normal.get("size_bytes") and bot.get("size_bytes"):
        sn = normal["size_bytes"]
        sb = bot["size_bytes"]
        size_diff_pct = round(abs(sn - sb) / max(sn, 1) * 100, 2)

    return jsonify({
        "url":           url,
        "normal":        normal,
        "bot":           bot,
        "size_diff_pct": size_diff_pct,
        "suspicious":    size_diff_pct > 20,
        "timestamp":     datetime.now().isoformat(),
    })


@app.route("/api/monitor-urls", methods=["POST"])
def api_monitor_urls():
    """Cek beberapa URL sekaligus."""
    data = request.get_json() or {}
    urls = data.get("urls", [TARGET_BASE_URL])[:10]  # max 10 URLs
    results = []
    for url in urls:
        res = _check_website(url, UA_NORMAL)
        results.append(res)
    return jsonify(results)


@app.route("/api/health")
def health():
    log_exists  = os.path.exists(LOG_PATH)
    log_size_mb = round(os.path.getsize(LOG_PATH) / 1024 / 1024, 2) if log_exists else 0
    return jsonify({
        "status":       "ok",
        "log_exists":   log_exists,
        "log_size_mb":  log_size_mb,
        "log_path":     LOG_PATH,
        "target_url":   TARGET_BASE_URL,
        "timestamp":    datetime.now().isoformat(),
    })


@app.route("/api/fetch-html")
def api_fetch_html():
    """Ambil HTML suatu URL dengan UA tertentu (untuk preview diff)."""
    url  = request.args.get("url", TARGET_BASE_URL)
    mode = request.args.get("mode", "normal")
    ua   = UA_BOT if mode == "bot" else UA_NORMAL
    try:
        r = req_lib.get(url, headers={"User-Agent": ua}, timeout=10, allow_redirects=True)
        return jsonify({
            "url":    url,
            "mode":   mode,
            "status": r.status_code,
            "size":   len(r.content),
            "html":   r.text[:50000],  # cap 50KB
        })
    except Exception as e:
        return jsonify({"error": str(e), "url": url, "mode": mode})


def run_dashboard():
    logger.info(f"Dashboard aktif: http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT,
            debug=FLASK_DEBUG, threaded=True)
