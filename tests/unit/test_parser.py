"""Unit tests for hivemind.core.parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from hivemind.core.parser import (
    REQUIRED_TASK_FIELDS,
    VALID_STATUSES,
    create_task_file,
    parse_task,
    update_frontmatter,
    validate_status,
    validate_task_frontmatter,
)


def _sample_frontmatter() -> dict[str, object]:
    return {
        "id": "TASK-001",
        "title": "Implement parser",
        "status": "pending",
        "priority": 1,
        "type": "feature",
    }


def _write_task_file(path: Path, fm: dict[str, object], body: str) -> None:
    """Helper to write a task file for testing."""
    create_task_file(path, fm, body)


class TestParseTask:
    """Tests for parse_task()."""

    def test_returns_frontmatter_and_body(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        fm = _sample_frontmatter()
        body = "This is the task body."
        _write_task_file(fpath, fm, body)

        result_fm, result_body = parse_task(fpath)
        assert result_fm["id"] == "TASK-001"
        assert result_fm["title"] == "Implement parser"
        assert result_fm["status"] == "pending"
        assert result_fm["priority"] == 1
        assert result_fm["type"] == "feature"
        assert result_body == body

    def test_file_not_found(self, tmp_path: Path) -> None:
        fpath = tmp_path / "nonexistent.md"
        with pytest.raises(FileNotFoundError):
            parse_task(fpath)

    def test_empty_body(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        fm = _sample_frontmatter()
        _write_task_file(fpath, fm, "")

        result_fm, result_body = parse_task(fpath)
        assert result_fm["id"] == "TASK-001"
        assert result_body == ""


class TestUpdateFrontmatter:
    """Tests for update_frontmatter()."""

    def test_modifies_frontmatter_preserves_body(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        fm = _sample_frontmatter()
        body = "Original body content."
        _write_task_file(fpath, fm, body)

        update_frontmatter(fpath, {"status": "in_progress"})

        result_fm, result_body = parse_task(fpath)
        assert result_fm["status"] == "in_progress"
        assert result_body == body

    def test_updates_multiple_keys(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        fm = _sample_frontmatter()
        body = "Some body."
        _write_task_file(fpath, fm, body)

        update_frontmatter(fpath, {"title": "New Title", "priority": 5})

        result_fm, result_body = parse_task(fpath)
        assert result_fm["title"] == "New Title"
        assert result_fm["priority"] == 5
        assert result_fm["id"] == "TASK-001"  # unchanged
        assert result_body == body

    def test_invalid_status_raises(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        _write_task_file(fpath, _sample_frontmatter(), "body")

        with pytest.raises(ValueError, match="Invalid status"):
            update_frontmatter(fpath, {"status": "bogus"})

    def test_update_to_blocked_succeeds(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        _write_task_file(fpath, _sample_frontmatter(), "body")

        update_frontmatter(fpath, {"status": "blocked"})

        result_fm, _ = parse_task(fpath)
        assert result_fm["status"] == "blocked"

    def test_update_to_cancelled_succeeds(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        _write_task_file(fpath, _sample_frontmatter(), "body")

        update_frontmatter(fpath, {"status": "cancelled"})

        result_fm, _ = parse_task(fpath)
        assert result_fm["status"] == "cancelled"

    def test_file_not_found(self, tmp_path: Path) -> None:
        fpath = tmp_path / "missing.md"
        with pytest.raises(FileNotFoundError):
            update_frontmatter(fpath, {"status": "done"})


class TestCreateTaskFile:
    """Tests for create_task_file()."""

    def test_creates_proper_file(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        fm = _sample_frontmatter()
        body = "Task description here."
        create_task_file(fpath, fm, body)

        assert fpath.exists()
        result_fm, result_body = parse_task(fpath)
        assert result_fm["id"] == "TASK-001"
        assert result_body == body

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        fpath = tmp_path / "deep" / "nested" / "task.md"
        create_task_file(fpath, _sample_frontmatter(), "body")
        assert fpath.exists()

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        incomplete_fm: dict[str, object] = {
            "id": "TASK-001",
            "title": "Missing fields",
        }
        with pytest.raises(ValueError, match="Missing required field"):
            create_task_file(fpath, incomplete_fm, "body")

    def test_invalid_status_raises(self, tmp_path: Path) -> None:
        fpath = tmp_path / "task.md"
        fm = _sample_frontmatter()
        fm["status"] = "invalid_status"
        with pytest.raises(ValueError, match="Invalid status"):
            create_task_file(fpath, fm, "body")


class TestValidateStatus:
    """Tests for validate_status()."""

    @pytest.mark.parametrize("status", VALID_STATUSES)
    def test_valid_statuses_pass(self, status: str) -> None:
        validate_status(status)  # should not raise

    def test_blocked_status_is_valid(self) -> None:
        validate_status("blocked")  # should not raise

    def test_cancelled_status_is_valid(self) -> None:
        validate_status("cancelled")  # should not raise

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            validate_status("not_a_status")


class TestValidateTaskFrontmatter:
    """Tests for validate_task_frontmatter()."""

    def test_valid_frontmatter_passes(self) -> None:
        validate_task_frontmatter(_sample_frontmatter())  # should not raise

    @pytest.mark.parametrize("missing_field", REQUIRED_TASK_FIELDS)
    def test_missing_field_raises(self, missing_field: str) -> None:
        fm = _sample_frontmatter()
        del fm[missing_field]
        with pytest.raises(ValueError, match="Missing required field"):
            validate_task_frontmatter(fm)

    def test_invalid_status_in_frontmatter_raises(self) -> None:
        fm = _sample_frontmatter()
        fm["status"] = "bad"
        with pytest.raises(ValueError, match="Invalid status"):
            validate_task_frontmatter(fm)
