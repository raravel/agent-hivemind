"""Integration tests for v1 -> v2 data directory migration.

Verifies that running ``hv init`` on a v1-style directory correctly
migrates files and config to the v2 format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from hivemind.__main__ import cli
from hivemind.core.config import HivemindConfig


def _noop_installers(config_path: Path, **kwargs: Any) -> dict[str, Any]:
    """Stub for ``run_installers`` that skips real Claude Code integration."""
    return {
        "skills": [],
        "skills_skipped": True,
        "hooks": False,
        "profiles": False,
    }


def _create_v1_data_dir(data_path: Path) -> None:
    """Create a v1-style hivemind data directory.

    V1 characteristics:
    - .hivemind.json exists without a ``version`` field
    - important.md lives at the data root (not in level1/)
    - No level2 subdirectory structure
    """
    data_path.mkdir(parents=True, exist_ok=True)

    # v1 config: no version field
    config = {
        "data_path": str(data_path),
        "git_enabled": False,
        "auto_commit": False,
        "model_profile": "balanced",
    }
    (data_path / ".hivemind.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )

    # important.md at root (v1 location)
    (data_path / "important.md").write_text(
        "---\nhits: {}\n---\n# Existing Lessons\n\nSome important content here.\n",
        encoding="utf-8",
    )

    # Some existing v1 data to preserve
    (data_path / "tasks").mkdir(exist_ok=True)
    existing_task = data_path / "tasks" / "OLD-001.md"
    existing_task.write_text(
        "---\nid: OLD-001\ntitle: Existing task\nstatus: done\n"
        "priority: medium\ntype: task\n---\nOld task body\n",
        encoding="utf-8",
    )


def _invoke_init(v1_dir: Path) -> Any:
    """Invoke ``hv init --path`` with installers stubbed out."""
    runner = CliRunner()
    with patch(
        "hivemind.commands.init.run_installers",
        side_effect=_noop_installers,
    ):
        return runner.invoke(cli, ["init", "--path", str(v1_dir)])


class TestV1ToV2Migration:
    """Verify ``hv init --path`` migrates a v1 directory to v2."""

    def test_migration_moves_important_md(self, tmp_path: Path) -> None:
        v1_dir = tmp_path / "v1-data"
        _create_v1_data_dir(v1_dir)

        result = _invoke_init(v1_dir)
        assert result.exit_code == 0, result.output
        assert "migration" in result.output.lower() or "Detected v1" in result.output

        # important.md should now exist in level1/
        level1_important = v1_dir / "level1" / "important.md"
        assert level1_important.exists()
        content = level1_important.read_text(encoding="utf-8")
        assert "Existing Lessons" in content

    def test_migration_updates_config_version(self, tmp_path: Path) -> None:
        v1_dir = tmp_path / "v1-data"
        _create_v1_data_dir(v1_dir)

        result = _invoke_init(v1_dir)
        assert result.exit_code == 0, result.output

        # .hivemind.json should have version 2.0.0
        cfg = HivemindConfig.load(v1_dir / ".hivemind.json")
        assert cfg.get("version") == "2.0.0"

    def test_migration_creates_v2_directories(self, tmp_path: Path) -> None:
        v1_dir = tmp_path / "v1-data"
        _create_v1_data_dir(v1_dir)

        result = _invoke_init(v1_dir)
        assert result.exit_code == 0, result.output

        # V2 directories should exist
        for d in ("projects", "level1", "level2", "level3"):
            assert (v1_dir / d).is_dir(), f"Missing directory: {d}"

        for sub in ("frontend", "backend", "infra", "general"):
            assert (v1_dir / "level2" / sub).is_dir()

    def test_migration_preserves_existing_data(self, tmp_path: Path) -> None:
        v1_dir = tmp_path / "v1-data"
        _create_v1_data_dir(v1_dir)

        result = _invoke_init(v1_dir)
        assert result.exit_code == 0, result.output

        # Existing task file should still be present
        existing_task = v1_dir / "tasks" / "OLD-001.md"
        assert existing_task.exists()
        content = existing_task.read_text(encoding="utf-8")
        assert "OLD-001" in content
        assert "Old task body" in content

    def test_migration_adds_profiles_and_projects(self, tmp_path: Path) -> None:
        v1_dir = tmp_path / "v1-data"
        _create_v1_data_dir(v1_dir)

        result = _invoke_init(v1_dir)
        assert result.exit_code == 0, result.output

        cfg = HivemindConfig.load(v1_dir / ".hivemind.json")
        # profiles should exist (added by migration)
        profiles = cfg.get("profiles")
        assert isinstance(profiles, dict)
        assert "balanced" in profiles

        # projects key should exist
        projects = cfg.get("projects")
        assert isinstance(projects, dict)

    def test_idempotent_migration(self, tmp_path: Path) -> None:
        """Running init twice on a migrated directory should not break anything."""
        v1_dir = tmp_path / "v1-data"
        _create_v1_data_dir(v1_dir)

        # First run: migration
        result1 = _invoke_init(v1_dir)
        assert result1.exit_code == 0

        # Second run: should be a no-op (or at least not fail)
        result2 = _invoke_init(v1_dir)
        assert result2.exit_code == 0

        # Data should still be intact
        cfg = HivemindConfig.load(v1_dir / ".hivemind.json")
        assert cfg.get("version") == "2.0.0"
        assert (v1_dir / "level1" / "important.md").exists()
