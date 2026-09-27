#!/usr/bin/env python3
"""Connect TalkToMe to Claude Code (user level: every project gets the voice).

    python install.py              # hooks + Rachel output style
    python install.py --no-style   # voice only, keep your current style
    python install.py --uninstall  # remove everything TalkToMe added
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
SETTINGS = CLAUDE_DIR / "settings.json"
STYLE_SRC = ROOT / "claude" / "output-styles" / "rachel.md"
STYLE_DST = CLAUDE_DIR / "output-styles" / "rachel.md"
# Earlier versions installed the persona as "Jarvis".
LEGACY_STYLE = CLAUDE_DIR / "output-styles" / "jarvis.md"
STYLE_NAMES = {"Rachel", "Jarvis"}
MARKER = "talktome.py"
EVENTS = {"SessionStart": "session", "UserPromptSubmit": "prompt", "Notification": "notification", "Stop": "stop"}


def _uses_powershell():
    """Claude Code runs hooks with Git Bash on Windows, PowerShell without it."""
    if os.name != "nt":
        return False
    candidates = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), shutil.which("bash"),
                  r"C:\Program Files\Git\bin\bash.exe"]
    return not any(c and Path(c).exists() for c in candidates)


def hook_command(event):
    python = Path(sys.executable).as_posix()
    launcher = (ROOT / "talktome.py").as_posix()
    call = "& " if _uses_powershell() else ""
    return f'{call}"{python}" "{launcher}" hook {event}'


def _strip_ours(hooks):
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if MARKER not in h.get("command", "")]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-style", action="store_true", help="no activar el estilo Rachel")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    settings = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    if SETTINGS.exists():
        shutil.copy2(SETTINGS, SETTINGS.with_name("settings.json.bak-talktome"))

    hooks = settings.setdefault("hooks", {})
    _strip_ours(hooks)
    if LEGACY_STYLE.exists():
        LEGACY_STYLE.unlink()
    if args.uninstall:
        if settings.get("outputStyle") in STYLE_NAMES:
            del settings["outputStyle"]
        if STYLE_DST.exists():
            STYLE_DST.unlink()
    else:
        for event, name in EVENTS.items():
            hooks.setdefault(event, []).append(
                {"hooks": [{"type": "command", "command": hook_command(name), "timeout": 10}]}
            )
        STYLE_DST.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(STYLE_SRC, STYLE_DST)
        if not args.no_style:
            settings["outputStyle"] = "Rachel"
        elif settings.get("outputStyle") == "Jarvis":
            del settings["outputStyle"]
    if not hooks:
        del settings["hooks"]

    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.uninstall:
        print(f"TalkToMe desinstalado de {SETTINGS}.")
        return
    print(f"Hooks instalados en {SETTINGS}")
    print(f"Estilo Rachel copiado a {STYLE_DST}" + ("" if args.no_style else " y activado"))
    if not (ROOT / ".env").exists():
        print("Siguiente paso: copia .env.example a .env y pon tu ELEVENLABS_API_KEY.")
    print("Luego: python talktome.py doctor  ·  python talktome.py say")


if __name__ == "__main__":
    main()
