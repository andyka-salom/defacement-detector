"""
scripts/generate_synthetic_log.py
Generate data sintetis Nginx access.log untuk pengujian sistem.
Mensimulasikan skenario: normal, cloaking ringan, cloaking berat, defacement eksplisit.

Format output: Nginx Combined Log Format (identik dengan Apache CLF).

Penggunaan:
  python scripts/generate_synthetic_log.py
  python scripts/generate_synthetic_log.py --days 30 --entries 8000
"""
import random
import datetime
import argparse
import os

random.seed(42)

DOMAIN = "x.com"

PAGES_DYNAMIC = [
    "/", "/tentang-kami", "/produk", "/produk/pria", "/produk/wanita",
    "/produk/unisex", "/kontak", "/promo", "/blog", "/blog/tips-parfum",
    "/blog/cara-memilih-parfum", "/brand", "/brand/chanel",
]
PAGES_STATIC = [
    "/robots.txt", "/sitemap.xml", "/favicon.ico",
    "/assets/css/style.css", "/assets/js/main.js",
    "/assets/img/banner.jpg", "/assets/img/logo.png",
]

UA_NORMAL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15 Version/17.0 Mobile",
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile",
    "Mozilla/5.0 (Windows NT 10.0; rv:120.0) Gecko/20100101 Firefox/120.0",
]
UA_BOT = [
    "Googlebot/2.1 (+http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "DuckDuckBot/1.0; (+http://duckduckgo.com/duckduckbot.html)",
    "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
]

IPS_NORMAL   = [f"103.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}" for _ in range(40)]
IPS_BOT      = ["66.249.66.1", "66.249.66.2", "157.55.39.1", "207.46.13.1", "40.77.167.1"]
IPS_ATTACKER = ["185.220.101.5", "45.33.32.156", "192.241.200.72", "178.62.12.45"]


def fmt_time(dt: datetime.datetime) -> str:
    return dt.strftime("%d/%b/%Y:%H:%M:%S +0700")


def make_entry(ip, dt, url, status, size, ua, referrer="-") -> str:
    """Buat satu baris log dalam format Nginx Combined Log."""
    return f'{ip} - - [{fmt_time(dt)}] "GET {url} HTTP/1.1" {status} {size} "{referrer}" "{ua}"'


def generate(days: int = 30, total_entries: int = 6000, output: str = "data/access.log"):
    os.makedirs(os.path.dirname(output), exist_ok=True)
    entries = []
    start   = datetime.datetime(2025, 11, 1)

    # 1. Akses normal (70%)
    n_normal = int(total_entries * 0.70)
    for _ in range(n_normal):
        dt   = start + datetime.timedelta(seconds=random.randint(0, days * 86400))
        page = random.choices(
            PAGES_DYNAMIC + PAGES_STATIC,
            weights=[10] * len(PAGES_DYNAMIC) + [2] * len(PAGES_STATIC)
        )[0]
        ua   = random.choice(UA_NORMAL)
        ip   = random.choice(IPS_NORMAL)
        size = (
            random.randint(800, 3000)
            if any(page.endswith(e) for e in [".css", ".js", ".jpg", ".ico", ".png"])
            else random.randint(18000, 42000)
        )
        entries.append(make_entry(ip, dt, page, 200, size, ua, f"https://{DOMAIN}/"))

    # 2. Akses bot normal (20%)
    n_bot = int(total_entries * 0.20)
    for _ in range(n_bot):
        dt   = start + datetime.timedelta(seconds=random.randint(0, days * 86400))
        page = random.choice(PAGES_DYNAMIC + ["/robots.txt", "/sitemap.xml"])
        ua   = random.choice(UA_BOT)
        ip   = random.choice(IPS_BOT)
        size = (
            random.randint(18000, 42000)
            if page in PAGES_DYNAMIC
            else random.randint(500, 2500)
        )
        entries.append(make_entry(ip, dt, page, 200, size, ua))

    # 3. Cloaking berat — hari 26-30 (ukuran bot >> normal)
    for _ in range(80):
        dt   = start + datetime.timedelta(days=random.randint(25, 29), seconds=random.randint(0, 86400))
        page = random.choice(["/", "/produk", "/promo", "/blog"])
        entries.append(make_entry(
            random.choice(IPS_NORMAL), dt, page, 200,
            random.randint(19000, 23000), random.choice(UA_NORMAL), f"https://{DOMAIN}/"
        ))
        entries.append(make_entry(
            random.choice(IPS_BOT), dt + datetime.timedelta(seconds=5),
            page, 200, random.randint(68000, 95000), random.choice(UA_BOT)
        ))

    # 4. Cloaking ringan — hari 20-26
    for _ in range(40):
        dt   = start + datetime.timedelta(days=random.randint(20, 25), seconds=random.randint(0, 86400))
        page = random.choice(["/blog/tips-parfum", "/blog/cara-memilih-parfum"])
        entries.append(make_entry(
            random.choice(IPS_NORMAL), dt, page, 200,
            random.randint(22000, 26000), random.choice(UA_NORMAL)
        ))
        entries.append(make_entry(
            random.choice(IPS_BOT), dt + datetime.timedelta(seconds=10),
            page, 200, random.randint(38000, 52000), random.choice(UA_BOT)
        ))

    # 5. Defacement eksplisit — hari 29 (ukuran sama ke semua UA, lebih besar)
    for _ in range(30):
        dt   = start + datetime.timedelta(days=29, seconds=random.randint(0, 3600))
        page = "/tentang-kami"
        for ua in [random.choice(UA_NORMAL), random.choice(UA_BOT)]:
            ip = random.choice(IPS_NORMAL if "Mozilla/5.0 (Windows" in ua else IPS_BOT)
            entries.append(make_entry(ip, dt, page, 200, random.randint(55000, 62000), ua))

    # 6. Scan path mencurigakan
    for _ in range(150):
        dt   = start + datetime.timedelta(seconds=random.randint(0, days * 86400))
        page = random.choice(["/admin", "/wp-admin", "/.env", "/shell.php", "/.git/config"])
        ip   = random.choice(IPS_ATTACKER)
        entries.append(make_entry(
            ip, dt, page, random.choice([404, 403]),
            random.randint(400, 1200), random.choice(UA_NORMAL)
        ))

    # Sort by timestamp
    random.shuffle(entries)
    entries.sort(key=lambda x: x[x.index("[") + 1: x.index("]")])

    with open(output, "w") as f:
        f.write("\n".join(entries))

    print(f"✓ Generated {len(entries)} log entries (Nginx format) → {output}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic Nginx access.log")
    parser.add_argument("--days",    type=int, default=30,               help="Jumlah hari simulasi")
    parser.add_argument("--entries", type=int, default=6000,             help="Target jumlah entri")
    parser.add_argument("--output",  type=str, default="data/access.log", help="Path output")
    args = parser.parse_args()
    generate(days=args.days, total_entries=args.entries, output=args.output)
