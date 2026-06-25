Re-register all active loops from ~/.looper/loops.md as Claude Code cron jobs, resetting expiry.

## Instructions

1. **Read the loop registry.** Read `~/.looper/loops.md`. If the file does not exist, stop and tell the user: "No loop registry found. Run `looper install` first to create ~/.looper/loops.md."

2. **Parse loop sections.** Each loop is a `## LoopName` section containing YAML-style metadata lines (`interval:`, `active:`, `project:`) followed by a prompt body (everything after the metadata block until the next `##` or EOF). Collect all loops into a list.

3. **Filter to active loops.** Keep only loops where `active: true`. Report any inactive loops as skipped.

4. **List existing cron jobs.** Use the `CronList` tool to get all currently scheduled tasks. If CronList is unavailable, read `~/.claude/scheduled_tasks.json` as a fallback.

5. **For each active loop, sync it:**

   a. **Check for existing job.** Search the cron list for any job whose name or description contains the loop name (case-insensitive match).

   b. **Delete stale jobs.** If a matching job exists and was created more than 6 days ago (i.e., approaching the 7-day expiry), delete it with `CronDelete`. If the job was created 6 days ago or less, mark it as "still current" and skip to the next loop.

   c. **Create the cron job.** Use `CronCreate` with:
      - **name**: `looper:{loop_name}` (this marker enables dedup on future runs)
      - **schedule**: The loop's `interval` value. Accept shorthand (`30m`, `1h`, `6h`) or cron expressions (`0 9 * * 1-5`). Convert shorthand: `30m` = `*/30 * * * *`, `1h` = `0 * * * *`, `6h` = `0 */6 * * *`, `12h` = `0 */12 * * *`, `1d` = `0 9 * * *`.
      - **prompt**: The loop's prompt body text exactly as written in loops.md.
      - **project**: The loop's `project:` value if specified, otherwise omit.
      - **recurring**: `true`

6. **Report summary.** Print a table or list showing:
   - Total loops in registry
   - Synced (newly created)
   - Already current (skipped, not expiring yet)
   - Inactive (skipped)
   - Errors (with details)

## Example loops.md format

```markdown
## pr-review
interval: 6h
active: true
project: /Users/me/workspace/myapp

Review open PRs in this repo. For each PR with no review comments from me, read the diff and leave a constructive review.

## deploy-check
interval: 30m
active: true

SSH to prod and check that all services are healthy. If any are down, send a Discord notification.

## old-loop
interval: 1d
active: false

This loop is paused.
```
