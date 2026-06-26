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
    CLAUDE_COMMANDS_DIR,
    CLAUDE_SETTINGS,
    LOOPER_HOME,
    LOOPS_FILE,
)

console = Console()

# Map of hook event -> the looper command it runs.
# SessionStart + Stop both run `looper sync` (claim/refresh the owner lease so
# only one session ever registers loops). SessionEnd releases the lease.
LOOPER_HOOKS = {
    "SessionStart": "looper sync",
    "Stop": "looper sync",
    "SessionEnd": "looper release",
}
LOOPER_HOOK_COMMANDS = set(LOOPER_HOOKS.values())


def _entry(command: str) -> dict:
    return {"matcher": "", "hooks": [{"type": "command", "command": command}]}

START_LOOPS_COMMAND = CLAUDE_COMMANDS_DIR / "start-loops.md"
DELETE_LOOP_COMMAND = CLAUDE_COMMANDS_DIR / "delete-loop.md"
STOP_LOOPS_COMMAND = CLAUDE_COMMANDS_DIR / "stop-loops.md"

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
Arm looper's durable loops for THIS session, without creating duplicates across
concurrent sessions.

Steps:
1. Run `looper sync --arm` with the Bash tool. It coordinates a single-owner
   lease so that only one live session registers the loops.

2. Read looper sync's output:
   - If it prints nothing (or says you are not the owner): another live session
     already owns the loops. Do NOT register anything. Tell the user the loops
     are already active in another session, and stop.
   - If it prints "[looper] You are now the loop owner" followed by a list of
     loops (each line `- <name> (<schedule>): <prompt>`): you are the owner —
     continue to step 3.

3. Run CronList to see what is already registered in THIS session.

4. For each loop in looper sync's list:
   - If a matching job already exists in CronList (same schedule + prompt), skip it.
   - Otherwise call CronCreate with recurring=true, using the loop's schedule and
     prompt. (This resets the 7-day expiry clock.)

5. Report a short summary: which loops were newly registered, which were already
   present, and any errors.

If `looper sync` fails because looper is not installed, tell the user to run
`looper install` first.
"""

DELETE_LOOP_CONTENT = """\
Delete a looper loop — remove it from the registry and stop it firing now.

Usage: /delete-loop <name>   (if no name is given, list loops and ask which)

Steps:
1. If no loop name was given in the command, run `looper list` with the Bash
   tool, show the user their loops, and ask which to delete. Wait for an answer.

2. Run `looper delete <name> --force` with Bash. This removes the loop from
   ~/.looper/loops.md so it won't be re-armed by /start-loops again.

3. Run CronList. If a live job in THIS session matches that loop (same prompt /
   schedule), call CronDelete on it so it stops firing immediately. (Jobs in
   other sessions will stop on their own once those sessions end.)

4. Confirm: removed from the registry, and whether a live job was also cancelled.

If `looper delete` says the loop doesn't exist, tell the user and stop.
"""

STOP_LOOPS_CONTENT = """\
Stop hosting looper's loops in THIS session and release the lease, so another
session can take over. (Use this to hand control to a different session — you do
NOT need it if you're just closing this session, which releases automatically.)

Steps:
1. Run `looper list` with the Bash tool to see the loops looper manages.
2. Run CronList. For each live job in THIS session that matches a looper loop
   (same prompt / schedule), call CronDelete so it stops firing here.
3. Run `looper release` with Bash to drop the ownership lease.
4. Report: which loops were stopped, and that the lease is released. Tell the
   user they can now run /start-loops in another session to resume them.

If `looper release` indicates nothing was held here, just report that this
session wasn't hosting the loops.
"""


def setup_looper_home() -> None:
    """Create ~/.looper/ directory structure and seed loops.md if missing."""
    LOOPER_HOME.mkdir(parents=True, exist_ok=True)
    console.print(f"  [green]+[/] {LOOPER_HOME}/")

    if not LOOPS_FILE.exists():
        LOOPS_FILE.write_text(LOOPS_MD_HEADER)
        console.print(f"  [green]+[/] {LOOPS_FILE} (initialized)")
    else:
        console.print(f"  [dim]-[/] {LOOPS_FILE} (already exists)")


def register_session_hook() -> None:
    """Register the SessionStart/Stop/SessionEnd hooks in ~/.claude/settings.json.

    Reads existing settings, adds any missing looper hooks (preserving every
    other hook), and writes back. Idempotent — re-running adds nothing new.
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
            console.print(f"  [yellow]![/] Backed up corrupt settings to {backup}")
            settings = {}
    else:
        settings = {}

    hooks = settings.get("hooks", {})
    if isinstance(hooks, list):
        hooks = {}

    for event, command in LOOPER_HOOKS.items():
        entries = hooks.get(event, [])
        already = any(
            h.get("command") == command
            for entry in entries
            for h in entry.get("hooks", [])
        )
        if already:
            console.print(f"  [dim]-[/] {event} hook (already registered)")
            continue
        entries.append(_entry(command))
        hooks[event] = entries
        console.print(f"  [green]+[/] {event} -> {command}")

    settings["hooks"] = hooks
    CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")


def install_start_loops_command() -> None:
    """Write looper's custom commands (/start-loops, /delete-loop) to ~/.claude/commands/."""
    CLAUDE_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)

    START_LOOPS_COMMAND.write_text(START_LOOPS_CONTENT)
    console.print(f"  [green]+[/] {START_LOOPS_COMMAND}")

    DELETE_LOOP_COMMAND.write_text(DELETE_LOOP_CONTENT)
    console.print(f"  [green]+[/] {DELETE_LOOP_COMMAND}")

    STOP_LOOPS_COMMAND.write_text(STOP_LOOPS_CONTENT)
    console.print(f"  [green]+[/] {STOP_LOOPS_COMMAND}")


def install() -> None:
    """Run the full looper installation.

    1. Set up ~/.looper/ home directory
    2. Register the SessionStart hook
    3. Install the /start-loops command
    """
    console.print("\n[bold]Installing looper...[/]\n")

    console.print("[bold]1.[/] Setting up looper home directory")
    setup_looper_home()

    console.print("\n[bold]2.[/] Registering hooks (SessionStart / Stop / SessionEnd)")
    register_session_hook()

    console.print("\n[bold]3.[/] Installing commands (/start-loops, /delete-loop, /stop-loops)")
    install_start_loops_command()

    console.print("\n[bold green]Done![/] looper is installed.\n")
    console.print("  Next steps:")
    console.print('    1. Open Claude and say: [cyan]"Using looper, schedule a loop to check deploys every 30m"[/]')
    console.print("    2. Or use the CLI:      [cyan]looper add <name> <interval> --prompt '...'[/]")
    console.print("    3. Or browse the TUI:   [cyan]looper tui[/]")
    console.print(
        "\n  Loops auto-sync on every Claude session start via hook.\n"
    )


def uninstall() -> None:
    """Remove looper's Claude Code integration.

    - Removes the SessionStart hook from settings.json (preserves other hooks)
    - Removes the /start-loops command file
    - Does NOT delete ~/.looper/ (user's data)
    """
    console.print("\n[bold]Uninstalling looper...[/]\n")

    # Remove looper hooks (SessionStart/Stop/SessionEnd), preserving others
    console.print("[bold]1.[/] Removing looper hooks")
    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
        except (json.JSONDecodeError, ValueError):
            settings = {}

        hooks = settings.get("hooks", {})
        if isinstance(hooks, list):
            hooks = {}

        removed = False
        for event in list(hooks.keys()):
            entries = hooks.get(event, [])
            kept = [
                entry for entry in entries
                if not any(
                    h.get("command") in LOOPER_HOOK_COMMANDS
                    for h in entry.get("hooks", [])
                )
            ]
            if len(kept) < len(entries):
                removed = True
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)

        settings["hooks"] = hooks
        CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
        console.print(
            "  [green]+[/] looper hooks removed" if removed
            else "  [dim]-[/] looper hooks (not found)"
        )
    else:
        console.print("  [dim]-[/] settings.json (not found)")

    # Remove custom commands
    console.print("\n[bold]2.[/] Removing commands (/start-loops, /delete-loop, /stop-loops)")
    for cmd in (START_LOOPS_COMMAND, DELETE_LOOP_COMMAND, STOP_LOOPS_COMMAND):
        if cmd.exists():
            cmd.unlink()
            console.print(f"  [green]+[/] Removed {cmd}")
        else:
            console.print(f"  [dim]-[/] {cmd} (not found)")

    console.print("\n[bold green]Done![/] looper integration removed.\n")
    console.print(
        f"  [dim]Note: {LOOPER_HOME}/ was preserved (your loop definitions are safe).[/]\n"
    )
