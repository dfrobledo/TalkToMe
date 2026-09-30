"""talktome: Claude Code con la voz de Rachel (ElevenLabs)."""
import argparse
import base64
import json
import sys
import traceback

from pathlib import Path

from . import alerts, companion, config, deck, hooks, lines, listen, mic, persona, player, projects, stt, tts, wake
from .player import LOG_FILE

SAMPLE = (
    "Buenas noches, {h}. Las pruebas pasan y el despliegue está listo. "
    "Si me permite una observación, tal vez le convendría dormir antes del lanzamiento... "
    "aunque entiendo que el insomnio tiene su encanto."
)

# Voice Design follows English briefs more faithfully. Without an explicit
# accent it drifts to Castilian Spanish, so the accent is spelled out.
ACCENTS = {
    "latino": "a neutral Latin American Spanish accent, like high-end Latin American dubbing",
    "mexicano": "a soft, educated Mexico City Spanish accent",
    "colombiano": "a warm, soft, educated Bogotá Colombian Spanish accent",
    "venezolano": "a warm, melodic Caracas Venezuelan Spanish accent",
    "argentino": "a Buenos Aires Rioplatense Spanish accent",
    "chileno": "a soft, educated Santiago Chilean Spanish accent",
}
VOICE_BRIEF = (
    "A Latin American woman in her mid-twenties, native Spanish speaker with {accent}, "
    "with seseo and absolutely no Castilian Spain accent. Low, velvety, slightly husky voice, "
    "sensual, warm and intimate, with a soft, breathy, close-to-the-microphone delivery. "
    "Like a film-noir heroine: cool and enigmatic on the surface, playful and warm underneath, "
    "with a dry, darkly witty tone. Unhurried, measured pacing with knowing pauses. "
    "Studio-quality recording."
)
DESIGN_TEXT = (
    "Buenas noches, {h}. Revisé su código con todo el cariño que se merece... "
    "y encontré tres errores, un bucle infinito y algo que parece una declaración de guerra "
    "contra la lógica. No se preocupe, ya lo arreglé. Usted solo ponga cara de que lo tenía todo previsto."
)


def _log_error(cfg=None):
    """Log the exception being handled and, with a config, have Rachel report it."""
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(traceback.format_exc() + "\n")
    if cfg is not None:
        error = sys.exc_info()[1]
        alerts.report(alerts.classify(error), cfg, str(error)[:200])


def cmd_hook(args, cfg):
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    try:
        decision = hooks.handle(args.event, payload, cfg)
    except Exception:
        _log_error(cfg)  # A voice failure must never break Claude Code.
        return 0
    if decision:
        print(json.dumps(decision, ensure_ascii=False))
    return 0


def cmd_worker(args, cfg):
    try:
        hooks.work(args.kind, args.payload, cfg)
    except Exception:
        _log_error(cfg)
    return 0


def _session(args, cfg):
    """The Claude Code session a detached command runs for, and its project's config."""
    session = getattr(args, "session", None) or None
    return session, projects.identify(getattr(args, "cwd", None), cfg)[1]


def cmd_repeat(args, cfg):
    session, cfg = _session(args, cfg)
    player.claim(session)
    try:
        if not player.replay(cfg, session):
            print("Todavía no hay ninguna respuesta que repetir.")
    except Exception:
        if args.command == "_repeat":
            _log_error(cfg)  # Detached: nobody is watching the console.
        else:
            raise
    finally:
        player.release(session)
    return 0


def cmd_accompany(args, cfg):
    try:
        companion.accompany(cfg, args.session, args.transcript)
    except Exception:
        _log_error(cfg)  # Detached: nobody is watching the console.
    return 0


def cmd_prepare(args, cfg):
    try:
        made = alerts.warm(cfg, persona.stock_lines(cfg["honorific"], cfg["model_id"] == "eleven_v3"))
        if made:
            hooks.log(f"frases y avisos listos en caché: {made} nuevos")
    except Exception:
        _log_error()  # no report: ElevenLabs failing here is reported when it matters
    return 0


def cmd_alerts(args, cfg):
    if args.prueba:
        if args.prueba not in alerts.LINES:
            print(f"Tipos: {', '.join(alerts.LINES)}", file=sys.stderr)
            return 1
        player.claim()
        try:
            player.speak(alerts.line(args.prueba, cfg), cfg)
        finally:
            player.release()
        return 0
    if args.preparar:
        stock = persona.stock_lines(cfg["honorific"], cfg["model_id"] == "eleven_v3")
        print(f"{alerts.warm(cfg, stock)} frases generadas; el resto ya estaba en caché.")
    for kind in alerts.LINES:
        text = alerts.line(kind, cfg)
        print(f"{'✓' if player.cached(text, cfg) else '·'} {kind:<11} {text}")
    print("✓ = en caché con su voz (funciona aunque ElevenLabs falle). --preparar genera los que falten.")
    return 0


def cmd_detail(args, cfg):
    session, cfg = _session(args, cfg)
    try:
        hooks.detail(cfg, session)
    except Exception:
        if args.command == "_detail":
            _log_error(cfg)  # Detached: nobody is watching the console.
        else:
            raise
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
    description = args.description or VOICE_BRIEF.format(accent=ACCENTS[args.acento])
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
    if mic.available():
        try:
            recorder = mic.Recorder()
            recorder.start()
            recorder.cancel()
            state = "micrófono OK"
        except mic.MicError as e:
            state = f"FALLA el {e}"
            ok = False
        active = listen.running()
        idle = "inactivo (arranca al abrir Claude Code)" if cfg["listen_on_start"] else "inactivo (talktome escucha)"
        print(f"Dictado:    {state} · tecla {cfg['listen_key']} · {cfg['stt_model']} · "
              f"{'tiempo real' if cfg['stt_realtime'] else 'por lotes'} · "
              f"{f'escuchando (proceso {active})' if active else idle}")
        ready, why = wake.engine(cfg)
        print(f"Activación: {'«Rachel» · Vosk listo' if wake.enabled(cfg) else why if cfg.get('wake') != False else 'apagada'}")
    else:
        print("Dictado:    solo en Windows por ahora")
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


def cmd_lines(args, cfg):
    if args.inventa:
        print("Pidiéndole frases nuevas a Claude...")
        added = persona.invent(cfg)
        print(f"{len(added)} nuevas." if added else "Claude no aportó ninguna frase utilizable.")
    invented = deck.invented()
    print(f"Banco: {len(lines.IDLE)} frases de espera, {len(lines.GREETINGS)} saludos, "
          f"{len(lines.PERMISSION_TOOL) + len(lines.PERMISSION)} de permiso.")
    print(f"Inventadas por Claude ({len(invented)}, se borran en {deck.STATE_FILE}):")
    for line in invented:
        print("  " + line.format(h=cfg["honorific"]))
    return 0


def cmd_listen(args, cfg):
    if args.detener:
        print("Escucha detenida." if listen.stop_listening() else "No había ninguna escucha activa.")
        return 0
    if not mic.available():
        print("El dictado por voz funciona en Windows por ahora.", file=sys.stderr)
        return 1
    try:
        if args.fondo:
            listen.serve(cfg, key=args.tecla, out=lambda text: None, background=True)
        else:
            listen.serve(cfg, key=args.tecla)
    except (mic.MicError, ValueError) as e:
        if args.fondo:
            hooks.log(f"escucha en segundo plano: {e}")
            if not listen.running():  # another one taking over is no error
                kind = alerts.classify(e)
                alerts.report(kind if kind != "crash" else "listen", cfg, str(e))
        else:
            print(e, file=sys.stderr)
            return 1
    except Exception:
        if not args.fondo:
            raise
        _log_error(cfg)  # Detached: nobody is watching the console.
    return 0


def cmd_wake(args, cfg):
    """Her name: install the local recognizer, test what it hears, or show its state."""
    if args.instalar:
        try:
            wake.install(cfg)
        except Exception as e:
            print(f"No se pudo instalar: {e}", file=sys.stderr)
            print(f"Manual: pip install vosk, y descomprima {wake.MODEL_URL} en {wake.model_path(cfg).parent}",
                  file=sys.stderr)
            return 1
        print("Abra una sesión nueva de Claude Code (o reinicie la escucha) y diga «Rachel».")
        return 0
    ready, why = wake.engine(cfg)
    if not args.prueba:
        state = "lista" if wake.enabled(cfg) else ("apagada en la config" if ready else why)
        print(f"Activación por voz: {state}")
        print(f"  Palabras: {', '.join(dict.fromkeys(wake.WAKE_WORDS + list(cfg.get('wake_words') or [])))}")
        print("  Pruebe qué oye: python talktome.py despierta --prueba")
        return 0 if ready else 1
    if not ready:
        print(f"Activación por voz: {why}", file=sys.stderr)
        return 1
    if not mic.available():
        print("La prueba con micrófono funciona en Windows.", file=sys.stderr)
        return 1
    import queue

    words = list(dict.fromkeys(wake.WAKE_WORDS + list(cfg.get("wake_words") or [])))
    spotter = wake.VoskSpotter(wake.model_path(cfg))
    chunks = queue.Queue()
    recorder = mic.Recorder()
    recorder.start(on_chunk=chunks.put, keep=False)
    print("Hable (Ctrl+C para salir). Diga «Rachel» y vea qué entiende el reconocedor local.")
    print("Si su nombre sale escrito de otra forma, agréguela a \"wake_words\" en la config.")
    try:
        while True:
            kind, text = spotter.feed(chunks.get())
            if kind == "final" and text:
                called = "  ← ¡la llamó!" if wake.find_wake(wake.normalize(text).split(), words) else ""
                print(f"\r» {text}{called}".ljust(70))
            elif text:
                print(f"\r  {text[-66:]}".ljust(70), end="", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        recorder.cancel()
    return 0


def cmd_hear(args, cfg):
    """Transcribe without typing anything: a file, or the microphone until Enter."""
    if args.archivo:
        path = Path(args.archivo)
        audio = path.read_bytes()
    elif mic.available():
        recorder = mic.Recorder()
        try:
            recorder.start()
            input("Hable ahora; pulse Enter para terminar...")
            path = listen.LAST_AUDIO
            audio = recorder.stop(path)
        except mic.MicError as e:
            recorder.cancel()
            print(e, file=sys.stderr)
            return 1
    else:
        print("Sin Windows no puedo grabar: pase un archivo de audio (talktome oye voz.wav).", file=sys.stderr)
        return 1
    print("Transcribiendo...")
    text = stt.clean(stt.transcribe(audio, cfg, filename=path.name))
    print(f"» {text}" if text else "(no se entendieron palabras)")
    return 0


def cmd_stop(args, cfg):
    player.stop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="talktome", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("hook", help="usado por Claude Code")
    p.add_argument("event", choices=["stop", "notification", "session", "prompt", "end"])
    p.set_defaults(fn=cmd_hook)
    p = sub.add_parser("_speak")
    p.add_argument("kind")
    p.add_argument("payload")
    p.set_defaults(fn=cmd_worker)
    sub.add_parser("repite", aliases=["repeat"], help="repite la última respuesta").set_defaults(fn=cmd_repeat)
    p = sub.add_parser("_repeat")
    p.add_argument("session", nargs="?")
    p.add_argument("cwd", nargs="?")
    p.set_defaults(fn=cmd_repeat)
    sub.add_parser("detalle", aliases=["detail"], help="narra el detalle de la última respuesta").set_defaults(fn=cmd_detail)
    p = sub.add_parser("_detail")
    p.add_argument("session", nargs="?")
    p.add_argument("cwd", nargs="?")
    p.set_defaults(fn=cmd_detail)
    sub.add_parser("_prepara").set_defaults(fn=cmd_prepare)
    p = sub.add_parser("avisos", aliases=["alerts"], help="avisos de error de Rachel: cuáles hay y si están en caché")
    p.add_argument("--preparar", action="store_true", help="generar ya los que falten en caché")
    p.add_argument("--prueba", metavar="TIPO", help="escuchar uno (auth, mic, network...)")
    p.set_defaults(fn=cmd_alerts)
    p = sub.add_parser("_acompana")
    p.add_argument("session")
    p.add_argument("transcript")
    p.set_defaults(fn=cmd_accompany)
    p = sub.add_parser("say", help="dice un texto (o una frase de prueba)")
    p.add_argument("text", nargs="*")
    p.set_defaults(fn=cmd_say)
    p = sub.add_parser("design", help="crea la voz de ella con Voice Design")
    p.add_argument("--description", help="descripción de la voz (por defecto, la de Rachel)")
    p.add_argument("--acento", choices=sorted(ACCENTS), default="latino", help="acento (por defecto: latino neutro)")
    p.add_argument("--name", default="Rachel", help="nombre en tu biblioteca de ElevenLabs")
    p.add_argument("--no-play", action="store_true", help="solo guardar los .mp3")
    p.set_defaults(fn=cmd_design)
    sub.add_parser("voices", help="lista tus voces de ElevenLabs").set_defaults(fn=cmd_voices)
    sub.add_parser("quota", help="caracteres disponibles").set_defaults(fn=cmd_quota)
    sub.add_parser("doctor", help="verifica la instalación").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("frases", aliases=["lines"], help="frases de Rachel, incluidas las inventadas")
    p.add_argument("--inventa", action="store_true", help="pedirle a Claude frases nuevas ahora")
    p.set_defaults(fn=cmd_lines)
    p = sub.add_parser("escucha", aliases=["listen"], help="dictado: mantenga una tecla, hable y se envía a Claude")
    p.add_argument("--tecla", help="tecla para hablar (por defecto la de la config, F9)")
    p.add_argument("--fondo", action="store_true", help=argparse.SUPPRESS)  # launched by SessionStart
    p.add_argument("--detener", action="store_true", help="detiene la escucha en segundo plano")
    p.set_defaults(fn=cmd_listen)
    p = sub.add_parser("despierta", aliases=["wake"], help="activación por voz: diga «Rachel»")
    p.add_argument("--instalar", action="store_true", help="instala Vosk y el modelo de español (~40 MB)")
    p.add_argument("--prueba", action="store_true", help="muestra en vivo lo que oye el reconocedor local")
    p.set_defaults(fn=cmd_wake)
    p = sub.add_parser("oye", aliases=["hear"], help="transcribe sin enviar: un archivo o el micrófono")
    p.add_argument("archivo", nargs="?", help="audio a transcribir (sin él, graba hasta Enter)")
    p.set_defaults(fn=cmd_hear)
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
