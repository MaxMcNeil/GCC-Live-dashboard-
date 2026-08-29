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

# ---------------------------------------------------------------------------
# 0bis. Garde-fous anti-mistraduction dangereuse
# ---------------------------------------------------------------------------
# Le jargon sportif/tabloïd anglais utilise des métaphores violentes de façon
# hyperbolique et inoffensive ("hit squad" = équipe de choc, "killer instinct"
# = instinct de gagnant, "demolished" = a largement battu...). Traduites mot à
# mot en arabe, ces expressions prennent un sens littéral alarmant qui n'existe
# pas dans le texte original. On neutralise ces idiomes AVANT traduction.
IDIOM_NORMALIZE = {
    "hit squad": "elite squad",
    "killer instinct": "winning instinct",
    "gunning for": "aiming for",
    "assassinate the record": "smash the record",
    "slaughtered": "defeated heavily",
    "annihilated": "defeated decisively",
    "demolished": "defeated decisively",
    "blew away": "clearly outperformed",
    "wiped out": "defeated",
    "executed the plan": "carried out the plan",
    "shot down": "rejected",
}

def normalize_idioms(text):
    lowered = text
    for phrase, safe in IDIOM_NORMALIZE.items():
        # remplacement insensible à la casse, en conservant le reste du texte
        idx = lowered.lower().find(phrase)
        if idx != -1:
            lowered = lowered[:idx] + safe + lowered[idx+len(phrase):]
    return lowered

# Mots arabes à forte charge (violence réelle) : si la traduction en contient
# un mais que l'anglais original ne porte aucun signal correspondant, on
# considère la traduction comme suspecte et on ne l'utilise pas.
ALARM_SIGNALS_AR_TO_EN = {
    "اغتيال": ["assassin"],
    "إرهاب": ["terror"],
    "قتل": ["kill", "murder", "slay"],
    "تفجير": ["explod", "bomb", "blast"],
    "انفجار": ["explod", "bomb", "blast"],
    "مجزرة": ["massacre"],
}

def is_translation_suspicious(original_en, translated_ar):
    orig_lower = original_en.lower()
    for ar_word, en_signals in ALARM_SIGNALS_AR_TO_EN.items():
        if ar_word in translated_ar and not any(sig in orig_lower for sig in en_signals):
            return True
    return False

def translate_title(text):
    """Traduit un titre EN -> AR. Ne bloque jamais le pipeline :
    en cas d'échec OU de traduction jugée dangereuse/suspecte, retourne le
    texte original (l'UI l'affichera tel quel plutôt que d'afficher une
    fausse information alarmante)."""
    if not text:
        return text
    if text in _translation_cache:
        return _translation_cache[text]
    if not TRANSLATOR_AVAILABLE:
        return text
    try:
        safe_source = normalize_idioms(text)
        result = _translator.translate(safe_source[:500])
        if result:
            if is_translation_suspicious(text, result):
                log_error("traduction-suspecte", text[:60],
                          Exception(f"traduction rejetée (contenu alarmant non justifié): {result[:80]}"))
                _translation_cache[text] = text  # on met en cache l'original pour ne pas retraduire à chaque run
                return text
            _translation_cache[text] = result
            time.sleep(0.3)  # rythme doux, respectueux du service gratuit
            return result
    except Exception as e:
        log_error("traduction", text[:60], e)
    return text

# ---------------------------------------------------------------------------
# 1. Flux RSS — priorité absolue aux sources NATIVEMENT arabes
# ---------------------------------------------------------------------------
# Stratégie changée : traduire des titres anglais (même avec garde-fous)
# produit un arabe globalement maladroit dès que la phrase est un peu longue,
# pas seulement sur des idiomes isolés. La vraie solution est d'aller chercher
# des articles déjà écrits en arabe par de vrais médias arabes, plutôt que de
# les faire passer par une machine à traduire gratuite.
RSS_FEEDS = {
    "وكالة الأنباء السعودية (SPA) 🇸🇦": "https://www.spa.gov.sa/rss.php?lang=ar",
    "وكالة أنباء الإمارات (WAM) 🇦🇪": "https://www.wam.ae/ar/rss",
    "أخبار السعودية 🇸🇦": "https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B3%D8%B9%D9%88%D8%AF%D9%8A%D8%A9&hl=ar&gl=SA&ceid=SA:ar",
    "أخبار الإمارات 🇦🇪": "https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%A5%D9%85%D8%A7%D8%B1%D8%A7%D8%AA&hl=ar&gl=AE&ceid=AE:ar",
    "أخبار عُمان 🇴🇲": "https://news.google.com/rss/search?q=%D8%B9%D9%8F%D9%85%D8%A7%D9%86&hl=ar&gl=OM&ceid=OM:ar",
    "أخبار الكويت 🇰🇼": "https://news.google.com/rss/search?q=%D8%A7%D9%84%D9%83%D9%88%D9%8A%D8%AA&hl=ar&gl=KW&ceid=KW:ar",
}

def fetch_rss(max_items=6):
    results = {}
    seen_links = set()   # dédup inter-sources : le même article ne doit apparaître qu'une fois
    seen_titles = set()  # repli si le lien est absent/vide : titre normalisé

    def normalize_title(t):
        return " ".join(t.split()).strip().lower()

    for name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            if getattr(feed, "bozo", 0) and not feed.entries:
                raise RuntimeError(getattr(feed, "bozo_exception", "flux RSS illisible / vide"))
            items = []
            for entry in feed.entries[:max_items]:
                title_en = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                norm = normalize_title(title_en)

                # Plusieurs de nos flux (Google News par pays + agences officielles)
                # remontent souvent LA MÊME actualité régionale (ex: un communiqué de
                # solidarité repris partout). On ne garde que la première occurrence.
                if link:
                    if link in seen_links:
                        continue
                    seen_links.add(link)
                elif norm:
                    if norm in seen_titles:
                        continue
                    seen_titles.add(norm)

                items.append({
                    "title": title_en,
                    "title_ar": translate_title(title_en) if title_en.isascii() else title_en,
                    "link": link,
                    "published": entry.get("published", ""),
                })
            if items:
                results[name] = items
                log_ok(name)
            else:
                raise RuntimeError("aucun article retourné (ou tout était en doublon d'une autre source)")
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
