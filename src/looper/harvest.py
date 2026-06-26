"""Capture live Claude crons into loops.md (the Claude -> looper direction).

Native Claude crons expose no durable identity: the `id` is regenerated every
session, and there is no name. So we track identity at two levels:

  - within a session, by the cron `id` (stable for the life of that session) —
    this is what lets us detect in-session edits and deletes correctly, since
    Claude has no edit op (an "edit" is really delete-old + create-new).
  - across sessions, by content `(schedule, prompt)` — this bridges a loop that
    looper re-injected so it is recognised as the same loop, not a new one.

`reconcile()` is a pure function (no IO) so it is fully unit-testable;
`harvest()` is the thin file-backed wrapper used by `looper sync`.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from looper import LOOPER_HOME
from looper.models import Loop
from looper.registry import parse_loops, remove_loop, write_loop

SESSIONS_DIR = LOOPER_HOME / "sessions"
LOOPS_LOCK = LOOPER_HOME / "loops.lock"


def _slug(prompt: str) -> str:
    words = re.findall(r"[a-z0-9]+", prompt.lower())
    return "-".join(words[:5]) or "loop"


def _unique_name(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _ck(schedule: str, prompt: str) -> tuple[str, str]:
    return (schedule.strip(), prompt.strip())


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).isoformat()


def reconcile(
    session_crons: list[dict],
    prev_map: dict[str, str],
    existing_loops: list[Loop],
    now: float,
) -> tuple[list[Loop], list[str], dict[str, str]]:
    """Pure reconcile of one session's live crons against loops.md.

    The registry is ADDITIVE: harvest only ever adds or binds loops, never
    removes them. A cron vanishing from session_crons is NOT treated as a
    deletion — we cannot tell expiry (keep it, so /start-loops can re-arm it)
    from a genuine delete using the payload alone, and silently dropping an
    expired loop would lose it. So removal is always explicit (`looper delete`
    / the /delete-loop command); a vanished id just falls out of the live map.

    Returns (loops_to_upsert, [], new_id_to_name_map). The empty list is kept
    in the signature so callers/tests stay uniform.
    """
    content_to_name = {_ck(lp.interval, lp.prompt): lp.name for lp in existing_loops}
    taken = {lp.name for lp in existing_loops}

    new_map: dict[str, str] = {}
    to_upsert: list[Loop] = []

    for c in session_crons:
        cid = c.get("id")
        if not cid:
            continue
        schedule = str(c.get("schedule", "")).strip()
        prompt = str(c.get("prompt", "")).strip()

        # Skip crons whose prompt is itself a slash-command (e.g. "/loop …",
        # "/start-loops"). Capturing those would make a loop that re-invokes a
        # command when it fires — recursive and almost never intended.
        if prompt.startswith("/"):
            continue

        if cid in prev_map:
            # Known id -> content can't have changed (native edit makes a new id).
            new_map[cid] = prev_map[cid]
            continue

        key = _ck(schedule, prompt)
        if key in content_to_name:
            # A loop we already know (e.g. one looper re-injected) — just bind it.
            new_map[cid] = content_to_name[key]
        else:
            name = _unique_name(_slug(prompt), taken)
            taken.add(name)
            to_upsert.append(
                Loop(name=name, interval=schedule, prompt=prompt, active=True, created_at=_iso(now))
            )
            content_to_name[key] = name
            new_map[cid] = name

    return to_upsert, [], new_map


# ---------------------------------------------------------------------------
# File-backed wrapper
# ---------------------------------------------------------------------------


def _state_path(session_id: str, sessions_dir: Optional[Path] = None) -> Path:
    return (sessions_dir or SESSIONS_DIR) / f"{session_id}.json"


def load_state(session_id: str, sessions_dir: Optional[Path] = None) -> dict[str, str]:
    p = _state_path(session_id, sessions_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get("crons", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(
    session_id: str,
    mapping: dict[str, str],
    pid: int = 0,
    cwd: str = "",
    sessions_dir: Optional[Path] = None,
) -> None:
    """Persist this session's live loops as a note: {pid, cwd, crons}."""
    d = sessions_dir or SESSIONS_DIR
    d.mkdir(parents=True, exist_ok=True)
    _state_path(session_id, d).write_text(
        json.dumps({"pid": pid, "cwd": cwd, "crons": mapping}, indent=2)
    )


def clear_state(session_id: str, sessions_dir: Optional[Path] = None) -> None:
    """Delete this session's note (called on SessionEnd)."""
    p = _state_path(session_id, sessions_dir)
    try:
        p.unlink()
    except OSError:
        pass


def running_loop_names(sessions_dir: Optional[Path] = None) -> set[str]:
    """Loop names hosted by any still-alive session.

    Reads every session note, skips/prunes notes whose process is dead, and
    returns the union of loop names the live sessions are hosting. This is how
    `looper list` knows running vs idle — and it works across multiple sessions
    (each leaves its own note), unlike the single-owner lease.
    """
    from looper.lease import pid_alive

    d = sessions_dir or SESSIONS_DIR
    if not d.exists():
        return set()

    names: set[str] = set()
    for f in d.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if pid_alive(data.get("pid", 0)):
            names.update(data.get("crons", {}).values())
        else:
            # Prune the note of a session that has died (fixes the leak).
            try:
                f.unlink()
            except OSError:
                pass
    return names


def harvest(
    session_id: str,
    session_crons: list[dict],
    pid: int = 0,
    cwd: str = "",
    now: Optional[float] = None,
) -> dict:
    """Capture a session's live crons into loops.md. Returns a summary dict."""
    from looper.lease import _locked

    now = time.time() if now is None else now
    with _locked(LOOPS_LOCK):
        prev = load_state(session_id)
        existing = parse_loops()
        upserts, removes, new_map = reconcile(session_crons, prev, existing, now)
        for lp in upserts:
            write_loop(lp)
        for name in removes:
            remove_loop(name)
        save_state(session_id, new_map, pid=pid, cwd=cwd)

    return {"added": [lp.name for lp in upserts], "removed": removes}
