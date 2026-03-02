# database.py — Helpers SQLite pour la gestion des tâches NeoLinkStudio
import sqlite3
import os
from datetime import datetime

# Chemin vers la base de données SQLite
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tasks.db')


def get_connection():
    """Retourne une connexion SQLite avec row_factory activé."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialise la base de données et crée la table des tâches si elle n'existe pas."""
    with get_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                comment_faire TEXT DEFAULT '',
                done_criteria TEXT DEFAULT '',
                priority TEXT DEFAULT 'backlog',
                status TEXT DEFAULT 'todo',
                created_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT
            )
        ''')
        conn.commit()


def is_empty():
    """Vérifie si la table des tâches est vide."""
    with get_connection() as conn:
        count = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        return count == 0


def insert_task(title, description='', comment_faire='', done_criteria='', priority='backlog'):
    """Insère une nouvelle tâche et retourne son ID."""
    with get_connection() as conn:
        cursor = conn.execute(
            '''INSERT INTO tasks (title, description, comment_faire, done_criteria, priority, status)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (title, description, comment_faire, done_criteria, priority, 'todo')
        )
        conn.commit()
        return cursor.lastrowid


def get_all_tasks():
    """Retourne toutes les tâches triées par priorité puis par date de création."""
    with get_connection() as conn:
        rows = conn.execute(
            '''SELECT * FROM tasks
               ORDER BY
                   CASE priority
                       WHEN 'bloquant' THEN 1
                       WHEN 'cette_semaine' THEN 2
                       WHEN 'backlog' THEN 3
                       ELSE 4
                   END,
                   created_at ASC'''
        ).fetchall()
        return [dict(row) for row in rows]


def get_task_by_id(task_id):
    """Retourne une tâche spécifique par son ID."""
    with get_connection() as conn:
        row = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
        return dict(row) if row else None


def get_next_task():
    """Retourne la prochaine tâche non complétée de plus haute priorité."""
    with get_connection() as conn:
        row = conn.execute(
            '''SELECT * FROM tasks
               WHERE status = 'todo'
               ORDER BY
                   CASE priority
                       WHEN 'bloquant' THEN 1
                       WHEN 'cette_semaine' THEN 2
                       WHEN 'backlog' THEN 3
                       ELSE 4
                   END,
                   created_at ASC
               LIMIT 1'''
        ).fetchone()
        return dict(row) if row else None


def get_top_tasks(limit=3):
    """Retourne les N prochaines tâches non complétées par priorité."""
    with get_connection() as conn:
        rows = conn.execute(
            '''SELECT * FROM tasks
               WHERE status = 'todo'
               ORDER BY
                   CASE priority
                       WHEN 'bloquant' THEN 1
                       WHEN 'cette_semaine' THEN 2
                       WHEN 'backlog' THEN 3
                       ELSE 4
                   END,
                   created_at ASC
               LIMIT ?''',
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def toggle_task(task_id):
    """Bascule le statut d'une tâche entre 'todo' et 'done'."""
    with get_connection() as conn:
        task = conn.execute('SELECT status FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if not task:
            return False
        new_status = 'done' if task['status'] == 'todo' else 'todo'
        completed_at = datetime.now().isoformat() if new_status == 'done' else None
        conn.execute(
            'UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?',
            (new_status, completed_at, task_id)
        )
        conn.commit()
        return True


def mark_done(task_id):
    """Marque une tâche comme complétée."""
    with get_connection() as conn:
        conn.execute(
            'UPDATE tasks SET status = "done", completed_at = ? WHERE id = ?',
            (datetime.now().isoformat(), task_id)
        )
        conn.commit()


def update_task(task_id, title, description, comment_faire, done_criteria, priority):
    """Met à jour les champs d'une tâche existante."""
    with get_connection() as conn:
        conn.execute(
            '''UPDATE tasks
               SET title = ?, description = ?, comment_faire = ?,
                   done_criteria = ?, priority = ?
               WHERE id = ?''',
            (title, description, comment_faire, done_criteria, priority, task_id)
        )
        conn.commit()


def delete_task(task_id):
    """Supprime une tâche par son ID."""
    with get_connection() as conn:
        conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        conn.commit()


def get_last_completion_time():
    """Retourne le timestamp ISO de la dernière tâche complétée aujourd'hui."""
    with get_connection() as conn:
        row = conn.execute(
            '''SELECT completed_at FROM tasks
               WHERE status = 'done' AND date(completed_at) = date('now', 'localtime')
               ORDER BY completed_at DESC
               LIMIT 1'''
        ).fetchone()
        return row['completed_at'] if row else None


def get_stats():
    """Retourne les statistiques générales des tâches."""
    with get_connection() as conn:
        total = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'done'").fetchone()[0]
        todo = total - done
        return {'total': total, 'done': done, 'todo': todo}
