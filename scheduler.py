# scheduler.py — Jobs automatiques NeoLinkStudio (AsyncIOScheduler)
# Tourne dans le même event loop asyncio que le bot Telegram (main thread).
import os
import asyncio
import logging
import functools
import requests
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import database as db

logger = logging.getLogger(__name__)

MONTREAL_TZ = pytz.timezone("America/Montreal")
TELEGRAM_USER_ID = int(os.environ.get("TELEGRAM_USER_ID", "0"))
APP_URL = os.environ.get("APP_URL", "http://localhost:5000")

# Référence à l'application Telegram (partagée depuis app.py via set_bot_app)
_bot_app = None

# Garde-fou re-engagement : un seul message par jour
_re_engagement_sent = {"date": None}


def set_bot_app(app):
    """Définit l'application Telegram. Appelé depuis app.py après create_application()."""
    global _bot_app
    _bot_app = app


# ─── Envoi de messages Telegram (async) ───────────────────────────────────────

async def _send_message(text: str):
    """Envoie un message Telegram. S'exécute dans le main event loop."""
    if not _bot_app:
        logger.warning("_send_message: bot non initialisé")
        return
    try:
        await _bot_app.bot.send_message(
            chat_id=TELEGRAM_USER_ID,
            text=text,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Erreur envoi message Telegram: {e}")


# ─── Jobs planifiés ────────────────────────────────────────────────────────────

async def job_morning_briefing():
    """Briefing matinal à 8h30 heure de Montréal — 3 prochaines tâches."""
    try:
        tasks = db.get_top_tasks(3)
        now_str = datetime.now(MONTREAL_TZ).strftime("%A %d %B")

        if not tasks:
            await _send_message(
                f"☀️ *Bonjour Tao!* ({now_str})\n\n"
                "Aucune tâche en attente. Ajoutes-en sur le dashboard! 🎉"
            )
            return

        priority_emoji = {"bloquant": "🔴", "cette_semaine": "🟡", "backlog": "🟢"}
        texte = f"☀️ *Briefing matinal — NeoLinkStudio* ({now_str})\n\n"

        for i, task in enumerate(tasks, 1):
            emoji = priority_emoji.get(task["priority"], "⚪")
            texte += f"{i}. {emoji} *{task['title']}*\n"
            if task.get("description"):
                desc = task["description"]
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                texte += f"   _{desc}_\n"
            texte += "\n"

        texte += "💪 Bonne journée! Tape /next pour commencer."
        await _send_message(texte)
        logger.info("✅ Briefing matinal envoyé")

    except Exception as e:
        logger.error(f"Erreur job briefing matinal: {e}")


async def job_self_ping():
    """
    Self-ping toutes les 10 minutes pour éviter la mise en veille sur Render.
    requests.get est synchrone — on l'exécute dans un executor pour ne pas
    bloquer l'event loop.
    """
    try:
        loop = asyncio.get_running_loop()
        fn = functools.partial(requests.get, f"{APP_URL}/ping", timeout=10)
        response = await loop.run_in_executor(None, fn)
        if response.status_code == 200:
            logger.debug("Self-ping OK")
        else:
            logger.warning(f"Self-ping retourné {response.status_code}")
    except requests.exceptions.ConnectionError:
        logger.debug("Self-ping: connexion refusée (normal au démarrage)")
    except Exception as e:
        logger.debug(f"Self-ping: {e}")


async def job_check_re_engagement():
    """
    Vérifie si Tao est inactif depuis plus de 3h entre 10h et 17h.
    Envoie UN seul message de re-engagement par jour.
    """
    try:
        now = datetime.now(MONTREAL_TZ)
        today = now.date()

        # Uniquement entre 10h et 17h
        if not (10 <= now.hour < 17):
            return

        # Un seul message par jour
        if _re_engagement_sent["date"] == today:
            return

        last_completion_str = db.get_last_completion_time()
        should_send = False
        hours_inactive = 0

        if last_completion_str is None:
            # Aucune tâche complétée aujourd'hui — envoyer si on dépasse 13h (10h + 3h)
            if now.hour >= 13:
                should_send = True
                hours_inactive = now.hour - 10
        else:
            try:
                last_dt = datetime.fromisoformat(last_completion_str)
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
            await _send_message(msg)
            logger.info("✅ Message de re-engagement envoyé")

    except Exception as e:
        logger.error(f"Erreur job re-engagement: {e}")


# ─── Création du scheduler ─────────────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    """
    Crée et configure l'AsyncIOScheduler avec les 3 jobs.
    Doit être appelé depuis un contexte asyncio (main thread) afin que
    le scheduler partage automatiquement le bon event loop.
    """
    scheduler = AsyncIOScheduler(timezone=MONTREAL_TZ)

    # Job 1 : Briefing matinal à 8h30
    scheduler.add_job(
        job_morning_briefing,
        CronTrigger(hour=8, minute=30, timezone=MONTREAL_TZ),
        id="morning_briefing",
        name="Briefing matinal",
        replace_existing=True,
    )

    # Job 2 : Self-ping toutes les 10 minutes
    scheduler.add_job(
        job_self_ping,
        "interval",
        minutes=10,
        id="self_ping",
        name="Self-ping Render",
        replace_existing=True,
    )

    # Job 3 : Vérification re-engagement toutes les 30 min entre 10h et 17h
    scheduler.add_job(
        job_check_re_engagement,
        CronTrigger(hour="10-16", minute="0,30", timezone=MONTREAL_TZ),
        id="re_engagement",
        name="Vérification re-engagement",
        replace_existing=True,
    )

    logger.info("AsyncIOScheduler configuré (3 jobs)")
    return scheduler
