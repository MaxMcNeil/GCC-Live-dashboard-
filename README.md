# GCC Live Desk — Dashboard temps réel pour OBS

Dashboard broadcast (actus, météo, devises, pétrole, crypto, trafic aérien) pour
Arabie Saoudite, Émirats, Oman, Koweït — 100% gratuit, hébergé sur GitHub Pages,
alimenté par GitHub Actions toutes les 10 minutes.

## 1. Déploiement (5 min)

1. Crée un nouveau repo GitHub (public, gratuit) et pousse tout ce dossier dedans :
   ```bash
   git init
   git add .
   git commit -m "init gcc live desk"
   git branch -M main
   git remote add origin https://github.com/<ton-user>/<ton-repo>.git
   git push -u origin main
   ```
2. Dans **Settings > Pages**, source = **GitHub Actions** (pas "Deploy from branch").
3. Dans **Settings > Actions > General**, coche **"Read and write permissions"**
   pour le workflow (nécessaire pour committer `data.json` automatiquement).
4. Lance manuellement le workflow une première fois : onglet **Actions** →
   "Update GCC Live Data" → **Run workflow**.
5. Ton dashboard sera en ligne sur :
   `https://<ton-user>.github.io/<ton-repo>/`

Il se rafraîchit tout seul : GitHub Actions relance `fetch_data.py` toutes les
10 min, commit le nouveau `data.json`, republie la page. Aucun serveur à gérer.

## 2. Brancher ça dans OBS (le vrai direct)

**Important** : GitHub Pages héberge une page web, pas un flux vidéo. Pour
passer "en direct" sur YouTube/Twitch/Instagram, il te faut OBS Studio (gratuit)
qui capture cette page et l'encode vers la plateforme via une clé de stream.

1. Ouvre OBS Studio → **Sources** → **+** → **Source Navigateur**.
2. Colle l'URL de ta page GitHub Pages.
3. Format paysage (1920x1080) : mets Largeur=1920, Hauteur=1080 → utilise la page telle quelle.
4. Format vertical (1080x1920, pour Reels/Shorts/TikTok) : crée une seconde
   **Scene** dans OBS avec une résolution de canevas 1080x1920 (Paramètres →
   Vidéo → Résolution de base), et ajoute la même Source Navigateur — le CSS
   du dashboard détecte automatiquement l'orientation et réarrange la mise en page.
5. Dans OBS, **Paramètres → Flux** → colle ta clé de stream (YouTube Studio →
   Créer un direct → clé RTMP, gratuite).
6. Pour un direct 24/7 sans garder ton PC allumé, OBS doit tourner sur une
   machine dédiée — un petit VPS gratuit (ex: offre gratuite Oracle Cloud) avec
   OBS headless + `ffmpeg` est l'option 100% gratuite la plus courante. Dis-moi
   si tu veux ce guide, c'est une étape à part.

## 3. Sources de données utilisées (toutes publiques et gratuites)

| Thème | Source | Type |
|---|---|---|
| Actualités officielles | SPA, WAM, Oman Observer, Google News | RSS public |
| Météo | Open-Meteo | API publique sans clé |
| Devises / Or / Pétrole | Yahoo Finance (yfinance) | Librairie Python |
| Crypto | CoinGecko | API publique |
| Trafic aérien | OpenSky Network | Open data ADS-B |

## 4. Notes importantes

- **Fiabilité de l'info** : le dashboard n'affiche que ce que les flux
  officiels publient réellement — pas de contenu inventé ou dramatisé. C'est
  ce qui construit une audience qui reste dans la durée, surtout un public
  qui vérifie ses sources.
- Les flux "faits divers / police" via Nitter ou RSSHub (mentionnés dans le
  brief initial) ne sont pas inclus par défaut : ce sont des contournements
  non-officiels de Twitter/Telegram, souvent instables et parfois contraires
  aux CGU. Si tu veux les ajouter quand même, dis-le moi et je t'explique les
  limites/risques exacts.
- Tout le pipeline tourne sur l'infra gratuite de GitHub (2 000 min
  Actions/mois sur repo public = largement suffisant pour un cron/10 min).
