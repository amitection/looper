"""Core registry — parse, write, diff, and sync loops against live cron jobs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from looper import (
    CANONICAL_TASKS,
    EXPIRY_DAYS,
    LOOPS_FILE,
    RENEW_BEFORE_DAYS,
    SHORTHAND_MULTIPLIERS,
    SHORTHAND_PATTERN,
)
from looper.models import CheckResult, Job, Loop, LoopStatus


# ---------------------------------------------------------------------------
# Interval helpers
# ---------------------------------------------------------------------------

def validate_interval(interval: str) -> bool:
    """Return True if *interval* is a valid shorthand (10m, 1h) or 5-field cron."""
    interval = interval.strip()
    if re.match(SHORTHAND_PATTERN, interval):
        return True
    return _is_valid_cron(interval)


def interval_to_seconds(interval: str) -> int:
    """Convert a shorthand interval to seconds.  Raises ValueError for cron."""
    interval = interval.strip()
    m = re.match(SHORTHAND_PATTERN, interval)
    if not m:
        raise ValueError(
            f"Cannot convert '{interval}' to seconds — only shorthand "
            f"intervals (e.g. 10m, 1h, 30s) are supported, not cron expressions."
        )
    value, unit = int(m.group(1)), m.group(2)
    return value * SHORTHAND_MULTIPLIERS[unit]


def _is_valid_cron(expr: str) -> bool:
    """Minimal validation for a 5-field cron expression."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return False
    # Each field must contain only digits, *, /, -, and commas.
    field_re = re.compile(r"^[\d*/,\-]+$")
    return all(field_re.match(p) for p in parts)


# ---------------------------------------------------------------------------
# loops.md parsing / writing
# ---------------------------------------------------------------------------

def parse_loops(path: Optional[Path] = None) -> list[Loop]:
    """Parse loops.md into a list of Loop objects.

    Each ``## <name>`` heading starts a section.  Metadata lines (``key: value``)
    come first, followed by a blank line separator, then the prompt body which
    runs until the next ``##`` heading or end-of-file.
    """
    path = path or LOOPS_FILE
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    return _parse_loops_text(text)


def _parse_loops_text(text: str) -> list[Loop]:
    """Parse raw markdown text into Loop objects."""
    loops: list[Loop] = []
    heading_re = re.compile(r"^##\s+(.+)$")

    # Split into sections by ## headings.
    sections: list[tuple[str, list[str]]] = []
    current_name: Optional[str] = None
    current_lines: list[str] = []

    for line in text.splitlines():
        m = heading_re.match(line)
        if m:
            # Save previous section (if any).
            if current_name is not None:
                sections.append((current_name, current_lines))
            current_name = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Don't forget the last section.
    if current_name is not None:
        sections.append((current_name, current_lines))

    for name, lines in sections:
        meta: dict[str, str] = {}
        body_start = 0

        # Parse metadata lines until we hit a blank line or a non-metadata line.
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "":
                body_start = i + 1
                break
            kv = _parse_meta_line(stripped)
            if kv:
                meta[kv[0]] = kv[1]
                body_start = i + 1
            else:
                # Non-metadata, non-blank line — body starts here.
                body_start = i
                break

        prompt = "\n".join(lines[body_start:]).strip()

        interval = meta.get("interval", "")
        if not interval:
            # Skip sections without an interval — they're not valid loops.
            continue

        active_str = meta.get("active", "true").lower()
        active = active_str not in ("false", "no", "0")

        loops.append(Loop(
            name=name,
            interval=interval,
            prompt=prompt,
            active=active,
            created_at=meta.get("created_at"),
            paused_at=meta.get("paused_at"),
        ))

    return loops


def _parse_meta_line(line: str) -> Optional[tuple[str, str]]:
    """Try to parse ``key: value`` from a line.  Returns None if not metadata."""
    m = re.match(r"^([a-z_]+)\s*:\s*(.+)$", line)
    if m:
        return m.group(1), m.group(2).strip()
    return None


def write_loop(loop: Loop, path: Optional[Path] = None) -> None:
    """Write or update a loop section in loops.md.

    If a section with the same name exists, it is replaced in-place.
    Otherwise the new section is appended at the end.
    """
    path = path or LOOPS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    new_section = loop.to_markdown()

    if not path.exists():
        path.write_text(new_section + "\n", encoding="utf-8")
        return

    text = path.read_text(encoding="utf-8")
    replaced, new_text = _replace_section(text, loop.name, new_section)

    if replaced:
        path.write_text(new_text, encoding="utf-8")
    else:
        # Append — ensure there's a blank line before the new section.
        if text and not text.endswith("\n"):
            text += "\n"
        if text and not text.endswith("\n\n"):
            text += "\n"
        path.write_text(text + new_section + "\n", encoding="utf-8")


def remove_loop(name: str, path: Optional[Path] = None) -> None:
    """Remove a loop section entirely from loops.md."""
    path = path or LOOPS_FILE
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")
    replaced, new_text = _replace_section(text, name, None)
    if replaced:
        # Clean up excessive blank lines left behind.
        new_text = re.sub(r"\n{3,}", "\n\n", new_text).strip()
        if new_text:
            new_text += "\n"
        path.write_text(new_text, encoding="utf-8")


def toggle_loop(name: str, active: bool, path: Optional[Path] = None) -> Loop:
    """Set active flag on a loop.  If pausing, set paused_at.  Returns updated Loop."""
    path = path or LOOPS_FILE
    loops = parse_loops(path)

    target: Optional[Loop] = None
    for loop in loops:
        if loop.name == name:
            target = loop
            break

    if target is None:
        raise KeyError(f"Loop '{name}' not found in {path}")

    target.active = active
    if not active:
        target.paused_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        target.paused_at = None

    write_loop(target, path)
    return target


def _replace_section(
    text: str, name: str, replacement: Optional[str]
) -> tuple[bool, str]:
    """Replace (or remove if *replacement* is None) a ``## <name>`` section.

    Returns (was_found, new_text).
    """
    heading_re = re.compile(r"^##\s+", re.MULTILINE)
    target_re = re.compile(
        r"^##\s+" + re.escape(name) + r"\s*$", re.MULTILINE
    )

    m = target_re.search(text)
    if not m:
        return False, text

    start = m.start()

    # Find the start of the *next* ## heading after this one.
    rest = text[m.end():]
    next_heading = heading_re.search(rest)
    if next_heading:
        end = m.end() + next_heading.start()
    else:
        end = len(text)

    if replacement is not None:
        # Ensure replacement ends with a newline.
        if not replacement.endswith("\n"):
            replacement += "\n"
        new_text = text[:start] + replacement + text[end:]
    else:
        new_text = text[:start] + text[end:]

    return True, new_text


# ---------------------------------------------------------------------------
# scheduled_tasks.json parsing
# ---------------------------------------------------------------------------

def parse_jobs(path: Optional[Path] = None) -> list[Job]:
    """Read scheduled_tasks.json and return Job objects.

    Handles missing file or invalid JSON gracefully (returns []).
    """
    path = path or CANONICAL_TASKS
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []

    jobs: list[Job] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            jobs.append(Job(
                id=str(entry.get("id", "")),
                name=str(entry.get("name", entry.get("description", ""))),
                interval=str(entry.get("interval", entry.get("schedule", ""))),
                prompt=str(entry.get("prompt", "")),
                created_at=str(entry.get("createdAt", entry.get("created_at", ""))),
            ))
        except Exception:
            continue

    return jobs


# ---------------------------------------------------------------------------
# Diff / reconcile
# ---------------------------------------------------------------------------

def diff(loops: list[Loop], jobs: list[Job]) -> CheckResult:
    """Diff declared loops against live jobs to produce a CheckResult."""
    statuses: list[LoopStatus] = []
    matched_job_ids: set[str] = set()

    for loop in loops:
        if not loop.active:
            statuses.append(LoopStatus(loop=loop, state="paused"))
            continue

        job = _find_matching_job(loop, jobs)
        if job is None:
            statuses.append(LoopStatus(loop=loop, state="missing"))
        else:
            matched_job_ids.add(job.id)
            days_left = _days_until_expiry(job)
            if days_left is not None and days_left <= RENEW_BEFORE_DAYS:
                statuses.append(LoopStatus(
                    loop=loop,
                    job=job,
                    state="expiring",
                    days_until_expiry=round(days_left, 1),
                ))
            else:
                statuses.append(LoopStatus(
                    loop=loop,
                    job=job,
                    state="active",
                    days_until_expiry=round(days_left, 1) if days_left is not None else None,
                ))

    # Orphan jobs — live jobs that don't match any declared loop.
    orphan_jobs: list[Job] = [j for j in jobs if j.id not in matched_job_ids]

    needs_sync = any(
        s.state in ("missing", "expiring") for s in statuses
    ) or bool(orphan_jobs)

    result = CheckResult(
        statuses=statuses,
        orphan_jobs=orphan_jobs,
        needs_sync=needs_sync,
    )
    result.message = _build_message(result)
    return result


def _find_matching_job(loop: Loop, jobs: list[Job]) -> Optional[Job]:
    """Find a job whose name contains the loop's name (case-insensitive)."""
    lower_name = loop.name.lower()
    for job in jobs:
        if lower_name in job.name.lower():
            return job
    return None


def _days_until_expiry(job: Job) -> Optional[float]:
    """Compute days remaining before *job* expires (EXPIRY_DAYS after createdAt)."""
    if not job.created_at:
        return None
    try:
        created = _parse_iso(job.created_at)
        expiry = created.timestamp() + EXPIRY_DAYS * 86400
        now = datetime.now(timezone.utc).timestamp()
        return (expiry - now) / 86400
    except (ValueError, OSError):
        return None


def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 datetime string to a tz-aware datetime."""
    # Handle both 'Z' suffix and +00:00 style offsets.
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _build_message(result: CheckResult) -> str:
    """Build a human-readable summary message for the CheckResult."""
    parts: list[str] = []

    if result.active_count:
        parts.append(f"{result.active_count} active")
    if result.missing_count:
        parts.append(f"{result.missing_count} missing")
    if result.expiring_count:
        parts.append(f"{result.expiring_count} expiring")

    paused = sum(1 for s in result.statuses if s.state == "paused")
    if paused:
        parts.append(f"{paused} paused")

    if result.orphan_jobs:
        parts.append(f"{len(result.orphan_jobs)} orphan")

    if not parts:
        return "No loops registered."

    summary = ", ".join(parts)

    if result.needs_sync:
        return f"{summary} -- sync needed"
    return summary


# ---------------------------------------------------------------------------
# Symlink management
# ---------------------------------------------------------------------------

def ensure_symlink(project_dir: Optional[Path] = None) -> bool:
    """Create or verify the symlink from project's scheduled_tasks.json to canonical.

    Returns True if the symlink is correct (created or already existed).
    Returns False if a non-symlink file already exists and cannot be replaced.
    """
    project_dir = project_dir or Path.cwd()
    link_path = project_dir / ".claude" / "scheduled_tasks.json"
    target = CANONICAL_TASKS

    # Ensure the canonical side exists.
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text("[]", encoding="utf-8")

    # Ensure the project .claude dir exists.
    link_path.parent.mkdir(parents=True, exist_ok=True)

    if link_path.is_symlink():
        if link_path.resolve() == target.resolve():
            return True
        # Symlink points elsewhere — relink.
        link_path.unlink()
        link_path.symlink_to(target)
        return True

    if link_path.exists():
        # A real file already exists.  Don't clobber it — the caller should
        # decide what to do.
        return False

    link_path.symlink_to(target)
    return True


# ---------------------------------------------------------------------------
# Full check (convenience)
# ---------------------------------------------------------------------------

def check(project_dir: Optional[Path] = None) -> CheckResult:
    """Full check: parse loops, parse jobs, diff, optionally ensure_symlink.

    Returns a CheckResult with needs_sync and a human-readable message.
    """
    if project_dir is not None:
        ensure_symlink(project_dir)

    loops = parse_loops()
    jobs = parse_jobs()
    return diff(loops, jobs)
