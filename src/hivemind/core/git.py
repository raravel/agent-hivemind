"""Git auto-commit utility for hivemind repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hivemind.core.config import HivemindConfig


def _run_git(repo_dir: Path, *args: str) -> tuple[int, str]:
    """Run a git command in *repo_dir*."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""


def auto_commit(repo_dir: Path, message: str, *, force: bool = False) -> bool:
    """Stage all changes in *repo_dir* and commit if auto_commit is enabled.

    The ``auto_commit`` toggle is resolved from the global hivemind config
    (looked up via :py:meth:`HivemindConfig.find_for_command`). The repo
    target is independent: project-local artifacts (specs, tasks, scores)
    commit into the linked project repo; cross-project artifacts (L2/index)
    commit into the data repo. Returns True if a commit was made.

    Pass ``force=True`` to bypass the ``auto_commit`` toggle — for one-shot
    operations the user has explicitly opted into (e.g., ``hv migrate``).
    Non-git directories are still a silent no-op.
    """
    if not force:
        try:
            cfg = HivemindConfig.find_for_command()
        except FileNotFoundError:
            return False
        if not cfg.get("auto_commit"):
            return False

    # Check if it's a git repo
    code, _ = _run_git(repo_dir, "rev-parse", "--git-dir")
    if code != 0:
        return False

    # Stage all changes
    _run_git(repo_dir, "add", "-A")

    # Check if there's anything to commit
    code, status = _run_git(repo_dir, "status", "--porcelain")
    if code != 0 or not status.strip():
        return False

    # Commit
    code, _ = _run_git(repo_dir, "commit", "-m", message)
    return code == 0
