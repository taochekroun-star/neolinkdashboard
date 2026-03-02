# app.py — Application Flask principale + démarrage du bot et du scheduler
import os
import threading
import asyncio
import logging

from flask import Flask, render_template, request, jsonify

import database as db
import ai
from bot import create_application
from scheduler import create_scheduler, set_bot_app, set_bot_loop

# ─── Configuration du logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Initialisation Flask ──────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "neolinkstudio-fallback-key")

# Initialisation de la base de données au démarrage
db.init_db()


def _generate_tasks_if_empty():
    """Génère les tâches initiales via l'API Anthropic si la DB est vide."""
    if db.is_empty():
        logger.info("DB vide — génération des tâches initiales par l'IA...")
        tasks = ai.generate_initial_tasks()
        if tasks:
            for task in tasks:
                db.insert_task(
                    title=task.get("title", "Tâche sans titre"),
                    description=task.get("description", ""),
                    comment_faire=task.get("comment_faire", ""),
                    done_criteria=task.get("done_criteria", ""),
                    priority=task.get("priority", "backlog"),
                )
            logger.info(f"✅ {len(tasks)} tâches insérées en base")
        else:
            logger.error("Aucune tâche générée par l'IA — vérifier ANTHROPIC_API_KEY")


# ─── Routes Flask ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Page principale du dashboard — affiche les tâches groupées par priorité."""
    _generate_tasks_if_empty()
    tasks = db.get_all_tasks()
    stats = db.get_stats()

    # Grouper les tâches par priorité
    grouped = {
        "bloquant": [t for t in tasks if t["priority"] == "bloquant"],
        "cette_semaine": [t for t in tasks if t["priority"] == "cette_semaine"],
        "backlog": [t for t in tasks if t["priority"] == "backlog"],
    }
    return render_template("index.html", grouped=grouped, stats=stats)


@app.route("/ping")
def ping():
    """Route health check — utilisée pour le self-ping et la surveillance Render."""
    return jsonify({"status": "ok", "service": "NeoLink Dashboard"}), 200


@app.route("/tasks", methods=["POST"])
def add_task():
    """Crée une nouvelle tâche."""
    data = request.get_json()
    if not data or not data.get("title", "").strip():
        return jsonify({"error": "Le titre est requis"}), 400

    task_id = db.insert_task(
        title=data["title"].strip(),
        description=data.get("description", "").strip(),
        comment_faire=data.get("comment_faire", "").strip(),
        done_criteria=data.get("done_criteria", "").strip(),
        priority=data.get("priority", "backlog"),
    )
    return jsonify({"id": task_id, "message": "Tâche créée avec succès"}), 201


@app.route("/tasks/<int:task_id>", methods=["GET"])
def get_task(task_id):
    """Retourne les données d'une tâche spécifique."""
    task = db.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Tâche introuvable"}), 404
    return jsonify(task)


@app.route("/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    """Met à jour une tâche existante."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Données manquantes"}), 400

    task = db.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Tâche introuvable"}), 404

    db.update_task(
        task_id=task_id,
        title=data.get("title", task["title"]).strip(),
        description=data.get("description", task["description"]).strip(),
        comment_faire=data.get("comment_faire", task["comment_faire"]).strip(),
        done_criteria=data.get("done_criteria", task["done_criteria"]).strip(),
        priority=data.get("priority", task["priority"]),
    )
    return jsonify({"message": "Tâche mise à jour"})


@app.route("/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    """Supprime une tâche."""
    task = db.get_task_by_id(task_id)
    if not task:
        return jsonify({"error": "Tâche introuvable"}), 404
    db.delete_task(task_id)
    return jsonify({"message": "Tâche supprimée"})


@app.route("/tasks/<int:task_id>/toggle", methods=["POST"])
def toggle_task(task_id):
    """Bascule le statut d'une tâche entre 'todo' et 'done'."""
    success = db.toggle_task(task_id)
    if not success:
        return jsonify({"error": "Tâche introuvable"}), 404
    task = db.get_task_by_id(task_id)
    return jsonify({"message": "Statut mis à jour", "status": task["status"]})


# ─── Démarrage du Bot Telegram ─────────────────────────────────────────────────

def _run_bot_in_thread(bot_app):
    """
    Lance le bot Telegram dans son propre event loop asyncio.
    Tourne dans un thread daemon séparé.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Partager le loop avec le scheduler pour les envois cross-thread
    set_bot_loop(loop)

    try:
        logger.info("Démarrage du bot Telegram (polling)...")
        loop.run_until_complete(
            bot_app.run_polling(
                allowed_updates=["message"],
                drop_pending_updates=True,
            )
        )
    except Exception as e:
        logger.error(f"Erreur fatale dans le thread bot: {e}")
    finally:
        loop.close()
        logger.info("Thread bot Telegram terminé")


# ─── Démarrage global (bot + scheduler) ───────────────────────────────────────

_startup_done = False


def startup():
    """
    Démarre le bot Telegram et le scheduler APScheduler.
    Appelé une seule fois au lancement du processus.
    """
    global _startup_done
    if _startup_done:
        return
    _startup_done = True

    logger.info("=== Démarrage NeoLink Dashboard ===")

    # Générer les tâches si la DB est vide
    _generate_tasks_if_empty()

    # Démarrer le bot Telegram dans un thread séparé
    try:
        bot_app = create_application()
        set_bot_app(bot_app)

        bot_thread = threading.Thread(
            target=_run_bot_in_thread,
            args=(bot_app,),
            daemon=True,
            name="TelegramBotThread",
        )
        bot_thread.start()
        logger.info("Thread bot Telegram lancé")
    except Exception as e:
        logger.error(f"Erreur démarrage bot Telegram: {e}")

    # Démarrer le scheduler APScheduler
    try:
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("Scheduler APScheduler démarré")
    except Exception as e:
        logger.error(f"Erreur démarrage scheduler: {e}")

    logger.info("=== NeoLink Dashboard prêt ===")


# Lancer le démarrage dès l'importation du module (compatible gunicorn 1 worker)
startup()


# ─── Point d'entrée direct ─────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
