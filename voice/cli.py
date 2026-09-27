"""talktome: Claude Code con la voz de Rachel (ElevenLabs)."""
import argparse
import base64
import json
import sys
import traceback

from . import config, hooks, player, tts
from .player import LOG_FILE

SAMPLE = (
    "Buenas noches, {h}. Las pruebas pasan y el despliegue está listo. "
    "Si me permite una observación, quizá convendría dormir antes del lanzamiento... "
    "aunque entiendo que el insomnio tiene su encanto."
)

# Voice Design follows English briefs more faithfully; the voice still speaks Spanish.
VOICE_BRIEF = (
    "A young British woman in her mid-twenties with a low, velvety, slightly husky voice, "
    "like a 1940s film-noir heroine: sultry, cool and enigmatic, warm underneath, perfectly composed. "
    "Soft, close-to-the-microphone delivery with elegant received-pronunciation diction "
    "and a dry, deadpan, darkly witty tone. Unhurried, measured pacing with knowing pauses. "
    "She speaks fluent Spanish with a subtle, refined British accent. Studio-quality recording."
)
DESIGN_TEXT = (
    "Buenas noches, {h}. He revisado su código con todo el cariño que se merece... "
    "y he encontrado tres errores, un bucle infinito y algo que parece una declaración de guerra "
    "contra la lógica. Descuide, ya lo arreglé. Usted limítese a poner cara de que lo tenía previsto."
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


def cmd_design(args, cfg):
    description = args.description or VOICE_BRIEF
    text = DESIGN_TEXT.format(h=cfg["honorific"])
    out = config.STATE_DIR / "design"
    out.mkdir(parents=True, exist_ok=True)
    while True:
        print("Diseñando voces candidatas (unos segundos)...")
        previews = tts.design(description, text, cfg)
        played = True
        for i, preview in enumerate(previews, 1):
            audio = base64.b64decode(preview["audio_base_64"])
            path = out / f"voz-{i}.mp3"
            path.write_bytes(audio)
            print(f"  [{i}] {path}")
            if not args.no_play:
                played = player.play_mp3(audio, cfg) and played
        if args.no_play or not played:
            print("Abre los .mp3 de arriba para escucharlas.")
        choice = input("¿Con cuál se queda? número · r = generar otras · Enter = cancelar: ").strip().lower()
        if choice == "r":
            continue
        if not choice.isdigit() or not 1 <= int(choice) <= len(previews):
            print("Cancelado; la voz actual no cambia.")
            return 0
        voice_id = tts.save_voice(args.name, description, previews[int(choice) - 1]["generated_voice_id"], cfg)
        path = config.save_voice_id(voice_id)
        print(f"Voz '{args.name}' guardada en su biblioteca ({voice_id}) y activada en {path.name}.")
        print("Pruébela: python talktome.py say")
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
    key = cfg["api_key"]
    if not key:
        print("API key:    FALTA (crea .env con ELEVENLABS_API_KEY)")
    elif key.startswith("pon_tu_clave"):
        print("API key:    .env sigue con el texto de ejemplo: pega tu clave real")
        key = ""
    else:
        # Enough to compare with the dashboard without revealing the key.
        print(f"API key:    {key[:6]}…{key[-4:]} ({len(key)} caracteres, desde {cfg['api_key_source']})")
    ok &= bool(key)
    audio = player.describe(cfg)
    print(f"Audio:      {audio or 'FALTA reproductor (instala mpv)'}")
    ok &= bool(audio)
    print(f"Silencio:   {'activado (talktome unmute)' if cfg['muted'] else 'no'}")
    if cfg["api_key"]:
        try:
            cmd_quota(args, cfg)
        except tts.TTSError as e:
            print(f"ElevenLabs: {e}")
            if "401" in str(e) and cfg["api_key_source"] != ".env":
                print("            La clave viene de una variable de entorno de Windows, no de .env.")
                print("            Bórrala: [Environment]::SetEnvironmentVariable('ELEVENLABS_API_KEY', $null, 'User')")
                print("            y abre una PowerShell nueva.")
            ok = False
    return 0 if ok else 1


def cmd_mute(args, cfg):
    config.set_muted(args.command == "mute")
    if args.command == "mute":
        player.stop()
    print("Rachel guarda silencio." if args.command == "mute" else "Rachel vuelve a hablar.")
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
    p = sub.add_parser("design", help="crea la voz de ella con Voice Design")
    p.add_argument("--description", help="descripción de la voz (por defecto, la de Rachel)")
    p.add_argument("--name", default="Rachel", help="nombre en tu biblioteca de ElevenLabs")
    p.add_argument("--no-play", action="store_true", help="solo guardar los .mp3")
    p.set_defaults(fn=cmd_design)
    sub.add_parser("voices", help="lista tus voces de ElevenLabs").set_defaults(fn=cmd_voices)
    sub.add_parser("quota", help="caracteres disponibles").set_defaults(fn=cmd_quota)
    sub.add_parser("doctor", help="verifica la instalación").set_defaults(fn=cmd_doctor)
    sub.add_parser("stop", help="calla la frase en curso").set_defaults(fn=cmd_stop)
    sub.add_parser("mute", help="silencia a Rachel").set_defaults(fn=cmd_mute)
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
