"""Unit tests for hivemind.commands.task."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from hivemind.commands.task import task
from hivemind.core.parser import parse_task


def _make_workspace(
    tmp_path: Path,
    projects: dict[str, dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    """Create a minimal workspace with .hivemind.json and tasks dir.

    Returns (config_path, data_path).
    """
    data_path = tmp_path / "data"
    data_path.mkdir(exist_ok=True)
    (data_path / "tasks").mkdir(exist_ok=True)

    if projects is None:
        projects = {
            "myproj": {
                "prefix": "MP",
                "linked_path": "/tmp/myproj",
                "counter": 0,
            }
        }

    config_data = {
        "version": "2.0.0",
        "data_path": str(data_path),
        "projects": projects,
    }

    config_path = tmp_path / ".hivemind.json"
    config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    return config_path, data_path


def _invoke(tmp_path: Path, args: list[str]) -> Any:
    """Invoke task CLI with cwd set to tmp_path (where .hivemind.json lives)."""
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(task, args)
    finally:
        os.chdir(old_cwd)


class TestCreate:
    """Tests for `hv task create`."""

    def test_generates_correct_id_and_increments_counter(
        self, tmp_path: Path
    ) -> None:
        config_path, data_path = _make_workspace(tmp_path)
        result = _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "First task"],
        )
        assert result.exit_code == 0, result.output
        assert "MP-001" in result.output

        # Counter should be 1 now in config
        cfg_data = json.loads(config_path.read_text(encoding="utf-8"))
        assert cfg_data["projects"]["myproj"]["counter"] == 1

        # Create a second task
        result2 = _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Second task"],
        )
        assert result2.exit_code == 0, result2.output
        assert "MP-002" in result2.output

        cfg_data2 = json.loads(config_path.read_text(encoding="utf-8"))
        assert cfg_data2["projects"]["myproj"]["counter"] == 2

    def test_generates_correct_frontmatter(self, tmp_path: Path) -> None:
        config_path, data_path = _make_workspace(tmp_path)
        result = _invoke(
            tmp_path,
            [
                "create",
                "-p",
                "myproj",
                "-t",
                "Test task",
                "--type",
                "feat",
                "--priority",
                "high",
                "--depends",
                "MP-000",
            ],
        )
        assert result.exit_code == 0, result.output

        task_file = data_path / "tasks" / "myproj" / "MP-001.md"
        assert task_file.exists()

        fm, body = parse_task(task_file)
        assert fm["id"] == "MP-001"
        assert fm["title"] == "Test task"
        assert fm["status"] == "pending"
        assert fm["priority"] == "high"
        assert fm["type"] == "feat"
        assert fm["depends_on"] == ["MP-000"]
        assert "created" in fm
        assert "updated" in fm


class TestList:
    """Tests for `hv task list`."""

    def _create_tasks(self, tmp_path: Path) -> None:
        """Create a few tasks for testing."""
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Task A", "--priority", "high"],
        )
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Task B", "--priority", "low"],
        )
        # Update Task A to in_progress
        _invoke(
            tmp_path,
            ["update", "MP-001", "--status", "in_progress"],
        )

    def test_lists_all_tasks(self, tmp_path: Path) -> None:
        _config_path, _data_path = _make_workspace(tmp_path)
        self._create_tasks(tmp_path)

        result = _invoke(tmp_path, ["list", "-p", "myproj"])
        assert result.exit_code == 0, result.output
        assert "MP-001" in result.output
        assert "MP-002" in result.output

    def test_filter_by_status(self, tmp_path: Path) -> None:
        _config_path, _data_path = _make_workspace(tmp_path)
        self._create_tasks(tmp_path)

        result = _invoke(
            tmp_path, ["list", "-p", "myproj", "-s", "pending"]
        )
        assert result.exit_code == 0, result.output
        assert "MP-002" in result.output
        assert "MP-001" not in result.output

    def test_filter_by_priority(self, tmp_path: Path) -> None:
        _config_path, _data_path = _make_workspace(tmp_path)
        self._create_tasks(tmp_path)

        result = _invoke(
            tmp_path,
            ["list", "-p", "myproj", "--priority", "low"],
        )
        assert result.exit_code == 0, result.output
        assert "MP-002" in result.output
        assert "MP-001" not in result.output


class TestGet:
    """Tests for `hv task get`."""

    def test_returns_full_task(self, tmp_path: Path) -> None:
        _config_path, _data_path = _make_workspace(tmp_path)
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Get me", "--priority", "high"],
        )

        result = _invoke(tmp_path, ["get", "MP-001"])
        assert result.exit_code == 0, result.output
        assert "MP-001" in result.output
        assert "Get me" in result.output
        assert "high" in result.output

    def test_format_json(self, tmp_path: Path) -> None:
        _config_path, _data_path = _make_workspace(tmp_path)
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "JSON task"],
        )

        result = _invoke(
            tmp_path, ["get", "MP-001", "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["id"] == "MP-001"
        assert data["title"] == "JSON task"
        assert "body" in data


class TestUpdate:
    """Tests for `hv task update`."""

    def test_modifies_frontmatter_preserves_body(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Update me"],
        )

        result = _invoke(
            tmp_path,
            ["update", "MP-001", "--status", "in_progress", "--title", "Updated"],
        )
        assert result.exit_code == 0, result.output
        assert "Updated" in result.output or "in_progress" in result.output

        task_file = data_path / "tasks" / "myproj" / "MP-001.md"
        fm, _body = parse_task(task_file)
        assert fm["status"] == "in_progress"
        assert fm["title"] == "Updated"
        # updated timestamp should be present
        assert "updated" in fm


class TestNext:
    """Tests for `hv task next`."""

    def test_respects_dependencies(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)

        # Create task A (no deps)
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Task A", "--priority", "low"],
        )
        # Create task B that depends on A
        _invoke(
            tmp_path,
            [
                "create",
                "-p",
                "myproj",
                "-t",
                "Task B",
                "--priority",
                "high",
                "--depends",
                "MP-001",
            ],
        )

        # B should NOT appear because A is not done
        result = _invoke(tmp_path, ["next", "-p", "myproj"])
        assert result.exit_code == 0, result.output
        assert "MP-001" in result.output
        # MP-002 should NOT be the next task (dep not met)
        assert "Next task: MP-002" not in result.output

        # Now mark A as done
        _invoke(
            tmp_path,
            ["update", "MP-001", "--status", "done"],
        )

        # Now B should be next (higher priority)
        result2 = _invoke(tmp_path, ["next", "-p", "myproj"])
        assert result2.exit_code == 0, result2.output
        assert "MP-002" in result2.output

    def test_sorts_by_priority_then_created(self, tmp_path: Path) -> None:
        _config_path, _data_path = _make_workspace(tmp_path)

        # Create tasks with different priorities
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Low task", "--priority", "low"],
        )
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "High task", "--priority", "high"],
        )
        _invoke(
            tmp_path,
            [
                "create",
                "-p",
                "myproj",
                "-t",
                "Medium task",
                "--priority",
                "medium",
            ],
        )

        result = _invoke(tmp_path, ["next", "-p", "myproj"])
        assert result.exit_code == 0, result.output
        # High priority task should be next
        assert "MP-002" in result.output
        assert "High task" in result.output
