"""
dashboard/app.py
Dashboard monitoring lengkap:
- Statistik real-time log akses Nginx
- Live log streaming via SSE
- Riwayat deteksi anomali
- Preview halaman website
- API endpoints untuk polling
"""
import os, subprocess, time, json
from flask import Flask, render_template, jsonify, Response, request
from config.settings import (FLASK_SECRET_KEY, FLASK_HOST, FLASK_PORT,
                              FLASK_DEBUG, LOG_PATH, TARGET_BASE_URL)
from core.storage  import get_recent_detections, get_stats
from core.streamer import get_stats as get_streamer_stats
from core.parser   import get_log_analytics, parse_line
from config.logger import get_logger

logger = get_logger("dashboard")

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = FLASK_SECRET_KEY


# ── Halaman utama ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html",
                           target_url=TARGET_BASE_URL,
                           log_path=LOG_PATH)


# ── API: Statistik log akses Nginx ───────────────────────────
@app.route("/api/log-stats")
def api_log_stats():
    try:
        data = get_log_analytics(LOG_PATH)
        return jsonify(data)
    except Exception as e:
        logger.error(f"log-stats error: {e}")
        return jsonify({"error": str(e), "total": 0})


# ── API: Statistik deteksi anomali ───────────────────────────
@app.route("/api/stats")
def api_stats():
    try:
        db  = get_stats()
        stm = get_streamer_stats()
        return jsonify({**db, **stm})
    except Exception as e:
        return jsonify({"error": str(e)})


# ── API: Riwayat deteksi ─────────────────────────────────────
@app.route("/api/detections")
def api_detections():
    limit = int(request.args.get("limit", 100))
    return jsonify(get_recent_detections(limit=limit))


# ── API: Live log (SSE — Server-Sent Events) ─────────────────
@app.route("/api/live-log")
def api_live_log():
    """Stream baris baru dari Nginx access.log ke browser via SSE."""
    def generate():
        if not os.path.exists(LOG_PATH):
            yield f"data: {json.dumps({'error': f'File tidak ditemukan: {LOG_PATH}'})}\n\n"
            return
        proc = subprocess.Popen(
            ["tail", "-n", "20", "-F", LOG_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                parsed = parse_line(line)
                payload = {
                    "raw":       line[:200],
                    "ip":        parsed["ip"]        if parsed else "-",
                    "method":    parsed["method"]     if parsed else "-",
                    "url":       parsed["url"]        if parsed else "-",
                    "status":    parsed["status"]     if parsed else 0,
                    "size":      parsed["size"]       if parsed else 0,
                    "is_bot":    parsed["is_bot"]     if parsed else False,
                    "time_str":  parsed["time_str"]   if parsed else "-",
                    "useragent": (parsed["useragent"][:70] if parsed else "-"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
        except GeneratorExit:
            proc.terminate()
        finally:
            if proc.poll() is None:
                proc.terminate()

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ── API: Tail log (polling fallback) ─────────────────────────
@app.route("/api/tail-log")
def api_tail_log():
    n = int(request.args.get("n", 50))
    if not os.path.exists(LOG_PATH):
        return jsonify({"lines": [], "error": f"File tidak ditemukan: {LOG_PATH}"})
    try:
        result = subprocess.run(["tail", "-n", str(n), LOG_PATH],
                                capture_output=True, text=True, timeout=5)
        lines = []
        for raw in result.stdout.strip().split("\n"):
            if not raw: continue
            p = parse_line(raw)
            lines.append({
                "raw":       raw[:200],
                "ip":        p["ip"]        if p else "-",
                "method":    p["method"]     if p else "-",
                "url":       p["url"]        if p else "-",
                "status":    p["status"]     if p else 0,
                "size":      p["size"]       if p else 0,
                "is_bot":    p["is_bot"]     if p else False,
                "time_str":  p["time_str"]   if p else "-",
                "useragent": (p["useragent"][:70] if p else "-"),
            })
        return jsonify({"lines": list(reversed(lines)), "error": None})
    except Exception as e:
        return jsonify({"lines": [], "error": str(e)})


# ── API: Health check ─────────────────────────────────────────
@app.route("/api/health")
def health():
    log_exists = os.path.exists(LOG_PATH)
    log_size   = os.path.getsize(LOG_PATH) if log_exists else 0
    return jsonify({
        "status":     "ok",
        "log_exists": log_exists,
        "log_size_mb": round(log_size/1024/1024, 2),
        "log_path":   LOG_PATH,
        "target_url": TARGET_BASE_URL,
    })


def run_dashboard():
    logger.info(f"Dashboard aktif: http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT,
            debug=FLASK_DEBUG, threaded=True)
