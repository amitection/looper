"""Unit tests for looper.installer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from looper.installer import (
    HOOK_COMMAND,
    LOOPS_MD_HEADER,
    SESSION_HOOK,
    START_LOOPS_CONTENT,
    install,
    install_start_loops_command,
    register_session_hook,
    setup_looper_home,
    uninstall,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all installer paths into tmp_path so nothing touches ~/."""
    looper_home = tmp_path / "looper"
    claude_dir = tmp_path / ".claude"
    settings = claude_dir / "settings.json"
    commands_dir = claude_dir / "commands"
    canonical = looper_home / ".claude" / "scheduled_tasks.json"
    loops_file = looper_home / "loops.md"

    monkeypatch.setattr("looper.installer.LOOPER_HOME", looper_home)
    monkeypatch.setattr("looper.installer.LOOPS_FILE", loops_file)
    monkeypatch.setattr("looper.installer.CANONICAL_TASKS", canonical)
    monkeypatch.setattr("looper.installer.CLAUDE_SETTINGS", settings)
    monkeypatch.setattr("looper.installer.CLAUDE_COMMANDS_DIR", commands_dir)
    monkeypatch.setattr(
        "looper.installer.START_LOOPS_COMMAND", commands_dir / "start-loops.md"
    )

    return tmp_path, looper_home, settings, commands_dir


# ---------------------------------------------------------------------------
# 1. setup_looper_home
# ---------------------------------------------------------------------------


class TestSetupLooperHome:
    def test_creates_directory_structure(self, isolated_env) -> None:
        """setup_looper_home creates ~/looper/, loops.md, and scheduled_tasks.json."""
        _, looper_home, _, _ = isolated_env

        setup_looper_home()

        assert looper_home.is_dir()
        loops_file = looper_home / "loops.md"
        assert loops_file.exists()
        assert loops_file.read_text() == LOOPS_MD_HEADER

        canonical = looper_home / ".claude" / "scheduled_tasks.json"
        assert canonical.exists()
        assert json.loads(canonical.read_text()) == []

    def test_idempotent_preserves_existing_loops(self, isolated_env) -> None:
        """Running twice doesn't overwrite an existing loops.md."""
        _, looper_home, _, _ = isolated_env

        setup_looper_home()

        # Write custom content to loops.md
        loops_file = looper_home / "loops.md"
        custom_content = "## my-loop\ninterval: 5m\nactive: true\n\nDo stuff.\n"
        loops_file.write_text(custom_content)

        # Also write custom scheduled_tasks.json
        canonical = looper_home / ".claude" / "scheduled_tasks.json"
        canonical.write_text('[{"name": "existing"}]')

        # Run again
        setup_looper_home()

        # Both files should be untouched
        assert loops_file.read_text() == custom_content
        assert canonical.read_text() == '[{"name": "existing"}]'


# ---------------------------------------------------------------------------
# 2. register_session_hook
# ---------------------------------------------------------------------------


class TestRegisterSessionHook:
    def test_creates_settings_with_hook(self, isolated_env) -> None:
        """Adds hook to a freshly created settings.json."""
        _, _, settings, _ = isolated_env

        register_session_hook()

        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "hooks" in data
        assert len(data["hooks"]) == 1
        assert data["hooks"][0] == SESSION_HOOK

    def test_idempotent_no_duplicate_hooks(self, isolated_env) -> None:
        """Calling twice doesn't add the hook a second time."""
        _, _, settings, _ = isolated_env

        register_session_hook()
        register_session_hook()

        data = json.loads(settings.read_text())
        matching = [h for h in data["hooks"] if h.get("command") == HOOK_COMMAND]
        assert len(matching) == 1

    def test_preserves_existing_settings(self, isolated_env) -> None:
        """Other keys and hooks in settings.json are preserved."""
        _, _, settings, _ = isolated_env

        # Pre-populate settings with other content
        settings.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "theme": "dark",
            "hooks": [
                {"type": "command", "event": "SessionStart", "command": "other-tool check"}
            ],
            "permissions": {"allow": ["bash"]},
        }
        settings.write_text(json.dumps(existing, indent=2) + "\n")

        register_session_hook()

        data = json.loads(settings.read_text())
        # Existing settings preserved
        assert data["theme"] == "dark"
        assert data["permissions"] == {"allow": ["bash"]}
        # Both hooks present
        assert len(data["hooks"]) == 2
        commands = [h["command"] for h in data["hooks"]]
        assert "other-tool check" in commands
        assert HOOK_COMMAND in commands

    def test_corrupt_settings_backed_up(self, isolated_env) -> None:
        """Corrupt settings.json is backed up and hook is written fresh."""
        _, _, settings, _ = isolated_env

        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("this is not valid JSON {{{")

        register_session_hook()

        # Backup created
        backup = settings.with_suffix(".json.bak")
        assert backup.exists()
        assert backup.read_text() == "this is not valid JSON {{{"

        # Fresh settings with hook
        data = json.loads(settings.read_text())
        assert len(data["hooks"]) == 1
        assert data["hooks"][0] == SESSION_HOOK


# ---------------------------------------------------------------------------
# 3. install_start_loops_command
# ---------------------------------------------------------------------------


class TestInstallStartLoopsCommand:
    def test_writes_command_file(self, isolated_env) -> None:
        """Creates start-loops.md in the commands directory."""
        _, _, _, commands_dir = isolated_env

        install_start_loops_command()

        cmd_file = commands_dir / "start-loops.md"
        assert cmd_file.exists()
        assert cmd_file.read_text() == START_LOOPS_CONTENT

    def test_creates_commands_dir(self, isolated_env) -> None:
        """Creates the commands directory if it doesn't exist."""
        _, _, _, commands_dir = isolated_env
        assert not commands_dir.exists()

        install_start_loops_command()

        assert commands_dir.is_dir()

    def test_overwrites_existing_command(self, isolated_env) -> None:
        """Overwrites an existing start-loops.md with the latest content."""
        _, _, _, commands_dir = isolated_env
        commands_dir.mkdir(parents=True, exist_ok=True)
        cmd_file = commands_dir / "start-loops.md"
        cmd_file.write_text("old content")

        install_start_loops_command()

        assert cmd_file.read_text() == START_LOOPS_CONTENT


# ---------------------------------------------------------------------------
# 4. install (full)
# ---------------------------------------------------------------------------


class TestInstall:
    def test_runs_all_steps(self, isolated_env) -> None:
        """install() creates home dir, registers hook, and installs command."""
        _, looper_home, settings, commands_dir = isolated_env

        install()

        # Step 1: home dir
        assert looper_home.is_dir()
        assert (looper_home / "loops.md").exists()
        assert (looper_home / ".claude" / "scheduled_tasks.json").exists()

        # Step 2: session hook
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert any(h.get("command") == HOOK_COMMAND for h in data.get("hooks", []))

        # Step 3: start-loops command
        assert (commands_dir / "start-loops.md").exists()


# ---------------------------------------------------------------------------
# 5. uninstall
# ---------------------------------------------------------------------------


class TestUninstall:
    def test_removes_hook_and_command(self, isolated_env) -> None:
        """uninstall removes the hook and command file but preserves ~/looper/."""
        _, looper_home, settings, commands_dir = isolated_env

        # First install
        install()

        # Verify everything is in place
        assert (commands_dir / "start-loops.md").exists()

        # Uninstall
        uninstall()

        # Hook removed from settings
        data = json.loads(settings.read_text())
        matching = [h for h in data.get("hooks", []) if h.get("command") == HOOK_COMMAND]
        assert len(matching) == 0

        # Command file removed
        assert not (commands_dir / "start-loops.md").exists()

        # looper home preserved
        assert looper_home.is_dir()
        assert (looper_home / "loops.md").exists()

    def test_preserves_other_hooks(self, isolated_env) -> None:
        """uninstall only removes the looper hook, not other hooks."""
        _, _, settings, _ = isolated_env

        # Install looper
        install()

        # Add another hook manually
        data = json.loads(settings.read_text())
        other_hook = {
            "type": "command",
            "event": "SessionStart",
            "command": "some-other-tool run",
        }
        data["hooks"].append(other_hook)
        settings.write_text(json.dumps(data, indent=2) + "\n")

        uninstall()

        data = json.loads(settings.read_text())
        assert len(data["hooks"]) == 1
        assert data["hooks"][0]["command"] == "some-other-tool run"

    def test_noop_when_nothing_installed(self, isolated_env) -> None:
        """uninstall doesn't error when nothing is installed."""
        _, _, settings, commands_dir = isolated_env

        # Neither settings.json nor start-loops.md exist
        assert not settings.exists()
        assert not commands_dir.exists()

        # Should not raise
        uninstall()

    def test_noop_with_empty_settings(self, isolated_env) -> None:
        """uninstall handles settings.json that exists but has no hooks."""
        _, _, settings, _ = isolated_env

        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"theme": "dark"}, indent=2) + "\n")

        uninstall()

        data = json.loads(settings.read_text())
        assert data["theme"] == "dark"
        assert data.get("hooks", []) == []

    def test_handles_corrupt_settings(self, isolated_env) -> None:
        """uninstall handles corrupt settings.json without crashing."""
        _, _, settings, _ = isolated_env

        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("not json!!!")

        # Should not raise
        uninstall()
