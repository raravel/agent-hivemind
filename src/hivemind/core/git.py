"""Git auto-commit utility for the hivemind data directory."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hivemind.core.config import HivemindConfig


def _run_git(data_path: Path, *args: str) -> tuple[int, str]:
    """Run a git command in the data directory."""
    try:
        result = subprocess.run(
            ["git", "-C", str(data_path), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""


def auto_commit(data_path: Path, message: str) -> bool:
    """Stage all changes and commit if auto_commit is enabled.

    Returns True if a commit was made.
    """
    config_path = data_path / ".hivemind.json"
    if not config_path.exists():
        return False

    cfg = HivemindConfig.load(config_path)
    if not cfg.get("auto_commit"):
        return False

    # Check if it's a git repo
    code, _ = _run_git(data_path, "rev-parse", "--git-dir")
    if code != 0:
        return False

    # Stage all changes
    _run_git(data_path, "add", "-A")

    # Check if there's anything to commit
    code, status = _run_git(data_path, "status", "--porcelain")
    if code != 0 or not status.strip():
        return False

    # Commit
    code, _ = _run_git(data_path, "commit", "-m", message)
    return code == 0
