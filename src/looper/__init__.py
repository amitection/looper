"""Looper - Durable loop registry for Claude Code scheduled loops."""

from pathlib import Path

__version__ = "0.1.0"

LOOPER_HOME = Path.home() / ".looper"
LOOPS_FILE = LOOPER_HOME / "loops.md"
CANONICAL_TASKS = LOOPER_HOME / ".claude" / "scheduled_tasks.json"
CLAUDE_COMMANDS_DIR = Path.home() / ".claude" / "commands"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"

RENEW_BEFORE_DAYS = 6
EXPIRY_DAYS = 7

SHORTHAND_PATTERN = r"^(\d+)([smhd])$"
SHORTHAND_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
