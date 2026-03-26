"""Unit tests for hv init command with installer integration."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from hivemind.commands.init import (
    _init_git,
    init_cmd,
    init_data_dir,
    run_installers,
)
from hivemind.core.config import HivemindConfig


# ---------------------------------------------------------------------------
# init_data_dir (existing behaviour, basic smoke tests)
# ---------------------------------------------------------------------------


class TestInitDataDir:
    """Verify directory structure creation."""

    def test_creates_all_directories(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        created = init_data_dir(data)
        assert len(created) > 0
        assert data.is_dir()
        assert (data / "projects").is_dir()
        assert (data / "tasks").is_dir()
        assert (data / "level1" / "important.md").exists()
        assert (data / ".hivemind.json").exists()

    def test_idempotent(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        init_data_dir(data)
        second = init_data_dir(data)
        assert second == []


# ---------------------------------------------------------------------------
# run_installers
# ---------------------------------------------------------------------------


class TestRunInstallers:
    """Tests for run_installers() orchestration."""

    def _make_data_dir(self, tmp_path: Path) -> Path:
        """Create a data dir with a valid .hivemind.json."""
        data = tmp_path / "data"
        init_data_dir(data)
        return data

    def test_skills_installed_when_source_exists(
        self, tmp_path: Path
    ) -> None:
        data = self._make_data_dir(tmp_path)
        skills_src = tmp_path / "skills_src"
        skills_src.mkdir()
        (skills_src / "test.md").write_text("# test", encoding="utf-8")

        hooks_src = tmp_path / "hooks_src"
        hooks_src.mkdir()

        summary = run_installers(
            data / ".hivemind.json",
            skills_source=skills_src,
            hooks_source=hooks_src,
        )

        assert summary["skills_skipped"] is False
        assert isinstance(summary["skills"], list)
        assert "test.md" in summary["skills"]

    def test_skills_skipped_when_source_missing(
        self, tmp_path: Path
    ) -> None:
        data = self._make_data_dir(tmp_path)
        hooks_src = tmp_path / "hooks_src"
        hooks_src.mkdir()

        summary = run_installers(
            data / ".hivemind.json",
            skills_source=tmp_path / "nonexistent",
            hooks_source=hooks_src,
        )

        assert summary["skills_skipped"] is True
        assert summary["skills"] == []

    def test_hooks_installed(self, tmp_path: Path) -> None:
        data = self._make_data_dir(tmp_path)
        skills_src = tmp_path / "skills_src"
        skills_src.mkdir()

        hooks_src = tmp_path / "hooks_src"
        hooks_src.mkdir()
        (hooks_src / "hv-pre-commit.js").write_text(
            "// hook", encoding="utf-8"
        )

        # Use a custom settings path so we don't touch the real one.
        settings = tmp_path / "claude" / "settings.json"
        with mock.patch(
            "hivemind.installer.hooks._SETTINGS_DEFAULT", settings
        ):
            summary = run_installers(
                data / ".hivemind.json",
                skills_source=skills_src,
                hooks_source=hooks_src,
            )

        assert summary["hooks"] is True

    def test_profiles_installed(self, tmp_path: Path) -> None:
        data = self._make_data_dir(tmp_path)
        # Remove profiles to trigger installation
        cfg = HivemindConfig.load(data / ".hivemind.json")
        cfg.set("profiles", {})
        cfg.save()

        hooks_src = tmp_path / "hooks_src"
        hooks_src.mkdir()
        skills_src = tmp_path / "skills_src"
        skills_src.mkdir()

        summary = run_installers(
            data / ".hivemind.json",
            skills_source=skills_src,
            hooks_source=hooks_src,
        )

        assert summary["profiles"] is True


# ---------------------------------------------------------------------------
# _init_git
# ---------------------------------------------------------------------------


class TestInitGit:
    """Tests for git initialization in data directory."""

    @pytest.mark.skipif(
        shutil.which("git") is None, reason="git not installed"
    )
    def test_git_init_creates_repo(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        init_data_dir(data)
        config_path = data / ".hivemind.json"

        result = _init_git(data, config_path)

        assert result is True
        assert (data / ".git").is_dir()

        cfg = HivemindConfig.load(config_path)
        assert cfg.get("git_enabled") is True
        assert cfg.get("auto_commit") is True

    def test_git_init_handles_missing_git(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        init_data_dir(data)
        config_path = data / ".hivemind.json"

        with mock.patch(
            "hivemind.commands.init.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            result = _init_git(data, config_path)

        assert result is False
        # Config should NOT have git_enabled set
        cfg = HivemindConfig.load(config_path)
        assert cfg.get("git_enabled") is False


# ---------------------------------------------------------------------------
# CLI integration (click runner)
# ---------------------------------------------------------------------------


class TestInitCmdCLI:
    """Test the full init_cmd via CliRunner."""

    def test_init_creates_data_and_runs_installers(
        self, tmp_path: Path
    ) -> None:
        data = tmp_path / "hv-data"
        skills_src = tmp_path / "skills_src"
        skills_src.mkdir()

        hooks_src = tmp_path / "hooks_src"
        hooks_src.mkdir()

        runner = CliRunner()
        with (
            mock.patch(
                "hivemind.commands.init._SKILLS_DIR", skills_src
            ),
            mock.patch(
                "hivemind.commands.init._HOOKS_DIR", hooks_src
            ),
        ):
            result = runner.invoke(init_cmd, ["--path", str(data)])

        assert result.exit_code == 0
        assert "Initializing hivemind data at:" in result.output
        assert "Claude Code integration:" in result.output
        assert "Done." in result.output

    def test_init_with_git_flag(self, tmp_path: Path) -> None:
        data = tmp_path / "hv-data"
        skills_src = tmp_path / "skills_src"
        skills_src.mkdir()
        hooks_src = tmp_path / "hooks_src"
        hooks_src.mkdir()

        runner = CliRunner()
        with (
            mock.patch(
                "hivemind.commands.init._SKILLS_DIR", skills_src
            ),
            mock.patch(
                "hivemind.commands.init._HOOKS_DIR", hooks_src
            ),
            mock.patch(
                "hivemind.commands.init._init_git", return_value=True
            ) as mock_git,
        ):
            result = runner.invoke(
                init_cmd, ["--path", str(data), "--git"]
            )

        assert result.exit_code == 0
        assert "Git repository initialized" in result.output
        mock_git.assert_called_once()

    def test_init_without_git_flag(self, tmp_path: Path) -> None:
        data = tmp_path / "hv-data"
        skills_src = tmp_path / "skills_src"
        skills_src.mkdir()
        hooks_src = tmp_path / "hooks_src"
        hooks_src.mkdir()

        runner = CliRunner()
        with (
            mock.patch(
                "hivemind.commands.init._SKILLS_DIR", skills_src
            ),
            mock.patch(
                "hivemind.commands.init._HOOKS_DIR", hooks_src
            ),
        ):
            result = runner.invoke(init_cmd, ["--path", str(data)])

        assert result.exit_code == 0
        assert "Git repository initialized" not in result.output

    def test_init_shows_skills_skipped_warning(
        self, tmp_path: Path
    ) -> None:
        data = tmp_path / "hv-data"
        hooks_src = tmp_path / "hooks_src"
        hooks_src.mkdir()

        runner = CliRunner()
        with (
            mock.patch(
                "hivemind.commands.init._SKILLS_DIR",
                tmp_path / "nonexistent",
            ),
            mock.patch(
                "hivemind.commands.init._HOOKS_DIR", hooks_src
            ),
        ):
            result = runner.invoke(init_cmd, ["--path", str(data)])

        assert result.exit_code == 0
        assert "skipped" in result.output
