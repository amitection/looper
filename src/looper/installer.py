"""Installation and setup for looper's Claude Code integration.

Handles:
- Creating ~/.looper/ directory structure and initial loops.md
- Registering a SessionStart hook in ~/.claude/settings.json
- Installing the /start-loops custom command
- Clean uninstall (preserves user data in ~/.looper/)
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from looper import (
    CANONICAL_TASKS,
    CLAUDE_COMMANDS_DIR,
    CLAUDE_SETTINGS,
    LOOPER_HOME,
    LOOPS_FILE,
)

console = Console()

HOOK_COMMAND = "looper check"
SESSION_HOOK = {
    "type": "command",
    "event": "SessionStart",
    "command": HOOK_COMMAND,
}

START_LOOPS_COMMAND = CLAUDE_COMMANDS_DIR / "start-loops.md"

LOOPS_MD_HEADER = """\
# looper loops
#
# Each ## section defines a loop. Metadata lines (key: value) come first,
# then a blank line, then the prompt body (everything until the next ## or EOF).
#
# Supported metadata:
#   interval   - Required. Shorthand (10m, 1h, 30m, 1d, 300s) or 5-field cron (0 9 * * 1-5)
#   active     - true (default) or false
#   created_at - ISO 8601 timestamp (auto-set on creation)
#   paused_at  - ISO 8601 timestamp (auto-set on pause)
#
# Example:
#
# ## my-loop
# interval: 30m
# active: true
#
# Do something useful every 30 minutes.
"""

START_LOOPS_CONTENT = """\
Reconcile all active loops from the looper registry.

Steps:
1. Read ~/.looper/loops.md to get all loop definitions.
2. Check existing scheduled tasks (CronList) to see what's already registered.
3. For each active loop in loops.md:
   - If a matching job already exists (same name/prompt), skip it.
   - If no matching job exists, use CronCreate to register it with the loop's interval and prompt. This resets the 7-day expiry clock.
4. Report a summary of what was synced:
   - How many loops were already registered (skipped)
   - How many loops were newly registered
   - How many loops are paused (not synced)
   - Any errors encountered

Use the loop name as the CronCreate name/label for deduplication.
"""


def setup_looper_home() -> None:
    """Create ~/.looper/ directory structure and seed loops.md if missing."""
    LOOPER_HOME.mkdir(parents=True, exist_ok=True)
    console.print(f"  [green]+[/] {LOOPER_HOME}/")

    claude_dir = CANONICAL_TASKS.parent
    claude_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"  [green]+[/] {claude_dir}/")

    if not LOOPS_FILE.exists():
        LOOPS_FILE.write_text(LOOPS_MD_HEADER)
        console.print(f"  [green]+[/] {LOOPS_FILE} (initialized)")
    else:
        console.print(f"  [dim]-[/] {LOOPS_FILE} (already exists)")

    if not CANONICAL_TASKS.exists():
        CANONICAL_TASKS.write_text("[]")
        console.print(f"  [green]+[/] {CANONICAL_TASKS} (initialized)")
    else:
        console.print(f"  [dim]-[/] {CANONICAL_TASKS} (already exists)")


def register_session_hook() -> None:
    """Add a SessionStart hook to ~/.claude/settings.json.

    Reads the existing settings, appends the hook to the hooks array
    (creating it if absent), and writes back. Skips if the hook is
    already registered (matched by command string).
    """
    settings_dir = CLAUDE_SETTINGS.parent
    settings_dir.mkdir(parents=True, exist_ok=True)

    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
        except (json.JSONDecodeError, ValueError):
            # Corrupted settings file -- back up and start fresh
            backup = CLAUDE_SETTINGS.with_suffix(".json.bak")
            CLAUDE_SETTINGS.rename(backup)
            console.print(
                f"  [yellow]![/] Backed up corrupt settings to {backup}"
            )
            settings = {}
    else:
        settings = {}

    hooks = settings.get("hooks", [])

    # Check if already registered
    for hook in hooks:
        if hook.get("command") == HOOK_COMMAND:
            console.print("  [dim]-[/] SessionStart hook (already registered)")
            return

    hooks.append(SESSION_HOOK)
    settings["hooks"] = hooks

    CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    console.print("  [green]+[/] SessionStart hook registered in settings.json")


def install_start_loops_command() -> None:
    """Write the /start-loops custom command to ~/.claude/commands/."""
    CLAUDE_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)

    START_LOOPS_COMMAND.write_text(START_LOOPS_CONTENT)
    console.print(f"  [green]+[/] {START_LOOPS_COMMAND}")


def install() -> None:
    """Run the full looper installation.

    1. Set up ~/.looper/ home directory
    2. Register the SessionStart hook
    3. Install the /start-loops command
    """
    console.print("\n[bold]Installing looper...[/]\n")

    console.print("[bold]1.[/] Setting up looper home directory")
    setup_looper_home()

    console.print("\n[bold]2.[/] Registering SessionStart hook")
    register_session_hook()

    console.print("\n[bold]3.[/] Installing /start-loops command")
    install_start_loops_command()

    console.print("\n[bold green]Done![/] looper is installed.\n")
    console.print("  Next steps:")
    console.print("    1. Add loops:  [cyan]looper add <name> <interval>[/]")
    console.print("    2. Sync now:   [cyan]/start-loops[/] in Claude Code")
    console.print(
        "    3. Auto-sync:  happens on every session start via hook\n"
    )


def uninstall() -> None:
    """Remove looper's Claude Code integration.

    - Removes the SessionStart hook from settings.json (preserves other hooks)
    - Removes the /start-loops command file
    - Does NOT delete ~/.looper/ (user's data)
    """
    console.print("\n[bold]Uninstalling looper...[/]\n")

    # Remove SessionStart hook
    console.print("[bold]1.[/] Removing SessionStart hook")
    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
        except (json.JSONDecodeError, ValueError):
            settings = {}

        hooks = settings.get("hooks", [])
        original_count = len(hooks)
        hooks = [h for h in hooks if h.get("command") != HOOK_COMMAND]

        if len(hooks) < original_count:
            settings["hooks"] = hooks
            CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
            console.print("  [green]+[/] SessionStart hook removed")
        else:
            console.print("  [dim]-[/] SessionStart hook (not found)")
    else:
        console.print("  [dim]-[/] settings.json (not found)")

    # Remove start-loops command
    console.print("\n[bold]2.[/] Removing /start-loops command")
    if START_LOOPS_COMMAND.exists():
        START_LOOPS_COMMAND.unlink()
        console.print(f"  [green]+[/] Removed {START_LOOPS_COMMAND}")
    else:
        console.print(f"  [dim]-[/] {START_LOOPS_COMMAND} (not found)")

    console.print("\n[bold green]Done![/] looper integration removed.\n")
    console.print(
        f"  [dim]Note: {LOOPER_HOME}/ was preserved (your loop definitions are safe).[/]\n"
    )
