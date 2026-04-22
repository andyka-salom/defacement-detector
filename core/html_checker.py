"""
core/html_checker.py
Analisis kesamaan konten HTML antara akses user-agent normal dan bot.
Dijalankan hanya ketika Isolation Forest mendeteksi anomali.
"""
import requests
from bs4 import BeautifulSoup
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from config.settings import UA_NORMAL, UA_BOT, DEFACEMENT_DICT, TARGET_BASE_URL
from config.logger import get_logger

logger = get_logger("html_checker")

TIMEOUT = 10  # detik


def fetch_html(url: str, user_agent: str) -> str:
    """Ambil HTML halaman menggunakan user-agent tertentu."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        return resp.text
    except requests.RequestException as e:
        logger.warning(f"Gagal fetch {url} [{user_agent[:30]}]: {e}")
        return ""


def extract_text(html: str) -> str:
    """
    Ekstrak teks utama dari HTML:
    - Hapus tag <script> dan <style>
    - Ambil teks bersih, lowercase, tanpa karakter khusus
    """
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "meta", "link", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        # Normalisasi
        text = " ".join(text.lower().split())
        return text
    except Exception as e:
        logger.warning(f"Gagal ekstraksi teks HTML: {e}")
        return ""


def compute_cosine_similarity(text_a: str, text_b: str) -> float:
    """Hitung Cosine Similarity antara dua teks menggunakan TF-IDF."""
    if not text_a or not text_b:
        return 1.0  # Anggap sama jika salah satu kosong
    try:
        vec  = TfidfVectorizer(max_features=5000, sublinear_tf=True)
        tfidf = vec.fit_transform([text_a, text_b])
        sim  = cosine_similarity(tfidf[0], tfidf[1])[0][0]
        return round(float(sim), 4)
    except Exception as e:
        logger.warning(f"Gagal hitung cosine similarity: {e}")
        return 1.0


def check_defacement_dict(text: str) -> dict:
    """
    Cocokkan teks dengan dictionary kata defacement.
    Return: dict dengan hits dan jumlahnya.
    """
    text_lower = text.lower()
    hits = [w for w in DEFACEMENT_DICT if w in text_lower]
    return {
        "dict_hits":      hits,
        "dict_hit_count": len(hits),
    }


def check_similarity(url_path: str) -> dict:
    """
    Analisis lengkap satu URL:
    1. Fetch HTML dengan UA normal dan bot
    2. Hitung Cosine Similarity
    3. Cek dictionary defacement
    4. Return ringkasan hasil

    url_path: path relatif (contoh: '/produk')
    """
    url = TARGET_BASE_URL.rstrip("/") + url_path

    logger.info(f"Menganalisis konten HTML: {url}")

    html_normal = fetch_html(url, UA_NORMAL)
    html_bot    = fetch_html(url, UA_BOT)

    text_normal = extract_text(html_normal)
    text_bot    = extract_text(html_bot)

    cosine_sim    = compute_cosine_similarity(text_normal, text_bot)
    dict_result   = check_defacement_dict(text_bot)  # cek di respons bot

    size_normal   = len(html_normal)
    size_bot      = len(html_bot)
    size_diff_pct = (
        round(abs(size_normal - size_bot) / max(size_normal, 1) * 100, 2)
        if size_normal > 0 else 0
    )

    result = {
        "url":              url_path,
        "cosine_similarity": cosine_sim,
        "size_normal":      size_normal,
        "size_bot":         size_bot,
        "size_diff_pct":    size_diff_pct,
        **dict_result,
    }

    logger.info(
        f"  cosine={cosine_sim} | size_diff={size_diff_pct}% "
        f"| dict_hits={dict_result['dict_hit_count']}"
    )
    return result
