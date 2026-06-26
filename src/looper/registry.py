"""Core registry — parse and edit loops.md (the durable loop registry)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from looper import LOOPS_FILE, SHORTHAND_MULTIPLIERS, SHORTHAND_PATTERN
from looper.models import Loop


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

    sections: list[tuple[str, list[str]]] = []
    current_name: Optional[str] = None
    current_lines: list[str] = []

    for line in text.splitlines():
        m = heading_re.match(line)
        if m:
            if current_name is not None:
                sections.append((current_name, current_lines))
            current_name = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_name is not None:
        sections.append((current_name, current_lines))

    for name, lines in sections:
        meta: dict[str, str] = {}
        body_start = 0

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
    target_re = re.compile(r"^##\s+" + re.escape(name) + r"\s*$", re.MULTILINE)

    m = target_re.search(text)
    if not m:
        return False, text

    start = m.start()

    rest = text[m.end():]
    next_heading = heading_re.search(rest)
    if next_heading:
        end = m.end() + next_heading.start()
    else:
        end = len(text)

    if replacement is not None:
        if not replacement.endswith("\n"):
            replacement += "\n"
        new_text = text[:start] + replacement + text[end:]
    else:
        new_text = text[:start] + text[end:]

    return True, new_text
