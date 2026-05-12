"""Per-project task counter helpers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import TracebackType

from hivemind.core.paths import task_dir


_COUNTER_FILENAME = "_counter.json"
_LOCK_FILENAME = "_counter.lock"
_WINDOWS_LOCK_TIMEOUT_SECONDS = 5.0
_WINDOWS_LOCK_RETRY_SECONDS = 0.05


class _CounterLock:
    """Exclusive lock for a project's counter files."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fd: int | None = None

    def __enter__(self) -> _CounterLock:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT)
        self._fd = fd
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")

        if sys.platform == "win32":
            self._acquire_windows(fd)
        else:
            self._acquire_posix(fd)

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fd is None:
            return

        fd = self._fd
        try:
            if sys.platform == "win32":
                self._release_windows(fd)
            else:
                self._release_posix(fd)
        finally:
            os.close(fd)
            self._fd = None

    @staticmethod
    def _acquire_posix(fd: int) -> None:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)

    @staticmethod
    def _release_posix(fd: int) -> None:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)

    @staticmethod
    def _acquire_windows(fd: int) -> None:
        import msvcrt

        deadline = time.monotonic() + _WINDOWS_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(_WINDOWS_LOCK_RETRY_SECONDS)

    @staticmethod
    def _release_windows(fd: int) -> None:
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _counter_path(linked_path: Path) -> Path:
    """Return the per-project counter path (v5 layout)."""
    return task_dir(linked_path) / _COUNTER_FILENAME


def _lock_path(linked_path: Path) -> Path:
    """Return the per-project counter lock path (v5 layout)."""
    return task_dir(linked_path) / _LOCK_FILENAME


def _valid_counter(value: object) -> bool:
    """Return True for real integers, excluding bool."""
    return type(value) is int and value >= 0


def _read_counter(counter_path: Path, legacy_counter: int = 0) -> int:
    """Read the per-project counter, falling back to the legacy value."""
    try:
        data = json.loads(counter_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return legacy_counter if _valid_counter(legacy_counter) else 0

    if not isinstance(data, dict):
        return legacy_counter if _valid_counter(legacy_counter) else 0

    value = data.get("value")
    if _valid_counter(value):
        return value
    return legacy_counter if _valid_counter(legacy_counter) else 0


def _write_counter(counter_path: Path, value: int) -> None:
    """Atomically write the per-project counter value."""
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{counter_path.name}.",
        suffix=".tmp",
        dir=counter_path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"value": value}, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, counter_path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def next_task_id(
    linked_path: Path,
    prefix: str,
    legacy_counter: int = 0,
) -> str:
    """Return the next task ID and persist the incremented counter."""
    with _CounterLock(_lock_path(linked_path)):
        counter_path = _counter_path(linked_path)
        # legacy_counter is consulted only when the per-project counter file
        # is absent/invalid. Once _counter.json exists, it is the source of
        # truth; manual edits to global config no longer move the counter.
        counter = _read_counter(counter_path, legacy_counter)
        counter += 1
        _write_counter(counter_path, counter)

    return f"{prefix}-{counter:03d}"
