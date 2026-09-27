"""Rachel's fixed lines: greetings, attention calls and sign-offs.

They are short and repeat often, so after the first time they are served
from the local cache and cost no ElevenLabs characters.
"""
import random
import re
from datetime import datetime

GREETINGS = [
    "Todos los sistemas en línea. De momento.",
    "¿Viene a hacerme otra prueba Voight-Kampff?",
    "¿Qué vamos a romper hoy?",
    "Café servido, errores pendientes. Lo de siempre.",
]


def greeting(h, now=None):
    hour = (now or datetime.now()).hour
    salute = "Buenos días" if 5 <= hour < 12 else "Buenas tardes" if hour < 20 else "Buenas noches"
    return f"{salute}, {h}. {random.choice(GREETINGS)}"


# Notification types worth interrupting the silence for.
ATTENTION = {"permission_prompt", "idle_prompt", "elicitation_dialog", "agent_needs_input"}


def notification(payload, h):
    """Translate Claude Code's notification into something Rachel would say.

    Returns "" for notifications that do not need the user (auth, quota...).
    """
    kind = payload.get("notification_type")
    message = payload.get("message") or ""
    if kind and kind not in ATTENTION:
        return ""
    tool = re.search(r"permission to use (.+?)\.?$", message)
    if tool:
        return f"{h.capitalize()}, necesito su permiso para usar {tool.group(1)}. Prometo no incendiar nada."
    if kind == "permission_prompt" or "permission" in message.lower():
        return f"Disculpe, {h}. Necesito su autorización para continuar."
    if kind == "idle_prompt" or "waiting for your input" in message.lower():
        return f"Sigo aquí, {h}. Los replicantes no dormimos."
    return f"{h.capitalize()}, requiero su atención un momento."


def is_idle(payload):
    """The "still waiting for you" reminder: pointless while Rachel is talking."""
    message = (payload.get("message") or "").lower()
    return payload.get("notification_type") == "idle_prompt" or "waiting for your input" in message


def needs_answer(h):
    return f"{h.capitalize()}, necesito que me responda algo. Está en pantalla."


def done(h):
    return f"Listo, {h}. El detalle está en pantalla."


def more_on_screen(h):
    return f"El detalle está en pantalla, {h}."
