# bot.py — Bot Telegram NeoLinkStudio (python-telegram-bot async)
import os
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import database as db
import ai

logger = logging.getLogger(__name__)

# ID Telegram de l'utilisateur autorisé (sécurité de base)
TELEGRAM_USER_ID = int(os.environ.get("TELEGRAM_USER_ID", "0"))
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Stockage en mémoire de la dernière tâche montrée (par session)
_last_shown_task = {"id": None}

# Emojis par priorité
PRIORITY_EMOJI = {
    "bloquant": "🔴",
    "cette_semaine": "🟡",
    "backlog": "🟢",
}


def _check_user(update: Update) -> bool:
    """Vérifie que le message provient de l'utilisateur autorisé."""
    return update.effective_user.id == TELEGRAM_USER_ID


def _format_task_detail(task: dict) -> str:
    """Formate une tâche pour affichage détaillé sur Telegram."""
    emoji = PRIORITY_EMOJI.get(task["priority"], "⚪")
    status_icon = "✅" if task["status"] == "done" else "⏳"
    lines = [f"{status_icon} {emoji} *{task['title']}*"]

    if task.get("description"):
        lines.append(f"📝 {task['description']}")
    if task.get("comment_faire"):
        lines.append(f"💡 *Comment faire:* {task['comment_faire']}")
    if task.get("done_criteria"):
        lines.append(f"✔️ *Critère:* {task['done_criteria']}")

    return "\n".join(lines)


# ─── Handlers des commandes ────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start — message de bienvenue et liste des commandes."""
    if not _check_user(update):
        return

    texte = (
        "👋 *Bonjour Tao\\! Je suis ton assistant NeoLinkStudio\\.*\n\n"
        "Voici ce que je peux faire:\n"
        "• /next — Prochaine tâche prioritaire\n"
        "• /done — Marquer la tâche actuelle comme faite\n"
        "• /stuck — Décomposer en micro\\-étapes\n"
        "• /briefing — Voir les 3 prochaines tâches\n\n"
        "💬 Tu peux aussi me parler librement\\!\n"
        "Je connais tout ton contexte NeoLinkStudio\\."
    )
    await update.message.reply_text(texte, parse_mode="MarkdownV2")


async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /next — affiche la prochaine tâche non complétée."""
    if not _check_user(update):
        return

    task = db.get_next_task()
    if not task:
        await update.message.reply_text(
            "🎉 Toutes les tâches sont complétées\\! Ajoutes\\-en de nouvelles sur le dashboard\\.",
            parse_mode="MarkdownV2",
        )
        return

    _last_shown_task["id"] = task["id"]
    texte = "📌 *Prochaine tâche:*\n\n" + _format_task_detail(task)
    await update.message.reply_text(texte, parse_mode="Markdown")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /done — marque la dernière tâche montrée comme complétée."""
    if not _check_user(update):
        return

    task_id = _last_shown_task.get("id")
    if not task_id:
        await update.message.reply_text(
            "Utilise /next d'abord pour voir une tâche\\!",
            parse_mode="MarkdownV2",
        )
        return

    task = db.get_task_by_id(task_id)
    if not task:
        await update.message.reply_text("Tâche introuvable.")
        return

    if task["status"] == "done":
        await update.message.reply_text(
            f"Cette tâche est déjà complétée\\! Tape /next pour la suivante\\.",
            parse_mode="MarkdownV2",
        )
        return

    db.mark_done(task_id)
    _last_shown_task["id"] = None

    await update.message.reply_text(
        f"✅ *{task['title']}* — Complétée\\! 🔥\n\nTape /next pour continuer\\.",
        parse_mode="MarkdownV2",
    )


async def cmd_stuck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /stuck — décompose la tâche prioritaire en micro-étapes via Claude."""
    if not _check_user(update):
        return

    task = db.get_next_task()
    if not task:
        await update.message.reply_text("Aucune tâche en attente\\!", parse_mode="MarkdownV2")
        return

    await update.message.reply_text("⚙️ Génération des micro\\-étapes en cours\\.\\.\\.", parse_mode="MarkdownV2")

    # Appel IA dans un executor pour ne pas bloquer l'event loop async
    loop = asyncio.get_running_loop()
    steps = await loop.run_in_executor(None, ai.get_micro_steps, task)

    # Échapper les caractères spéciaux pour MarkdownV2 dans le titre
    title_safe = task["title"].replace(".", "\\.").replace("!", "\\!").replace("-", "\\-").replace("(", "\\(").replace(")", "\\)")
    texte = f"🔍 *Micro\\-étapes pour:* {title_safe}\n\n{steps}"

    # Envoyer en Markdown simple car les micro-étapes peuvent contenir des caractères variés
    try:
        await update.message.reply_text(texte, parse_mode="MarkdownV2")
    except Exception:
        await update.message.reply_text(f"🔍 Micro-étapes pour: {task['title']}\n\n{steps}")


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /briefing — affiche les 3 prochaines tâches prioritaires."""
    if not _check_user(update):
        return

    tasks = db.get_top_tasks(3)
    if not tasks:
        await update.message.reply_text(
            "🎉 Aucune tâche en attente\\! Dashboard propre\\.",
            parse_mode="MarkdownV2",
        )
        return

    texte = "📋 *Briefing — 3 prochaines tâches:*\n\n"
    for i, task in enumerate(tasks, 1):
        emoji = PRIORITY_EMOJI.get(task["priority"], "⚪")
        texte += f"{i}\\. {emoji} *{task['title']}*\n"
        if task.get("description"):
            desc = task["description"]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            texte += f"   _{desc}_\n"
        texte += "\n"

    try:
        await update.message.reply_text(texte, parse_mode="MarkdownV2")
    except Exception:
        # Fallback sans Markdown si des caractères posent problème
        texte_plain = "📋 Briefing — 3 prochaines tâches:\n\n"
        for i, task in enumerate(tasks, 1):
            emoji = PRIORITY_EMOJI.get(task["priority"], "⚪")
            texte_plain += f"{i}. {emoji} {task['title']}\n"
            if task.get("description"):
                texte_plain += f"   {task['description'][:80]}\n"
            texte_plain += "\n"
        await update.message.reply_text(texte_plain)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les messages texte libres — conversation avec Claude."""
    if not _check_user(update):
        return

    message = update.message.text
    tasks = db.get_all_tasks()

    # Appel IA dans un executor pour ne pas bloquer
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(None, ai.chat_with_claude, message, tasks)

    await update.message.reply_text(response)


# ─── Création de l'application ─────────────────────────────────────────────────

def create_application() -> Application:
    """Crée et configure l'application Telegram avec tous les handlers."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN non défini dans les variables d'environnement")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Enregistrement des handlers de commandes
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("stuck", cmd_stuck))
    app.add_handler(CommandHandler("briefing", cmd_briefing))

    # Handler pour les messages texte libres (hors commandes)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Application Telegram configurée avec succès")
    return app
