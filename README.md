# NeoLink Daily Dashboard

Dashboard de productivité personnel pour NeoLinkStudio — construit avec Flask, SQLite, Telegram Bot et Claude (Anthropic).

## Fonctionnalités

- **Dashboard web** : tâches groupées par priorité (🔴 Bloquant / 🟡 Cette semaine / 🟢 Backlog), interface sombre et minimaliste
- **Bot Telegram** : `/next`, `/done`, `/stuck`, `/briefing` + conversation libre avec Claude
- **Automatisations** : briefing matinal à 8h30 (MTL), self-ping anti-sleep, alerte de re-engagement
- **IA générative** : génération automatique de 15 tâches initiales au premier lancement

---

## Déploiement sur Render

### 1. Préparer le dépôt GitHub

```bash
git init
git add .
git commit -m "Initial commit — NeoLink Dashboard"
git remote add origin https://github.com/TON_USERNAME/neolinkdashboard.git
git push -u origin main
```

### 2. Créer le service sur Render

1. Aller sur [render.com](https://render.com) → **New** → **Web Service**
2. Connecter le dépôt GitHub
3. Configurer le service :
   - **Name** : `neolinkdashboard` (ou autre)
   - **Region** : `US East (Ohio)` ou `Oregon` (le plus proche)
   - **Branch** : `main`
   - **Runtime** : `Python 3`
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `python app.py`
   - **Instance Type** : Free (suffisant pour usage personnel)

### 3. Variables d'environnement

Dans l'onglet **Environment** du service Render, ajouter les variables suivantes :

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token du bot Telegram (obtenu via @BotFather) |
| `TELEGRAM_USER_ID` | Ton ID Telegram (obtenu via @userinfobot) |
| `ANTHROPIC_API_KEY` | Clé API Anthropic (console.anthropic.com) |
| `SECRET_KEY` | Clé secrète Flask pour les sessions (chaîne aléatoire) |
| `APP_URL` | URL publique Render, ex: `https://neolinkdashboard.onrender.com` |
| `PORT` | **Ne pas définir** — Render le fournit automatiquement |

### 4. Configurer APP_URL

Après le premier déploiement, copier l'URL publique Render (ex: `https://neolinkdashboard.onrender.com`) et l'ajouter comme variable `APP_URL`. Cela active le self-ping anti-sleep.

---

## Structure des fichiers

```
neolinkdashboard/
├── app.py          # Flask + routes + démarrage du bot et scheduler
├── bot.py          # Bot Telegram (python-telegram-bot async)
├── scheduler.py    # Jobs APScheduler (briefing, ping, re-engagement)
├── database.py     # Helpers SQLite
├── ai.py           # Appels API Anthropic
├── templates/
│   └── index.html  # Dashboard HTML/CSS/JS (vanilla, dark theme)
├── requirements.txt
├── Procfile        # Point d'entrée Render
└── README.md
```

---

## Commandes Telegram

| Commande | Action |
|---|---|
| `/start` | Message de bienvenue + liste des commandes |
| `/next` | Affiche la prochaine tâche prioritaire |
| `/done` | Marque la tâche affichée comme complétée |
| `/stuck` | Décompose la tâche en 3-5 micro-étapes (via Claude) |
| `/briefing` | Affiche les 3 prochaines tâches |
| *(message libre)* | Conversation avec Claude (contexte NeoLinkStudio injecté) |

---

## Développement local

```bash
# Installer les dépendances
pip install -r requirements.txt

# Définir les variables d'environnement
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_USER_ID="..."
export ANTHROPIC_API_KEY="..."
export SECRET_KEY="dev-secret-key"
export APP_URL="http://localhost:5000"

# Lancer l'application
python app.py
```

L'application sera accessible sur [http://localhost:5000](http://localhost:5000).

---

## Notes importantes

- **Single process** : Flask + Bot Telegram + Scheduler tournent dans le même processus Python
- **Base de données** : SQLite locale (`tasks.db`) — persistée sur le disque Render si un disque est configuré, sinon réinitialisée à chaque déploiement
- **Persistence** : Pour conserver les données entre déploiements Render, ajouter un **Disk** dans le service (Mount Path: `/opt/render/project/src`, taille: 1 GB)
- **Sécurité** : Le bot ne répond qu'à l'utilisateur défini par `TELEGRAM_USER_ID`
