"""Unit tests for hivemind.commands.link."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from hivemind.commands.link import (
    _detect_name,
    _generate_prefix,
    link_cmd,
    link_project,
)


def _make_data_repo(tmp_path: Path) -> Path:
    """Create a minimal hivemind data repo with .hivemind.json.

    Returns the data_path directory.
    """
    data_path = tmp_path / "hivemind-data"
    data_path.mkdir(exist_ok=True)

    for d in ("projects", "tasks", "level1", "level2", "level3"):
        (data_path / d).mkdir(exist_ok=True)

    config_data: dict[str, Any] = {
        "version": "2.0.0",
        "data_path": str(data_path),
        "projects": {},
    }
    config_path = data_path / ".hivemind.json"
    config_path.write_text(
        json.dumps(config_data, indent=2), encoding="utf-8"
    )
    return data_path


class TestDetectName:
    """Tests for _detect_name helper."""

    def test_explicit_name_takes_precedence(self, tmp_path: Path) -> None:
        assert _detect_name("myproject", tmp_path) == "myproject"

    def test_falls_back_to_directory_name(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "cool-project"
        project_dir.mkdir()
        result = _detect_name(None, project_dir)
        assert result == "cool-project"


class TestGeneratePrefix:
    """Tests for _generate_prefix helper."""

    def test_short_name(self) -> None:
        assert _generate_prefix("ab") == "AB"

    def test_three_char_name(self) -> None:
        assert _generate_prefix("abc") == "ABC"

    def test_long_name(self) -> None:
        assert _generate_prefix("myproject") == "MYP"

    def test_strips_hyphens(self) -> None:
        assert _generate_prefix("my-proj") == "MYP"

    def test_strips_underscores(self) -> None:
        assert _generate_prefix("my_proj") == "MYP"

    def test_single_char(self) -> None:
        assert _generate_prefix("x") == "X"


class TestLinkProject:
    """Tests for the link_project function."""

    def _setup_workspace(
        self, tmp_path: Path
    ) -> tuple[Path, Path]:
        """Create data repo and project dir. Returns (project_dir, data_path)."""
        data_path = _make_data_repo(tmp_path)
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        return project_dir, data_path

    def test_creates_link_file(self, tmp_path: Path) -> None:
        project_dir, data_path = self._setup_workspace(tmp_path)
        config_path = data_path / ".hivemind.json"

        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            # Patch _find_config to use our test config
            with patch(
                "hivemind.commands.link._find_config"
            ) as mock_fc:
                from hivemind.core.config import HivemindConfig

                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                link_project(project_dir, name="testproj")
        finally:
            os.chdir(old_cwd)

        link_file = project_dir / ".hivemind-link.json"
        assert link_file.exists()
        link_data = json.loads(link_file.read_text(encoding="utf-8"))
        assert link_data == {"project": "testproj", "prefix": "TES"}
        # v4 link files carry only {project, prefix} — data_path is derived
        # from the config dirname and targets live in runtime.enabled_targets.
        assert "data_path" not in link_data
        assert "targets" not in link_data

    def test_creates_data_directories(self, tmp_path: Path) -> None:
        project_dir, data_path = self._setup_workspace(tmp_path)
        config_path = data_path / ".hivemind.json"

        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with patch(
                "hivemind.commands.link._find_config"
            ) as mock_fc:
                from hivemind.core.config import HivemindConfig

                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                link_project(project_dir, name="testproj")
        finally:
            os.chdir(old_cwd)

        assert (data_path / "projects" / "testproj").is_dir()
        assert (data_path / "tasks" / "testproj").is_dir()
        assert (data_path / "tasks" / "testproj" / "_reports").is_dir()
        assert (data_path / "level3" / "testproj").is_dir()

    def test_registers_in_config(self, tmp_path: Path) -> None:
        project_dir, data_path = self._setup_workspace(tmp_path)
        config_path = data_path / ".hivemind.json"

        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with patch(
                "hivemind.commands.link._find_config"
            ) as mock_fc:
                from hivemind.core.config import HivemindConfig

                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                link_project(project_dir, name="testproj")
        finally:
            os.chdir(old_cwd)

        # Reload config to verify persistence
        updated = json.loads(config_path.read_text(encoding="utf-8"))
        assert "testproj" in updated["projects"]
        assert updated["projects"]["testproj"]["prefix"] == "TES"
        assert updated["projects"]["testproj"]["linked_path"] == str(
            project_dir
        )

    def test_refresh_preserves_project_and_prefix(self, tmp_path: Path) -> None:
        project_dir, data_path = self._setup_workspace(tmp_path)

        # Pre-create v4-shaped link file with an explicit prefix.
        link_file = project_dir / ".hivemind-link.json"
        link_file.write_text(
            json.dumps({"project": "existing", "prefix": "EXI"}),
            encoding="utf-8",
        )

        config_path = data_path / ".hivemind.json"
        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with patch("hivemind.commands.link._find_config") as mock_fc:
                from hivemind.core.config import HivemindConfig

                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                result = link_project(project_dir, name="testproj", target="codex")
        finally:
            os.chdir(old_cwd)

        # Project name from the existing link wins over the explicit --name arg.
        assert result == "existing"
        refreshed = json.loads(link_file.read_text(encoding="utf-8"))
        assert refreshed == {"project": "existing", "prefix": "EXI"}
        cfg_data = json.loads(
            (data_path / ".hivemind.json").read_text(encoding="utf-8")
        )
        assert "existing" in cfg_data.get("projects", {})
        assert cfg_data["projects"]["existing"]["prefix"] == "EXI"

    def test_refresh_drops_legacy_v3_fields(self, tmp_path: Path) -> None:
        project_dir, data_path = self._setup_workspace(tmp_path)

        # Pre-create a v3-shaped link file (data_path + targets, no prefix).
        link_file = project_dir / ".hivemind-link.json"
        link_file.write_text(
            json.dumps(
                {
                    "project": "legacy",
                    "data_path": str(data_path),
                    "targets": ["claude"],
                }
            ),
            encoding="utf-8",
        )

        config_path = data_path / ".hivemind.json"
        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with patch("hivemind.commands.link._find_config") as mock_fc:
                from hivemind.core.config import HivemindConfig

                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                link_project(project_dir, target="codex")
        finally:
            os.chdir(old_cwd)

        refreshed = json.loads(link_file.read_text(encoding="utf-8"))
        assert refreshed["project"] == "legacy"
        # Prefix is auto-generated since the v3 link had none.
        assert refreshed["prefix"] == "LEG"
        assert "data_path" not in refreshed
        assert "targets" not in refreshed

    def test_writes_managed_blocks(self, tmp_path: Path) -> None:
        project_dir, data_path = self._setup_workspace(tmp_path)
        config_path = data_path / ".hivemind.json"

        # Create a CLAUDE.md in project dir
        claude_md = project_dir / "CLAUDE.md"
        claude_md.write_text("# My Project\n", encoding="utf-8")
        agents_md = project_dir / "AGENTS.md"
        agents_md.write_text("# Repo Rules\n", encoding="utf-8")

        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with patch(
                "hivemind.commands.link._find_config"
            ) as mock_fc:
                from hivemind.core.config import HivemindConfig

                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                link_project(project_dir, name="testproj")
        finally:
            os.chdir(old_cwd)

        content = claude_md.read_text(encoding="utf-8")
        assert "<!-- hivemind:start -->" in content
        assert "@AGENTS.md" in content
        agents_content = agents_md.read_text(encoding="utf-8")
        assert "Hivemind Project" in agents_content
        assert "tech-stack.md" in agents_content

    def test_agents_md_created_for_codex_target(self, tmp_path: Path) -> None:
        project_dir, data_path = self._setup_workspace(tmp_path)
        config_path = data_path / ".hivemind.json"

        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with patch(
                "hivemind.commands.link._find_config"
            ) as mock_fc:
                from hivemind.core.config import HivemindConfig

                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                link_project(project_dir, name="testproj", target="codex")
        finally:
            os.chdir(old_cwd)

        assert (project_dir / "AGENTS.md").exists()
        content = (project_dir / "AGENTS.md").read_text(encoding="utf-8")
        assert "Hivemind Project" in content
        assert "project: testproj" in content
        assert not (project_dir / "CLAUDE.md").exists()
        hooks = json.loads((project_dir / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        assert "UserPromptSubmit" in hooks["hooks"]

    def test_claude_target_creates_agents_and_claude(self, tmp_path: Path) -> None:
        project_dir, data_path = self._setup_workspace(tmp_path)
        config_path = data_path / ".hivemind.json"

        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with patch("hivemind.commands.link._find_config") as mock_fc:
                from hivemind.core.config import HivemindConfig

                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                link_project(project_dir, name="testproj", target="claude")
        finally:
            os.chdir(old_cwd)

        assert (project_dir / "AGENTS.md").exists()
        assert (project_dir / "CLAUDE.md").exists()


class TestLinkCli:
    """Tests for the CLI command integration."""

    def test_link_via_cli(self, tmp_path: Path) -> None:
        data_path = _make_data_repo(tmp_path)
        project_dir = tmp_path / "cli-project"
        project_dir.mkdir()

        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with patch(
                "hivemind.commands.link._find_config"
            ) as mock_fc:
                from hivemind.core.config import HivemindConfig

                config_path = data_path / ".hivemind.json"
                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                result = runner.invoke(link_cmd, ["--name", "cliproj"])
        finally:
            os.chdir(old_cwd)

        assert result.exit_code == 0, result.output
        assert "Linked project: cliproj" in result.output

    def test_link_cli_skip_if_linked(self, tmp_path: Path) -> None:
        data_path = _make_data_repo(tmp_path)
        project_dir = tmp_path / "cli-project2"
        project_dir.mkdir()

        # Pre-create v4-shaped link file
        link_file = project_dir / ".hivemind-link.json"
        link_file.write_text(
            json.dumps({"project": "prev", "prefix": "PRE"}),
            encoding="utf-8",
        )

        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            with patch("hivemind.commands.link._find_config") as mock_fc:
                from hivemind.core.config import HivemindConfig

                config_path = data_path / ".hivemind.json"
                cfg = HivemindConfig.load(config_path)
                mock_fc.return_value = (cfg, data_path)

                result = runner.invoke(link_cmd, ["--name", "newname", "--target", "codex"])
        finally:
            os.chdir(old_cwd)

        assert result.exit_code == 0, result.output
        assert "Refreshing existing link" in result.output
