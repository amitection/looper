"""Tests for looper.lease — the single-owner lease that prevents duplicate loops."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from looper import lease as lease_mod
from looper.lease import claim_or_refresh, pid_alive, read_lease, release


# -- claim=False (hooks must never squat the lease) ------------------------


def test_claim_false_does_not_take_free_lease():
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    lp, lk = d / "owner.json", d / "owner.lock"
    # No lease yet; a background hook (claim=False) must NOT create one.
    result = claim_or_refresh("hook-sess", 4242, claim=False, lease_path=lp, lock_path=lk)
    assert result == "follower"
    assert read_lease(lp) is None


def test_claim_false_still_refreshes_if_owner():
    import os
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    lp, lk = d / "owner.json", d / "owner.lock"
    claim_or_refresh("S", os.getpid(), lease_path=lp, lock_path=lk)  # claim
    result = claim_or_refresh("S", os.getpid(), claim=False, lease_path=lp, lock_path=lk)
    assert result == "refreshed"




@pytest.fixture()
def paths(tmp_path: Path):
    return tmp_path / "owner.json", tmp_path / "owner.lock"


# -- pid_alive -------------------------------------------------------------


def test_pid_alive_self() -> None:
    assert pid_alive(os.getpid()) is True


def test_pid_alive_dead() -> None:
    # PID 999999 is almost certainly not running
    assert pid_alive(999999) is False


def test_pid_alive_zero_or_negative() -> None:
    assert pid_alive(0) is False
    assert pid_alive(-1) is False


# -- claim -----------------------------------------------------------------


def test_claim_when_no_lease(paths) -> None:
    lease_p, lock_p = paths
    result = claim_or_refresh("sess-A", os.getpid(), lease_path=lease_p, lock_path=lock_p)
    assert result == "claimed"

    data = read_lease(lease_p)
    assert data["session_id"] == "sess-A"
    assert data["pid"] == os.getpid()


def test_refresh_when_already_owner(paths) -> None:
    lease_p, lock_p = paths
    claim_or_refresh("sess-A", os.getpid(), now=1000.0, lease_path=lease_p, lock_path=lock_p)
    result = claim_or_refresh("sess-A", os.getpid(), now=2000.0, lease_path=lease_p, lock_path=lock_p)
    assert result == "refreshed"

    data = read_lease(lease_p)
    assert data["heartbeat_ts"] == 2000.0
    assert data["acquired_at"] == 1000.0  # acquired time unchanged on refresh


def test_follower_when_owner_alive(paths) -> None:
    lease_p, lock_p = paths
    # Owner is THIS process (alive); the other session is a different live pid.
    claim_or_refresh("sess-A", os.getpid(), lease_path=lease_p, lock_path=lock_p)
    result = claim_or_refresh("sess-B", os.getppid(), lease_path=lease_p, lock_path=lock_p)
    assert result == "follower"

    data = read_lease(lease_p)
    assert data["session_id"] == "sess-A"  # unchanged


def test_pid_match_is_same_owner(paths) -> None:
    """Same process, different session id (hook uuid vs manual pid-id) -> owner.

    This is the bridge that lets a manual `looper sync` (from /start-loops)
    register as the same owner the hooks already claimed under the session uuid.
    """
    lease_p, lock_p = paths
    claim_or_refresh("uuid-X", os.getpid(), lease_path=lease_p, lock_path=lock_p)
    result = claim_or_refresh("pid-fallback", os.getpid(), lease_path=lease_p, lock_path=lock_p)
    assert result == "refreshed"


def test_idle_alive_owner_is_not_stolen(paths) -> None:
    """An alive owner keeps its lease even if heartbeat is ancient (idle == normal)."""
    lease_p, lock_p = paths
    claim_or_refresh("sess-A", os.getpid(), now=0.0, lease_path=lease_p, lock_path=lock_p)
    # Much later, a different live session; owner pid still alive.
    result = claim_or_refresh(
        "sess-B", os.getppid(), now=10_000.0, lease_path=lease_p, lock_path=lock_p, stale=120
    )
    assert result == "follower"


def test_takeover_when_owner_pid_dead(paths) -> None:
    lease_p, lock_p = paths
    # Owner recorded with a dead pid
    lease_mod._write(lease_p, {
        "session_id": "sess-dead",
        "pid": 999999,
        "heartbeat_ts": 0.0,
        "acquired_at": 0.0,
    })
    result = claim_or_refresh("sess-B", os.getpid(), lease_path=lease_p, lock_path=lock_p)
    assert result == "claimed"
    assert read_lease(lease_p)["session_id"] == "sess-B"


def test_takeover_by_heartbeat_when_no_pid(paths) -> None:
    """With no usable pid, fall back to heartbeat staleness."""
    lease_p, lock_p = paths
    lease_mod._write(lease_p, {
        "session_id": "sess-old",
        "pid": 0,
        "heartbeat_ts": 0.0,
        "acquired_at": 0.0,
    })
    # within window -> follower
    assert claim_or_refresh(
        "sess-B", 0, now=60.0, lease_path=lease_p, lock_path=lock_p, stale=120
    ) == "follower"
    # beyond window -> claimed
    assert claim_or_refresh(
        "sess-B", 0, now=200.0, lease_path=lease_p, lock_path=lock_p, stale=120
    ) == "claimed"


# -- release ---------------------------------------------------------------


def test_release_by_owner(paths) -> None:
    lease_p, lock_p = paths
    claim_or_refresh("sess-A", os.getpid(), lease_path=lease_p, lock_path=lock_p)
    assert release("sess-A", lease_path=lease_p, lock_path=lock_p) is True
    assert read_lease(lease_p) is None


def test_release_by_non_owner_is_noop(paths) -> None:
    lease_p, lock_p = paths
    claim_or_refresh("sess-A", os.getpid(), lease_path=lease_p, lock_path=lock_p)
    assert release("sess-B", lease_path=lease_p, lock_path=lock_p) is False
    assert read_lease(lease_p)["session_id"] == "sess-A"


def test_release_when_no_lease(paths) -> None:
    lease_p, lock_p = paths
    assert release("sess-A", lease_path=lease_p, lock_path=lock_p) is False


# -- handoff scenario ------------------------------------------------------


def test_full_handoff_cycle(paths) -> None:
    """Owner dies -> follower takes over -> original re-claim is a no-op follower."""
    lease_p, lock_p = paths

    # Session A claims (simulate dead pid after crash)
    lease_mod._write(lease_p, {
        "session_id": "A", "pid": 999999, "heartbeat_ts": 0.0, "acquired_at": 0.0,
    })
    # Session B (alive) takes over the crashed lease
    assert claim_or_refresh("B", os.getpid(), lease_path=lease_p, lock_path=lock_p) == "claimed"
    # Session C (a different live pid) sees B alive -> follower
    assert claim_or_refresh("C", os.getppid(), lease_path=lease_p, lock_path=lock_p) == "follower"


# -- corruption tolerance --------------------------------------------------


def test_read_lease_corrupt_returns_none(paths) -> None:
    lease_p, _ = paths
    lease_p.write_text("not json {{{")
    assert read_lease(lease_p) is None


def test_claim_over_corrupt_lease(paths) -> None:
    lease_p, lock_p = paths
    lease_p.write_text("not json {{{")
    # Corrupt lease reads as None -> claimable
    assert claim_or_refresh("A", os.getpid(), lease_path=lease_p, lock_path=lock_p) == "claimed"
