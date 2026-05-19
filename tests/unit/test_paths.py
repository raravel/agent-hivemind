"""Unit tests for ``hivemind.core.paths`` task-directory helpers.

Covers the v6 layout split (active/done/archive/{YYYY-MM}) plus the
legacy flat-layout fallback that lets old fixtures keep resolving.
"""

from __future__ import annotations

from pathlib import Path

from hivemind.core.paths import (
    active_dir,
    archive_dir,
    done_dir,
    iter_task_dirs,
)


def test_subdir_helpers_return_expected_paths(tmp_path: Path) -> None:
    base = tmp_path / "tasks"
    assert active_dir(base) == base / "active"
    assert done_dir(base) == base / "done"
    assert archive_dir(base) == base / "archive"
    assert archive_dir(base, "2026-05") == base / "archive" / "2026-05"


def test_iter_task_dirs_falls_back_to_flat_layout(tmp_path: Path) -> None:
    """Pre-v6 (flat) layouts yield the tasks dir itself."""
    base = tmp_path / "tasks"
    base.mkdir()
    (base / "AGE-001.md").write_text("---\nid: AGE-001\n---\n", encoding="utf-8")

    result = [p.relative_to(tmp_path) for p in iter_task_dirs(base)]
    assert result == [Path("tasks")]


def test_iter_task_dirs_yields_v6_subdirs_when_present(tmp_path: Path) -> None:
    base = tmp_path / "tasks"
    (base / "active").mkdir(parents=True)
    (base / "done").mkdir()
    (base / "archive" / "2026-05").mkdir(parents=True)
    (base / "archive" / "2026-06").mkdir(parents=True)

    result = [p.relative_to(tmp_path).as_posix() for p in iter_task_dirs(base)]
    # active/done first (insertion order), then archive buckets sorted.
    assert result == [
        "tasks/active",
        "tasks/done",
        "tasks/archive/2026-05",
        "tasks/archive/2026-06",
    ]


def test_iter_task_dirs_skips_flat_when_subdirs_exist(tmp_path: Path) -> None:
    """When active/done exist, the flat root is NOT yielded as well.

    Otherwise a half-migrated layout would double-count tasks.
    """
    base = tmp_path / "tasks"
    (base / "active").mkdir(parents=True)
    (base / "AGE-orphan.md").write_text(
        "---\nid: AGE-orphan\n---\n", encoding="utf-8"
    )

    result = list(iter_task_dirs(base))
    assert result == [base / "active"]


def test_iter_task_dirs_handles_missing_dir(tmp_path: Path) -> None:
    base = tmp_path / "nonexistent"
    assert list(iter_task_dirs(base)) == []
