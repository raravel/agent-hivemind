"""Unit tests for hivemind.core.counter."""

from __future__ import annotations

import concurrent.futures
import json
import re
import sys
from pathlib import Path

import pytest

from hivemind.core.counter import _read_counter, next_task_id


_ID_RE = re.compile(r"^(?P<prefix>[A-Z]+)-(?P<num>\d{3,})-(?P<hash>[0-9a-f]{4})$")


def _counter_file(linked_path: Path) -> Path:
    return linked_path / "hivemind" / "tasks" / "_counter.json"


def _read_counter_value(linked_path: Path) -> int:
    raw = json.loads(_counter_file(linked_path).read_text(encoding="utf-8"))
    return int(raw["value"])


def _parse(task_id: str) -> tuple[str, int]:
    """Parse PFX-NNN-XXXX into (prefix, number); validates the hash suffix."""
    match = _ID_RE.match(task_id)
    assert match is not None, f"unexpected task ID format: {task_id!r}"
    return match["prefix"], int(match["num"])


def test_absent_file_starts_at_one(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"

    task_id = next_task_id(linked_path, "PFX", legacy_counter=0)

    prefix, number = _parse(task_id)
    assert (prefix, number) == ("PFX", 1)
    assert _read_counter_value(linked_path) == 1


def test_absent_file_uses_legacy_counter(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"

    task_id = next_task_id(linked_path, "PFX", legacy_counter=5)

    _, number = _parse(task_id)
    assert number == 6
    assert _read_counter_value(linked_path) == 6


def test_present_file_advances_value(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"
    counter_file = _counter_file(linked_path)
    counter_file.parent.mkdir(parents=True)
    counter_file.write_text(json.dumps({"value": 7}) + "\n", encoding="utf-8")

    task_id = next_task_id(linked_path, "PFX", legacy_counter=0)

    _, number = _parse(task_id)
    assert number == 8
    assert _read_counter_value(linked_path) == 8


def test_sequential_calls_advance_by_one(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"

    first_id = next_task_id(linked_path, "PFX")
    second_id = next_task_id(linked_path, "PFX")

    assert _parse(first_id) == ("PFX", 1)
    assert _parse(second_id) == ("PFX", 2)
    assert _read_counter_value(linked_path) == 2


def test_corrupt_file_falls_back_to_legacy_counter(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"
    counter_file = _counter_file(linked_path)
    counter_file.parent.mkdir(parents=True)
    counter_file.write_text("not json", encoding="utf-8")

    task_id = next_task_id(linked_path, "PFX", legacy_counter=9)

    _, number = _parse(task_id)
    assert number == 10
    assert _read_counter_value(linked_path) == 10


def test_missing_value_falls_back_to_legacy_counter(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"
    counter_file = _counter_file(linked_path)
    counter_file.parent.mkdir(parents=True)
    counter_file.write_text(json.dumps({"other": 3}) + "\n", encoding="utf-8")

    task_id = next_task_id(linked_path, "PFX", legacy_counter=4)

    _, number = _parse(task_id)
    assert number == 5
    assert _read_counter_value(linked_path) == 5


def test_parent_dir_missing_is_created(tmp_path: Path) -> None:
    linked_path = tmp_path / "missing"

    task_id = next_task_id(linked_path, "PFX")

    _, number = _parse(task_id)
    assert number == 1
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

    _, first = _parse(next_task_id(linked_path, "PFX", legacy_counter=41))
    _, second = _parse(next_task_id(linked_path, "PFX", legacy_counter=100))
    assert (first, second) == (42, 43)
    assert _read_counter_value(linked_path) == 43


def test_disk_scan_recovers_when_counter_file_is_stale(tmp_path: Path) -> None:
    """Hash-suffixed files on disk move the sequence forward even if the
    counter cache lags behind (e.g., dropped during a bad merge resolve)."""
    linked_path = tmp_path / "proj"
    tasks = linked_path / "hivemind" / "tasks"
    tasks.mkdir(parents=True)
    # Plant a stale file from a peer that wasn't reflected in the counter.
    (tasks / "PFX-042-abcd.md").write_text("stub", encoding="utf-8")
    # Counter file is missing → would naively start at 1.
    task_id = next_task_id(linked_path, "PFX", legacy_counter=0)
    _, number = _parse(task_id)
    assert number == 43


def test_legacy_filename_also_advances_sequence(tmp_path: Path) -> None:
    """Pre-v5.1 files (no hash suffix) are counted too."""
    linked_path = tmp_path / "proj"
    tasks = linked_path / "hivemind" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "PFX-007.md").write_text("stub", encoding="utf-8")
    task_id = next_task_id(linked_path, "PFX", legacy_counter=0)
    _, number = _parse(task_id)
    assert number == 8


def test_hash_suffix_is_lower_hex(tmp_path: Path) -> None:
    linked_path = tmp_path / "proj"
    task_id = next_task_id(linked_path, "PFX")
    match = _ID_RE.match(task_id)
    assert match is not None
    assert len(match["hash"]) == 4
    assert all(c in "0123456789abcdef" for c in match["hash"])


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

    # Extract numeric part (penultimate segment after splitting by "-").
    numbers = sorted(_parse(task_id)[1] for task_id in task_ids)
    assert len(numbers) == 100
    assert len(set(numbers)) == 100
    assert numbers == list(range(min(numbers), max(numbers) + 1))
    assert _read_counter_value(linked_path) == max(numbers)
