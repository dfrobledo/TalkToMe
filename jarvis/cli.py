"""talktome: Claude Code con la voz de Jarvis (ElevenLabs)."""
import argparse
import json
import sys
import traceback

from . import config, hooks, player, tts
from .player import LOG_FILE

SAMPLE = (
    "Buenas, {h}. He revisado el repositorio: las pruebas pasan y el despliegue está listo. "
    "Si me permite una observación, quizá convendría dormir antes del lanzamiento."
)


def _log_error():
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(traceback.format_exc() + "\n")


def cmd_hook(args, cfg):
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    try:
        hooks.handle(args.event, payload, cfg)
    except Exception:
        _log_error()  # A voice failure must never break Claude Code.
    return 0


def cmd_worker(args, cfg):
    try:
        hooks.work(args.kind, args.payload, cfg)
    except Exception:
        _log_error()
    return 0


def cmd_say(args, cfg):
    text = " ".join(args.text) or SAMPLE.format(h=cfg["honorific"])
    player.claim()
    try:
        player.speak(text, cfg)
    finally:
        player.release()
    return 0


def cmd_voices(args, cfg):
    for v in sorted(tts.voices(cfg), key=lambda v: v.get("name", "")):
        labels = v.get("labels") or {}
        tags = ", ".join(str(labels[k]) for k in ("gender", "accent", "age", "descriptive") if labels.get(k))
        print(f"{v['voice_id']}  {v.get('name', ''):<28} {tags}")
    return 0


def cmd_quota(args, cfg):
    sub = tts.subscription(cfg)
    used, limit = sub.get("character_count", 0), sub.get("character_limit", 0)
    print(f"Plan {sub.get('tier', '?')}: {used:,} / {limit:,} caracteres usados ({limit - used:,} disponibles).")
    return 0


def cmd_doctor(args, cfg):
    ok = True
    print(f"Config:     voz {cfg['voice_id']} · modelo {cfg['model_id']} · modo {cfg['mode']}")
    print(f"API key:    {'OK' if cfg['api_key'] else 'FALTA (crea .env con ELEVENLABS_API_KEY)'}")
    ok &= bool(cfg["api_key"])
    audio = player.describe(cfg)
    print(f"Audio:      {audio or 'FALTA reproductor (instala mpv)'}")
    ok &= bool(audio)
    print(f"Silencio:   {'activado (talktome unmute)' if cfg['muted'] else 'no'}")
    if cfg["api_key"]:
        try:
            cmd_quota(args, cfg)
        except tts.TTSError as e:
            print(f"ElevenLabs: {e}")
            ok = False
    return 0 if ok else 1


def cmd_mute(args, cfg):
    config.set_muted(args.command == "mute")
    if args.command == "mute":
        player.stop()
    print("Jarvis en silencio." if args.command == "mute" else "Jarvis vuelve a hablar.")
    return 0


def cmd_stop(args, cfg):
    player.stop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="talktome", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("hook", help="usado por Claude Code")
    p.add_argument("event", choices=["stop", "notification", "session", "prompt"])
    p.set_defaults(fn=cmd_hook)
    p = sub.add_parser("_speak")
    p.add_argument("kind")
    p.add_argument("payload")
    p.set_defaults(fn=cmd_worker)
    p = sub.add_parser("say", help="dice un texto (o una frase de prueba)")
    p.add_argument("text", nargs="*")
    p.set_defaults(fn=cmd_say)
    sub.add_parser("voices", help="lista tus voces de ElevenLabs").set_defaults(fn=cmd_voices)
    sub.add_parser("quota", help="caracteres disponibles").set_defaults(fn=cmd_quota)
    sub.add_parser("doctor", help="verifica la instalación").set_defaults(fn=cmd_doctor)
    sub.add_parser("stop", help="calla la frase en curso").set_defaults(fn=cmd_stop)
    sub.add_parser("mute", help="silencia a Jarvis").set_defaults(fn=cmd_mute)
    sub.add_parser("unmute", help="reactiva la voz").set_defaults(fn=cmd_mute)

    args = parser.parse_args(argv)
    cfg = config.load()
    try:
        return args.fn(args, cfg)
    except tts.TTSError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
