"""
dashboard/app.py
Flask dashboard untuk monitoring hasil deteksi.
Akses di: http://VPS_IP:5000
"""
from flask import Flask, render_template, jsonify
from config.settings import FLASK_SECRET_KEY, FLASK_HOST, FLASK_PORT, FLASK_DEBUG
from core.storage import get_recent_detections, get_stats
from core.streamer import get_stats as get_streamer_stats

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = FLASK_SECRET_KEY


@app.route("/")
def index():
    stats      = get_stats()
    detections = get_recent_detections(limit=50)
    return render_template("dashboard.html", stats=stats, detections=detections)


@app.route("/api/detections")
def api_detections():
    return jsonify(get_recent_detections(limit=100))


@app.route("/api/stats")
def api_stats():
    db_stats      = get_stats()
    stream_stats  = get_streamer_stats()
    return jsonify({**db_stats, **stream_stats})


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


def run_dashboard():
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
