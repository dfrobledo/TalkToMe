"""Which project a Claude Code session belongs to, and how Rachel says its name.

With two terminals open, each on its own project, Rachel names the project
she speaks from whenever her voice jumps from one to the other. The name
comes from the folder of the repository (the nearest one with `.git`),
split so it can be pronounced: RockAvionics becomes "Rock Avionics".
`projects` in the config gives it a spoken name of its own and, if wanted,
its own voice or honorific.
"""
import re
from pathlib import Path


def root(cwd):
    """The repository `cwd` belongs to, or `cwd` itself outside one."""
    path = Path(cwd)
    for folder in (path, *path.parents):
        if (folder / ".git").exists():
            return folder
    return path


def speakable_name(name):
    """RockAvionics → Rock Avionics, rocket_yeah → rocket yeah."""
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return " ".join(re.sub(r"[_\-.]+", " ", name).split())


def identify(cwd, cfg):
    """(spoken project name, cfg with that project's overrides); ("", cfg) if unknown.

    `projects` maps a folder name (any case) to its spoken name, or to a dict
    with "name" plus config keys for that project only ("voice_id",
    "voice_settings", "honorific"...).
    """
    if not cwd:
        return "", cfg
    folder = root(cwd).name
    if not folder:
        return "", cfg
    entries = {key.lower(): value for key, value in (cfg.get("projects") or {}).items()}
    entry = entries.get(folder.lower())
    if isinstance(entry, str) and entry.strip():
        return entry.strip(), cfg
    if isinstance(entry, dict):
        overrides = {key: value for key, value in entry.items() if key != "name"}
        merged = {**cfg, **overrides}
        if isinstance(overrides.get("voice_settings"), dict):
            merged["voice_settings"] = {**cfg.get("voice_settings", {}), **overrides["voice_settings"]}
        return entry.get("name") or speakable_name(folder), merged
    return speakable_name(folder), cfg
