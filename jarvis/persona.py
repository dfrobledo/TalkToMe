"""Jarvis' fixed lines: greetings, attention calls and sign-offs.

They are short and repeat often, so after the first time they are served
from the local cache and cost no ElevenLabs characters.
"""
import random
import re
from datetime import datetime

GREETINGS = [
    "Todos los sistemas en línea.",
    "A su disposición.",
    "¿En qué trabajamos hoy?",
]


def greeting(h, now=None):
    hour = (now or datetime.now()).hour
    salute = "Buenos días" if 5 <= hour < 12 else "Buenas tardes" if hour < 20 else "Buenas noches"
    return f"{salute}, {h}. {random.choice(GREETINGS)}"


# Notification types worth interrupting the silence for.
ATTENTION = {"permission_prompt", "idle_prompt", "elicitation_dialog", "agent_needs_input"}


def notification(payload, h):
    """Translate Claude Code's notification into something Jarvis would say.

    Returns "" for notifications that do not need the user (auth, quota...).
    """
    kind = payload.get("notification_type")
    message = payload.get("message") or ""
    if kind and kind not in ATTENTION:
        return ""
    tool = re.search(r"permission to use (.+?)\.?$", message)
    if tool:
        return f"Disculpe, {h}. Necesito su autorización para usar {tool.group(1)}."
    if kind == "permission_prompt" or "permission" in message.lower():
        return f"Disculpe, {h}. Necesito su autorización para continuar."
    if kind == "idle_prompt" or "waiting for your input" in message.lower():
        return f"Sigo a la espera de sus instrucciones, {h}."
    return f"{h.capitalize()}, requiero su atención un momento."


def more_on_screen(h):
    return f"El detalle está en pantalla, {h}."
