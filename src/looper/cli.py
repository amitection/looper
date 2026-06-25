"""CLI interface for looper — Click commands with Rich output."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from looper import LOOPS_FILE
from looper.models import Loop
from looper.registry import (
    check,
    ensure_symlink,
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
    """Show all loops and their current state."""
    result = check()

    if not result.statuses and not result.orphan_jobs:
        console.print("[dim]No loops registered. Run [bold]looper add[/bold] to create one.[/dim]")
        return

    if result.statuses:
        table = Table(title="Loops", show_lines=False)
        table.add_column("", width=2)  # icon
        table.add_column("Name", style="bold")
        table.add_column("Interval")
        table.add_column("State")
        table.add_column("Active")
        table.add_column("Expiry")

        for status in result.statuses:
            expiry = ""
            if status.days_until_expiry is not None:
                days = status.days_until_expiry
                if days < 1:
                    expiry = f"[red]{days:.1f}d[/]"
                elif days < 3:
                    expiry = f"[yellow]{days:.1f}d[/]"
                else:
                    expiry = f"{days:.1f}d"

            active_str = "[green]yes[/]" if status.loop.active else "[dim]no[/]"

            table.add_row(
                status.icon,
                status.loop.name,
                status.loop.interval,
                status.state,
                active_str,
                expiry,
            )

        console.print(table)

    if result.orphan_jobs:
        console.print()
        orphan_table = Table(title="[red]Orphan Jobs[/] (in cron but not in loops.md)")
        orphan_table.add_column("ID", style="dim")
        orphan_table.add_column("Name")
        orphan_table.add_column("Interval")

        for job in result.orphan_jobs:
            orphan_table.add_row(job.id[:8] + "...", job.name, job.interval)

        console.print(orphan_table)

    if result.needs_sync:
        console.print()
        console.print(
            "[yellow]Out of sync.[/] Run [bold]/start-loops[/bold] in Claude to reconcile."
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
# looper retrigger
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
def retrigger(name: str) -> None:
    """Print a loop's prompt for one-shot execution or CronCreate re-registration."""
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
    console.rule("Prompt (paste into Claude for one-shot run)")
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
# looper check
# ---------------------------------------------------------------------------


@main.command("check")
@click.option(
    "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project directory to check symlink for.",
)
def check_cmd(project_dir: Path | None) -> None:
    """Check loop health: registry vs live cron jobs."""
    result = check(project_dir)

    # Summary line
    parts = []
    if result.active_count:
        parts.append(f"[green]{result.active_count} active[/]")
    if result.missing_count:
        parts.append(f"[red]{result.missing_count} missing[/]")
    if result.expiring_count:
        parts.append(f"[yellow]{result.expiring_count} expiring[/]")
    paused = sum(1 for s in result.statuses if s.state == "paused")
    if paused:
        parts.append(f"[dim]{paused} paused[/]")
    if result.orphan_jobs:
        parts.append(f"[red]{len(result.orphan_jobs)} orphan[/]")

    if parts:
        console.print(f"looper: {', '.join(parts)}")
    else:
        console.print("[dim]looper: no loops registered[/]")

    # Detail per status
    for status in result.statuses:
        detail = f"  {status.icon} {status.loop.name}: {status.state}"
        if status.days_until_expiry is not None:
            detail += f" ({status.days_until_expiry:.1f}d until expiry)"
        console.print(detail)

    for job in result.orphan_jobs:
        console.print(f"  [red]?[/] {job.name}: orphan (no loops.md entry)")

    if result.message:
        console.print()
        console.print(f"[dim]{result.message}[/]")

    if result.needs_sync:
        console.print()
        console.print(
            "[yellow]Sync needed.[/] Run [bold]/start-loops[/bold] in Claude to reconcile."
        )


# ---------------------------------------------------------------------------
# looper link
# ---------------------------------------------------------------------------


@main.command()
@click.argument(
    "project_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
)
def link(project_dir: Path) -> None:
    """Symlink a project's scheduled_tasks.json to the canonical file."""
    project_dir = project_dir.resolve()
    created = ensure_symlink(project_dir)

    if created:
        console.print(
            f"[green]Linked[/] {project_dir / '.claude' / 'scheduled_tasks.json'}\n"
            f"    -> {LOOPS_FILE.parent / '.claude' / 'scheduled_tasks.json'}"
        )
    else:
        console.print("[dim]Symlink already exists and points to the canonical file.[/dim]")


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
