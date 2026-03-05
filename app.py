# app.py — Orchestrateur principal NeoLink Dashboard
# Architecture: Bot Telegram + Scheduler dans le main thread (asyncio),
#               Flask dans un thread daemon séparé.
import os
import signal
import threading
import asyncio
import logging

from flask import Flask, render_template, request, jsonify

import database as db
import ai
from bot import create_application
from scheduler import create_scheduler, set_bot_app

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Application Flask ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "neolinkstudio-fallback-key")

# Initialisation de la base de données (sûr à appeler plusieurs fois)
db.init_db()

# Verrou pour la génération des tâches initiales — empêche la double génération
# si le thread _delayed_task_init et la route / s'exécutent dans la même fenêtre de 3s.
_task_init_lock = threading.Lock()


def _generate_tasks_if_empty():
    """
    Génère les tâches initiales si et seulement si la DB est vide. Thread-safe.
    Le verrou garantit qu'un seul thread fait la vérification + insertion à la fois.
    La vérification db.is_empty() se fait AVANT toute insertion, à l'intérieur du verrou.
    """
    # Vérification rapide sans verrou pour court-circuiter les appels redondants
    if not db.is_empty():
        return

    with _task_init_lock:
        # Re-vérifier après acquisition du verrou : un autre thread a peut-être déjà inséré
        if not db.is_empty():
            return

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
            logger.error("Aucune tâche générée — vérifier ANTHROPIC_API_KEY")


# ─── Routes Flask ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Page principale — tâches groupées par priorité."""
    _generate_tasks_if_empty()
    tasks = db.get_all_tasks()
    stats = db.get_stats()
    grouped = {
        "bloquant":      [t for t in tasks if t["priority"] == "bloquant"],
        "cette_semaine": [t for t in tasks if t["priority"] == "cette_semaine"],
        "backlog":       [t for t in tasks if t["priority"] == "backlog"],
    }
    return render_template("index.html", grouped=grouped, stats=stats)


@app.route("/ping")
def ping():
    """Health check — utilisé pour le self-ping Render."""
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
    """Retourne les données d'une tâche."""
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


@app.route("/admin/reset-tasks")
def admin_reset_tasks():
    """Supprime toutes les tâches et en régénère 5 via l'API Anthropic."""
    # Supprimer toutes les tâches existantes
    for task in db.get_all_tasks():
        db.delete_task(task["id"])

    # Régénérer les tâches initiales
    tasks = ai.generate_initial_tasks()
    for task in tasks:
        db.insert_task(
            title=task.get("title", "Tâche sans titre"),
            description=task.get("description", ""),
            comment_faire=task.get("comment_faire", ""),
            done_criteria=task.get("done_criteria", ""),
            priority=task.get("priority", "backlog"),
        )

    return jsonify({"tasks_created": len(tasks)})


# ─── Flask dans un thread daemon ───────────────────────────────────────────────

def _run_flask():
    """Lance le serveur Flask dans un thread daemon séparé."""
    port = int(os.environ.get("PORT", 5000))
    # use_reloader=False obligatoire : le reloader fork le process,
    # ce qui casserait l'event loop asyncio du thread principal.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ─── Point d'entrée asyncio principal ─────────────────────────────────────────

async def main_async():
    """
    Coroutine principale. S'exécute dans le main thread avec asyncio.run().

    Ordre de démarrage:
    1. Flask dans un thread daemon (bind sur PORT immédiatement — évite timeout Render)
    2. Génération des tâches initiales dans un thread séparé avec délai de 3s
    3. Bot Telegram en polling dans le main event loop (drop_pending_updates évite le conflit)
    4. AsyncIOScheduler démarré (partage le même event loop)
    5. Attente infinie jusqu'à signal d'arrêt
    """
    logger.info("=== Démarrage NeoLink Dashboard ===")

    # 1. Flask en premier — bind sur PORT immédiatement pour satisfaire Render
    flask_thread = threading.Thread(target=_run_flask, daemon=True, name="FlaskThread")
    flask_thread.start()
    logger.info("Flask démarré dans un thread daemon")

    # 2. Génération différée des tâches initiales
    def _delayed_task_init():
        import time
        time.sleep(3)
        _generate_tasks_if_empty()

    task_init_thread = threading.Thread(
        target=_delayed_task_init, daemon=True, name="TaskInitThread"
    )
    task_init_thread.start()
    logger.info("Génération des tâches initiales planifiée (délai 3s)")

    # 3. Bot Telegram en polling dans le main event loop.
    # drop_pending_updates=True évite le conflit "terminated by other getUpdates request"
    # lors des redéploiements Render (l'ancienne instance est écrasée proprement).
    bot_app = create_application()
    set_bot_app(bot_app)

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(
        allowed_updates=["message"],
        drop_pending_updates=True,
    )
    logger.info("Bot Telegram en polling (main thread)")

    # 4. Scheduler AsyncIO — partage le même event loop que le bot
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler AsyncIO démarré")

    logger.info("=== NeoLink Dashboard prêt ===")

    # 5. Attendre le signal d'arrêt (SIGTERM sur Render, SIGINT en local)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _on_signal():
        logger.info("Signal d'arrêt reçu")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except (NotImplementedError, RuntimeError):
            pass  # Windows ne supporte pas add_signal_handler

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("Arrêt propre en cours...")
        scheduler.shutdown(wait=False)
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        logger.info("=== NeoLink Dashboard arrêté ===")


if __name__ == "__main__":
    asyncio.run(main_async())
