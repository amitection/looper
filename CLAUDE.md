# looper - Project Guidelines

looper makes Claude Code's `CronCreate` loops durable. It keeps a human-editable
registry (`~/.looper/loops.md`), auto-captures loops you create in Claude (via a
`Stop` hook reading `session_crons`), and re-arms them with `/start-loops`. A
single-owner lease prevents duplicate firing across sessions. Python 3.11+, Click
CLI, Textual TUI, Rich output.

## Quick Commands

```bash
uv run pytest tests/ -q          # Run tests
uv run looper list               # Try the CLI
pip install -e .                 # Editable install
```

## Package Structure

```
src/looper/
  __init__.py     # Constants (LOOPER_HOME, LOOPS_FILE, CLAUDE_*, SHORTHAND_*)
  models.py       # Data classes: Loop, LoopStatus
  registry.py     # loops.md parse/write/remove/toggle + interval helpers
  harvest.py      # Capture: reconcile session_crons -> loops.md; per-session
                  #          notes; running_loop_names() for status
  lease.py        # Single-owner lease (claim/refresh/release, pid liveness)
  cli.py          # Click CLI: list, add, pause, resume, delete, retrigger,
                  #            sync, release, install, tui
  tui.py          # Textual TUI for interactive loop management
  installer.py    # Setup: ~/.looper, hooks, /start-loops /stop-loops /delete-loop
```

## Key Design Decisions

- **`loops.md` is the source of truth** — a human-editable markdown registry.
- **Capture** — `Stop` hook runs `looper sync`, which reads the session's live
  crons from the hook payload and writes new ones into `loops.md`. Slash-command
  prompts (e.g. `/loop …`) are skipped to avoid recursion.
- **Additive registry** — a vanished/expired cron is never auto-removed (can't be
  told apart from a delete); removal is explicit (`looper delete` / `/delete-loop`).
- **Single-owner lease** (`~/.looper/owner.json`) — only `/start-loops` (`sync
  --arm`) claims it; background hooks never claim, so idle sessions can't squat.
  Control moves explicitly via `/stop-loops` then `/start-loops` (no hot-transfer).
- **Status via per-session notes** — each session writes `~/.looper/sessions/<id>.json`
  (pid + hosted loops); `looper list` shows a loop `running` if any live session's
  note lists it, else `idle`, else `paused`. Dead-session notes are pruned.

## Testing

- pytest with `tmp_path` fixtures; monkeypatch the module path constants
  (`looper.LOOPS_FILE`, `looper.lease.LEASE_FILE`, `looper.harvest.SESSIONS_DIR`, …)
  for isolation. No external test deps beyond pytest (+ pytest-asyncio for the TUI).
- A standalone end-to-end script drives the real binary with simulated hook
  payloads (kept in scratch during development, not in the repo).
