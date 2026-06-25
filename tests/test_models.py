"""Tests for looper.models data classes."""

from __future__ import annotations

import pytest

from looper.models import CheckResult, Job, Loop, LoopStatus
from looper.registry import parse_loops


# ---------------------------------------------------------------------------
# Loop construction & defaults
# ---------------------------------------------------------------------------


class TestLoopConstruction:
    def test_required_fields(self):
        loop = Loop(name="my-loop", interval="10m", prompt="Do the thing.")
        assert loop.name == "my-loop"
        assert loop.interval == "10m"
        assert loop.prompt == "Do the thing."

    def test_defaults(self):
        loop = Loop(name="x", interval="1h", prompt="p")
        assert loop.active is True
        assert loop.created_at is None
        assert loop.paused_at is None

    def test_explicit_active_false(self):
        loop = Loop(name="x", interval="5m", prompt="p", active=False)
        assert loop.active is False

    def test_created_at_and_paused_at(self):
        loop = Loop(
            name="x",
            interval="1d",
            prompt="p",
            created_at="2025-01-15T10:00:00Z",
            paused_at="2025-02-01T08:00:00Z",
        )
        assert loop.created_at == "2025-01-15T10:00:00Z"
        assert loop.paused_at == "2025-02-01T08:00:00Z"


# ---------------------------------------------------------------------------
# Loop.to_markdown
# ---------------------------------------------------------------------------


class TestLoopToMarkdown:
    def test_minimal_active_loop(self):
        loop = Loop(name="check-deploys", interval="30m", prompt="Check deployment status.")
        md = loop.to_markdown()

        assert md.startswith("## check-deploys\n")
        assert "interval: 30m\n" in md
        assert "active: true\n" in md
        assert "created_at:" not in md
        assert "paused_at:" not in md
        assert "Check deployment status." in md

    def test_paused_loop_with_timestamps(self):
        loop = Loop(
            name="daily-report",
            interval="0 9 * * 1-5",
            prompt="Generate the daily metrics report.",
            active=False,
            created_at="2025-01-15T10:00:00Z",
            paused_at="2025-02-01T08:00:00Z",
        )
        md = loop.to_markdown()

        assert "## daily-report\n" in md
        assert "interval: 0 9 * * 1-5\n" in md
        assert "active: false\n" in md
        assert "created_at: 2025-01-15T10:00:00Z\n" in md
        assert "paused_at: 2025-02-01T08:00:00Z\n" in md
        assert "Generate the daily metrics report." in md

    def test_created_at_only(self):
        loop = Loop(
            name="x",
            interval="1h",
            prompt="p",
            created_at="2025-06-01T00:00:00Z",
        )
        md = loop.to_markdown()

        assert "created_at: 2025-06-01T00:00:00Z" in md
        assert "paused_at:" not in md

    def test_paused_at_only(self):
        loop = Loop(
            name="x",
            interval="1h",
            prompt="p",
            paused_at="2025-06-01T00:00:00Z",
        )
        md = loop.to_markdown()

        assert "paused_at: 2025-06-01T00:00:00Z" in md
        # created_at should be absent
        assert "created_at:" not in md

    def test_prompt_is_stripped(self):
        loop = Loop(name="x", interval="1h", prompt="  hello world  \n\n")
        md = loop.to_markdown()
        # The prompt should appear stripped in the output
        assert "hello world" in md
        assert "  hello world  " not in md

    def test_ends_with_newline(self):
        loop = Loop(name="x", interval="1h", prompt="Do stuff.")
        md = loop.to_markdown()
        assert md.endswith("\n")

    def test_metadata_order(self):
        """interval comes before active, which comes before created_at, then paused_at."""
        loop = Loop(
            name="ordered",
            interval="5m",
            prompt="p",
            active=False,
            created_at="2025-01-01T00:00:00Z",
            paused_at="2025-01-02T00:00:00Z",
        )
        md = loop.to_markdown()
        lines = md.splitlines()

        # Find positions of metadata lines
        interval_idx = next(i for i, l in enumerate(lines) if l.startswith("interval:"))
        active_idx = next(i for i, l in enumerate(lines) if l.startswith("active:"))
        created_idx = next(i for i, l in enumerate(lines) if l.startswith("created_at:"))
        paused_idx = next(i for i, l in enumerate(lines) if l.startswith("paused_at:"))

        assert interval_idx < active_idx < created_idx < paused_idx


# ---------------------------------------------------------------------------
# Loop.to_markdown round-trip through parse_loops
# ---------------------------------------------------------------------------


class TestLoopRoundTrip:
    def test_active_loop_round_trip(self, tmp_path):
        original = Loop(
            name="check-deploys",
            interval="30m",
            prompt="Check the latest deployment status and report any issues.",
            active=True,
            created_at="2025-01-15T10:00:00Z",
        )

        md_path = tmp_path / "loops.md"
        md_path.write_text(original.to_markdown(), encoding="utf-8")

        parsed = parse_loops(md_path)
        assert len(parsed) == 1

        loop = parsed[0]
        assert loop.name == original.name
        assert loop.interval == original.interval
        assert loop.active == original.active
        assert loop.created_at == original.created_at
        assert loop.paused_at == original.paused_at
        assert loop.prompt == original.prompt.strip()

    def test_paused_loop_round_trip(self, tmp_path):
        original = Loop(
            name="daily-report",
            interval="0 9 * * 1-5",
            prompt="Generate the daily metrics report.",
            active=False,
            paused_at="2025-02-01T08:00:00Z",
        )

        md_path = tmp_path / "loops.md"
        md_path.write_text(original.to_markdown(), encoding="utf-8")

        parsed = parse_loops(md_path)
        assert len(parsed) == 1

        loop = parsed[0]
        assert loop.name == original.name
        assert loop.interval == original.interval
        assert loop.active == original.active
        assert loop.paused_at == original.paused_at
        assert loop.prompt == original.prompt.strip()

    def test_multiple_loops_round_trip(self, tmp_path):
        loops = [
            Loop(name="check-deploys", interval="30m", prompt="Check deploys.", active=True,
                 created_at="2025-01-15T10:00:00Z"),
            Loop(name="daily-report", interval="0 9 * * 1-5", prompt="Daily report.",
                 active=False, paused_at="2025-02-01T08:00:00Z"),
            Loop(name="cleanup", interval="1h", prompt="Clean up old temporary files.",
                 active=True),
        ]

        md_text = "\n".join(l.to_markdown() for l in loops)
        md_path = tmp_path / "loops.md"
        md_path.write_text(md_text, encoding="utf-8")

        parsed = parse_loops(md_path)
        assert len(parsed) == 3

        for original, result in zip(loops, parsed):
            assert result.name == original.name
            assert result.interval == original.interval
            assert result.active == original.active
            assert result.created_at == original.created_at
            assert result.paused_at == original.paused_at
            assert result.prompt == original.prompt.strip()


# ---------------------------------------------------------------------------
# Job construction
# ---------------------------------------------------------------------------


class TestJob:
    def test_construction(self):
        job = Job(
            id="abc-123",
            name="check-deploys",
            interval="30m",
            prompt="Check deployment status.",
            created_at="2025-01-15T10:00:00Z",
        )
        assert job.id == "abc-123"
        assert job.name == "check-deploys"
        assert job.interval == "30m"
        assert job.prompt == "Check deployment status."
        assert job.created_at == "2025-01-15T10:00:00Z"

    def test_all_string_fields(self):
        """All Job fields are strings."""
        job = Job(id="1", name="n", interval="5m", prompt="p", created_at="2025-01-01T00:00:00Z")
        for field_val in [job.id, job.name, job.interval, job.prompt, job.created_at]:
            assert isinstance(field_val, str)


# ---------------------------------------------------------------------------
# LoopStatus
# ---------------------------------------------------------------------------


class TestLoopStatus:
    @pytest.fixture
    def sample_loop(self):
        return Loop(name="test", interval="10m", prompt="Test loop.")

    @pytest.fixture
    def sample_job(self):
        return Job(id="j1", name="test", interval="10m", prompt="Test.", created_at="2025-01-01T00:00:00Z")

    def test_construction_defaults(self, sample_loop):
        status = LoopStatus(loop=sample_loop)
        assert status.loop is sample_loop
        assert status.job is None
        assert status.state == "unknown"
        assert status.days_until_expiry is None

    def test_construction_with_all_fields(self, sample_loop, sample_job):
        status = LoopStatus(
            loop=sample_loop,
            job=sample_job,
            state="active",
            days_until_expiry=5.2,
        )
        assert status.loop is sample_loop
        assert status.job is sample_job
        assert status.state == "active"
        assert status.days_until_expiry == 5.2

    def test_icon_active(self, sample_loop):
        status = LoopStatus(loop=sample_loop, state="active")
        assert status.icon == "[green]●[/]"

    def test_icon_missing(self, sample_loop):
        status = LoopStatus(loop=sample_loop, state="missing")
        assert status.icon == "[red]○[/]"

    def test_icon_expiring(self, sample_loop):
        status = LoopStatus(loop=sample_loop, state="expiring")
        assert status.icon == "[yellow]◐[/]"

    def test_icon_paused(self, sample_loop):
        status = LoopStatus(loop=sample_loop, state="paused")
        assert status.icon == "[dim]◌[/]"

    def test_icon_orphan(self, sample_loop):
        status = LoopStatus(loop=sample_loop, state="orphan")
        assert status.icon == "[red]?[/]"

    def test_icon_unknown_state(self, sample_loop):
        status = LoopStatus(loop=sample_loop, state="bogus")
        assert status.icon == "?"


# ---------------------------------------------------------------------------
# CheckResult
# ---------------------------------------------------------------------------


class TestCheckResult:
    def test_construction_defaults(self):
        result = CheckResult()
        assert result.statuses == []
        assert result.orphan_jobs == []
        assert result.needs_sync is False
        assert result.message == ""

    def test_empty_counts(self):
        result = CheckResult()
        assert result.active_count == 0
        assert result.missing_count == 0
        assert result.expiring_count == 0

    def test_active_count(self):
        loop = Loop(name="a", interval="1h", prompt="p")
        result = CheckResult(statuses=[
            LoopStatus(loop=loop, state="active"),
            LoopStatus(loop=loop, state="active"),
            LoopStatus(loop=loop, state="missing"),
        ])
        assert result.active_count == 2

    def test_missing_count(self):
        loop = Loop(name="a", interval="1h", prompt="p")
        result = CheckResult(statuses=[
            LoopStatus(loop=loop, state="missing"),
            LoopStatus(loop=loop, state="active"),
            LoopStatus(loop=loop, state="missing"),
        ])
        assert result.missing_count == 2

    def test_expiring_count(self):
        loop = Loop(name="a", interval="1h", prompt="p")
        result = CheckResult(statuses=[
            LoopStatus(loop=loop, state="expiring"),
            LoopStatus(loop=loop, state="active"),
            LoopStatus(loop=loop, state="expiring"),
            LoopStatus(loop=loop, state="expiring"),
        ])
        assert result.expiring_count == 3

    def test_mixed_states(self):
        loop = Loop(name="a", interval="1h", prompt="p")
        result = CheckResult(statuses=[
            LoopStatus(loop=loop, state="active"),
            LoopStatus(loop=loop, state="missing"),
            LoopStatus(loop=loop, state="expiring"),
            LoopStatus(loop=loop, state="paused"),
        ])
        assert result.active_count == 1
        assert result.missing_count == 1
        assert result.expiring_count == 1
        # paused is not counted by any of the three properties

    def test_needs_sync_and_message(self):
        result = CheckResult(needs_sync=True, message="1 missing -- sync needed")
        assert result.needs_sync is True
        assert result.message == "1 missing -- sync needed"

    def test_orphan_jobs_stored(self):
        job = Job(id="j1", name="orphan-task", interval="5m", prompt="p", created_at="2025-01-01T00:00:00Z")
        result = CheckResult(orphan_jobs=[job])
        assert len(result.orphan_jobs) == 1
        assert result.orphan_jobs[0].name == "orphan-task"
