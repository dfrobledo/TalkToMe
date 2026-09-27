#!/usr/bin/env python3
"""Launcher: works from any directory, so Claude Code hooks can call it by path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
