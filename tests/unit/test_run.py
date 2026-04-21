"""Unit tests for hivemind.commands.run."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from hivemind.commands.run import run
from hivemind.commands.task import task


def _make_workspace(
    tmp_path: Path,
    projects: dict[str, dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    """Create a minimal workspace with .hivemind.json and tasks dir."""
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
        "version": "3.0.0",
        "data_path": str(data_path),
        "projects": projects,
    }

    config_path = tmp_path / ".hivemind.json"
    config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    return config_path, data_path


def _invoke_task(tmp_path: Path, args: list[str]) -> Any:
    """Invoke the task CLI in tmp_path context."""
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(task, args)
    finally:
        os.chdir(old_cwd)


def _invoke_run(tmp_path: Path, args: list[str]) -> Any:
    """Invoke the run CLI in tmp_path context."""
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(run, args)
    finally:
        os.chdir(old_cwd)


class TestRunWithTaskId:
    """Tests for `hv run --task ID`."""

    def test_returns_specific_task(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Alpha task", "--priority", "high"])
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Beta task", "--priority", "low"])

        result = _invoke_run(tmp_path, ["--task", "MP-002"])
        assert result.exit_code == 0, result.output
        assert "Beta task" in result.output
        assert "MP-002" in result.output

    def test_task_id_json_format(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "JSON task"])

        result = _invoke_run(tmp_path, ["--task", "MP-001", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["id"] == "MP-001"
        assert data["frontmatter"]["title"] == "JSON task"
        assert "body" in data
        assert "path" in data


class TestAutoDetectInProgress:
    """Tests for auto-detecting in_progress tasks."""

    def test_resumes_in_progress_task(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Task A", "--priority", "low"])
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Task B", "--priority", "high"])
        # Mark A as in_progress
        _invoke_task(tmp_path, ["update", "MP-001", "--status", "in_progress"])

        result = _invoke_run(tmp_path, [])
        assert result.exit_code == 0, result.output
        # Should pick up the in_progress task (MP-001), not the higher-priority pending one
        assert "Task A" in result.output
        assert "MP-001" in result.output


class TestFallbackToNextPending:
    """Tests for fallback to next pending task."""

    def test_picks_highest_priority_pending(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Low task", "--priority", "low"])
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "High task", "--priority", "high"])

        result = _invoke_run(tmp_path, [])
        assert result.exit_code == 0, result.output
        assert "High task" in result.output
        assert "MP-002" in result.output

    def test_respects_dependencies(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Task A", "--priority", "low"])
        _invoke_task(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Task B", "--priority", "high", "--depends", "MP-001"],
        )

        # B has higher priority but depends on A which is not done
        result = _invoke_run(tmp_path, [])
        assert result.exit_code == 0, result.output
        assert "Task A" in result.output

        # Mark A as done, now B should be picked
        _invoke_task(tmp_path, ["update", "MP-001", "--status", "done"])
        result2 = _invoke_run(tmp_path, [])
        assert result2.exit_code == 0, result2.output
        assert "Task B" in result2.output


class TestFormatJson:
    """Tests for --format json output structure."""

    def test_json_output_has_required_keys(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "My task"])

        result = _invoke_run(tmp_path, ["--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "id" in data
        assert "frontmatter" in data
        assert "body" in data
        assert "path" in data
        assert data["id"] == "MP-001"
        assert isinstance(data["frontmatter"], dict)
        assert data["frontmatter"]["title"] == "My task"


class TestNoTasksAvailable:
    """Tests for the no-tasks-available case."""

    def test_no_tasks_exits_with_code_1(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)

        result = _invoke_run(tmp_path, [])
        assert result.exit_code == 1
        assert "No tasks available" in result.output

    def test_all_done_exits_with_code_1(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Done task"])
        _invoke_task(tmp_path, ["update", "MP-001", "--status", "done"])

        result = _invoke_run(tmp_path, [])
        assert result.exit_code == 1
        assert "No tasks available" in result.output

    def test_project_filter_no_match(self, tmp_path: Path) -> None:
        _make_workspace(
            tmp_path,
            projects={
                "myproj": {"prefix": "MP", "linked_path": "/tmp/myproj", "counter": 0},
                "other": {"prefix": "OT", "linked_path": "/tmp/other", "counter": 0},
            },
        )
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "A task"])

        # Search in 'other' project which has no tasks
        result = _invoke_run(tmp_path, ["--project", "other"])
        assert result.exit_code == 1
        assert "No tasks available" in result.output


class TestReadyOnly:
    """Tests for --ready-only (DAG parallel orchestration)."""

    def test_returns_array_of_ready_tasks(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Task A", "--priority", "high"])
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Task B", "--priority", "medium"])

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 2
        # High priority first
        assert data[0]["frontmatter"]["title"] == "Task A"

    def test_respects_depends_on(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", "Root", "--priority", "low"])
        _invoke_task(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Child", "--priority", "high", "--depends", "MP-001"],
        )

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        # Only root is ready; child is blocked by dependency
        assert len(data) == 1
        assert data[0]["frontmatter"]["title"] == "Root"

    def test_limit_caps_results(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        for i in range(5):
            _invoke_task(tmp_path, ["create", "-p", "myproj", "-t", f"T{i}"])

        result = _invoke_run(tmp_path, ["--ready-only", "--limit", "2", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data) == 2

    def test_empty_returns_empty_array_and_exit_1(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 1
        assert result.output.strip() == "[]"
