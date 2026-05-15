"""Path resolution helpers for hivemind project artifacts.

From v4.0.0, project-specific artifacts (specs, tasks, scores, link metadata)
live INSIDE the project repo at ``<linked_path>/hivemind/``. Cross-project
assets (L2 lessons, search index, level3 graphs) remain in the machine-local
data directory.

This module is the single resolution point — every call site that needs a
spec or task path routes through these helpers. Callers pass the resolved
``linked_path`` (from ``cfg.get_project(name)["linked_path"]``); helpers do
not depend on :class:`HivemindConfig`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hivemind.core.config import HivemindConfig


def linked_path_for(cfg: HivemindConfig, project: str) -> Path:
    """Resolve a registered project's absolute ``linked_path``.

    Raises ``FileNotFoundError`` if the project isn't in config or has no
    ``linked_path``. Callers convert to a click error message where useful.
    """
    proj_cfg = cfg.get_project(project)
    if not isinstance(proj_cfg, dict):
        raise FileNotFoundError(
            f"Project '{project}' is not linked. Run `hv link` first."
        )
    raw = proj_cfg.get("linked_path")
    if not isinstance(raw, str) or not raw:
        raise FileNotFoundError(
            f"Project '{project}' has no linked_path. Re-run `hv link`."
        )
    return Path(raw).expanduser()


def project_hivemind_dir(linked_path: Path | str) -> Path:
    """Return ``<linked_path>/hivemind`` — the per-project namespace dir."""
    return Path(linked_path).expanduser() / "hivemind"


def harness_spec_dir(linked_path: Path | str) -> Path:
    """Return ``<linked_path>/hivemind/docs`` — harness spec documents."""
    return project_hivemind_dir(linked_path) / "docs"


def harness_meta_dir(linked_path: Path | str) -> Path:
    """Return ``<linked_path>/hivemind`` — non-doc project metadata.

    Holds: ``harness-scores.jsonl``, ``link.json``.
    """
    return project_hivemind_dir(linked_path)


def task_dir(linked_path: Path | str) -> Path:
    """Return ``<linked_path>/hivemind/tasks`` — task files for the project."""
    return project_hivemind_dir(linked_path) / "tasks"


def harness_scores_path(linked_path: Path | str) -> Path:
    """Return path to ``harness-scores.jsonl`` (renamed from ``_harness_scores.jsonl`` in v5)."""
    return harness_meta_dir(linked_path) / "harness-scores.jsonl"


_NEW_LINK_NAME = "link.json"
_LEGACY_LINK_NAME = ".hivemind-link.json"


def resolve_link_file(project_dir: Path) -> Path | None:
    """Find the project's link file.

    Prefer the v5 location ``<project_dir>/hivemind/link.json``. Fall back to
    the legacy ``<project_dir>/.hivemind-link.json`` for projects not yet
    migrated. Returns ``None`` if neither exists.
    """
    new = project_dir / "hivemind" / _NEW_LINK_NAME
    if new.exists():
        return new
    legacy = project_dir / _LEGACY_LINK_NAME
    if legacy.exists():
        return legacy
    return None


def link_file_target(project_dir: Path) -> Path:
    """Path where ``hv link`` should write the link file (v5 location).

    Ensures the parent directory ``<project_dir>/hivemind/`` exists.
    """
    target = project_dir / "hivemind" / _NEW_LINK_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def reflect_dir(linked_path: Path | str) -> Path:
    """Return ``<linked_path>/hivemind/reflect`` — meta-harness reflection logs."""
    return project_hivemind_dir(linked_path) / "reflect"


def lesson_log_path(linked_path: Path | str) -> Path:
    """Return path to ``lesson-log.jsonl`` (auto-applied feedback entries)."""
    return reflect_dir(linked_path) / "lesson-log.jsonl"


def rollback_log_path(linked_path: Path | str) -> Path:
    """Return path to ``rollback-log.jsonl`` (auto-rollback events)."""
    return reflect_dir(linked_path) / "rollback-log.jsonl"
