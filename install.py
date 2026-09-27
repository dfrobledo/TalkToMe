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


def _on_path(python):
    """A bare command name (python, py...) that runs this same interpreter."""
    for name in ("python", "python3", "py"):
        found = shutil.which(name)
        try:
            if found and Path(found).samefile(python):
                return name
        except OSError:
            continue
    return None


def hook_entry(event, python=None, launcher=None):
    """Hook definition that runs the same under Git Bash and PowerShell.

    The first word of the command is what differs between shells: bash takes
    a quoted path as is, PowerShell needs `& "..."`, which bash rejects. So the
    interpreter goes unquoted (plain path or its name on PATH); arguments may
    be quoted in both. Only if neither is possible do we pin PowerShell.
    """
    python = Path(python or sys.executable)
    launcher = Path(launcher or ROOT / "talktome.py").as_posix()
    script = f'"{launcher}"' if " " in launcher else launcher
    entry = {"type": "command", "timeout": 10}
    exe = python.as_posix() if " " not in python.as_posix() else _on_path(python)
    if exe:
        entry["command"] = f"{exe} {script} hook {event}"
    else:
        entry["command"] = f'& "{python.as_posix()}" "{launcher}" hook {event}'
        entry["shell"] = "powershell"
    return entry


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
                {"hooks": [hook_entry(name)]}
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
    print(f"  comando: {hook_entry('stop')['command']}")
    print(f"Estilo Rachel copiado a {STYLE_DST}" + ("" if args.no_style else " y activado"))
    if not (ROOT / ".env").exists():
        print("Siguiente paso: copia .env.example a .env y pon tu ELEVENLABS_API_KEY.")
    print("Luego: python talktome.py doctor  ·  python talktome.py say")


if __name__ == "__main__":
    main()
