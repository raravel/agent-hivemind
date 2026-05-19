"""Unit tests for ``hv task archive`` (Phase 4 of the v6 directory split)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import frontmatter
from click.testing import CliRunner

from hivemind.commands.task import task


def _make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    data_path = tmp_path / "data"
    proj_path = tmp_path / "proj"
    data_path.mkdir()
    proj_path.mkdir()
    config = {
        "version": "6.0.0",
        "git_enabled": False,
        "auto_commit": False,
        "projects": {
            "p": {"prefix": "P", "linked_path": str(proj_path), "counter": 0}
        },
    }
    (data_path / ".hivemind.json").write_text(json.dumps(config), encoding="utf-8")
    (data_path / "level2").mkdir()
    (data_path / "level3").mkdir()
    return data_path, proj_path


def _seed_done_task(
    proj_path: Path, task_id: str, completed_at: datetime
) -> Path:
    """Write a done task directly into done/ with the given completed_at."""
    done = proj_path / "hivemind" / "tasks" / "done"
    done.mkdir(parents=True, exist_ok=True)
    target = done / f"{task_id}.md"
    fm: dict[str, Any] = {
        "id": task_id,
        "title": "demo",
        "status": "done",
        "type": "task",
        "priority": "medium",
        "depends_on": [],
        "created": completed_at.date().isoformat(),
        "updated": completed_at.date().isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    target.write_text(
        frontmatter.dumps(frontmatter.Post("", **fm)), encoding="utf-8"
    )
    # Keep _index.json fresh so resolution stays cheap.
    from hivemind.commands.task import _rebuild_task_index

    _rebuild_task_index(proj_path / "hivemind" / "tasks")
    return target


def _invoke(data_path: Path, args: list[str]) -> Any:
    runner = CliRunner()
    old = os.getcwd()
    try:
        os.chdir(data_path)
        return runner.invoke(task, args)
    finally:
        os.chdir(old)


class TestArchiveAge:
    def test_skips_recently_done(self, tmp_path: Path) -> None:
        """Default ``--older-than 14d`` leaves freshly-done tasks alone."""
        data_path, proj_path = _make_workspace(tmp_path)
        _seed_done_task(
            proj_path, "P-001-fresh", completed_at=datetime.now()
        )
        result = _invoke(data_path, ["archive", "-p", "p"])
        assert result.exit_code == 0, result.output
        assert "0 archived" in result.output
        assert (proj_path / "hivemind/tasks/done/P-001-fresh.md").exists()
        assert not (proj_path / "hivemind/tasks/archive").exists()

    def test_moves_old_done_to_monthly_bucket(self, tmp_path: Path) -> None:
        data_path, proj_path = _make_workspace(tmp_path)
        old_dt = datetime(2026, 1, 15, 10, 0, 0)
        _seed_done_task(proj_path, "P-001-old", completed_at=old_dt)

        result = _invoke(data_path, ["archive", "-p", "p"])
        assert result.exit_code == 0, result.output
        assert "1 archived" in result.output

        bucket = proj_path / "hivemind/tasks/archive/2026-01/P-001-old.md"
        assert bucket.exists()
        assert not (proj_path / "hivemind/tasks/done/P-001-old.md").exists()

        # Index path field tracks the new location.
        idx = json.loads(
            (proj_path / "hivemind/tasks/_index.json").read_text(encoding="utf-8")
        )
        assert idx["tasks"]["P-001-old"]["path"] == "archive/2026-01/P-001-old.md"


class TestArchiveFlags:
    def test_dry_run_does_not_move(self, tmp_path: Path) -> None:
        data_path, proj_path = _make_workspace(tmp_path)
        old_dt = datetime.now() - timedelta(days=60)
        _seed_done_task(proj_path, "P-001-dr", completed_at=old_dt)

        result = _invoke(data_path, ["archive", "-p", "p", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "[dry-run]" in result.output
        assert (proj_path / "hivemind/tasks/done/P-001-dr.md").exists()
        assert not (proj_path / "hivemind/tasks/archive").exists()

    def test_all_overrides_age_threshold(self, tmp_path: Path) -> None:
        data_path, proj_path = _make_workspace(tmp_path)
        _seed_done_task(proj_path, "P-001-now", completed_at=datetime.now())

        result = _invoke(data_path, ["archive", "-p", "p", "--all"])
        assert result.exit_code == 0, result.output
        assert "1 archived" in result.output
        # Freshly-done task gets archived under the current month.
        bucket = datetime.now().strftime("%Y-%m")
        assert (
            proj_path / "hivemind/tasks/archive" / bucket / "P-001-now.md"
        ).exists()

    def test_rejects_invalid_older_than(self, tmp_path: Path) -> None:
        data_path, _proj_path = _make_workspace(tmp_path)
        result = _invoke(data_path, ["archive", "-p", "p", "--older-than", "junk"])
        assert result.exit_code != 0
        assert "Invalid --older-than" in result.output
