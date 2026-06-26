"""Looper - Durable loop registry for Claude Code scheduled loops."""

from pathlib import Path

__version__ = "0.1.0"

LOOPER_HOME = Path.home() / ".looper"
LOOPS_FILE = LOOPER_HOME / "loops.md"
CLAUDE_COMMANDS_DIR = Path.home() / ".claude" / "commands"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"

SHORTHAND_PATTERN = r"^(\d+)([smhd])$"
SHORTHAND_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
