# scheduler.py — Jobs automatiques APScheduler pour NeoLinkStudio
import os
import asyncio
import logging
import requests
from datetime import datetime, date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import database as db

logger = logging.getLogger(__name__)

# Timezone de Montréal
MONTREAL_TZ = pytz.timezone("America/Montreal")

# Variables globales pour la communication cross-thread
_bot_app = None      # Référence à l'application Telegram
_bot_loop = None     # Event loop du thread bot (pour asyncio.run_coroutine_threadsafe)

# Garde-fou pour le message de re-engagement (1 seul par jour)
_re_engagement_sent = {"date": None}

# URL de l'application pour le self-ping (configurable via variable d'env)
APP_URL = os.environ.get("APP_URL", "http://localhost:5000")
TELEGRAM_USER_ID = int(os.environ.get("TELEGRAM_USER_ID", "0"))


def set_bot_app(app):
    """Définit l'application Telegram. Appelé depuis app.py au démarrage."""
    global _bot_app
    _bot_app = app


def set_bot_loop(loop):
    """Définit l'event loop du thread bot. Appelé depuis le thread bot."""
    global _bot_loop
    _bot_loop = loop


def _send_telegram_sync(text: str):
    """
    Envoie un message Telegram depuis un contexte synchrone (job APScheduler).
    Utilise asyncio.run_coroutine_threadsafe pour envoyer dans le loop du bot.
    """
    if not _bot_app or not _bot_loop:
        logger.warning("Bot non initialisé, impossible d'envoyer le message Telegram")
        return

    async def _send():
        try:
            await _bot_app.bot.send_message(
                chat_id=TELEGRAM_USER_ID,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Erreur envoi message Telegram: {e}")

    try:
        future = asyncio.run_coroutine_threadsafe(_send(), _bot_loop)
        future.result(timeout=15)
    except Exception as e:
        logger.error(f"Erreur run_coroutine_threadsafe: {e}")


# ─── Jobs planifiés ────────────────────────────────────────────────────────────

def job_morning_briefing():
    """
    Briefing matinal: envoyé à 8h30 heure de Montréal.
    Affiche les 3 prochaines tâches prioritaires.
    """
    try:
        tasks = db.get_top_tasks(3)
        now_str = datetime.now(MONTREAL_TZ).strftime("%A %d %B")

        if not tasks:
            _send_telegram_sync(
                f"☀️ *Bonjour Tao!* ({now_str})\n\n"
                "Aucune tâche en attente. Ajoutes-en de nouvelles sur le dashboard! 🎉"
            )
            return

        priority_emoji = {"bloquant": "🔴", "cette_semaine": "🟡", "backlog": "🟢"}
        texte = f"☀️ *Briefing matinal — NeoLinkStudio* ({now_str})\n\n"

        for i, task in enumerate(tasks, 1):
            emoji = priority_emoji.get(task["priority"], "⚪")
            texte += f"{i}. {emoji} *{task['title']}*\n"
            if task.get("description"):
                desc = task["description"][:80] + ("..." if len(task["description"]) > 80 else "")
                texte += f"   _{desc}_\n"
            texte += "\n"

        texte += "💪 Bonne journée! Tape /next pour commencer."
        _send_telegram_sync(texte)
        logger.info("✅ Briefing matinal envoyé")

    except Exception as e:
        logger.error(f"Erreur job briefing matinal: {e}")


def job_self_ping():
    """
    Self-ping toutes les 10 minutes pour éviter la mise en veille sur Render.
    Envoie une requête GET sur /ping.
    """
    try:
        response = requests.get(f"{APP_URL}/ping", timeout=10)
        if response.status_code == 200:
            logger.debug("Self-ping OK")
        else:
            logger.warning(f"Self-ping retourné {response.status_code}")
    except requests.exceptions.ConnectionError:
        logger.debug("Self-ping: connexion refusée (normal au démarrage)")
    except Exception as e:
        logger.debug(f"Self-ping: {e}")


def job_check_re_engagement():
    """
    Vérifie si Tao est inactif depuis plus de 3h entre 10h et 17h.
    Envoie UN seul message de re-engagement par jour si nécessaire.
    """
    try:
        now = datetime.now(MONTREAL_TZ)
        today = now.date()

        # Vérifier seulement entre 10h et 17h
        if not (10 <= now.hour < 17):
            return

        # Un seul message de re-engagement par jour
        if _re_engagement_sent["date"] == today:
            return

        last_completion_str = db.get_last_completion_time()

        should_send = False
        hours_inactive = 0

        if last_completion_str is None:
            # Aucune tâche complétée aujourd'hui — envoyer si on est après 13h (10h + 3h)
            if now.hour >= 13:
                should_send = True
                hours_inactive = now.hour - 10
        else:
            # Calculer le temps écoulé depuis la dernière complétion
            try:
                last_dt = datetime.fromisoformat(last_completion_str)
                # Assurer que la date est timezone-aware
                if last_dt.tzinfo is None:
                    last_dt = MONTREAL_TZ.localize(last_dt)
                else:
                    last_dt = last_dt.astimezone(MONTREAL_TZ)

                hours_inactive = (now - last_dt).total_seconds() / 3600
                if hours_inactive >= 3:
                    should_send = True
            except ValueError as e:
                logger.error(f"Erreur parsing date complétion: {e}")

        if should_send:
            _re_engagement_sent["date"] = today
            heures = int(hours_inactive)
            if heures > 0:
                msg = (
                    f"⚡ *Hé Tao!* Ça fait {heures}h sans progression sur NeoLinkStudio.\n\n"
                    "Une petite tâche, c'est mieux que zéro. Tape /next! 🚀"
                )
            else:
                msg = (
                    "⚡ *Hé Tao!* Aucune tâche complétée depuis ce matin.\n\n"
                    "Lance-toi sur la prochaine priorité. Tape /next! 💪"
                )
            _send_telegram_sync(msg)
            logger.info("✅ Message de re-engagement envoyé")

    except Exception as e:
        logger.error(f"Erreur job re-engagement: {e}")


# ─── Création du scheduler ─────────────────────────────────────────────────────

def create_scheduler() -> BackgroundScheduler:
    """
    Crée et configure le scheduler APScheduler avec tous les jobs.
    Le scheduler est retourné mais PAS démarré (appelé depuis app.py).
    """
    scheduler = BackgroundScheduler(timezone=MONTREAL_TZ)

    # Job 1: Briefing matinal à 8h30 heure de Montréal
    scheduler.add_job(
        job_morning_briefing,
        CronTrigger(hour=8, minute=30, timezone=MONTREAL_TZ),
        id="morning_briefing",
        name="Briefing matinal NeoLinkStudio",
        replace_existing=True,
    )

    # Job 2: Self-ping toutes les 10 minutes pour Render
    scheduler.add_job(
        job_self_ping,
        "interval",
        minutes=10,
        id="self_ping",
        name="Self-ping Render",
        replace_existing=True,
    )

    # Job 3: Vérification re-engagement toutes les 30 minutes entre 10h et 17h
    scheduler.add_job(
        job_check_re_engagement,
        CronTrigger(hour="10-16", minute="0,30", timezone=MONTREAL_TZ),
        id="re_engagement",
        name="Vérification re-engagement",
        replace_existing=True,
    )

    logger.info("Scheduler APScheduler configuré (3 jobs)")
    return scheduler
