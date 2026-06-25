"""Unit tests for looper.registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from looper.models import CheckResult, Job, Loop, LoopStatus
from looper.registry import (
    diff,
    ensure_symlink,
    interval_to_seconds,
    parse_loops,
    remove_loop,
    toggle_loop,
    validate_interval,
    write_loop,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MULTI_LOOP_MD = """\
## daily-report
interval: 1d
active: true
created_at: 2025-06-01T00:00:00Z

Generate a daily status report.

## health-check
interval: 30m
active: false
paused_at: 2025-06-10T12:00:00Z

Check service health and alert if anything is down.

## backup-db
interval: 1h
active: true

Run database backup.
"""


# ---------------------------------------------------------------------------
# 1. parse_loops: multiple loops
# ---------------------------------------------------------------------------


class TestParseLoops:
    def test_parse_multiple_loops(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        f.write_text(MULTI_LOOP_MD, encoding="utf-8")

        loops = parse_loops(f)

        assert len(loops) == 3

        daily = loops[0]
        assert daily.name == "daily-report"
        assert daily.interval == "1d"
        assert daily.prompt == "Generate a daily status report."
        assert daily.active is True
        assert daily.created_at == "2025-06-01T00:00:00Z"

        health = loops[1]
        assert health.name == "health-check"
        assert health.interval == "30m"
        assert health.active is False
        assert health.paused_at == "2025-06-10T12:00:00Z"
        assert health.prompt == "Check service health and alert if anything is down."

        backup = loops[2]
        assert backup.name == "backup-db"
        assert backup.interval == "1h"
        assert backup.active is True
        assert backup.created_at is None
        assert backup.prompt == "Run database backup."

    # -----------------------------------------------------------------------
    # 2. parse_loops edge cases
    # -----------------------------------------------------------------------

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        f.write_text("", encoding="utf-8")
        assert parse_loops(f) == []

    def test_missing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "nonexistent.md"
        assert parse_loops(f) == []

    def test_only_comments(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        f.write_text(
            "# This is a top-level heading (not ##)\n\nSome random text.\n",
            encoding="utf-8",
        )
        assert parse_loops(f) == []

    def test_single_loop(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        f.write_text(
            "## my-loop\ninterval: 5m\nactive: true\n\nDo the thing.\n",
            encoding="utf-8",
        )
        loops = parse_loops(f)
        assert len(loops) == 1
        assert loops[0].name == "my-loop"
        assert loops[0].interval == "5m"
        assert loops[0].prompt == "Do the thing."

    def test_multiline_prompt(self, tmp_path: Path) -> None:
        content = (
            "## multi-prompt\n"
            "interval: 10m\n"
            "active: true\n"
            "\n"
            "Line one of the prompt.\n"
            "Line two of the prompt.\n"
            "\n"
            "Line four after a blank.\n"
        )
        f = tmp_path / "loops.md"
        f.write_text(content, encoding="utf-8")

        loops = parse_loops(f)
        assert len(loops) == 1
        expected_prompt = "Line one of the prompt.\nLine two of the prompt.\n\nLine four after a blank."
        assert loops[0].prompt == expected_prompt


# ---------------------------------------------------------------------------
# 3. write_loop: new loop
# ---------------------------------------------------------------------------


class TestWriteLoop:
    def test_write_new_loop(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        loop = Loop(
            name="test-loop",
            interval="15m",
            prompt="Run the test.",
            active=True,
            created_at="2025-06-20T10:00:00Z",
        )
        write_loop(loop, f)

        loops = parse_loops(f)
        assert len(loops) == 1
        assert loops[0].name == "test-loop"
        assert loops[0].interval == "15m"
        assert loops[0].prompt == "Run the test."
        assert loops[0].active is True
        assert loops[0].created_at == "2025-06-20T10:00:00Z"

    def test_write_to_nonexistent_file_creates_it(self, tmp_path: Path) -> None:
        f = tmp_path / "subdir" / "loops.md"
        loop = Loop(name="new-one", interval="1h", prompt="Hello.")
        write_loop(loop, f)

        assert f.exists()
        loops = parse_loops(f)
        assert len(loops) == 1
        assert loops[0].name == "new-one"

    def test_write_appends_to_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        loop1 = Loop(name="first", interval="5m", prompt="Prompt one.")
        loop2 = Loop(name="second", interval="10m", prompt="Prompt two.")

        write_loop(loop1, f)
        write_loop(loop2, f)

        loops = parse_loops(f)
        assert len(loops) == 2
        assert loops[0].name == "first"
        assert loops[1].name == "second"

    # -----------------------------------------------------------------------
    # 4. write_loop update: replace existing
    # -----------------------------------------------------------------------

    def test_write_replaces_existing_loop(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        original = Loop(name="updatable", interval="5m", prompt="Original prompt.")
        write_loop(original, f)

        updated = Loop(name="updatable", interval="30m", prompt="Updated prompt.")
        write_loop(updated, f)

        loops = parse_loops(f)
        assert len(loops) == 1
        assert loops[0].name == "updatable"
        assert loops[0].interval == "30m"
        assert loops[0].prompt == "Updated prompt."

    def test_write_replaces_without_affecting_others(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        write_loop(Loop(name="aaa", interval="1m", prompt="A."), f)
        write_loop(Loop(name="bbb", interval="2m", prompt="B."), f)
        write_loop(Loop(name="ccc", interval="3m", prompt="C."), f)

        # Replace the middle one.
        write_loop(Loop(name="bbb", interval="20m", prompt="B updated."), f)

        loops = parse_loops(f)
        assert len(loops) == 3
        names = [l.name for l in loops]
        assert names == ["aaa", "bbb", "ccc"]
        assert loops[1].interval == "20m"
        assert loops[1].prompt == "B updated."
        # Others are untouched.
        assert loops[0].prompt == "A."
        assert loops[2].prompt == "C."


# ---------------------------------------------------------------------------
# 5. remove_loop
# ---------------------------------------------------------------------------


class TestRemoveLoop:
    def test_remove_existing_loop(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        write_loop(Loop(name="keep-me", interval="5m", prompt="Stay."), f)
        write_loop(Loop(name="remove-me", interval="10m", prompt="Go."), f)

        remove_loop("remove-me", f)

        loops = parse_loops(f)
        assert len(loops) == 1
        assert loops[0].name == "keep-me"

    def test_remove_nonexistent_is_noop(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        write_loop(Loop(name="solo", interval="5m", prompt="Only one."), f)

        remove_loop("ghost", f)

        loops = parse_loops(f)
        assert len(loops) == 1
        assert loops[0].name == "solo"

    def test_remove_from_missing_file_is_noop(self, tmp_path: Path) -> None:
        f = tmp_path / "nope.md"
        remove_loop("anything", f)  # Should not raise.

    def test_remove_only_loop_leaves_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        write_loop(Loop(name="lonely", interval="5m", prompt="Alone."), f)

        remove_loop("lonely", f)

        loops = parse_loops(f)
        assert len(loops) == 0


# ---------------------------------------------------------------------------
# 6. toggle_loop
# ---------------------------------------------------------------------------


class TestToggleLoop:
    def test_toggle_active_to_inactive(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        write_loop(Loop(name="toggler", interval="10m", prompt="Toggle me."), f)

        result = toggle_loop("toggler", active=False, path=f)

        assert result.active is False
        assert result.paused_at is not None
        # paused_at should be a valid ISO timestamp.
        assert "T" in result.paused_at

        # Verify persistence.
        loops = parse_loops(f)
        assert loops[0].active is False
        assert loops[0].paused_at is not None

    def test_toggle_inactive_to_active(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        loop = Loop(
            name="paused-one",
            interval="10m",
            prompt="Resume me.",
            active=False,
            paused_at="2025-06-15T08:00:00Z",
        )
        write_loop(loop, f)

        result = toggle_loop("paused-one", active=True, path=f)

        assert result.active is True
        assert result.paused_at is None

        # Verify persistence.
        loops = parse_loops(f)
        assert loops[0].active is True
        assert loops[0].paused_at is None

    def test_toggle_nonexistent_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "loops.md"
        write_loop(Loop(name="exists", interval="5m", prompt="Here."), f)

        with pytest.raises(KeyError, match="not-here"):
            toggle_loop("not-here", active=False, path=f)


# ---------------------------------------------------------------------------
# 7. validate_interval
# ---------------------------------------------------------------------------


class TestValidateInterval:
    @pytest.mark.parametrize("interval", ["10m", "1h", "30m", "1d", "30s", "5m"])
    def test_valid_shorthand(self, interval: str) -> None:
        assert validate_interval(interval) is True

    @pytest.mark.parametrize(
        "interval",
        [
            "0 9 * * 1-5",
            "*/15 * * * *",
            "0 0 1 * *",
            "30 2 * * 0",
        ],
    )
    def test_valid_cron(self, interval: str) -> None:
        assert validate_interval(interval) is True

    @pytest.mark.parametrize("interval", ["abc", "10x", "", "foo bar", "* *", "10"])
    def test_invalid(self, interval: str) -> None:
        assert validate_interval(interval) is False


# ---------------------------------------------------------------------------
# 8. interval_to_seconds
# ---------------------------------------------------------------------------


class TestIntervalToSeconds:
    @pytest.mark.parametrize(
        ("interval", "expected"),
        [
            ("10m", 600),
            ("1h", 3600),
            ("30s", 30),
            ("2d", 172800),
            ("5m", 300),
            ("24h", 86400),
        ],
    )
    def test_conversions(self, interval: str, expected: int) -> None:
        assert interval_to_seconds(interval) == expected

    def test_cron_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot convert"):
            interval_to_seconds("0 9 * * 1-5")

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            interval_to_seconds("nope")


# ---------------------------------------------------------------------------
# 9. diff: verify states
# ---------------------------------------------------------------------------


class TestDiff:
    def _make_loop(self, name: str, active: bool = True) -> Loop:
        return Loop(name=name, interval="10m", prompt=f"Prompt for {name}.", active=active)

    def _make_job(
        self, name: str, created_at: str = "2025-06-01T00:00:00Z"
    ) -> Job:
        return Job(
            id=f"job-{name}",
            name=f"loop: {name}",
            interval="10m",
            prompt=f"Prompt for {name}.",
            created_at=created_at,
        )

    def test_active_state(self) -> None:
        """Loop with a matching non-expiring job -> active."""
        loops = [self._make_loop("foo")]
        # created_at far in the future so it's not expiring.
        jobs = [self._make_job("foo", created_at="2099-01-01T00:00:00Z")]

        result = diff(loops, jobs)

        assert len(result.statuses) == 1
        assert result.statuses[0].state == "active"
        assert result.needs_sync is False
        assert result.orphan_jobs == []

    def test_missing_state(self) -> None:
        """Active loop with no matching job -> missing."""
        loops = [self._make_loop("bar")]
        jobs: list[Job] = []

        result = diff(loops, jobs)

        assert len(result.statuses) == 1
        assert result.statuses[0].state == "missing"
        assert result.needs_sync is True

    def test_expiring_state(self) -> None:
        """Loop whose job was created long ago -> expiring."""
        loops = [self._make_loop("old")]
        # Created 6.5 days ago - within RENEW_BEFORE_DAYS (6).
        jobs = [self._make_job("old", created_at="2020-01-01T00:00:00Z")]

        result = diff(loops, jobs)

        assert len(result.statuses) == 1
        assert result.statuses[0].state == "expiring"
        assert result.needs_sync is True

    def test_paused_state(self) -> None:
        """Inactive loop -> paused, regardless of jobs."""
        loops = [self._make_loop("paused", active=False)]
        jobs = [self._make_job("paused", created_at="2099-01-01T00:00:00Z")]

        result = diff(loops, jobs)

        assert len(result.statuses) == 1
        assert result.statuses[0].state == "paused"

    def test_orphan_jobs(self) -> None:
        """Jobs with no matching loop -> orphan."""
        loops: list[Loop] = []
        jobs = [self._make_job("orphan-task", created_at="2099-01-01T00:00:00Z")]

        result = diff(loops, jobs)

        assert len(result.orphan_jobs) == 1
        assert result.orphan_jobs[0].id == "job-orphan-task"
        assert result.needs_sync is True

    def test_mixed_states(self) -> None:
        """Multiple loops with different states in a single diff."""
        loops = [
            self._make_loop("active-one"),
            self._make_loop("missing-one"),
            self._make_loop("paused-one", active=False),
        ]
        jobs = [
            self._make_job("active-one", created_at="2099-01-01T00:00:00Z"),
            self._make_job("stray-job", created_at="2099-01-01T00:00:00Z"),
        ]

        result = diff(loops, jobs)

        states = {s.loop.name: s.state for s in result.statuses}
        assert states["active-one"] == "active"
        assert states["missing-one"] == "missing"
        assert states["paused-one"] == "paused"
        assert len(result.orphan_jobs) == 1
        assert result.orphan_jobs[0].name == "loop: stray-job"
        assert result.needs_sync is True

    def test_empty_inputs(self) -> None:
        """No loops and no jobs -> no sync needed."""
        result = diff([], [])
        assert result.statuses == []
        assert result.orphan_jobs == []
        assert result.needs_sync is False


# ---------------------------------------------------------------------------
# 10. ensure_symlink
# ---------------------------------------------------------------------------


class TestEnsureSymlink:
    def test_creates_symlink(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Symlink is created pointing to CANONICAL_TASKS."""
        canonical = tmp_path / "canonical" / ".claude" / "scheduled_tasks.json"
        monkeypatch.setattr("looper.registry.CANONICAL_TASKS", canonical)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result = ensure_symlink(project_dir)

        assert result is True
        link = project_dir / ".claude" / "scheduled_tasks.json"
        assert link.is_symlink()
        assert link.resolve() == canonical.resolve()

    def test_existing_correct_symlink_returns_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canonical = tmp_path / "canonical" / ".claude" / "scheduled_tasks.json"
        monkeypatch.setattr("looper.registry.CANONICAL_TASKS", canonical)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create symlink first time.
        ensure_symlink(project_dir)
        # Call again - should return True without error.
        result = ensure_symlink(project_dir)
        assert result is True

    def test_existing_wrong_symlink_is_relinked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canonical = tmp_path / "canonical" / ".claude" / "scheduled_tasks.json"
        monkeypatch.setattr("looper.registry.CANONICAL_TASKS", canonical)

        project_dir = tmp_path / "project"
        link_path = project_dir / ".claude" / "scheduled_tasks.json"
        link_path.parent.mkdir(parents=True)

        # Point to a wrong target.
        wrong_target = tmp_path / "wrong.json"
        wrong_target.write_text("[]", encoding="utf-8")
        link_path.symlink_to(wrong_target)

        result = ensure_symlink(project_dir)

        assert result is True
        assert link_path.resolve() == canonical.resolve()

    def test_existing_real_file_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canonical = tmp_path / "canonical" / ".claude" / "scheduled_tasks.json"
        monkeypatch.setattr("looper.registry.CANONICAL_TASKS", canonical)

        project_dir = tmp_path / "project"
        real_file = project_dir / ".claude" / "scheduled_tasks.json"
        real_file.parent.mkdir(parents=True)
        real_file.write_text("[1,2,3]", encoding="utf-8")

        result = ensure_symlink(project_dir)

        assert result is False
        # The real file should not have been clobbered.
        assert real_file.read_text(encoding="utf-8") == "[1,2,3]"

    def test_canonical_file_created_if_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canonical = tmp_path / "canonical" / ".claude" / "scheduled_tasks.json"
        monkeypatch.setattr("looper.registry.CANONICAL_TASKS", canonical)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        assert not canonical.exists()
        ensure_symlink(project_dir)
        assert canonical.exists()
        assert canonical.read_text(encoding="utf-8") == "[]"
