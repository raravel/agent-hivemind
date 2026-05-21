"""Unit tests for the scope-aware CLI surface (AGE-004-6d59).

Covers:
- ``hv task create --scope ...`` writes scope to frontmatter and to the
  ``_index.json`` entry.
- ``hv task scope-add`` / ``scope-rm`` / ``scope-set`` propagate to both
  frontmatter and the index.
- ``_index.json`` bumps to version 3 and every entry carries a ``scope``
  key (defaulting to ``[]`` when the task was created without scope).
- A v2 index on disk auto-rebuilds to v3 on next read.
- ``validate_task_frontmatter`` accepts missing / list scope and rejects
  non-list scope.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from hivemind.commands.task import (
    _load_task_index,
    _save_task_index,
    task,
)
from hivemind.core.parser import parse_task, validate_task_frontmatter


def _make_workspace(
    tmp_path: Path,
    projects: dict[str, dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    """Create a minimal workspace with .hivemind.json and tasks dir.

    Returns (config_path, data_path). Mirrors ``tests/unit/test_task.py``.
    """
    data_path = tmp_path / "data"
    data_path.mkdir(exist_ok=True)
    (data_path / "tasks").mkdir(exist_ok=True)

    if projects is None:
        projects = {
            "myproj": {
                "prefix": "MP",
                "linked_path": str(tmp_path / "myproj"),
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


def _invoke(
    tmp_path: Path, args: list[str], input: str | None = None
) -> Any:
    """Invoke task CLI with cwd set to *tmp_path* (where .hivemind.json lives)."""
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(task, args, input=input)
    finally:
        os.chdir(old_cwd)


def _tasks_dir(tmp_path: Path, project: str = "myproj") -> Path:
    """v5/v6 tasks dir: ``<linked_path>/hivemind/tasks``."""
    return tmp_path / project / "hivemind" / "tasks"


def _task_file(tmp_path: Path, short_id: str, project: str = "myproj") -> Path:
    """Resolve ``MP-001`` short form to its file under the tasks dir."""
    tasks = _tasks_dir(tmp_path, project)
    candidates: list[Path] = []
    search_roots = [tasks / "active", tasks / "done"]
    archive_root = tasks / "archive"
    if archive_root.is_dir():
        search_roots.extend(
            sub for sub in sorted(archive_root.iterdir()) if sub.is_dir()
        )
    search_roots.append(tasks)  # legacy flat fallback

    for root in search_roots:
        if not root.is_dir():
            continue
        direct = root / f"{short_id}.md"
        if direct.exists():
            return direct
        candidates.extend(sorted(root.glob(f"{short_id}-*.md")))

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise AssertionError(
            f"Ambiguous short ID {short_id!r}: {[p.name for p in candidates]}"
        )
    raise FileNotFoundError(f"No task matching {short_id!r} in {tasks}")


def _task_id(tmp_path: Path, short_id: str, project: str = "myproj") -> str:
    """Return the canonical full task ID (file stem) for *short_id*."""
    return _task_file(tmp_path, short_id, project).stem


class TestCreateWithScope:
    """`hv task create --scope` writes scope to frontmatter + index."""

    def test_create_with_multiple_scope_flags(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        result = _invoke(
            tmp_path,
            [
                "create",
                "-p",
                "myproj",
                "-t",
                "tmp",
                "--scope",
                "src/a.py",
                "--scope",
                "manifest:python",
            ],
        )
        assert result.exit_code == 0, result.output

        task_path = _task_file(tmp_path, "MP-001")
        fm, _body = parse_task(task_path)
        assert fm["scope"] == ["src/a.py", "manifest:python"]

        canonical = _task_id(tmp_path, "MP-001")
        loaded = _load_task_index(_tasks_dir(tmp_path))
        assert loaded is not None
        assert loaded["tasks"][canonical]["scope"] == [
            "src/a.py",
            "manifest:python",
        ]


class TestScopeAdd:
    """`hv task scope-add` appends entries, idempotently."""

    def _setup(self, tmp_path: Path) -> str:
        _make_workspace(tmp_path)
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "tmp", "--scope", "src/a.py"],
        )
        return _task_id(tmp_path, "MP-001")

    def test_scope_add_appends_to_frontmatter_and_index(
        self, tmp_path: Path
    ) -> None:
        canonical = self._setup(tmp_path)
        result = _invoke(
            tmp_path, ["scope-add", "MP-001", "tests/b.py"]
        )
        assert result.exit_code == 0, result.output

        fm, _body = parse_task(_task_file(tmp_path, "MP-001"))
        assert fm["scope"] == ["src/a.py", "tests/b.py"]

        loaded = _load_task_index(_tasks_dir(tmp_path))
        assert loaded is not None
        assert loaded["tasks"][canonical]["scope"] == [
            "src/a.py",
            "tests/b.py",
        ]

    def test_scope_add_is_idempotent(self, tmp_path: Path) -> None:
        canonical = self._setup(tmp_path)
        result = _invoke(tmp_path, ["scope-add", "MP-001", "src/a.py"])
        assert result.exit_code == 0, result.output

        fm, _body = parse_task(_task_file(tmp_path, "MP-001"))
        assert fm["scope"] == ["src/a.py"]

        loaded = _load_task_index(_tasks_dir(tmp_path))
        assert loaded is not None
        assert loaded["tasks"][canonical]["scope"] == ["src/a.py"]


class TestScopeRm:
    """`hv task scope-rm` removes entries; missing entry is a no-op."""

    def _setup(self, tmp_path: Path) -> str:
        _make_workspace(tmp_path)
        _invoke(
            tmp_path,
            [
                "create",
                "-p",
                "myproj",
                "-t",
                "tmp",
                "--scope",
                "src/a.py",
                "--scope",
                "tests/b.py",
            ],
        )
        return _task_id(tmp_path, "MP-001")

    def test_scope_rm_removes_entry(self, tmp_path: Path) -> None:
        canonical = self._setup(tmp_path)
        result = _invoke(tmp_path, ["scope-rm", "MP-001", "src/a.py"])
        assert result.exit_code == 0, result.output

        fm, _body = parse_task(_task_file(tmp_path, "MP-001"))
        assert fm["scope"] == ["tests/b.py"]

        loaded = _load_task_index(_tasks_dir(tmp_path))
        assert loaded is not None
        assert loaded["tasks"][canonical]["scope"] == ["tests/b.py"]

    def test_scope_rm_missing_entry_is_noop(self, tmp_path: Path) -> None:
        canonical = self._setup(tmp_path)
        result = _invoke(tmp_path, ["scope-rm", "MP-001", "nope.py"])
        assert result.exit_code == 0, result.output

        fm, _body = parse_task(_task_file(tmp_path, "MP-001"))
        assert fm["scope"] == ["src/a.py", "tests/b.py"]

        loaded = _load_task_index(_tasks_dir(tmp_path))
        assert loaded is not None
        assert loaded["tasks"][canonical]["scope"] == [
            "src/a.py",
            "tests/b.py",
        ]


class TestScopeSet:
    """`hv task scope-set` replaces scope wholesale."""

    def test_scope_set_replaces_scope(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _invoke(
            tmp_path,
            ["create", "-p", "myproj", "-t", "tmp", "--scope", "src/a.py"],
        )
        canonical = _task_id(tmp_path, "MP-001")

        result = _invoke(tmp_path, ["scope-set", "MP-001", "a", "b", "c"])
        assert result.exit_code == 0, result.output

        fm, _body = parse_task(_task_file(tmp_path, "MP-001"))
        assert fm["scope"] == ["a", "b", "c"]

        loaded = _load_task_index(_tasks_dir(tmp_path))
        assert loaded is not None
        assert loaded["tasks"][canonical]["scope"] == ["a", "b", "c"]


class TestIndexV3:
    """Index version bumps to 3; every entry has a ``scope`` key."""

    def test_create_writes_v3_index_with_scope_default(
        self, tmp_path: Path
    ) -> None:
        _make_workspace(tmp_path)
        result = _invoke(tmp_path, ["create", "-p", "myproj", "-t", "no-scope"])
        assert result.exit_code == 0, result.output

        idx_path = _tasks_dir(tmp_path) / "_index.json"
        raw = json.loads(idx_path.read_text(encoding="utf-8"))
        assert raw["version"] == 3

        canonical = _task_id(tmp_path, "MP-001")
        entry = raw["tasks"][canonical]
        assert "scope" in entry
        assert entry["scope"] == []

    def test_v2_index_auto_rebuilds_to_v3(self, tmp_path: Path) -> None:
        """A v2 index on disk auto-rebuilds to v3 on next read."""
        _make_workspace(tmp_path)
        _invoke(tmp_path, ["create", "-p", "myproj", "-t", "existing"])
        canonical = _task_id(tmp_path, "MP-001")
        tasks_dir = _tasks_dir(tmp_path)
        idx_path = tasks_dir / "_index.json"

        # Manually downgrade index to v2 (strip the scope key from entries).
        raw = json.loads(idx_path.read_text(encoding="utf-8"))
        raw["version"] = 2
        for entry in raw["tasks"].values():
            entry.pop("scope", None)
        _save_task_index(tasks_dir, raw)

        # Confirm we wrote a v2 index without scope.
        before = json.loads(idx_path.read_text(encoding="utf-8"))
        assert before["version"] == 2
        assert "scope" not in before["tasks"][canonical]

        # Any read path triggers the version-mismatch auto-rebuild.
        result = _invoke(tmp_path, ["list", "-p", "myproj", "--flat"])
        assert result.exit_code == 0, result.output

        after = json.loads(idx_path.read_text(encoding="utf-8"))
        assert after["version"] == 3
        assert canonical in after["tasks"]
        assert after["tasks"][canonical]["scope"] == []
        # Existing fields survive the rebuild.
        assert after["tasks"][canonical]["title"] == "existing"


class TestValidateFrontmatterScope:
    """`validate_task_frontmatter` enforces scope typing rules."""

    def _base_fm(self) -> dict[str, object]:
        return {
            "id": "X-001",
            "title": "T",
            "status": "pending",
            "priority": "medium",
            "type": "task",
            "created": "2026-01-01",
            "updated": "2026-01-01",
        }

    def test_rejects_non_list_scope(self) -> None:
        fm = self._base_fm()
        fm["scope"] = "not-a-list"
        with pytest.raises(ValueError):
            validate_task_frontmatter(fm)

    def test_accepts_missing_scope(self) -> None:
        fm = self._base_fm()
        # No scope key — must not raise.
        validate_task_frontmatter(fm)

    def test_accepts_empty_list_scope(self) -> None:
        fm = self._base_fm()
        fm["scope"] = []
        validate_task_frontmatter(fm)

    def test_accepts_list_scope(self) -> None:
        fm = self._base_fm()
        fm["scope"] = ["src/a.py", "manifest:python"]
        validate_task_frontmatter(fm)
