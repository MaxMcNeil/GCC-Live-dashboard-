#!/usr/bin/env python3
"""
GCC Live Dashboard - Data Aggregator
Agrège des sources 100% gratuites et publiques (RSS + APIs sans clé)
pour KSA, UAE, Oman, Kuwait. Génère data.json consommé par index.html.

Toutes les sources sont officielles ou publiques. Aucune donnée n'est
inventée : si une source échoue, elle est simplement omise (pas de
fallback fictif) -- mais l'échec est enregistré dans data["_meta"]["errors"]
et affiché comme annotation GitHub Actions + dans le résumé du run, pour
qu'une panne soit visible en un coup d'œil sans fouiller les logs bruts.
"""
import json
import os
import sys
import time
import datetime
import feedparser
import requests

OUT_FILE = "data.json"
CACHE_FILE = "translation_cache.json"
TIMEOUT = 10

# ---------------------------------------------------------------------------
# Suivi des erreurs / statut par source (pour diagnostic facile)
# ---------------------------------------------------------------------------
ERRORS = []      # [{"source": "...", "stage": "...", "error": "..."}]
STATUS = {}      # {"nom_de_la_source": True/False}

def log_error(stage, source, exc):
    msg = f"{exc.__class__.__name__}: {exc}"
    ERRORS.append({"stage": stage, "source": source, "error": msg})
    STATUS[source] = False
    # Annotation GitHub Actions : apparaît en rouge/orange en haut du run,
    # pas besoin d'ouvrir les logs pour voir quoi a échoué et pourquoi.
    print(f"::warning title=Échec {stage}::{source} -> {msg}")

def log_ok(source):
    STATUS[source] = True

# ---------------------------------------------------------------------------
# 0. Traduction anglais -> arabe (MyMemory, gratuit, sans clé, avec cache)
# ---------------------------------------------------------------------------
try:
    from deep_translator import MyMemoryTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False
    print("::warning title=Traduction indisponible::le paquet deep-translator n'est pas installé")

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_error("cache", "translation_cache.json", e)
    return {}

def save_cache(cache):
    try:
        # on garde le cache à taille raisonnable (les titres tournent vite)
        if len(cache) > 2000:
            cache = dict(list(cache.items())[-1500:])
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("cache", "translation_cache.json", e)

_translation_cache = load_cache()
_translator = MyMemoryTranslator(source="en-GB", target="ar-SA") if TRANSLATOR_AVAILABLE else None

def translate_title(text):
    """Traduit un titre EN -> AR. Ne bloque jamais le pipeline :
    en cas d'échec, retourne le texte original (l'UI l'affichera tel quel)."""
    if not text:
        return text
    if text in _translation_cache:
        return _translation_cache[text]
    if not TRANSLATOR_AVAILABLE:
        return text
    try:
        result = _translator.translate(text[:500])
        if result:
            _translation_cache[text] = result
            time.sleep(0.3)  # rythme doux, respectueux du service gratuit
            return result
    except Exception as e:
        log_error("traduction", text[:60], e)
    return text

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
            if getattr(feed, "bozo", 0) and not feed.entries:
                raise RuntimeError(getattr(feed, "bozo_exception", "flux RSS illisible / vide"))
            items = []
            for entry in feed.entries[:max_items]:
                title_en = entry.get("title", "").strip()
                items.append({
                    "title": title_en,
                    "title_ar": translate_title(title_en) if title_en.isascii() else title_en,
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
            if items:
                results[name] = items
                log_ok(name)
            else:
                raise RuntimeError("aucun article retourné")
        except Exception as e:
            log_error("RSS", name, e)
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
            r.raise_for_status()
            data = r.json().get("current", {})
            if not data:
                raise RuntimeError("réponse sans champ 'current'")
            out[city] = data
            log_ok(f"Météo {city}")
        except Exception as e:
            log_error("Météo", city, e)
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
                    log_ok(f"Marché {label}")
                else:
                    raise RuntimeError("historique vide")
            except Exception as e:
                log_error("Marchés", label, e)
    except ImportError as e:
        log_error("Marchés", "yfinance", e)

    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum", "vs_currencies": "usd"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        crypto = r.json()
        if not crypto:
            raise RuntimeError("réponse vide")
        markets["crypto"] = crypto
        log_ok("Crypto (CoinGecko)")
    except Exception as e:
        log_error("Crypto", "CoinGecko", e)

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
            r.raise_for_status()
            states = r.json().get("states") or []
            out[name] = len(states)
            log_ok(f"Vols {name}")
        except Exception as e:
            log_error("Vols", name, e)
    return out

# ---------------------------------------------------------------------------
# Résumé lisible pour GitHub Actions (Job Summary)
# ---------------------------------------------------------------------------
def write_job_summary():
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = ["## 🛰️ Résultat de la mise à jour GCC Live\n"]
    lines.append(f"Généré : `{datetime.datetime.now(datetime.UTC).isoformat()}`\n")
    lines.append("| Source | Statut |")
    lines.append("|---|---|")
    for src, ok in sorted(STATUS.items()):
        lines.append(f"| {src} | {'✅' if ok else '❌'} |")
    if ERRORS:
        lines.append("\n### Détail des erreurs\n")
        lines.append("| Étape | Source | Erreur |")
        lines.append("|---|---|---|")
        for e in ERRORS:
            err = e["error"].replace("|", "\\|")
            lines.append(f"| {e['stage']} | {e['source']} | {err} |")
    else:
        lines.append("\nAucune erreur — toutes les sources ont répondu. ✅\n")
    text = "\n".join(lines)
    print(text)
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    news = fetch_rss()
    weather = fetch_weather()
    markets = fetch_markets()
    flights = fetch_flights()

    payload = {
        "generated_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "news": news,
        "weather": weather,
        "markets": markets,
        "flights": flights,
        "_meta": {
            "status": STATUS,
            "errors": ERRORS,
            "ok": len(ERRORS) == 0,
        },
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    save_cache(_translation_cache)

    write_job_summary()
    print(f"OK - data.json généré ({len(json.dumps(payload))} octets), {len(ERRORS)} erreur(s)")

    # Le job ne doit PAS échouer bruyamment pour une source en panne isolée
    # (le dashboard doit rester en ligne avec des données partielles) —
    # mais si TOUT a échoué, on fait échouer le run pour être alerté.
    if news == {} and weather == {} and markets == {} and flights == {}:
        print("::error title=Panne totale::Toutes les sources ont échoué, voir le tableau ci-dessus.")
        sys.exit(1)

if __name__ == "__main__":
    main()
