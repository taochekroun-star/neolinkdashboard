# ai.py — Appels à l'API Anthropic pour NeoLinkStudio
import os
import json
import logging
import anthropic

logger = logging.getLogger(__name__)

# Contexte NeoLinkStudio injecté dans les prompts
NEOLINKSTUDIO_CONTEXT = """Tu es l'assistant IA personnel de Tao, 15 ans, fondateur de NeoLinkStudio à Québec, Canada.
NeoLinkStudio vend des systèmes d'automatisation IA pour les PME locales dans le secteur HVAC (chauffage, ventilation, climatisation).
Objectif immédiat: obtenir le premier client test via une offre gratuite en échange d'un témoignage vidéo.
Stack technique actuel: n8n sur Railway, Airtable, Tally (formulaires), Calendly (prise de rendez-vous), OpenAI/Claude.
Ton rôle: aider Tao à rester focalisé, avancer concrètement et atteindre son premier client.
Réponds TOUJOURS en français. Sois direct, concis et actionnable."""


def _get_client():
    """Retourne un client Anthropic initialisé depuis la variable d'environnement."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY non définie dans les variables d'environnement")
    return anthropic.Anthropic(api_key=api_key)


def generate_initial_tasks():
    """
    Génère 5 tâches initiales pertinentes pour NeoLinkStudio via l'API Anthropic.
    Limité à 5 tâches pour rester dans les limites du free tier (8000 tokens/min).
    Retourne une liste de dicts ou une liste vide en cas d'erreur.
    """
    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{
                "role": "user",
                "content": """Génère exactement 5 tâches concrètes pour Tao, fondateur de NeoLinkStudio.

Contexte:
- Tao a 15 ans, vit à Québec, Canada
- Il vend des systèmes d'automatisation IA pour les PME HVAC locales
- Objectif IMMÉDIAT: obtenir son PREMIER client test gratuitement en échange d'un témoignage vidéo
- Stack: n8n (Railway), Airtable, Tally, Calendly, OpenAI/Claude

Répartition OBLIGATOIRE:
- 2 tâches priorité "bloquant"
- 2 tâches priorité "cette_semaine"
- 1 tâche priorité "backlog"

Réponds UNIQUEMENT avec un tableau JSON valide, sans texte avant ou après:
[
  {
    "title": "Titre court et actionnable (max 60 chars)",
    "description": "1-2 phrases max. Ce qu'il faut faire et pourquoi.",
    "comment_faire": "1-2 phrases max. Étapes concrètes pour accomplir la tâche.",
    "done_criteria": "1 phrase max. Comment savoir que c'est terminé.",
    "priority": "bloquant"
  }
]

Valeurs valides pour priority: "bloquant", "cette_semaine", "backlog"
Sois ultra-concis: chaque champ texte = 1 à 2 phrases maximum."""
            }]
        )

        content = response.content[0].text.strip()

        # Extraire le JSON proprement
        start = content.find('[')
        end = content.rfind(']') + 1
        if start == -1 or end <= start:
            logger.error("Impossible de trouver le JSON dans la réponse de génération de tâches")
            return []

        tasks = json.loads(content[start:end])
        logger.info(f"✅ {len(tasks)} tâches initiales générées par l'IA")
        return tasks

    except json.JSONDecodeError as e:
        logger.error(f"Erreur parsing JSON tâches initiales: {e}")
        return []
    except Exception as e:
        logger.error(f"Erreur génération tâches initiales: {e}")
        return []


def get_micro_steps(task):
    """
    Décompose une tâche en 3-5 micro-étapes très concrètes via Anthropic.
    Retourne une chaîne de texte formatée.
    """
    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=NEOLINKSTUDIO_CONTEXT,
            messages=[{
                "role": "user",
                "content": f"""Décompose cette tâche en 3 à 5 micro-étapes TRÈS concrètes.
Chaque étape doit être faisable en moins de 30 minutes.

Tâche: {task.get('title', '')}
Description: {task.get('description', '')}
Comment faire: {task.get('comment_faire', '')}

Format: liste numérotée simple, chaque étape = 1 action précise. En français."""
            }]
        )
        return response.content[0].text

    except Exception as e:
        logger.error(f"Erreur génération micro-étapes: {e}")
        return "❌ Erreur lors de la génération des micro-étapes. Réessaie avec /stuck."


def chat_with_claude(message, tasks_list):
    """
    Conversation libre avec Claude. Injecte le contexte NeoLinkStudio et la liste des tâches.
    Retourne une chaîne de texte (réponse de Claude).
    """
    try:
        client = _get_client()

        # Résumé des tâches pour le contexte
        priority_emoji = {"bloquant": "🔴", "cette_semaine": "🟡", "backlog": "🟢"}
        tasks_text = "\n".join([
            f"- {priority_emoji.get(t['priority'], '⚪')} [{t['priority'].upper()}] "
            f"{t['title']} ({'✅ fait' if t['status'] == 'done' else '⏳ à faire'})"
            for t in tasks_list[:15]  # Limiter pour ne pas dépasser le contexte
        ])

        system_prompt = f"""{NEOLINKSTUDIO_CONTEXT}

=== TÂCHES ACTUELLES DE TAO ===
{tasks_text if tasks_text else "Aucune tâche pour le moment."}
=== FIN DES TÂCHES ===

Réponds en 2-4 phrases maximum. Sois direct et donne une action concrète si pertinent."""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": message
            }]
        )
        return response.content[0].text

    except Exception as e:
        logger.error(f"Erreur chat Claude: {e}")
        return "Désolé, une erreur s'est produite avec l'IA. Réessaie dans un moment."
