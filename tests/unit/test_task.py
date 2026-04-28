"""Unit tests for hivemind.commands.task."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from hivemind.commands.task import (
    _fm_to_index_entry,
    _load_task_index,
    _rebuild_task_index,
    _save_task_index,
    _update_task_index_entry,
    task,
)
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

    def test_auto_detects_project_from_cwd(self, tmp_path: Path) -> None:
        _config_path, _data_path = _make_workspace(tmp_path)
        self._create_tasks(tmp_path)

        linked = tmp_path / "myproj_linked"
        linked.mkdir()
        cfg = json.loads(_config_path.read_text(encoding="utf-8"))
        cfg["projects"]["myproj"]["linked_path"] = str(linked)
        _config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        import shutil
        shutil.copy2(str(_config_path), str(linked / ".hivemind.json"))

        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(linked)
            result = runner.invoke(task, ["list"])
        finally:
            os.chdir(old_cwd)

        assert result.exit_code == 0, result.output
        assert "MP-001" in result.output
        assert "MP-002" in result.output

    def test_auto_detect_fails_gracefully(self, tmp_path: Path) -> None:
        _config_path, _data_path = _make_workspace(tmp_path)
        self._create_tasks(tmp_path)

        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(task, ["list"])
        finally:
            os.chdir(old_cwd)

        assert result.exit_code != 0
        assert "--all-projects" in result.output

    def test_hides_old_done_tasks_by_default(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "Old done"])
        _invoke(tmp_path, ["update", "MP-001", "--status", "done"])

        task_file = data_path / "tasks" / "myproj" / "MP-001.md"
        old_dt = (datetime.now() - timedelta(days=4)).isoformat()
        from hivemind.core.parser import update_frontmatter
        update_frontmatter(task_file, {"completed_at": old_dt})
        _rebuild_task_index(data_path, "myproj")

        result = _invoke(tmp_path, ["list", "-p", "myproj", "--flat"])
        assert result.exit_code == 0, result.output
        assert "Old done" not in result.output

    def test_shows_old_done_tasks_with_all_tasks(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "Old done"])
        _invoke(tmp_path, ["update", "MP-001", "--status", "done"])

        task_file = data_path / "tasks" / "myproj" / "MP-001.md"
        old_dt = (datetime.now() - timedelta(days=4)).isoformat()
        from hivemind.core.parser import update_frontmatter
        update_frontmatter(task_file, {"completed_at": old_dt})
        _rebuild_task_index(data_path, "myproj")

        result = _invoke(
            tmp_path, ["list", "-p", "myproj", "--flat", "--all-tasks"]
        )
        assert result.exit_code == 0, result.output
        assert "Old done" in result.output


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

    def test_sets_completed_at_when_marked_done(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "Done me"])

        result = _invoke(
            tmp_path, ["update", "MP-001", "--status", "done"]
        )
        assert result.exit_code == 0, result.output

        task_file = data_path / "tasks" / "myproj" / "MP-001.md"
        fm, _body = parse_task(task_file)
        assert fm["status"] == "done"
        assert "completed_at" in fm


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


class TestTaskIndex:
    """Tests for _index.json task index helpers."""

    def test_load_returns_none_when_missing(self, tmp_path: Path) -> None:
        data_path = tmp_path / "data"
        data_path.mkdir()
        (data_path / "tasks" / "proj").mkdir(parents=True)
        assert _load_task_index(data_path, "proj") is None

    def test_load_returns_none_on_bad_json(self, tmp_path: Path) -> None:
        data_path = tmp_path / "data"
        idx = data_path / "tasks" / "proj" / "_index.json"
        idx.parent.mkdir(parents=True)
        idx.write_text("NOT JSON", encoding="utf-8")
        assert _load_task_index(data_path, "proj") is None

    def test_load_returns_none_on_version_mismatch(self, tmp_path: Path) -> None:
        data_path = tmp_path / "data"
        idx = data_path / "tasks" / "proj" / "_index.json"
        idx.parent.mkdir(parents=True)
        idx.write_text(
            json.dumps({"version": 999, "tasks": {}}),
            encoding="utf-8",
        )
        assert _load_task_index(data_path, "proj") is None

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        data_path = tmp_path / "data"
        (data_path / "tasks" / "proj").mkdir(parents=True)
        index_data: dict[str, Any] = {
            "version": 1,
            "tasks": {
                "P-001": {
                    "status": "pending",
                    "priority": "high",
                    "type": "task",
                    "parent": None,
                    "depends_on": [],
                    "title": "Test",
                    "updated": "2025-01-01",
                },
            },
        }
        _save_task_index(data_path, "proj", index_data)
        loaded = _load_task_index(data_path, "proj")
        assert loaded is not None
        assert loaded["tasks"]["P-001"]["status"] == "pending"

    def test_fm_to_index_entry_extracts_fields(self) -> None:
        fm: dict[str, object] = {
            "id": "X-001",
            "title": "My task",
            "status": "done",
            "priority": "low",
            "type": "bug",
            "parent": "X-000",
            "depends_on": ["X-999"],
            "created": "2025-01-01",
            "updated": "2025-01-02",
            "completed_at": "2025-01-02T10:00:00",
            "extra_field": "should be ignored",
        }
        entry = _fm_to_index_entry(fm)
        assert entry["title"] == "My task"
        assert entry["status"] == "done"
        assert entry["parent"] == "X-000"
        assert entry["depends_on"] == ["X-999"]
        assert entry["completed_at"] == "2025-01-02T10:00:00"
        assert "id" not in entry
        assert "created" not in entry
        assert "extra_field" not in entry

    def test_fm_to_index_entry_defaults(self) -> None:
        fm: dict[str, object] = {"id": "X-001", "status": "pending"}
        entry = _fm_to_index_entry(fm)
        assert entry["depends_on"] == []
        assert entry["parent"] is None

    def test_rebuild_creates_index(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        # Create two tasks via CLI
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "First"])
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "Second"])

        # Delete existing index to force rebuild
        idx_path = data_path / "tasks" / "myproj" / "_index.json"
        if idx_path.exists():
            idx_path.unlink()

        index_data = _rebuild_task_index(data_path, "myproj")
        assert "MP-001" in index_data["tasks"]
        assert "MP-002" in index_data["tasks"]
        assert index_data["tasks"]["MP-001"]["title"] == "First"
        assert index_data["version"] == 1

        # File should exist on disk
        assert idx_path.exists()

    def test_update_entry_creates_index_if_missing(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "Task"])

        # Remove the index that create built
        idx_path = data_path / "tasks" / "myproj" / "_index.json"
        if idx_path.exists():
            idx_path.unlink()

        _update_task_index_entry(
            data_path,
            "myproj",
            "MP-001",
            {
                "status": "in_progress",
                "priority": "high",
                "type": "task",
                "title": "Task",
                "updated": "2025-01-15",
            },
        )

        loaded = _load_task_index(data_path, "myproj")
        assert loaded is not None
        assert "MP-001" in loaded["tasks"]

    def test_create_writes_index_entry(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        result = _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "Indexed task", "--priority", "high"],
        )
        assert result.exit_code == 0, result.output

        loaded = _load_task_index(data_path, "myproj")
        assert loaded is not None
        assert "MP-001" in loaded["tasks"]
        assert loaded["tasks"]["MP-001"]["title"] == "Indexed task"
        assert loaded["tasks"]["MP-001"]["priority"] == "high"
        assert loaded["tasks"]["MP-001"]["status"] == "pending"

    def test_update_writes_index_entry(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "To update"])

        result = _invoke(
            tmp_path, ["update", "MP-001", "--status", "in_progress"]
        )
        assert result.exit_code == 0, result.output

        loaded = _load_task_index(data_path, "myproj")
        assert loaded is not None
        assert loaded["tasks"]["MP-001"]["status"] == "in_progress"

    def test_scan_uses_index_when_available(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "Alpha"])
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "Beta"])

        # Index exists from create; list should work via index
        result = _invoke(tmp_path, ["list", "-p", "myproj", "--flat"])
        assert result.exit_code == 0, result.output
        assert "MP-001" in result.output
        assert "MP-002" in result.output

    def test_scan_falls_back_and_rebuilds_when_index_missing(
        self, tmp_path: Path
    ) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "Fallback"])

        # Delete the index
        idx_path = data_path / "tasks" / "myproj" / "_index.json"
        if idx_path.exists():
            idx_path.unlink()

        # list should still work via glob fallback
        result = _invoke(tmp_path, ["list", "-p", "myproj", "--flat"])
        assert result.exit_code == 0, result.output
        assert "MP-001" in result.output

        # And the index should have been rebuilt
        assert idx_path.exists()
        loaded = _load_task_index(data_path, "myproj")
        assert loaded is not None
        assert "MP-001" in loaded["tasks"]

    def test_scan_falls_back_on_corrupt_index(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "Corrupt test"])

        # Corrupt the index
        idx_path = data_path / "tasks" / "myproj" / "_index.json"
        idx_path.write_text("{{bad json}}", encoding="utf-8")

        # list should still work
        result = _invoke(tmp_path, ["list", "-p", "myproj", "--flat"])
        assert result.exit_code == 0, result.output
        assert "MP-001" in result.output

        # Index should be rebuilt and valid now
        loaded = _load_task_index(data_path, "myproj")
        assert loaded is not None

    def test_index_schema_matches_spec(self, tmp_path: Path) -> None:
        """Verify the index file matches the documented schema."""
        _config_path, data_path = _make_workspace(tmp_path)
        _invoke(
            tmp_path,
            [
                "create", "-p", "myproj", "-t", "Schema test",
                "--priority", "high", "--depends", "MP-000",
            ],
        )

        idx_path = data_path / "tasks" / "myproj" / "_index.json"
        raw = json.loads(idx_path.read_text(encoding="utf-8"))

        assert raw["version"] == 1
        assert isinstance(raw["tasks"], dict)

        entry = raw["tasks"]["MP-001"]
        assert entry["status"] == "pending"
        assert entry["priority"] == "high"
        assert entry["type"] == "task"
        assert entry["parent"] is None
        assert entry["depends_on"] == ["MP-000"]
        assert entry["title"] == "Schema test"
        assert "updated" in entry
        assert "completed_at" in entry
