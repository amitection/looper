"""Unit tests for looper.installer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from looper.installer import (
    LOOPER_HOOKS,
    LOOPS_MD_HEADER,
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
    loops_file = looper_home / "loops.md"

    monkeypatch.setattr("looper.installer.LOOPER_HOME", looper_home)
    monkeypatch.setattr("looper.installer.LOOPS_FILE", loops_file)
    monkeypatch.setattr("looper.installer.CLAUDE_SETTINGS", settings)
    monkeypatch.setattr("looper.installer.CLAUDE_COMMANDS_DIR", commands_dir)
    monkeypatch.setattr(
        "looper.installer.START_LOOPS_COMMAND", commands_dir / "start-loops.md"
    )
    monkeypatch.setattr(
        "looper.installer.DELETE_LOOP_COMMAND", commands_dir / "delete-loop.md"
    )
    monkeypatch.setattr(
        "looper.installer.STOP_LOOPS_COMMAND", commands_dir / "stop-loops.md"
    )

    return tmp_path, looper_home, settings, commands_dir


# ---------------------------------------------------------------------------
# 1. setup_looper_home
# ---------------------------------------------------------------------------


class TestSetupLooperHome:
    def test_creates_directory_structure(self, isolated_env) -> None:
        """setup_looper_home creates ~/.looper/ and an initial loops.md."""
        _, looper_home, _, _ = isolated_env

        setup_looper_home()

        assert looper_home.is_dir()
        loops_file = looper_home / "loops.md"
        assert loops_file.exists()
        assert loops_file.read_text() == LOOPS_MD_HEADER

    def test_idempotent_preserves_existing_loops(self, isolated_env) -> None:
        """Running twice doesn't overwrite an existing loops.md."""
        _, looper_home, _, _ = isolated_env

        setup_looper_home()

        loops_file = looper_home / "loops.md"
        custom_content = "## my-loop\ninterval: 5m\nactive: true\n\nDo stuff.\n"
        loops_file.write_text(custom_content)

        setup_looper_home()

        assert loops_file.read_text() == custom_content


# ---------------------------------------------------------------------------
# 2. register_session_hook
# ---------------------------------------------------------------------------


def _commands_for(settings_data: dict, event: str) -> list[str]:
    return [
        h.get("command")
        for entry in settings_data.get("hooks", {}).get(event, [])
        for h in entry.get("hooks", [])
    ]


class TestRegisterSessionHook:
    def test_creates_all_three_hooks(self, isolated_env) -> None:
        """Registers SessionStart, Stop, and SessionEnd."""
        _, _, settings, _ = isolated_env

        register_session_hook()

        data = json.loads(settings.read_text())
        assert "looper sync" in _commands_for(data, "SessionStart")
        assert "looper sync" in _commands_for(data, "Stop")
        assert "looper release" in _commands_for(data, "SessionEnd")

    def test_hook_entries_have_matcher_and_nested_hooks(self, isolated_env) -> None:
        """Each entry is a matcher + nested hooks array (Claude Code's required shape)."""
        _, _, settings, _ = isolated_env

        register_session_hook()
        data = json.loads(settings.read_text())
        entry = data["hooks"]["SessionStart"][0]
        assert entry["matcher"] == ""
        assert entry["hooks"][0]["type"] == "command"
        assert entry["hooks"][0]["command"] == "looper sync"

    def test_idempotent_no_duplicates(self, isolated_env) -> None:
        """Calling twice doesn't duplicate any hook."""
        _, _, settings, _ = isolated_env

        register_session_hook()
        register_session_hook()

        data = json.loads(settings.read_text())
        for event in LOOPER_HOOKS:
            cmds = _commands_for(data, event)
            assert cmds.count(LOOPER_HOOKS[event]) == 1

    def test_preserves_existing_settings(self, isolated_env) -> None:
        """Other keys and hooks in settings.json are preserved."""
        _, _, settings, _ = isolated_env

        settings.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "theme": "dark",
            "hooks": {
                "SessionStart": [
                    {"matcher": "", "hooks": [{"type": "command", "command": "other-tool check"}]},
                ],
            },
            "permissions": {"allow": ["bash"]},
        }
        settings.write_text(json.dumps(existing, indent=2) + "\n")

        register_session_hook()

        data = json.loads(settings.read_text())
        assert data["theme"] == "dark"
        assert data["permissions"] == {"allow": ["bash"]}
        start_cmds = _commands_for(data, "SessionStart")
        assert "other-tool check" in start_cmds
        assert "looper sync" in start_cmds

    def test_corrupt_settings_backed_up(self, isolated_env) -> None:
        """Corrupt settings.json is backed up and hooks written fresh."""
        _, _, settings, _ = isolated_env

        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("this is not valid JSON {{{")

        register_session_hook()

        backup = settings.with_suffix(".json.bak")
        assert backup.exists()
        assert backup.read_text() == "this is not valid JSON {{{"

        data = json.loads(settings.read_text())
        assert "looper sync" in _commands_for(data, "SessionStart")


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

    def test_writes_delete_loop_command(self, isolated_env) -> None:
        """Creates delete-loop.md alongside start-loops.md."""
        _, _, _, commands_dir = isolated_env

        install_start_loops_command()

        delete_cmd = commands_dir / "delete-loop.md"
        assert delete_cmd.exists()
        assert "looper delete" in delete_cmd.read_text()

    def test_writes_close_loops_command(self, isolated_env) -> None:
        """Creates stop-loops.md (release the lease / hand off)."""
        _, _, _, commands_dir = isolated_env

        install_start_loops_command()

        close_cmd = commands_dir / "stop-loops.md"
        assert close_cmd.exists()
        assert "looper release" in close_cmd.read_text()


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

        # Step 2: hooks registered
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "looper sync" in _commands_for(data, "SessionStart")
        assert "looper sync" in _commands_for(data, "Stop")
        assert "looper release" in _commands_for(data, "SessionEnd")

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
        assert (commands_dir / "delete-loop.md").exists()
        assert (commands_dir / "stop-loops.md").exists()

        # Uninstall
        uninstall()

        data = json.loads(settings.read_text())
        assert "looper sync" not in _commands_for(data, "SessionStart")
        assert "looper sync" not in _commands_for(data, "Stop")
        assert "looper release" not in _commands_for(data, "SessionEnd")

        # Command files removed
        assert not (commands_dir / "start-loops.md").exists()
        assert not (commands_dir / "delete-loop.md").exists()
        assert not (commands_dir / "stop-loops.md").exists()

        # looper home preserved
        assert looper_home.is_dir()
        assert (looper_home / "loops.md").exists()

    def test_preserves_other_hooks(self, isolated_env) -> None:
        """uninstall only removes the looper hook, not other hooks."""
        _, _, settings, _ = isolated_env

        # Install looper
        install()

        data = json.loads(settings.read_text())
        other_entry = {
            "matcher": "",
            "hooks": [{"type": "command", "command": "some-other-tool run"}],
        }
        data["hooks"]["SessionStart"].append(other_entry)
        settings.write_text(json.dumps(data, indent=2) + "\n")

        uninstall()

        data = json.loads(settings.read_text())
        start_cmds = _commands_for(data, "SessionStart")
        assert start_cmds == ["some-other-tool run"]

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
        assert data.get("hooks", {}) == {} or data.get("hooks") == {}

    def test_handles_corrupt_settings(self, isolated_env) -> None:
        """uninstall handles corrupt settings.json without crashing."""
        _, _, settings, _ = isolated_env

        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("not json!!!")

        # Should not raise
        uninstall()
