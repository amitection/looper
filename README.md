# Looper

**Make Claude Code loops run forever.** Claude Code's `CronCreate` jobs silently expire after 7 days. Looper keeps them alive — automatically.

## The problem

You set up a loop to slack you morning briefs, check pipelines, etc and a week later, it stops. No warning, no error — the cron job just expired. You have to manually re-create it. Every week. For every loop.

Looper fixes this. It keeps a persistent registry of your loops and auto-renews them on every Claude session start.

## How it works

looper uses a three-layer model:

```
~/.looper/loops.md                          <-- source of truth (hand-editable)
~/.looper/.claude/scheduled_tasks.json      <-- canonical live-jobs file
~/<project>/.claude/scheduled_tasks.json    <-- per-project symlink to canonical
```

**Layer 1: `loops.md`** is a markdown file you own. Each `## heading` defines a loop
with metadata (interval, active flag) and a prompt body. You can edit it by hand or
use the CLI.

**Layer 2: `scheduled_tasks.json`** is the file Claude Code reads for its cron jobs.
looper keeps one canonical copy in `~/.looper/.claude/` and diffs it against `loops.md`
to detect missing, expiring, or orphan jobs.

**Layer 3: Per-project symlinks** point each project's `.claude/scheduled_tasks.json`
to the canonical file, so loops work regardless of which project you open.

A `SessionStart` hook runs `looper check` on every Claude session. The `/start-loops`
slash command reconciles -- re-creating any missing or expiring jobs via `CronCreate`.

## Install

```bash
uv tool install git+https://github.com/amitection/looper.git
```

Or clone and install locally:

```bash
git clone https://github.com/amitection/looper.git
cd looper
pip install .
```

Then run the installer to set up directories, hooks, and the slash command:

```bash
looper install
```

This creates:
- `~/.looper/` directory with an initial `loops.md`
- `~/.looper/.claude/scheduled_tasks.json`
- A `SessionStart` hook in `~/.claude/settings.json`
- The `/start-loops` command in `~/.claude/commands/`

## Usage

### Add a loop

```bash
looper add my-check 30m --prompt "Check the deploy status and report any failures."
```

### List all loops

```bash
looper list
```

Output:

```
               Loops
  Name       Interval  State    Active  Expiry
  my-check   30m       active   yes     6.2d
  my-report  0 9 * * 1 paused   no
```

### Pause / resume

```bash
looper pause my-check
looper resume my-check
```

Paused loops stay in `loops.md` but are not registered as cron jobs.

### Delete

```bash
looper delete my-check --force
```

Requires `--force` to confirm. Removes the loop from `loops.md` entirely. If you might
want it back, use `pause` instead.

### Retrigger

```bash
looper retrigger my-check
```

Prints the loop's prompt (for one-shot execution) and the `CronCreate` command (for
manual re-registration).

### Check health

```bash
looper check
```

Diffs `loops.md` against live cron jobs and reports status:

```
looper: 2 active, 1 missing, 1 paused
  * my-check: active (5.8d until expiry)
  * my-report: paused
  * my-deploy: missing
```

### Link a project

```bash
looper link /path/to/project
# or from the project directory:
looper link .
```

Creates a symlink from the project's `.claude/scheduled_tasks.json` to the canonical file.

### Interactive TUI

```bash
looper tui
```

A Textual-based dashboard for viewing and managing loops.

### Reconcile in Claude Code

Type `/start-loops` in any Claude Code session. It reads `loops.md`, checks what's
already registered via `CronList`, and calls `CronCreate` for anything missing or
expiring. This is what keeps loops alive past 7 days.

## Interval formats

looper accepts two interval formats:

**Shorthand** -- a number followed by a unit:
- `30s` -- every 30 seconds
- `10m` -- every 10 minutes
- `1h` -- every hour
- `1d` -- every day

**5-field cron** -- standard cron syntax:
- `*/30 * * * *` -- every 30 minutes
- `0 9 * * 1-5` -- 9 AM weekdays
- `0 */6 * * *` -- every 6 hours

## How loops survive beyond 7 days

The refresh mechanism:

1. You open a Claude Code session (any project).
2. The `SessionStart` hook runs `looper check`.
3. If any active loops are missing or within `RENEW_BEFORE_DAYS` (6 days) of expiry,
   check reports "sync needed".
4. `/start-loops` re-creates each active loop via `CronCreate`, resetting the 7-day
   expiry clock.

As long as you open Claude Code at least once every ~7 days, loops run indefinitely.
`RENEW_BEFORE_DAYS = 6` gives a 1-day buffer -- loops are flagged for renewal with
a day to spare.

If you don't open Claude for more than 7 days, the cron jobs expire, but `loops.md`
preserves every definition. The next time you open a session and run `/start-loops`,
all active loops are re-registered.

## Limitations

- **Cron jobs only fire while Claude Code is open and idle.** If Claude is not running,
  scheduled loops do not execute.
- **You need a session within ~7 days or loops go stale.** The cron jobs expire server-side.
  `loops.md` preserves definitions, but execution stops until the next `/start-loops`.
- **Two concurrent sessions can briefly duplicate a loop.** If two sessions run
  `/start-loops` at the same time, the same loop may be registered twice. This is
  self-healing -- the next check detects the duplicate -- and rare in practice.

## File locations

| File | Purpose |
|------|---------|
| `~/.looper/loops.md` | Source of truth. All loop definitions live here. |
| `~/.looper/.claude/scheduled_tasks.json` | Canonical cron jobs file. Claude reads this. |
| `~/<project>/.claude/scheduled_tasks.json` | Symlink to canonical file. |
| `~/.claude/settings.json` | Contains the `SessionStart` hook. |
| `~/.claude/commands/start-loops.md` | The `/start-loops` slash command definition. |

## loops.md format

```markdown
## my-check
interval: 30m
active: true
created_at: 2025-06-20T10:00:00Z

Check the deploy status and report any failures.

## daily-report
interval: 0 9 * * 1-5
active: true
created_at: 2025-06-18T08:00:00Z

Generate the daily metrics report and post it to the team channel.

## old-loop
interval: 1h
active: false
paused_at: 2025-06-22T14:30:00Z

This loop is paused and will not be registered as a cron job.
```

Metadata keys: `interval` (required), `active` (default: true), `created_at`, `paused_at`.
Everything after the blank line following metadata is the prompt body.

## License

MIT
