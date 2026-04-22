"""
core/detector.py
Implementasi Isolation Forest untuk deteksi anomali
perbedaan response size normal vs bot.
"""
import os
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib
from config.settings import CONTAMINATION, MODEL_DIR
from config.logger import get_logger

logger = get_logger("detector")

FEATURES = [
    "size_diff_abs",
    "size_ratio",
    "size_diff_pct",
    "size_normal_std",
    "size_bot_std",
]

MODEL_PATH  = os.path.join(MODEL_DIR, "isolation_forest.pkl")
SCALER_PATH = os.path.join(MODEL_DIR, "scaler.pkl")


def train(df: pd.DataFrame, contamination: float = CONTAMINATION) -> tuple:
    """
    Latih model Isolation Forest dari DataFrame fitur.
    Model dan scaler disimpan ke disk.
    """
    os.makedirs(MODEL_DIR, exist_ok=True)

    X = df[FEATURES].fillna(0)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=100,
        contamination=contamination,
        max_samples="auto",
        max_features=1.0,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    joblib.dump(model,  MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    logger.info(f"Model dilatih dengan {len(df)} URL, contamination={contamination}")
    return model, scaler


def load_model() -> tuple:
    """Load model dan scaler dari disk."""
    if not os.path.exists(MODEL_PATH) or not os.path.exists(SCALER_PATH):
        raise FileNotFoundError(
            "Model belum dilatih. Jalankan: python main.py --train"
        )
    model  = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    logger.debug("Model berhasil dimuat dari disk")
    return model, scaler


def predict(df: pd.DataFrame, model, scaler) -> pd.DataFrame:
    """
    Prediksi anomali untuk DataFrame fitur.
    Menambahkan kolom: anomaly_score, is_anomaly
    """
    X = df[FEATURES].fillna(0)
    X_scaled = scaler.transform(X)

    df = df.copy()
    df["anomaly_score"] = model.score_samples(X_scaled).round(4)
    df["is_anomaly"]    = (model.predict(X_scaled) == -1)

    n_anomaly = df["is_anomaly"].sum()
    logger.info(f"Prediksi: {len(df)} URL → {n_anomaly} anomali terdeteksi")
    return df


def predict_single_url(url_data: dict, model, scaler) -> dict:
    """
    Prediksi satu URL (dict dengan key FEATURES).
    Digunakan untuk analisis real-time dari buffer.
    """
    row = pd.DataFrame([url_data])[FEATURES].fillna(0)
    scaled = scaler.transform(row)
    score  = float(model.score_samples(scaled)[0])
    flag   = bool(model.predict(scaled)[0] == -1)
    return {"anomaly_score": round(score, 4), "is_anomaly": flag}
