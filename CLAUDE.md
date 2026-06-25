# looper - Project Guidelines

looper is a durable loop registry for Claude Code scheduled loops. It tracks loop definitions in a human-editable markdown file, reconciles them with Claude Code's `scheduled_tasks.json`, and provides both a Click CLI and a Textual TUI for management. Python 3.11+, Click CLI, Textual TUI, Rich output.

## Quick Commands

```bash
uv run pytest tests/ -v          # Run tests
uv run ruff check src/           # Lint
uv run looper list              # Try the CLI
pip install -e .                 # Editable install
```

## Package Structure

```
src/looper/
  __init__.py        # Package init
  registry.py        # Core loop registry: CRUD, reconciliation, loops.md parsing/writing
  cli.py             # Click CLI (list, add, remove, reconcile, install, tui)
  tui.py             # Textual TUI for interactive loop management
  installer.py       # Setup: creates loops.md, symlinks scheduled_tasks.json, installs hooks
  models.py          # Data classes (Loop, Job, LoopStatus, CheckResult)
```

## Key Design Decisions

- **`loops.md` is the source of truth** -- a human-editable markdown file that defines all loops. Machine-parseable but readable and hand-editable.
- **`scheduled_tasks.json` is symlinked across projects** -- one canonical file, symlinked into each project's `.claude/` directory so Claude Code picks it up.
- **`RENEW_BEFORE_DAYS = 6`** -- loops are renewed with a 1-day buffer before Claude Code's 7-day expiry window.
- **SessionStart hook + `/start-loops` command** -- auto-reconciliation on session start ensures loops stay registered without manual intervention.
- **Reconciliation** syncs loops.md definitions into scheduled_tasks.json, adding missing loops and updating stale ones.

## Testing

- pytest with `tmp_path` fixtures for filesystem isolation.
- No external test dependencies beyond pytest.
- Tests cover registry CRUD, markdown round-tripping, reconciliation logic, and CLI commands.
