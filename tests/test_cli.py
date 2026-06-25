"""Comprehensive CLI tests for looper — every Click command via CliRunner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from looper.cli import main


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

SAMPLE_LOOPS_MD = """\
## check-deploys
interval: 30m
active: true
created_at: 2025-01-15T10:00:00Z

Check the latest deployment status and report any issues.

## daily-report
interval: 0 9 * * 1-5
active: false
paused_at: 2025-02-01T08:00:00Z

Generate the daily metrics report.

## cleanup
interval: 1h
active: true

Clean up old temporary files.
"""


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all looper paths into tmp_path so tests never touch real dirs."""
    loops_file = tmp_path / "loops.md"
    canonical = tmp_path / ".claude" / "scheduled_tasks.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("[]")

    monkeypatch.setattr("looper.LOOPER_HOME", tmp_path)
    monkeypatch.setattr("looper.LOOPS_FILE", loops_file)
    monkeypatch.setattr("looper.CANONICAL_TASKS", canonical)
    monkeypatch.setattr("looper.registry.LOOPS_FILE", loops_file)
    monkeypatch.setattr("looper.registry.CANONICAL_TASKS", canonical)
    monkeypatch.setattr("looper.cli.LOOPS_FILE", loops_file)
    return tmp_path, loops_file


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _seed_loops(loops_file: Path, content: str = SAMPLE_LOOPS_MD) -> None:
    """Write sample loops.md content."""
    loops_file.write_text(content, encoding="utf-8")


def _seed_jobs(tmp_path: Path, jobs: list[dict]) -> None:
    """Write sample scheduled_tasks.json."""
    canonical = tmp_path / ".claude" / "scheduled_tasks.json"
    canonical.write_text(json.dumps(jobs), encoding="utf-8")


# ===========================================================================
# 1. looper list
# ===========================================================================


class TestList:
    def test_empty_state(self, runner: CliRunner, isolated_env) -> None:
        """Empty registry prints guidance message."""
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "No loops registered" in result.output

    def test_with_loops(self, runner: CliRunner, isolated_env) -> None:
        """Populated registry shows loop names in a table."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "check-deploys" in result.output
        assert "daily-report" in result.output
        assert "cleanup" in result.output

    def test_with_orphan_jobs(self, runner: CliRunner, isolated_env) -> None:
        """Jobs without matching loops appear as orphans."""
        tmp_path, _ = isolated_env
        _seed_jobs(tmp_path, [
            {
                "id": "orphan-abc",
                "name": "stray-task",
                "interval": "5m",
                "prompt": "I have no loop.",
                "createdAt": "2099-01-01T00:00:00Z",
            }
        ])

        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "orphan" in result.output.lower()
        assert "stray-task" in result.output

    def test_mixed_states(self, runner: CliRunner, isolated_env) -> None:
        """Active, paused, and missing loops all render."""
        tmp_path, loops_file = isolated_env
        _seed_loops(loops_file)
        # Provide a job only for check-deploys; daily-report is paused;
        # cleanup has no matching job so it's "missing".
        _seed_jobs(tmp_path, [
            {
                "id": "job-check-deploys",
                "name": "loop: check-deploys",
                "interval": "30m",
                "prompt": "Check...",
                "createdAt": "2099-01-01T00:00:00Z",
            }
        ])

        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "check-deploys" in result.output
        assert "daily-report" in result.output
        assert "cleanup" in result.output
        # Sync needed because cleanup is missing.
        assert "sync" in result.output.lower() or "start-loops" in result.output

    def test_shows_active_and_paused_labels(self, runner: CliRunner, isolated_env) -> None:
        """List output distinguishes active vs paused loops."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        # "paused" state should appear for daily-report.
        assert "paused" in result.output.lower()


# ===========================================================================
# 2. looper add
# ===========================================================================


class TestAdd:
    def test_valid_add(self, runner: CliRunner, isolated_env) -> None:
        """Adding a loop with valid args succeeds."""
        _, loops_file = isolated_env

        result = runner.invoke(main, ["add", "my-loop", "10m", "-p", "Run the check."])
        assert result.exit_code == 0
        assert "Added" in result.output
        assert "my-loop" in result.output

        content = loops_file.read_text(encoding="utf-8")
        assert "my-loop" in content
        assert "10m" in content
        assert "Run the check." in content

    def test_invalid_interval(self, runner: CliRunner, isolated_env) -> None:
        """Invalid interval string is rejected."""
        result = runner.invoke(main, ["add", "bad-loop", "banana", "-p", "Some prompt."])
        assert result.exit_code != 0
        assert "Invalid interval" in result.output

    def test_duplicate_name(self, runner: CliRunner, isolated_env) -> None:
        """Adding a loop with an existing name fails."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["add", "check-deploys", "5m", "-p", "Dup."])
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_missing_prompt_flag(self, runner: CliRunner, isolated_env) -> None:
        """Omitting the required --prompt option causes a Click error."""
        result = runner.invoke(main, ["add", "no-prompt", "10m"])
        assert result.exit_code != 0
        assert "prompt" in result.output.lower() or "Missing" in result.output

    def test_add_with_cron_interval(self, runner: CliRunner, isolated_env) -> None:
        """A 5-field cron expression is accepted."""
        result = runner.invoke(
            main, ["add", "cron-loop", "0 9 * * 1-5", "-p", "Weekday mornings."]
        )
        assert result.exit_code == 0
        assert "Added" in result.output
        assert "cron-loop" in result.output

    def test_add_with_shorthand_units(self, runner: CliRunner, isolated_env) -> None:
        """All shorthand units (s, m, h, d) are accepted."""
        for unit, name in [("30s", "sec-loop"), ("5m", "min-loop"),
                           ("2h", "hour-loop"), ("1d", "day-loop")]:
            result = runner.invoke(main, ["add", name, unit, "-p", f"{name} prompt."])
            assert result.exit_code == 0, f"Failed for {unit}: {result.output}"
            assert "Added" in result.output

    def test_add_persists_created_at(self, runner: CliRunner, isolated_env) -> None:
        """Newly added loops have a created_at timestamp."""
        _, loops_file = isolated_env

        runner.invoke(main, ["add", "ts-loop", "10m", "-p", "Timestamped."])

        content = loops_file.read_text(encoding="utf-8")
        assert "created_at:" in content

    def test_add_sets_active_true(self, runner: CliRunner, isolated_env) -> None:
        """Newly added loops default to active: true."""
        _, loops_file = isolated_env

        runner.invoke(main, ["add", "active-loop", "10m", "-p", "Active by default."])

        content = loops_file.read_text(encoding="utf-8")
        assert "active: true" in content


# ===========================================================================
# 3. looper pause
# ===========================================================================


class TestPause:
    def test_pause_active_loop(self, runner: CliRunner, isolated_env) -> None:
        """Pausing an active loop succeeds and persists."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["pause", "check-deploys"])
        assert result.exit_code == 0
        assert "Paused" in result.output
        assert "check-deploys" in result.output

        content = loops_file.read_text(encoding="utf-8")
        assert "active: false" in content

    def test_pause_already_paused(self, runner: CliRunner, isolated_env) -> None:
        """Pausing an already-paused loop is idempotent (still succeeds)."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        # daily-report is already paused in the fixture.
        result = runner.invoke(main, ["pause", "daily-report"])
        assert result.exit_code == 0
        assert "Paused" in result.output

    def test_pause_nonexistent(self, runner: CliRunner, isolated_env) -> None:
        """Pausing a nonexistent loop fails with an error."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["pause", "ghost-loop"])
        assert result.exit_code != 0

    def test_pause_sets_paused_at(self, runner: CliRunner, isolated_env) -> None:
        """Pausing a loop persists a paused_at timestamp."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        runner.invoke(main, ["pause", "check-deploys"])

        content = loops_file.read_text(encoding="utf-8")
        assert "paused_at:" in content

    def test_pause_empty_registry(self, runner: CliRunner, isolated_env) -> None:
        """Pausing with no loops.md file at all fails."""
        result = runner.invoke(main, ["pause", "nonexistent"])
        assert result.exit_code != 0


# ===========================================================================
# 4. looper resume
# ===========================================================================


class TestResume:
    def test_resume_paused_loop(self, runner: CliRunner, isolated_env) -> None:
        """Resuming a paused loop sets active=true and clears paused_at."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["resume", "daily-report"])
        assert result.exit_code == 0
        assert "Resumed" in result.output
        assert "daily-report" in result.output

        from looper.registry import parse_loops

        loops = parse_loops(loops_file)
        daily = next(l for l in loops if l.name == "daily-report")
        assert daily.active is True
        assert daily.paused_at is None

    def test_resume_already_active(self, runner: CliRunner, isolated_env) -> None:
        """Resuming an already-active loop is idempotent."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["resume", "check-deploys"])
        assert result.exit_code == 0
        assert "Resumed" in result.output

    def test_resume_nonexistent(self, runner: CliRunner, isolated_env) -> None:
        """Resuming a nonexistent loop fails."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["resume", "no-such-loop"])
        assert result.exit_code != 0

    def test_resume_empty_registry(self, runner: CliRunner, isolated_env) -> None:
        """Resuming with no loops.md file fails."""
        result = runner.invoke(main, ["resume", "nope"])
        assert result.exit_code != 0


# ===========================================================================
# 5. looper delete
# ===========================================================================


class TestDelete:
    def test_delete_without_force(self, runner: CliRunner, isolated_env) -> None:
        """Delete without --force prints a warning and exits non-zero."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["delete", "check-deploys"])
        assert result.exit_code != 0
        assert "--force" in result.output

        # Loop should still exist.
        assert "check-deploys" in loops_file.read_text(encoding="utf-8")

    def test_delete_with_force(self, runner: CliRunner, isolated_env) -> None:
        """Delete with --force actually removes the loop."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["delete", "check-deploys", "--force"])
        assert result.exit_code == 0
        assert "Deleted" in result.output
        assert "check-deploys" in result.output

        content = loops_file.read_text(encoding="utf-8")
        assert "check-deploys" not in content
        # Other loops should remain.
        assert "daily-report" in content
        assert "cleanup" in content

    def test_delete_nonexistent_with_force(self, runner: CliRunner, isolated_env) -> None:
        """Deleting a nonexistent loop with --force is a no-op (remove_loop is silent)."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["delete", "ghost", "--force"])
        # remove_loop on a missing name is a no-op, so "Deleted" prints.
        assert result.exit_code == 0

    def test_delete_last_loop(self, runner: CliRunner, isolated_env) -> None:
        """Deleting the only loop leaves no loops parseable."""
        _, loops_file = isolated_env
        loops_file.write_text(
            "## only-one\ninterval: 5m\nactive: true\n\nSolo loop.\n",
            encoding="utf-8",
        )

        result = runner.invoke(main, ["delete", "only-one", "--force"])
        assert result.exit_code == 0

        from looper.registry import parse_loops

        loops = parse_loops(loops_file)
        assert len(loops) == 0

    def test_delete_mentions_pause_alternative(self, runner: CliRunner, isolated_env) -> None:
        """Delete without --force suggests pausing as an alternative."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["delete", "cleanup"])
        assert result.exit_code != 0
        assert "pause" in result.output.lower()


# ===========================================================================
# 6. looper retrigger
# ===========================================================================


class TestRetrigger:
    def test_retrigger_existing(self, runner: CliRunner, isolated_env) -> None:
        """Retrigger prints the loop's prompt and CronCreate command."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["retrigger", "check-deploys"])
        assert result.exit_code == 0
        assert "check-deploys" in result.output
        assert "Check the latest deployment status" in result.output
        assert "CronCreate" in result.output
        assert "30m" in result.output

    def test_retrigger_nonexistent(self, runner: CliRunner, isolated_env) -> None:
        """Retrigger for a missing loop fails."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["retrigger", "missing-loop"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_retrigger_paused_loop(self, runner: CliRunner, isolated_env) -> None:
        """Retrigger works on paused loops too (shows prompt regardless)."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["retrigger", "daily-report"])
        assert result.exit_code == 0
        assert "daily-report" in result.output
        assert "Generate the daily metrics report" in result.output

    def test_retrigger_shows_interval(self, runner: CliRunner, isolated_env) -> None:
        """Retrigger output includes the loop's interval."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["retrigger", "cleanup"])
        assert result.exit_code == 0
        assert "1h" in result.output

    def test_retrigger_empty_registry(self, runner: CliRunner, isolated_env) -> None:
        """Retrigger with no loops.md fails."""
        result = runner.invoke(main, ["retrigger", "anything"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ===========================================================================
# 7. looper check
# ===========================================================================


class TestCheck:
    def test_check_empty(self, runner: CliRunner, isolated_env) -> None:
        """Check with no loops prints 'no loops registered'."""
        result = runner.invoke(main, ["check"])
        assert result.exit_code == 0
        assert "no loops" in result.output.lower()

    def test_check_with_sync_needed(self, runner: CliRunner, isolated_env) -> None:
        """Check with active loops but no jobs flags sync needed."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["check"])
        assert result.exit_code == 0
        assert "missing" in result.output.lower()
        assert "sync" in result.output.lower() or "start-loops" in result.output

    def test_check_all_current(self, runner: CliRunner, isolated_env) -> None:
        """Check with all loops matched by fresh jobs shows active, no sync needed."""
        tmp_path, loops_file = isolated_env
        loops_file.write_text(
            "## my-loop\ninterval: 10m\nactive: true\n\nDo something.\n",
            encoding="utf-8",
        )
        _seed_jobs(tmp_path, [
            {
                "id": "job-1",
                "name": "loop: my-loop",
                "interval": "10m",
                "prompt": "Do something.",
                "createdAt": "2099-01-01T00:00:00Z",
            }
        ])

        result = runner.invoke(main, ["check"])
        assert result.exit_code == 0
        assert "active" in result.output.lower()
        assert "sync needed" not in result.output.lower()

    def test_check_with_project_dir(self, runner: CliRunner, isolated_env) -> None:
        """Check with --project-dir creates a symlink and reports."""
        tmp_path, _ = isolated_env
        project = tmp_path / "my-project"
        project.mkdir()

        result = runner.invoke(main, ["check", "--project-dir", str(project)])
        assert result.exit_code == 0

        link = project / ".claude" / "scheduled_tasks.json"
        assert link.is_symlink()

    def test_check_with_orphan_jobs(self, runner: CliRunner, isolated_env) -> None:
        """Check detects orphan jobs (in cron but not in loops.md)."""
        tmp_path, _ = isolated_env
        _seed_jobs(tmp_path, [
            {
                "id": "orphan-123",
                "name": "stale-cron-job",
                "interval": "5m",
                "prompt": "Orphaned.",
                "createdAt": "2099-01-01T00:00:00Z",
            }
        ])

        result = runner.invoke(main, ["check"])
        assert result.exit_code == 0
        assert "orphan" in result.output.lower()
        assert "stale-cron-job" in result.output

    def test_check_shows_paused_count(self, runner: CliRunner, isolated_env) -> None:
        """Check reports paused loops in the summary."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["check"])
        assert result.exit_code == 0
        assert "paused" in result.output.lower()

    def test_check_shows_per_loop_detail(self, runner: CliRunner, isolated_env) -> None:
        """Check output includes the name of each loop."""
        _, loops_file = isolated_env
        _seed_loops(loops_file)

        result = runner.invoke(main, ["check"])
        assert result.exit_code == 0
        assert "check-deploys" in result.output
        assert "daily-report" in result.output
        assert "cleanup" in result.output


# ===========================================================================
# 8. looper link
# ===========================================================================


class TestLink:
    def test_link_creates_symlink(self, runner: CliRunner, isolated_env) -> None:
        """Link creates a symlink from the project dir to the canonical file."""
        tmp_path, _ = isolated_env
        project = tmp_path / "my-project"
        project.mkdir()

        result = runner.invoke(main, ["link", str(project)])
        assert result.exit_code == 0
        assert "Linked" in result.output or "symlink" in result.output.lower()

        link = project / ".claude" / "scheduled_tasks.json"
        assert link.is_symlink()

    def test_link_idempotent(self, runner: CliRunner, isolated_env) -> None:
        """Linking twice does not fail."""
        tmp_path, _ = isolated_env
        project = tmp_path / "my-project"
        project.mkdir()

        result1 = runner.invoke(main, ["link", str(project)])
        assert result1.exit_code == 0

        result2 = runner.invoke(main, ["link", str(project)])
        assert result2.exit_code == 0

    def test_link_default_cwd(self, runner: CliRunner, isolated_env) -> None:
        """Link with no argument uses current directory (default='.')."""
        tmp_path, _ = isolated_env

        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            result = runner.invoke(main, ["link"])
            assert result.exit_code == 0

            link = Path(td) / ".claude" / "scheduled_tasks.json"
            assert link.is_symlink()

    def test_link_nonexistent_dir_fails(self, runner: CliRunner, isolated_env) -> None:
        """Link to a nonexistent directory fails."""
        tmp_path, _ = isolated_env
        result = runner.invoke(main, ["link", str(tmp_path / "does-not-exist")])
        assert result.exit_code != 0


# ===========================================================================
# 9. --version
# ===========================================================================


class TestVersion:
    def test_version_flag(self, runner: CliRunner) -> None:
        """--version prints the version string and exits 0."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_version_contains_version_number(self, runner: CliRunner) -> None:
        """--version output includes a version number pattern."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "version" in result.output.lower()
        assert "0.1.0" in result.output


# ===========================================================================
# 10. --help
# ===========================================================================


class TestHelp:
    def test_help_flag(self, runner: CliRunner) -> None:
        """--help prints usage information with the description."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Durable loop registry" in result.output

    def test_help_lists_commands(self, runner: CliRunner) -> None:
        """--help shows available subcommands."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        for cmd in ["list", "add", "pause", "resume", "delete", "retrigger", "check", "link"]:
            assert cmd in result.output, f"Command '{cmd}' not listed in help"

    def test_subcommand_help(self, runner: CliRunner) -> None:
        """Each subcommand supports --help."""
        for cmd in ["list", "add", "pause", "resume", "delete", "retrigger", "check", "link"]:
            result = runner.invoke(main, [cmd, "--help"])
            assert result.exit_code == 0, f"{cmd} --help failed"
            assert "Usage" in result.output or "usage" in result.output, (
                f"{cmd} --help missing usage"
            )


# ===========================================================================
# 11. Integration / lifecycle tests
# ===========================================================================


class TestLifecycle:
    def test_add_pause_resume_delete(self, runner: CliRunner, isolated_env) -> None:
        """Full lifecycle: add -> pause -> resume -> delete."""
        _, loops_file = isolated_env

        # Add
        result = runner.invoke(main, ["add", "lifecycle", "15m", "-p", "Lifecycle test."])
        assert result.exit_code == 0

        # Pause
        result = runner.invoke(main, ["pause", "lifecycle"])
        assert result.exit_code == 0

        from looper.registry import parse_loops

        loops = parse_loops(loops_file)
        lc = next(l for l in loops if l.name == "lifecycle")
        assert lc.active is False

        # Resume
        result = runner.invoke(main, ["resume", "lifecycle"])
        assert result.exit_code == 0

        loops = parse_loops(loops_file)
        lc = next(l for l in loops if l.name == "lifecycle")
        assert lc.active is True

        # Delete
        result = runner.invoke(main, ["delete", "lifecycle", "--force"])
        assert result.exit_code == 0

        loops = parse_loops(loops_file)
        assert not any(l.name == "lifecycle" for l in loops)

    def test_add_then_retrigger(self, runner: CliRunner, isolated_env) -> None:
        """Add a loop then retrigger shows its prompt."""
        runner.invoke(main, ["add", "trigger-me", "5m", "-p", "Unique prompt text here."])

        result = runner.invoke(main, ["retrigger", "trigger-me"])
        assert result.exit_code == 0
        assert "Unique prompt text here." in result.output

    def test_add_multiple_then_list_shows_all(self, runner: CliRunner, isolated_env) -> None:
        """Add several loops and verify list shows all of them."""
        runner.invoke(main, ["add", "loop-a", "5m", "-p", "A"])
        runner.invoke(main, ["add", "loop-b", "10m", "-p", "B"])
        runner.invoke(main, ["add", "loop-c", "1h", "-p", "C"])

        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "loop-a" in result.output
        assert "loop-b" in result.output
        assert "loop-c" in result.output

    def test_add_then_check_shows_missing(self, runner: CliRunner, isolated_env) -> None:
        """A newly added loop with no matching job shows as missing in check."""
        runner.invoke(main, ["add", "new-loop", "10m", "-p", "New."])

        result = runner.invoke(main, ["check"])
        assert result.exit_code == 0
        assert "missing" in result.output.lower()
        assert "new-loop" in result.output

    def test_delete_middle_preserves_others(self, runner: CliRunner, isolated_env) -> None:
        """Deleting a loop in the middle preserves loops before and after it."""
        runner.invoke(main, ["add", "first", "5m", "-p", "First."])
        runner.invoke(main, ["add", "second", "10m", "-p", "Second."])
        runner.invoke(main, ["add", "third", "15m", "-p", "Third."])

        result = runner.invoke(main, ["delete", "second", "--force"])
        assert result.exit_code == 0

        result = runner.invoke(main, ["list"])
        assert "first" in result.output
        assert "second" not in result.output
        assert "third" in result.output
