"""Unit tests for hivemind.core.counter."""

from __future__ import annotations

import concurrent.futures
import json
import sys
from pathlib import Path

import pytest

from hivemind.core.counter import _read_counter, next_task_id


def _counter_file(linked_path: Path) -> Path:
    return linked_path / "hivemind" / "tasks" / "_counter.json"


def _read_counter_value(linked_path: Path) -> int:
    raw = json.loads(_counter_file(linked_path).read_text(encoding="utf-8"))
    return int(raw["value"])


def test_absent_file_starts_at_one(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"

    task_id = next_task_id(linked_path, "PFX", legacy_counter=0)

    assert task_id == "PFX-001"
    assert _read_counter_value(linked_path) == 1


def test_absent_file_uses_legacy_counter(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"

    task_id = next_task_id(linked_path, "PFX", legacy_counter=5)

    assert task_id == "PFX-006"
    assert _read_counter_value(linked_path) == 6


def test_present_file_advances_value(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"
    counter_file = _counter_file(linked_path)
    counter_file.parent.mkdir(parents=True)
    counter_file.write_text(json.dumps({"value": 7}) + "\n", encoding="utf-8")

    task_id = next_task_id(linked_path, "PFX", legacy_counter=0)

    assert task_id == "PFX-008"
    assert _read_counter_value(linked_path) == 8


def test_sequential_calls_advance_by_one(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"

    first_id = next_task_id(linked_path, "PFX")
    second_id = next_task_id(linked_path, "PFX")

    assert first_id == "PFX-001"
    assert second_id == "PFX-002"
    assert _read_counter_value(linked_path) == 2


def test_corrupt_file_falls_back_to_legacy_counter(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"
    counter_file = _counter_file(linked_path)
    counter_file.parent.mkdir(parents=True)
    counter_file.write_text("not json", encoding="utf-8")

    task_id = next_task_id(linked_path, "PFX", legacy_counter=9)

    assert task_id == "PFX-010"
    assert _read_counter_value(linked_path) == 10


def test_missing_value_falls_back_to_legacy_counter(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"
    counter_file = _counter_file(linked_path)
    counter_file.parent.mkdir(parents=True)
    counter_file.write_text(json.dumps({"other": 3}) + "\n", encoding="utf-8")

    task_id = next_task_id(linked_path, "PFX", legacy_counter=4)

    assert task_id == "PFX-005"
    assert _read_counter_value(linked_path) == 5


def test_parent_dir_missing_is_created(tmp_path: Path) -> None:
    linked_path = tmp_path / "missing"

    task_id = next_task_id(linked_path, "PFX")

    assert task_id == "PFX-001"
    assert _counter_file(linked_path).exists()
    assert _read_counter_value(linked_path) == 1


def test_read_counter_rejects_bool_and_falls_back_to_legacy(
    tmp_path: Path,
) -> None:
    counter_path = tmp_path / "tasks" / "myproj" / "_counter.json"
    counter_path.parent.mkdir(parents=True)
    counter_path.write_text(json.dumps({"value": True}), encoding="utf-8")

    assert _read_counter(counter_path, legacy_counter=12) == 12


def test_legacy_counter_ignored_after_first_write(tmp_path: Path) -> None:
    """Once _counter.json exists, legacy_counter no longer moves the value."""
    linked_path = tmp_path / "proj"

    assert next_task_id(linked_path, "PFX", legacy_counter=41) == "PFX-042"
    assert next_task_id(linked_path, "PFX", legacy_counter=100) == "PFX-043"
    assert _read_counter_value(linked_path) == 43


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="file-locking test unreliable on Windows CI",
)
def test_concurrent_writers_yield_unique_contiguous_ids(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"

    def call_many() -> list[str]:
        return [
            next_task_id(linked_path, "MP", legacy_counter=0)
            for _ in range(50)
        ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(call_many) for _ in range(2)]
        task_ids = [
            task_id
            for future in concurrent.futures.as_completed(futures)
            for task_id in future.result()
        ]

    values = sorted(int(task_id.rsplit("-", 1)[1]) for task_id in task_ids)
    assert len(values) == 100
    assert len(set(values)) == 100
    assert values == list(range(min(values), max(values) + 1))
    assert _read_counter_value(linked_path) == max(values)
