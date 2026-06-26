"""Tests for looper.models data classes."""

from __future__ import annotations

import pytest

from looper.models import Loop, LoopStatus
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
# LoopStatus
# ---------------------------------------------------------------------------


class TestLoopStatus:
    @pytest.fixture
    def sample_loop(self):
        return Loop(name="test", interval="10m", prompt="Test loop.")

    def test_construction_defaults(self, sample_loop):
        status = LoopStatus(loop=sample_loop)
        assert status.loop is sample_loop
        assert status.state == "idle"

    def test_icon_running(self, sample_loop):
        assert LoopStatus(loop=sample_loop, state="running").icon == "[green]●[/]"

    def test_icon_idle(self, sample_loop):
        assert LoopStatus(loop=sample_loop, state="idle").icon == "[yellow]○[/]"

    def test_icon_paused(self, sample_loop):
        assert LoopStatus(loop=sample_loop, state="paused").icon == "[dim]◌[/]"

    def test_icon_unknown_state(self, sample_loop):
        assert LoopStatus(loop=sample_loop, state="bogus").icon == "?"
