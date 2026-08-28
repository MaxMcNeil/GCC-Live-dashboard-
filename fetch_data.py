#!/usr/bin/env python3
"""
GCC Live Dashboard - Data Aggregator
Agrège des sources 100% gratuites et publiques (RSS + APIs sans clé)
pour KSA, UAE, Oman, Kuwait. Génère data.json consommé par index.html.

Toutes les sources sont officielles ou publiques. Aucune donnée n'est
inventée : si une source échoue, elle est simplement omise (pas de fallback fictif).
"""
import json
import time
import datetime
import feedparser
import requests

OUT_FILE = "data.json"
TIMEOUT = 10

# ---------------------------------------------------------------------------
# 1. Flux RSS officiels (actualités / communiqués)
# ---------------------------------------------------------------------------
RSS_FEEDS = {
    "SPA (Arabie Saoudite)": "https://www.spa.gov.sa/rss.php?lang=ar",
    "WAM (Émirats)": "https://www.wam.ae/en/rss",
    "Oman Observer": "https://www.omanobserver.om/rss",
    "Google News - Saudi Arabia": "https://news.google.com/rss/search?q=Saudi+Arabia&hl=en",
    "Google News - UAE": "https://news.google.com/rss/search?q=UAE&hl=en",
    "Google News - Oman": "https://news.google.com/rss/search?q=Oman&hl=en",
    "Google News - Kuwait": "https://news.google.com/rss/search?q=Kuwait&hl=en",
}

def fetch_rss(max_items=6):
    results = {}
    for name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            items = []
            for entry in feed.entries[:max_items]:
                items.append({
                    "title": entry.get("title", "").strip(),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
            if items:
                results[name] = items
        except Exception as e:
            print(f"[RSS] échec {name}: {e}")
    return results

# ---------------------------------------------------------------------------
# 2. Météo & qualité de l'air (Open-Meteo - gratuit, sans clé)
# ---------------------------------------------------------------------------
CITIES = {
    "Riyadh": (24.7136, 46.6753),
    "Jeddah": (21.4858, 39.1925),
    "Dubai": (25.2048, 55.2708),
    "Abu Dhabi": (24.4539, 54.3773),
    "Muscat": (23.5859, 58.4059),
    "Kuwait City": (29.3759, 47.9774),
}

def fetch_weather():
    out = {}
    for city, (lat, lon) in CITIES.items():
        try:
            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                    "timezone": "auto",
                },
                timeout=TIMEOUT,
            )
            data = r.json().get("current", {})
            out[city] = data
        except Exception as e:
            print(f"[Weather] échec {city}: {e}")
    return out

# ---------------------------------------------------------------------------
# 3. Devises, or, pétrole (via yfinance) & crypto (CoinGecko)
# ---------------------------------------------------------------------------
def fetch_markets():
    markets = {}
    try:
        import yfinance as yf
        tickers = {
            "USD/SAR": "SAR=X",
            "USD/AED": "AED=X",
            "USD/OMR": "OMR=X",
            "USD/KWD": "KWD=X",
            "Brent Crude": "BZ=F",
            "Gold": "GC=F",
        }
        for label, symbol in tickers.items():
            try:
                t = yf.Ticker(symbol)
                hist = t.history(period="1d")
                if not hist.empty:
                    markets[label] = round(float(hist["Close"].iloc[-1]), 4)
            except Exception as e:
                print(f"[Markets] échec {label}: {e}")
    except ImportError:
        print("[Markets] yfinance non installé")

    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum", "vs_currencies": "usd"},
            timeout=TIMEOUT,
        )
        markets["crypto"] = r.json()
    except Exception as e:
        print(f"[Crypto] échec: {e}")

    return markets

# ---------------------------------------------------------------------------
# 4. Trafic aérien (OpenSky Network - open data ADS-B)
# ---------------------------------------------------------------------------
AIRPORTS_BBOX = {
    "DXB (Dubai)": (24.9, 55.1, 25.4, 55.5),
    "RUH (Riyadh)": (24.7, 46.5, 25.1, 46.9),
    "MCT (Muscat)": (23.4, 58.2, 23.8, 58.6),
}

def fetch_flights():
    out = {}
    for name, (lamin, lomin, lamax, lomax) in AIRPORTS_BBOX.items():
        try:
            r = requests.get(
                "https://opensky-network.org/api/states/all",
                params={"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax},
                timeout=TIMEOUT,
            )
            states = r.json().get("states") or []
            out[name] = len(states)
        except Exception as e:
            print(f"[Flights] échec {name}: {e}")
    return out

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    payload = {
        "generated_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "news": fetch_rss(),
        "weather": fetch_weather(),
        "markets": fetch_markets(),
        "flights": fetch_flights(),
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"OK - data.json généré ({len(json.dumps(payload))} octets)")

if __name__ == "__main__":
    main()
