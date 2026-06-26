"""Single-owner lease so only one Claude session registers loops at a time.

Claude Code cron jobs are in-memory and per-session: a session cannot see
another session's jobs. So if every session re-registered loops on start,
multiple open sessions would each spawn their own copy and loops would fire
N times. The lease fixes this: exactly one session ("the owner") holds the
loops at any moment.

Coordination happens through a file, since that is the only state shared
across sessions. Liveness is determined by the owner's process id — an idle
but alive owner keeps its lease (idle is the normal loop-firing state, so it
must NOT be stolen). A dead pid means the owner crashed and another session
may take over. Heartbeat time is only a fallback when no usable pid is known.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from looper import LOOPER_HOME

LEASE_FILE = LOOPER_HOME / "owner.json"
LOCK_FILE = LOOPER_HOME / "owner.lock"
STALE_SECONDS = 120

try:
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - non-unix
    _HAVE_FCNTL = False


@contextmanager
def _locked(lock_path: Path):
    """Hold an exclusive flock for the duration of a read-modify-write."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not _HAVE_FCNTL:  # pragma: no cover - non-unix
        yield
        return
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def pid_alive(pid: int) -> bool:
    """True if a process with *pid* currently exists."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    return True


def _proc_info(pid: int) -> tuple[int, str]:
    """Return (ppid, command) for *pid* via ps. (0, '') if unknown."""
    try:
        out = subprocess.run(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return (0, "")
    line = out.stdout.strip()
    if not line:
        return (0, "")
    parts = line.split(None, 1)
    try:
        ppid = int(parts[0])
    except (ValueError, IndexError):
        return (0, "")
    comm = parts[1] if len(parts) > 1 else ""
    return (ppid, comm)


def discover_session_pid() -> int:
    """Best-effort: walk up the process tree to the Claude session process.

    The hook runs as a descendant of the Claude process. We climb parents
    until we find one whose command looks like Claude Code, and use that pid
    as the liveness token (it lives exactly as long as the session). Falls
    back to the immediate parent if no match is found.

    NOTE: the exact command name to match is environment-specific; the
    `looper _hookdump` probe captures the real ancestry so this matcher can
    be locked down per platform.
    """
    pid = os.getpid()
    seen: set[int] = set()
    fallback = os.getppid()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        ppid, comm = _proc_info(pid)
        # Match the process *named* claude (basename), not any path that merely
        # contains "claude" — the hook's own interpreter may live under a path
        # like .../tools/looper/bin/python and must not false-match.
        base = os.path.basename(comm).lower()
        if base == "claude" or base.startswith("claude"):
            return pid
        if ppid <= 1:
            break
        pid = ppid
    return fallback


def read_lease(path: Optional[Path] = None) -> Optional[dict]:
    path = path or LEASE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _is_stale(lease: dict, now: float, stale: int) -> bool:
    """Is the current owner gone?

    If a usable pid is recorded, trust process liveness exclusively — an
    idle-but-alive owner is NOT stale. Only fall back to heartbeat age when
    no pid is available.
    """
    pid = lease.get("pid", 0) or 0
    if pid > 0:
        return not pid_alive(pid)
    hb = lease.get("heartbeat_ts", 0) or 0
    return (now - hb) > stale


def _owns(lease: Optional[dict], session_id: str, pid: int) -> bool:
    """True if (session_id, pid) owns *lease*, matched by session id OR pid.

    The pid bridge is essential: the hooks identify a session by Claude's
    uuid, but a manual `looper sync` (from /start-loops) has no uuid and falls
    back to a pid-derived id — same process, so the pid match recognises it as
    the same owner instead of locking it out as a follower.
    """
    if lease is None:
        return False
    return lease.get("session_id") == session_id or bool(pid and lease.get("pid") == pid)


def claim_or_refresh(
    session_id: str,
    pid: int,
    now: Optional[float] = None,
    *,
    claim: bool = True,
    cwd: Optional[str] = None,
    lease_path: Optional[Path] = None,
    lock_path: Optional[Path] = None,
    stale: int = STALE_SECONDS,
) -> str:
    """Refresh-if-owner, optionally claim a free lease, else stand down.

    Returns one of:
      "claimed"   - this session is now the owner (caller should register loops)
      "refreshed" - this session was already the owner; heartbeat bumped
      "follower"  - not the owner (and either didn't claim, or another live
                    session holds it)

    With claim=False the lease is NEVER taken — only refreshed if already owned.
    The background hooks pass claim=False so an idle dev session never *squats*
    the lease; ownership is established only by /start-loops (claim=True).
    """
    lease_path = lease_path or LEASE_FILE
    lock_path = lock_path or LOCK_FILE
    now = time.time() if now is None else now

    with _locked(lock_path):
        lease = read_lease(lease_path)

        if _owns(lease, session_id, pid):
            lease["session_id"] = session_id
            lease["pid"] = pid
            lease["heartbeat_ts"] = now
            if cwd:
                lease["cwd"] = cwd
            lease.setdefault("acquired_at", now)
            _write(lease_path, lease)
            return "refreshed"

        if claim and (lease is None or _is_stale(lease, now, stale)):
            _write(
                lease_path,
                {
                    "session_id": session_id,
                    "pid": pid,
                    "cwd": cwd,
                    "heartbeat_ts": now,
                    "acquired_at": now,
                },
            )
            return "claimed"

        return "follower"


def release(
    session_id: str,
    pid: int = 0,
    *,
    lease_path: Optional[Path] = None,
    lock_path: Optional[Path] = None,
) -> bool:
    """Drop the lease if this session owns it (by session id or pid)."""
    lease_path = lease_path or LEASE_FILE
    lock_path = lock_path or LOCK_FILE
    with _locked(lock_path):
        lease = read_lease(lease_path)
        if _owns(lease, session_id, pid):
            try:
                lease_path.unlink()
            except OSError:
                return False
            return True
    return False


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)
