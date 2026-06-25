"""Textual TUI for browsing and managing looper loops."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TextArea,
)

from looper.models import CheckResult, Loop, LoopStatus
from looper.registry import (
    check,
    parse_loops,
    remove_loop,
    toggle_loop,
    validate_interval,
    write_loop,
)


# ---------------------------------------------------------------------------
# Modal dialogs
# ---------------------------------------------------------------------------


class AddLoopScreen(ModalScreen[Loop | None]):
    """Modal dialog to add a new loop."""

    CSS = """
    AddLoopScreen {
        align: center middle;
    }
    #add-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #add-dialog Label {
        margin: 1 0 0 0;
    }
    #add-dialog Input {
        margin: 0 0 1 0;
    }
    #add-dialog TextArea {
        height: 8;
        margin: 0 0 1 0;
    }
    #add-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    #add-buttons Button {
        margin-left: 1;
    }
    .error-text {
        color: $error;
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="add-dialog"):
            yield Label("Add New Loop", classes="title")
            yield Label("Name:")
            yield Input(placeholder="my-loop-name", id="name-input")
            yield Label("Interval (e.g. 30m, 1h, '0 9 * * 1-5'):")
            yield Input(placeholder="30m", id="interval-input")
            yield Label("Prompt:")
            yield TextArea(id="prompt-input")
            yield Label("", id="add-error", classes="error-text")
            with Horizontal(id="add-buttons"):
                yield Button("Cancel", variant="default", id="add-cancel")
                yield Button("Add", variant="primary", id="add-submit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-cancel":
            self.dismiss(None)
        elif event.button.id == "add-submit":
            self._submit()

    def _submit(self) -> None:
        name = self.query_one("#name-input", Input).value.strip()
        interval = self.query_one("#interval-input", Input).value.strip()
        prompt = self.query_one("#prompt-input", TextArea).text.strip()
        error_label = self.query_one("#add-error", Label)

        if not name:
            error_label.update("Name is required.")
            return
        if not interval:
            error_label.update("Interval is required.")
            return
        if not validate_interval(interval):
            error_label.update("Invalid interval format.")
            return
        if not prompt:
            error_label.update("Prompt is required.")
            return

        loop = Loop(
            name=name,
            interval=interval,
            prompt=prompt,
            active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.dismiss(loop)

    def action_cancel(self) -> None:
        self.dismiss(None)


class EditLoopScreen(ModalScreen[str | None]):
    """Modal dialog to edit a loop's prompt."""

    CSS = """
    EditLoopScreen {
        align: center middle;
    }
    #edit-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #edit-dialog Label {
        margin: 1 0 0 0;
    }
    #edit-dialog TextArea {
        height: 12;
        margin: 0 0 1 0;
    }
    #edit-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    #edit-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, loop_name: str, current_prompt: str) -> None:
        super().__init__()
        self._loop_name = loop_name
        self._current_prompt = current_prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-dialog"):
            yield Label(f"Edit Prompt: {self._loop_name}", classes="title")
            yield TextArea(self._current_prompt, id="edit-prompt")
            with Horizontal(id="edit-buttons"):
                yield Button("Cancel", variant="default", id="edit-cancel")
                yield Button("Save", variant="primary", id="edit-save")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "edit-cancel":
            self.dismiss(None)
        elif event.button.id == "edit-save":
            prompt = self.query_one("#edit-prompt", TextArea).text.strip()
            self.dismiss(prompt if prompt else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDeleteScreen(ModalScreen[bool]):
    """Modal confirmation dialog for deleting a loop."""

    CSS = """
    ConfirmDeleteScreen {
        align: center middle;
    }
    #confirm-dialog {
        width: 50;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    #confirm-dialog Label {
        margin: 1 0;
        text-align: center;
        width: 100%;
    }
    #confirm-buttons {
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    #confirm-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, loop_name: str) -> None:
        super().__init__()
        self._loop_name = loop_name

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(f"Delete loop '{self._loop_name}'?")
            yield Label("This cannot be undone.")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", variant="default", id="confirm-cancel")
                yield Button("Delete", variant="error", id="confirm-delete")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-cancel":
            self.dismiss(False)
        elif event.button.id == "confirm-delete":
            self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class PromptViewScreen(ModalScreen[None]):
    """Modal to display a loop's prompt (for copy/retrigger)."""

    CSS = """
    PromptViewScreen {
        align: center middle;
    }
    #prompt-dialog {
        width: 80;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #prompt-dialog Label {
        margin: 1 0 0 0;
    }
    #prompt-dialog TextArea {
        height: 12;
        margin: 0 0 1 0;
    }
    #prompt-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
    ]

    def __init__(self, loop_name: str, prompt: str) -> None:
        super().__init__()
        self._loop_name = loop_name
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-dialog"):
            yield Label(f"Prompt: {self._loop_name}", classes="title")
            yield TextArea(self._prompt, id="prompt-text", read_only=True)
            with Horizontal(id="prompt-buttons"):
                yield Button("Close", variant="default", id="prompt-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "prompt-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class CheckResultScreen(ModalScreen[None]):
    """Modal to display check results."""

    CSS = """
    CheckResultScreen {
        align: center middle;
    }
    #check-dialog {
        width: 80;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #check-dialog .title {
        text-style: bold;
        margin: 0 0 1 0;
    }
    #check-content {
        height: auto;
        max-height: 60%;
        margin: 0 0 1 0;
    }
    #check-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
    ]

    def __init__(self, result: CheckResult) -> None:
        super().__init__()
        self._result = result

    def compose(self) -> ComposeResult:
        r = self._result
        with Vertical(id="check-dialog"):
            yield Label("Check Results", classes="title")
            with VerticalScroll(id="check-content"):
                yield Static(self._format_results())
            yield Static(
                f"Active: {r.active_count}  "
                f"Missing: {r.missing_count}  "
                f"Expiring: {r.expiring_count}  "
                f"Orphans: {len(r.orphan_jobs)}  "
                f"Sync needed: {'yes' if r.needs_sync else 'no'}"
            )
            if r.message:
                yield Static(r.message)
            with Horizontal(id="check-buttons"):
                yield Button("Close", variant="default", id="check-close")

    def _format_results(self) -> str:
        lines: list[str] = []
        for s in self._result.statuses:
            expiry = ""
            if s.days_until_expiry is not None:
                expiry = f"  (expires in {s.days_until_expiry:.1f}d)"
            lines.append(f"  {s.state.upper():10s}  {s.loop.name}{expiry}")
        if self._result.orphan_jobs:
            lines.append("")
            lines.append("Orphan jobs (no matching loop):")
            for j in self._result.orphan_jobs:
                lines.append(f"  {j.id}  {j.name}")
        return "\n".join(lines) if lines else "No loops found."

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "check-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class LooperApp(App):
    """TUI for browsing and managing looper loops."""

    TITLE = "looper"
    SUB_TITLE = "Loop Registry Manager"

    CSS = """
    #main-container {
        height: 1fr;
    }
    #table-pane {
        height: 2fr;
        border: solid $primary;
    }
    #detail-pane {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }
    #detail-title {
        text-style: bold;
        margin: 0 0 1 0;
    }
    #detail-body {
        height: 1fr;
    }
    #status-bar {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("a", "add_loop", "Add"),
        Binding("e", "edit_loop", "Edit"),
        Binding("t", "toggle_loop", "Toggle"),
        Binding("p", "pause_loop", "Pause"),
        Binding("r", "retrigger", "Retrigger"),
        Binding("d", "delete_loop", "Delete"),
        Binding("c", "run_check", "Check"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._loops: list[Loop] = []
        self._statuses: list[LoopStatus] = []
        self._check_result: CheckResult | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-container"):
            with VerticalScroll(id="table-pane"):
                yield DataTable(id="loops-table", cursor_type="row")
            with VerticalScroll(id="detail-pane"):
                yield Static("Select a loop to view details", id="detail-title")
                yield Static("", id="detail-body")
        yield Static("Loading...", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#loops-table", DataTable)
        table.add_columns("Name", "Interval", "State", "Active", "Expiry")
        self._refresh_data()

    # -- Data loading -------------------------------------------------------

    def _refresh_data(self) -> None:
        """Reload loops from registry and refresh the table."""
        try:
            result = check()
            self._check_result = result
            self._statuses = result.statuses
            self._loops = [s.loop for s in result.statuses]
        except Exception:
            # Fallback: just parse loops without job diffing
            self._loops = parse_loops()
            self._statuses = [LoopStatus(loop=lp, state="paused" if not lp.active else "unknown") for lp in self._loops]
            self._check_result = None

        self._rebuild_table()
        self._update_status_bar()
        self._update_detail_panel()

    def _rebuild_table(self) -> None:
        table = self.query_one("#loops-table", DataTable)
        table.clear()
        for status in self._statuses:
            lp = status.loop
            expiry_str = ""
            if status.days_until_expiry is not None:
                expiry_str = f"{status.days_until_expiry:.1f}d"
            table.add_row(
                lp.name,
                lp.interval,
                status.state,
                "yes" if lp.active else "no",
                expiry_str,
                key=lp.name,
            )

    def _update_status_bar(self) -> None:
        total = len(self._loops)
        active = sum(1 for lp in self._loops if lp.active)
        sync = ""
        if self._check_result and self._check_result.needs_sync:
            sync = " | SYNC NEEDED"
        bar = self.query_one("#status-bar", Static)
        bar.update(f"Loops: {total}  Active: {active}{sync}")

    def _update_detail_panel(self) -> None:
        """Update the detail panel for the currently selected loop."""
        loop = self._get_selected_loop()
        title = self.query_one("#detail-title", Static)
        body = self.query_one("#detail-body", Static)
        if loop is None:
            title.update("No loop selected")
            body.update("")
            return
        status = self._get_selected_status()
        state_str = status.state if status else "unknown"
        meta_parts = [f"Interval: {loop.interval}", f"State: {state_str}"]
        if loop.created_at:
            meta_parts.append(f"Created: {loop.created_at}")
        if loop.paused_at:
            meta_parts.append(f"Paused: {loop.paused_at}")
        title.update(f"{loop.name}  ({', '.join(meta_parts)})")
        body.update(loop.prompt)

    # -- Selection helpers --------------------------------------------------

    def _get_selected_loop(self) -> Loop | None:
        table = self.query_one("#loops-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(
                Coordinate(table.cursor_row, 0)
            )
            name = row_key.value
            for lp in self._loops:
                if lp.name == name:
                    return lp
        except Exception:
            pass
        return None

    def _get_selected_status(self) -> LoopStatus | None:
        loop = self._get_selected_loop()
        if loop is None:
            return None
        for s in self._statuses:
            if s.loop.name == loop.name:
                return s
        return None

    # -- Table events -------------------------------------------------------

    def on_data_table_cursor_moved(self, event: DataTable.CursorMoved) -> None:
        self._update_detail_panel()

    # -- Actions ------------------------------------------------------------

    def action_add_loop(self) -> None:
        def on_result(loop: Loop | None) -> None:
            if loop is not None:
                try:
                    write_loop(loop)
                    self.notify(f"Added loop: {loop.name}", title="Loop Added")
                except Exception as exc:
                    self.notify(f"Error adding loop: {exc}", severity="error")
                self._refresh_data()

        self.push_screen(AddLoopScreen(), callback=on_result)

    def action_edit_loop(self) -> None:
        loop = self._get_selected_loop()
        if loop is None:
            self.notify("No loop selected.", severity="warning")
            return

        def on_result(new_prompt: str | None) -> None:
            if new_prompt is not None and loop is not None:
                try:
                    updated = Loop(
                        name=loop.name,
                        interval=loop.interval,
                        prompt=new_prompt,
                        active=loop.active,
                        created_at=loop.created_at,
                        paused_at=loop.paused_at,
                    )
                    write_loop(updated)
                    self.notify(f"Updated loop: {loop.name}", title="Loop Updated")
                except Exception as exc:
                    self.notify(f"Error updating loop: {exc}", severity="error")
                self._refresh_data()

        self.push_screen(
            EditLoopScreen(loop.name, loop.prompt), callback=on_result
        )

    def action_toggle_loop(self) -> None:
        loop = self._get_selected_loop()
        if loop is None:
            self.notify("No loop selected.", severity="warning")
            return
        try:
            new_active = not loop.active
            toggle_loop(loop.name, new_active)
            state_word = "activated" if new_active else "paused"
            self.notify(f"Loop {loop.name} {state_word}.", title="Toggled")
        except Exception as exc:
            self.notify(f"Error toggling loop: {exc}", severity="error")
        self._refresh_data()

    def action_pause_loop(self) -> None:
        """Pause the selected loop (same as toggle when active)."""
        loop = self._get_selected_loop()
        if loop is None:
            self.notify("No loop selected.", severity="warning")
            return
        if not loop.active:
            self.notify(f"Loop {loop.name} is already paused.", severity="warning")
            return
        try:
            toggle_loop(loop.name, False)
            self.notify(f"Loop {loop.name} paused.", title="Paused")
        except Exception as exc:
            self.notify(f"Error pausing loop: {exc}", severity="error")
        self._refresh_data()

    def action_retrigger(self) -> None:
        loop = self._get_selected_loop()
        if loop is None:
            self.notify("No loop selected.", severity="warning")
            return
        self.push_screen(PromptViewScreen(loop.name, loop.prompt))

    def action_delete_loop(self) -> None:
        loop = self._get_selected_loop()
        if loop is None:
            self.notify("No loop selected.", severity="warning")
            return

        def on_result(confirmed: bool) -> None:
            if confirmed and loop is not None:
                try:
                    remove_loop(loop.name)
                    self.notify(f"Deleted loop: {loop.name}", title="Deleted")
                except Exception as exc:
                    self.notify(f"Error deleting loop: {exc}", severity="error")
                self._refresh_data()

        self.push_screen(ConfirmDeleteScreen(loop.name), callback=on_result)

    def action_run_check(self) -> None:
        try:
            result = check()
            self._check_result = result
            self._statuses = result.statuses
            self._loops = [s.loop for s in result.statuses]
            self._rebuild_table()
            self._update_status_bar()
            self._update_detail_panel()
            self.push_screen(CheckResultScreen(result))
        except Exception as exc:
            self.notify(f"Check failed: {exc}", severity="error")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Create and run the looper TUI app."""
    app = LooperApp()
    app.run()
