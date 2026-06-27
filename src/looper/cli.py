"""CLI interface for looper — Click commands with Rich output."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from looper import LOOPS_FILE
from looper.models import Loop
from looper.registry import (
    parse_loops,
    remove_loop,
    toggle_loop,
    validate_interval,
    write_loop,
)

console = Console()
err_console = Console(stderr=True)


@click.group()
@click.version_option(package_name="looper")
def main() -> None:
    """looper - Durable loop registry for Claude Code scheduled loops."""


# ---------------------------------------------------------------------------
# looper list
# ---------------------------------------------------------------------------


@main.command("list")
def list_cmd() -> None:
    """Show the loops declared in loops.md.

    This is what looper *knows about* — the durable registry. It does NOT show
    whether a loop is live in a Claude session right now: native crons are
    session-only and in-memory, so the CLI genuinely cannot observe them. Use
    /start-loops inside Claude to (re)arm these in a session.
    """
    from looper.harvest import running_loop_names

    loops = parse_loops()

    if not loops:
        console.print(
            "[dim]No loops registered. Create one in Claude ([italic]\"create a loop "
            "to …\"[/]) or run [bold]looper add[/bold].[/dim]"
        )
        return

    # A loop is "running" if any still-alive session reports hosting it.
    running = running_loop_names()

    table = Table(title="Loops", show_lines=False)
    table.add_column("", width=2)
    table.add_column("Name", style="bold")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Prompt")

    idle_count = 0
    for lp in loops:
        if not lp.active:
            icon, status = "[dim]◌[/]", "[dim]paused[/]"
        elif lp.name in running:
            icon, status = "[green]●[/]", "[green]running[/]"
        else:
            icon, status = "[yellow]○[/]", "[yellow]idle[/]"
            idle_count += 1
        preview = lp.prompt.replace("\n", " ")
        if len(preview) > 50:
            preview = preview[:49] + "…"
        table.add_row(icon, lp.name, lp.interval, status, preview)

    console.print(table)
    if idle_count:
        console.print(
            "\n[dim]"
            f"{idle_count} enabled loop(s) are idle (no live session hosting them). "
            "Run [bold]/start-loops[/bold] in Claude to start them.[/dim]"
        )
    else:
        console.print(
            "\n[dim]status: [green]running[/] = a live session is hosting it · "
            "[yellow]idle[/] = run [bold]/start-loops[/bold] · [dim]paused[/] = disabled[/dim]"
        )


# ---------------------------------------------------------------------------
# looper add
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
@click.argument("interval")
@click.option("--prompt", "-p", required=True, help="The prompt text for the loop.")
def add(name: str, interval: str, prompt: str) -> None:
    """Add a new loop to the registry."""
    if not validate_interval(interval):
        err_console.print(
            f"[red]Invalid interval:[/] [bold]{interval}[/]\n"
            "Use shorthand (10m, 1h, 30m, 1d) or 5-field cron ('0 9 * * 1-5')."
        )
        raise SystemExit(1)

    # Check for duplicate names
    existing = parse_loops()
    for loop in existing:
        if loop.name == name:
            err_console.print(
                f"[red]Loop [bold]{name}[/bold] already exists.[/] "
                "Delete it first or choose a different name."
            )
            raise SystemExit(1)

    new_loop = Loop(
        name=name,
        interval=interval,
        prompt=prompt,
        active=True,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    write_loop(new_loop)
    console.print(f"[green]Added loop [bold]{name}[/bold][/] (interval: {interval})")
    console.print("[dim]Run [bold]/start-loops[/bold] in Claude to activate it.[/dim]")


# ---------------------------------------------------------------------------
# looper pause
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
def pause(name: str) -> None:
    """Pause a loop (set active=false)."""
    try:
        loop = toggle_loop(name, active=False)
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc

    console.print(f"[yellow]Paused loop [bold]{loop.name}[/bold].[/]")
    console.print("[dim]Run [bold]/start-loops[/bold] in Claude to apply.[/dim]")


# ---------------------------------------------------------------------------
# looper resume
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
def resume(name: str) -> None:
    """Resume a paused loop (set active=true)."""
    try:
        loop = toggle_loop(name, active=True)
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc

    console.print(f"[green]Resumed loop [bold]{loop.name}[/bold].[/]")
    console.print("[dim]Run [bold]/start-loops[/bold] in Claude to activate.[/dim]")


# ---------------------------------------------------------------------------
# looper delete
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
@click.option("--force", is_flag=True, help="Confirm permanent deletion.")
def delete(name: str, force: bool) -> None:
    """Remove a loop from the registry permanently."""
    if not force:
        console.print(
            f"[yellow]This will permanently remove [bold]{name}[/bold] from {LOOPS_FILE}.[/]\n"
            "Consider [bold]looper pause[/bold] instead if you might want it back.\n\n"
            "To confirm, re-run with [bold]--force[/bold]."
        )
        raise SystemExit(1)

    try:
        remove_loop(name)
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc

    console.print(f"[red]Deleted loop [bold]{name}[/bold].[/]")
    console.print(
        "[dim]This did not touch live cron jobs. "
        "Run [bold]/start-loops[/bold] in Claude to clean up.[/dim]"
    )


# ---------------------------------------------------------------------------
# looper show
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
def show(name: str) -> None:
    """Print a loop's details, prompt, and CronCreate command."""
    loops = parse_loops()
    target = None
    for loop in loops:
        if loop.name == name:
            target = loop
            break

    if target is None:
        err_console.print(f"[red]Loop [bold]{name}[/bold] not found in {LOOPS_FILE}.[/]")
        raise SystemExit(1)

    console.print(f"[bold]Loop:[/] {target.name}")
    console.print(f"[bold]Interval:[/] {target.interval}")
    console.print()
    console.rule("Prompt")
    console.print()
    # Print raw prompt to stdout so it can be piped/copied
    click.echo(target.prompt)
    console.print()
    console.rule("CronCreate command")
    console.print()
    console.print(f'CronCreate(interval="{target.interval}", prompt="""')
    console.print(target.prompt)
    console.print('""")')


# ---------------------------------------------------------------------------
# looper install
# ---------------------------------------------------------------------------


@main.command()
def install() -> None:
    """Set up looper: directories, hooks, and slash command."""
    from looper.installer import install as run_install

    run_install()


# ---------------------------------------------------------------------------
# looper tui
# ---------------------------------------------------------------------------


@main.command()
def tui() -> None:
    """Launch the interactive TUI dashboard."""
    from looper.tui import LooperApp

    app = LooperApp()
    app.run()


# ---------------------------------------------------------------------------
# Hook helpers: read the JSON payload Claude Code passes on stdin
# ---------------------------------------------------------------------------


def _read_hook_payload() -> dict:
    """Parse the JSON Claude Code pipes to a hook on stdin. {} if none."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# looper sync  (SessionStart + Stop hook)
# ---------------------------------------------------------------------------


@main.command()
@click.option("--session-id", default=None, help="Override session id (else read from hook stdin).")
@click.option("--pid", type=int, default=None, help="Override the liveness pid (else auto-discover).")
@click.option("--arm", is_flag=True, help="If this session is the owner, print the loops to register.")
@click.option("--watchdog", is_flag=True, help="Also list a 1/min self-check loop to register.")
def sync(session_id: str | None, pid: int | None, arm: bool, watchdog: bool) -> None:
    """Claim/refresh the owner lease and capture this session's live crons.

    Wired to the SessionStart and Stop hooks for lease coordination + capture.
    Exactly one live session owns the loops at a time, so they never fire in
    duplicate across concurrent sessions.

    With --arm (used by /start-loops): if this session owns the lease, print the
    active loops that should be registered. A follower prints nothing — that is
    what prevents a second session from re-registering the same loops.
    """
    import os

    from looper import lease as lease_mod
    from looper.harvest import harvest as _harvest
    from looper.registry import parse_loops as _parse

    payload = _read_hook_payload()
    pid = pid if pid is not None else lease_mod.discover_session_pid()
    # Fall back to a pid-derived id (stable per session) when not invoked as a
    # hook, so manual `looper sync` calls in the same session are recognised.
    sid = session_id or payload.get("session_id") or f"pid-{pid}"
    session_crons = payload.get("session_crons") or []
    cwd = payload.get("cwd") or os.getcwd()

    # Only /start-loops (--arm) may take ownership. Background hooks pass
    # claim=False so an idle session never squats the lease.
    result = lease_mod.claim_or_refresh(sid, pid, claim=arm, cwd=cwd)

    # Capture (Claude -> looper): mirror this session's live crons into loops.md,
    # and record this session's note (pid + cwd) so `looper list` can show running.
    _harvest(sid, session_crons, pid, cwd)

    if not arm:
        return  # background hook: capture only

    # Follower: another live session owns the loops. Name it, and tell the user
    # how to move control here. Stay non-destructive (no takeover).
    if result == "follower":
        holder = lease_mod.read_lease() or {}
        where = holder.get("cwd") or "another session"
        hpid = holder.get("pid", "?")
        click.echo(
            f"[looper] Your loops are already running in {where} (pid {hpid}).\n"
            f"To move them here: run /stop-loops in that session, then /start-loops here."
        )
        return

    live = {(str(c.get("schedule", "")).strip(), str(c.get("prompt", "")).strip()) for c in session_crons}
    missing = [
        lp for lp in _parse()
        if lp.active and (lp.interval.strip(), lp.prompt.strip()) not in live
    ]
    if not missing:
        click.echo("[looper] You are the loop owner. All active loops are already live.")
        return

    lines = [
        "[looper] You are now the loop owner for this machine.",
        "Register these loops as recurring cron jobs (CronCreate, recurring=true):",
        "",
    ]
    for lp in missing:
        lines.append(f"  - {lp.name} ({lp.interval}): {lp.prompt}")
    if watchdog:
        lines.append("")
        lines.append("  - looper-watchdog (every 1 min): run `looper sync` via Bash, report nothing")
    click.echo("\n".join(lines))


# ---------------------------------------------------------------------------
# looper release  (SessionEnd hook)
# ---------------------------------------------------------------------------


@main.command()
@click.option("--session-id", default=None, help="Override session id (else read from hook stdin).")
@click.option("--pid", type=int, default=None, help="Override the liveness pid (else auto-discover).")
def release(session_id: str | None, pid: int | None) -> None:
    """Drop the owner lease if this session holds it. Wired to SessionEnd."""
    from looper import lease as lease_mod

    from looper.harvest import clear_state

    payload = _read_hook_payload()
    pid = pid if pid is not None else lease_mod.discover_session_pid()
    sid = session_id or payload.get("session_id") or f"pid-{pid}"
    lease_mod.release(sid, pid)
    clear_state(sid)  # drop this session's note so its loops show idle


# ---------------------------------------------------------------------------
# looper _hookdump  (probe — capture the raw hook payload + process ancestry)
# ---------------------------------------------------------------------------


@main.command("_hookdump")
def hookdump() -> None:
    """Append the raw hook stdin payload and process ancestry to a log.

    Temporary probe to confirm what liveness signal the hook actually exposes.
    """
    from looper import LOOPER_HOME
    from looper import lease as lease_mod

    payload = _read_hook_payload()
    ancestry = []
    pid = lease_mod.os.getpid()
    seen: set[int] = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        ppid, comm = lease_mod._proc_info(pid)
        ancestry.append({"pid": pid, "ppid": ppid, "comm": comm})
        if ppid <= 1:
            break
        pid = ppid

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "ancestry": ancestry,
        "discovered_session_pid": lease_mod.discover_session_pid(),
    }
    log = LOOPER_HOME / "hookdump.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as f:
        f.write(json.dumps(record) + "\n")
