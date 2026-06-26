"""TUI tests for looper.tui using Textual's async pilot framework."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from looper.models import Loop, LoopStatus


# ---------------------------------------------------------------------------
# Sample data
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all looper paths to tmp_path so tests never touch real user dirs."""
    loops_file = tmp_path / "loops.md"

    monkeypatch.setattr("looper.LOOPER_HOME", tmp_path)
    monkeypatch.setattr("looper.LOOPS_FILE", loops_file)
    monkeypatch.setattr("looper.registry.LOOPS_FILE", loops_file)
    monkeypatch.setattr("looper.harvest.SESSIONS_DIR", tmp_path / "sessions")
    return tmp_path, loops_file


@pytest.fixture()
def populated_env(isolated_env):
    """isolated_env with the sample loops.md already written."""
    tmp_path, loops_file = isolated_env
    loops_file.write_text(SAMPLE_LOOPS_MD)
    return tmp_path, loops_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app():
    """Import and instantiate LooperApp fresh (avoids module-level import issues)."""
    from looper.tui import LooperApp
    return LooperApp()


# ---------------------------------------------------------------------------
# 1. App launches without error
# ---------------------------------------------------------------------------


async def test_app_launches_without_error(isolated_env):
    app = _make_app()
    async with app.run_test() as pilot:
        assert app.is_running


# ---------------------------------------------------------------------------
# 2. App shows correct title
# ---------------------------------------------------------------------------


async def test_app_shows_correct_title(isolated_env):
    app = _make_app()
    async with app.run_test() as pilot:
        assert app.title == "looper"
        assert app.sub_title == "Loop Registry Manager"


# ---------------------------------------------------------------------------
# 3. Empty state shows no rows
# ---------------------------------------------------------------------------


async def test_empty_state_shows_no_rows(isolated_env):
    app = _make_app()
    async with app.run_test() as pilot:
        table = app.query_one("#loops-table", DataTable)
        assert table.row_count == 0


# ---------------------------------------------------------------------------
# 4. With loops in loops.md, table shows them
# ---------------------------------------------------------------------------


async def test_table_shows_loops_from_file(populated_env):
    app = _make_app()
    async with app.run_test() as pilot:
        table = app.query_one("#loops-table", DataTable)
        assert table.row_count == 3


async def test_table_row_names(populated_env):
    app = _make_app()
    async with app.run_test() as pilot:
        table = app.query_one("#loops-table", DataTable)
        names = set()
        for i in range(table.row_count):
            row = table.get_row_at(i)
            names.add(str(row[0]))
        assert names == {"check-deploys", "daily-report", "cleanup"}


async def test_table_row_status_column(populated_env):
    app = _make_app()
    async with app.run_test() as pilot:
        table = app.query_one("#loops-table", DataTable)
        rows = {}
        for i in range(table.row_count):
            row = table.get_row_at(i)
            rows[str(row[0])] = row
        # Columns: Name, Schedule, Status. No live session note in the test, so
        # enabled loops are "idle"; daily-report is paused.
        assert str(rows["check-deploys"][2]) == "idle"
        assert str(rows["daily-report"][2]) == "paused"
        assert str(rows["cleanup"][2]) == "idle"


# ---------------------------------------------------------------------------
# 5. Pressing 'q' quits the app
# ---------------------------------------------------------------------------


async def test_press_q_quits(isolated_env):
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("q")
        # The context manager exits cleanly if the app quit.


# ---------------------------------------------------------------------------
# 6. Pressing 'a' opens the AddLoopScreen modal
# ---------------------------------------------------------------------------


async def test_press_a_opens_add_screen(isolated_env):
    from looper.tui import AddLoopScreen
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, AddLoopScreen)


async def test_add_screen_has_inputs(isolated_env):
    from looper.tui import AddLoopScreen
    from textual.widgets import Input, TextArea
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, AddLoopScreen)
        # Widgets live on the modal screen, not the default screen.
        name_input = app.screen.query_one("#name-input", Input)
        interval_input = app.screen.query_one("#interval-input", Input)
        prompt_input = app.screen.query_one("#prompt-input", TextArea)
        assert name_input is not None
        assert interval_input is not None
        assert prompt_input is not None


async def test_add_screen_escape_closes(isolated_env):
    from looper.tui import AddLoopScreen
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, AddLoopScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, AddLoopScreen)


# ---------------------------------------------------------------------------
# 7. Pressing 't' on a selected loop toggles it
# ---------------------------------------------------------------------------


async def test_press_t_toggles_loop_active_state(populated_env):
    _, loops_file = populated_env
    from looper.registry import parse_loops

    app = _make_app()
    async with app.run_test() as pilot:
        table = app.query_one("#loops-table", DataTable)
        assert table.row_count == 3

        # Identify the first row to know its initial status.
        row0_before = table.get_row_at(0)
        first_name = str(row0_before[0])
        initial_status = str(row0_before[2])

        # Press 't' to toggle.
        await pilot.press("t")
        await pilot.pause()

        # Verify on disk that the toggle persisted.
        loops = parse_loops(loops_file)
        toggled = next(lp for lp in loops if lp.name == first_name)
        if initial_status == "paused":
            assert toggled.active is True
        else:
            assert toggled.active is False


async def test_press_t_updates_table(populated_env):
    app = _make_app()
    async with app.run_test() as pilot:
        table = app.query_one("#loops-table", DataTable)
        row0_before = table.get_row_at(0)
        initial_status = str(row0_before[2])

        await pilot.press("t")
        await pilot.pause()

        # After toggle and refresh the status column should flip (idle <-> paused
        # in the test, since no live session is hosting).
        table = app.query_one("#loops-table", DataTable)
        row0_after = table.get_row_at(0)
        new_status = str(row0_after[2])
        expected = "idle" if initial_status == "paused" else "paused"
        assert new_status == expected


# ---------------------------------------------------------------------------
# 8. Pressing 'd' on a selected loop opens ConfirmDeleteScreen
# ---------------------------------------------------------------------------


async def test_press_d_opens_confirm_delete(populated_env):
    from looper.tui import ConfirmDeleteScreen
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDeleteScreen)


async def test_confirm_delete_cancel_preserves_rows(populated_env):
    from looper.tui import ConfirmDeleteScreen
    app = _make_app()
    async with app.run_test() as pilot:
        table = app.query_one("#loops-table", DataTable)
        original_count = table.row_count

        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDeleteScreen)

        # Cancel via escape.
        await pilot.press("escape")
        await pilot.pause()

        table = app.query_one("#loops-table", DataTable)
        assert table.row_count == original_count


async def test_confirm_delete_removes_loop(populated_env):
    from looper.tui import ConfirmDeleteScreen
    app = _make_app()
    async with app.run_test() as pilot:
        table = app.query_one("#loops-table", DataTable)
        assert table.row_count == 3

        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDeleteScreen)

        # Click the Delete button on the confirmation modal.
        await pilot.click("#confirm-delete")
        await pilot.pause()

        table = app.query_one("#loops-table", DataTable)
        assert table.row_count == 2


# ---------------------------------------------------------------------------
# 9. Pressing 'r' on a selected loop opens PromptViewScreen
# ---------------------------------------------------------------------------


async def test_press_r_opens_prompt_view(populated_env):
    from looper.tui import PromptViewScreen
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, PromptViewScreen)


async def test_prompt_view_shows_prompt_text(populated_env):
    from looper.tui import PromptViewScreen
    from textual.widgets import TextArea
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, PromptViewScreen)

        text_area = app.screen.query_one("#prompt-text", TextArea)
        # The prompt text should not be empty.
        assert len(text_area.text.strip()) > 0


async def test_prompt_view_escape_closes(populated_env):
    from looper.tui import PromptViewScreen
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, PromptViewScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, PromptViewScreen)


# ---------------------------------------------------------------------------
# 10. Pressing 'g' refreshes
# ---------------------------------------------------------------------------


async def test_press_g_refreshes(populated_env):
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("g")
        await pilot.pause()
        # Table is still populated after a refresh.
        assert app.query_one("#loops-table", DataTable).row_count == 3


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------


async def test_status_bar_shows_loop_counts(populated_env):
    """Status bar should display total and running loop counts."""
    app = _make_app()
    async with app.run_test() as pilot:
        bar = app.query_one("#status-bar", Static)
        text = str(bar.content)
        # 3 total loops; none running (no live session note in the test).
        assert "Loops: 3" in text
        assert "Running: 0" in text


async def test_detail_panel_updates_on_mount(populated_env):
    """On mount with loops, the detail panel should show info about the first loop."""
    app = _make_app()
    async with app.run_test() as pilot:
        title = app.query_one("#detail-name", Static)
        body = app.query_one("#detail-body", Static)

        title_text = str(title.content)
        body_text = str(body.content)

        # The first loop's details should be visible.
        assert len(title_text) > 0
        assert len(body_text) > 0


async def test_no_loop_selected_actions_do_not_crash(isolated_env):
    """Pressing action keys with no loops should not raise."""
    app = _make_app()
    async with app.run_test(notifications=True) as pilot:
        # With no loops, pressing action keys should produce warnings, not crashes.
        for key in ("t", "d", "r", "e", "p"):
            await pilot.press(key)
            await pilot.pause()
        # Reaching here without exception means no crashes.


