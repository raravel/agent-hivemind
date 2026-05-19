"""Implementation of `hv task` command group."""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import click

from hivemind.core.config import HivemindConfig
from hivemind.core.counter import next_task_id
from hivemind.core.git import auto_commit
from hivemind.core.parser import (
    create_task_file,
    parse_task,
    update_frontmatter,
    validate_status,
)
from hivemind.core.paths import (
    active_dir,
    archive_dir,
    done_dir,
    iter_task_dirs,
    linked_path_for,
    task_dir,
)

_log = logging.getLogger(__name__)

PRIORITY_ORDER: dict[str, int] = {"high": 3, "medium": 2, "low": 1}

# Types that behave like "story" for hierarchy purposes
_STORY_TYPES: frozenset[str] = frozenset({"story", "feature"})

# Leaf types that can be assigned as actual work items
_LEAF_TYPES: frozenset[str] = frozenset({"task", "bug", "chore"})

# Statuses that mean "no further work" — both hide by default and propagate
# upward when every sibling reaches one of them.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "cancelled"})

# Valid parent type for each child type
_VALID_PARENT: dict[str, str | frozenset[str] | None] = {
    "epic": None,  # epic must have no parent
    "story": "epic",
    "feature": "epic",
    "task": _STORY_TYPES,
    "bug": _STORY_TYPES,
    "chore": _STORY_TYPES,
}

# Current schema version for _index.json
# v2 (hivemind v6): adds per-task ``path`` field — relative to tasks_dir,
# e.g. ``"active/AGE-001-abcd1234.md"``. Lets resolution skip directory
# scans when the index is fresh. v1 indexes are auto-rebuilt on read.
_INDEX_VERSION: int = 2

# Frontmatter keys stored in the index. ``path`` is not a frontmatter
# field — it tracks the file's location under tasks_dir and is supplied
# separately to :func:`_fm_to_index_entry`.
_INDEX_FIELDS: list[str] = [
    "status",
    "priority",
    "type",
    "parent",
    "depends_on",
    "title",
    "updated",
    "completed_at",
    "path",
]


def _index_path(tasks_dir: Path) -> Path:
    """Return the path to ``_index.json`` inside *tasks_dir*."""
    return tasks_dir / "_index.json"


def _load_task_index(tasks_dir: Path) -> dict[str, Any] | None:
    """Load ``_index.json`` from *tasks_dir*.

    Returns the parsed dict or ``None`` if the file is missing, corrupt,
    or has an incompatible version.
    """
    path = _index_path(tasks_dir)
    try:
        raw = path.read_text(encoding="utf-8")
        data: dict[str, Any] = json.loads(raw)
        if data.get("version") != _INDEX_VERSION:
            _log.debug("Index version mismatch at %s", path)
            return None
        if not isinstance(data.get("tasks"), dict):
            return None
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _save_task_index(tasks_dir: Path, index_data: dict[str, Any]) -> None:
    """Write *index_data* to ``_index.json`` inside *tasks_dir*."""
    path = _index_path(tasks_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(index_data, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _fm_to_index_entry(
    fm: dict[str, object], *, path: str | None = None
) -> dict[str, object]:
    """Extract the subset of frontmatter fields stored in the index.

    *path* is the file's location relative to ``tasks_dir`` (forward-slash
    POSIX form, e.g. ``"active/AGE-001-abcd1234.md"``). It is not a
    frontmatter key so the caller supplies it; passing ``None`` records a
    null entry which downstream resolvers treat as "scan to find it".
    """
    entry: dict[str, object] = {}
    for key in _INDEX_FIELDS:
        if key == "path":
            entry[key] = path
            continue
        value = fm.get(key)
        # Normalise None / missing to a sensible default
        if key == "depends_on":
            entry[key] = list(value) if isinstance(value, list) else []
        elif key == "parent":
            entry[key] = str(value) if value else None
        else:
            entry[key] = value
    return entry


def _rebuild_task_index(tasks_dir: Path) -> dict[str, Any]:
    """Scan task files under *tasks_dir* and build a fresh index.

    Walks every directory yielded by :func:`iter_task_dirs` (active/,
    done/, archive/{YYYY-MM}/ — or the flat root for legacy layouts) and
    records each task's location relative to *tasks_dir* in the entry's
    ``path`` field.
    """
    tasks: dict[str, dict[str, object]] = {}

    if tasks_dir.exists():
        for sub_dir in iter_task_dirs(tasks_dir):
            for md_file in sorted(sub_dir.glob("*.md")):
                if md_file.name.startswith("_"):
                    continue
                try:
                    fm, _body = parse_task(md_file)
                    task_id = fm.get("id")
                    if isinstance(task_id, str):
                        rel = md_file.relative_to(tasks_dir).as_posix()
                        tasks[task_id] = _fm_to_index_entry(fm, path=rel)
                except Exception:
                    continue

    index_data: dict[str, Any] = {
        "version": _INDEX_VERSION,
        "tasks": tasks,
    }
    _save_task_index(tasks_dir, index_data)
    return index_data


def _update_task_index_entry(
    tasks_dir: Path,
    task_id: str,
    fm_dict: dict[str, object],
    *,
    path: str | None = None,
) -> None:
    """Update a single entry in the index, creating the index if needed.

    *path* — file location relative to *tasks_dir* (POSIX). When omitted,
    the existing entry's recorded path is preserved if present, so
    callers that only touch frontmatter (e.g. ``_bump_updated``,
    ``body-set``) don't need to know the file's location.
    """
    index_data = _load_task_index(tasks_dir)
    if index_data is None:
        _rebuild_task_index(tasks_dir)
        return  # rebuild already populates path from the file's actual location

    if path is None:
        existing = index_data["tasks"].get(task_id)
        if isinstance(existing, dict):
            prior = existing.get("path")
            if isinstance(prior, str) and prior:
                path = prior
    index_data["tasks"][task_id] = _fm_to_index_entry(fm_dict, path=path)
    _save_task_index(tasks_dir, index_data)


def _move_task_to_status_dir(
    task_path: Path, tasks_dir: Path, status: object
) -> Path:
    """Relocate *task_path* to the directory that matches its *status*.

    Terminal states (``done`` / ``cancelled``) live under ``done/``;
    everything else lives under ``active/``. Tasks that are already in
    the correct directory are left in place. Tasks currently under
    ``archive/{YYYY-MM}/`` are restored to ``active/`` or ``done/`` —
    archive is meant as a snapshot, so any status mutation implies the
    user wants the task back in active circulation.
    """
    status_str = str(status) if status is not None else ""
    target_dir = (
        done_dir(tasks_dir) if status_str in _TERMINAL_STATUSES else active_dir(tasks_dir)
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    if task_path.parent.resolve() == target_dir.resolve():
        return task_path
    new_path = target_dir / task_path.name
    task_path.rename(new_path)
    return new_path


def _find_config() -> tuple[HivemindConfig, Path]:
    """Locate .hivemind.json and return (config, data_path)."""
    try:
        cfg = HivemindConfig.find_for_command()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    return cfg, cfg.data_path


def _find_project_by_cwd(cfg: HivemindConfig) -> str | None:
    cwd = Path.cwd().resolve()
    projects = cfg.raw.get("projects", {})
    if not isinstance(projects, dict):
        return None
    for name, proj in projects.items():
        if not isinstance(proj, dict):
            continue
        linked = proj.get("linked_path")
        if linked:
            try:
                linked_path = Path(str(linked)).expanduser().resolve()
                if linked_path == cwd:
                    return str(name)
            except Exception:
                continue
    return None


def _project_tasks_dir(cfg: HivemindConfig, project: str) -> Path:
    """Return ``<linked_path>/hivemind/tasks`` for *project* (v5)."""
    return task_dir(linked_path_for(cfg, project))


def _iter_project_task_dirs(
    cfg: HivemindConfig, project: str | None = None
) -> list[tuple[str, Path]]:
    """Yield (project_name, tasks_dir) for registered projects.

    When *project* is given, restrict to that one. Skips projects without a
    valid ``linked_path``.
    """
    projects = cfg.raw.get("projects", {})
    if not isinstance(projects, dict):
        return []

    out: list[tuple[str, Path]] = []
    for name, proj in projects.items():
        if project is not None and name != project:
            continue
        if not isinstance(proj, dict):
            continue
        linked = proj.get("linked_path")
        if not isinstance(linked, str) or not linked:
            continue
        out.append((name, task_dir(Path(linked).expanduser())))
    return out


def _resolve_in_tasks_dir(tasks_dir: Path, task_id: str) -> Path | None:
    """Resolve a task ID to its file under *tasks_dir*.

    Fast path: consult ``_index.json`` (v2 schema records a ``path`` field
    relative to *tasks_dir*) and return the recorded location when the
    file still exists. Slow path: walk every directory yielded by
    :func:`iter_task_dirs` (``active/``, ``done/``, each
    ``archive/{YYYY-MM}/``, or the flat root for legacy layouts).

    Accepts the canonical ``<PREFIX>-NNN-<hash>`` form (direct match) and
    the legacy short form ``<PREFIX>-NNN`` (glob fallback
    ``<id>-*.md``). Raises a click error when the short form matches more
    than one canonical ID.
    """
    # Fast path: index lookup.
    index_data = _load_task_index(tasks_dir)
    if index_data is not None:
        entries = index_data.get("tasks", {})
        if isinstance(entries, dict):
            entry = entries.get(task_id)
            if isinstance(entry, dict):
                rel = entry.get("path")
                if isinstance(rel, str) and rel:
                    cand = tasks_dir / rel
                    if cand.exists():
                        return cand
            # Short-form lookup: find canonical IDs starting with <task_id>-.
            short_hits = [
                cid
                for cid in entries
                if isinstance(cid, str) and cid.startswith(f"{task_id}-")
            ]
            if len(short_hits) == 1:
                entry = entries.get(short_hits[0])
                if isinstance(entry, dict):
                    rel = entry.get("path")
                    if isinstance(rel, str) and rel:
                        cand = tasks_dir / rel
                        if cand.exists():
                            return cand
            elif len(short_hits) > 1:
                raise click.ClickException(
                    f"Ambiguous task ID {task_id!r}: matches "
                    f"{', '.join(sorted(short_hits))}. Use the full ID."
                )

    # Slow path: directory scan across active/done/archive (and flat
    # legacy layout as a final fallback inside iter_task_dirs).
    candidates: list[Path] = []
    for sub_dir in iter_task_dirs(tasks_dir):
        direct = sub_dir / f"{task_id}.md"
        if direct.exists():
            return direct
        candidates.extend(sorted(sub_dir.glob(f"{task_id}-*.md")))

    if not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(p.stem for p in candidates)
        raise click.ClickException(
            f"Ambiguous task ID {task_id!r}: matches {names}. Use the full ID."
        )
    return candidates[0]


def _find_task_file(cfg: HivemindConfig, task_id: str) -> Path:
    """Find a task markdown file by its ID across all registered projects."""
    for _name, tasks_dir in _iter_project_task_dirs(cfg):
        resolved = _resolve_in_tasks_dir(tasks_dir, task_id)
        if resolved is not None:
            return resolved

    raise click.ClickException(f"Task not found: {task_id}")


def _find_task_with_project(
    cfg: HivemindConfig, task_id: str
) -> tuple[Path, str, Path, str]:
    """Return (task_path, project_name, tasks_dir, canonical_id) for a task ID.

    ``canonical_id`` is the full hash-suffixed ID derived from the file's
    stem. Callers should use it (not the user-supplied short ``task_id``)
    when writing to the task index or any other ID-keyed store.
    """
    for name, tasks_dir in _iter_project_task_dirs(cfg):
        resolved = _resolve_in_tasks_dir(tasks_dir, task_id)
        if resolved is not None:
            return resolved, name, tasks_dir, resolved.stem
    raise click.ClickException(f"Task not found: {task_id}")


def _resolve_to_canonical_id(cfg: HivemindConfig, task_id: str) -> str:
    """Normalize a user-supplied task ID to the canonical full form.

    Used at create time for ``--parent`` and ``--depends`` references so
    cross-task wiring stores the hash-suffixed ID even when the user
    typed the legacy short form. Returns the input unchanged when the
    referenced task doesn't exist (e.g. a forward reference) so existing
    fixtures and tests that depend on string identity keep working.
    """
    for _name, tasks_dir in _iter_project_task_dirs(cfg):
        resolved = _resolve_in_tasks_dir(tasks_dir, task_id)
        if resolved is not None:
            return resolved.stem
    return task_id


def _scan_tasks_from_index(
    tasks_dir: Path,
) -> list[tuple[dict[str, object], str, Path]] | None:
    """Build scan results from the index, or ``None`` when unavailable.

    Uses each entry's ``path`` field (v2 schema) to construct the file
    path. Entries with a missing/null path fall back to ``<id>.md`` at
    the *tasks_dir* root so a partially-migrated index does not strand
    callers. Body is always ``""`` because the index does not store
    bodies.
    """
    index_data = _load_task_index(tasks_dir)
    if index_data is None:
        return None

    results: list[tuple[dict[str, object], str, Path]] = []
    entries = index_data.get("tasks", {})
    if not isinstance(entries, dict):
        return None
    for task_id, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        fm: dict[str, object] = {"id": task_id, **entry}
        rel = entry.get("path")
        if isinstance(rel, str) and rel:
            path = tasks_dir / rel
        else:
            path = tasks_dir / f"{task_id}.md"
        results.append((fm, "", path))
    return results


def _scan_tasks_glob(
    tasks_dir: Path,
) -> list[tuple[dict[str, object], str, Path]]:
    """Glob+parse fallback for scanning task files under *tasks_dir*.

    Walks every directory yielded by :func:`iter_task_dirs`. Names
    starting with ``_`` (reserved like ``_reports`` or ``_index.json``)
    are skipped.
    """
    results: list[tuple[dict[str, object], str, Path]] = []
    for d in iter_task_dirs(tasks_dir):
        for md_file in sorted(d.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                fm, body = parse_task(md_file)
                results.append((fm, body, md_file))
            except Exception:
                continue
    return results


def _scan_tasks(
    cfg: HivemindConfig,
    project: str | None = None,
) -> list[tuple[dict[str, object], str, Path]]:
    """Scan task files and return list of (frontmatter, body, path).

    Reads from ``_index.json`` when available for better performance.
    Falls back to glob+parse and rebuilds the index on a miss.
    """
    results: list[tuple[dict[str, object], str, Path]] = []

    for _name, tasks_dir in _iter_project_task_dirs(cfg, project):
        if not tasks_dir.exists():
            continue
        indexed = _scan_tasks_from_index(tasks_dir)
        if indexed is not None:
            results.extend(indexed)
        else:
            # Fallback: glob+parse, then rebuild index for next time
            scanned = _scan_tasks_glob(tasks_dir)
            results.extend(scanned)
            _rebuild_task_index(tasks_dir)

    return results


# ---------------------------------------------------------------------------
# Helpers for hierarchical tasks
# ---------------------------------------------------------------------------


def _load_all_tasks(
    cfg: HivemindConfig, project: str | None = None
) -> list[dict[str, object]]:
    """Load all tasks as a flat list of frontmatter dicts."""
    scanned = _scan_tasks(cfg, project)
    return [fm for fm, _body, _path in scanned]


def _build_tree(
    tasks: list[dict[str, object]],
) -> dict[str | None, list[dict[str, object]]]:
    """Build parent_id -> children mapping.

    Tasks with no ``parent`` key (or ``parent`` is ``None``) are roots
    (keyed under ``None``).
    """
    tree: dict[str | None, list[dict[str, object]]] = defaultdict(list)
    for t in tasks:
        parent = t.get("parent")
        parent_key = str(parent) if parent else None
        tree[parent_key].append(t)
    return dict(tree)


def _auto_complete_parents(
    cfg: HivemindConfig,
    task_fm: dict[str, object],
    all_tasks: list[dict[str, object]],
) -> None:
    """Walk up the hierarchy and auto-complete parents when appropriate.

    When every child of a parent has reached a terminal status (``done`` or
    ``cancelled``), mark the parent terminal too and recurse upward. The
    parent becomes ``cancelled`` only when every child is ``cancelled``;
    a mix of ``done`` and ``cancelled`` resolves to ``done`` (some work
    landed).
    """
    parent_id = task_fm.get("parent")
    if not parent_id or not isinstance(parent_id, str):
        return

    by_id: dict[str, dict[str, object]] = {}
    for t in all_tasks:
        tid = t.get("id")
        if isinstance(tid, str):
            by_id[tid] = t

    parent_fm = by_id.get(parent_id)
    if parent_fm is None:
        return

    if parent_fm.get("status") in _TERMINAL_STATUSES:
        return

    siblings = [t for t in all_tasks if str(t.get("parent", "")) == parent_id]
    if not siblings:
        return

    if not all(t.get("status") in _TERMINAL_STATUSES for t in siblings):
        return

    new_status = (
        "cancelled"
        if all(t.get("status") == "cancelled" for t in siblings)
        else "done"
    )

    parent_path, _proj, parent_tasks_dir, parent_canonical_id = _find_task_with_project(
        cfg, parent_id
    )
    today = date.today().isoformat()
    now_iso = datetime.now().isoformat()
    update_frontmatter(
        parent_path,
        {"status": new_status, "updated": today, "completed_at": now_iso},
    )

    parent_fm_fresh, _ = parse_task(parent_path)
    parent_path = _move_task_to_status_dir(
        parent_path, parent_tasks_dir, parent_fm_fresh.get("status")
    )
    parent_rel = parent_path.relative_to(parent_tasks_dir).as_posix()
    _update_task_index_entry(
        parent_tasks_dir, parent_canonical_id, parent_fm_fresh, path=parent_rel
    )

    parent_type = str(parent_fm.get("type", ""))
    click.echo(f"Auto-completed: {parent_id} [{parent_type}] -> {new_status}")

    parent_fm["status"] = new_status

    _auto_complete_parents(cfg, parent_fm, all_tasks)


def _validate_parent_hierarchy(
    child_type: str,
    parent_id: str | None,
    all_tasks: list[dict[str, object]],
) -> None:
    """Validate that the parent relationship is valid for the hierarchy.

    Rules:
    - epic must have no parent
    - story/feature parent must be an epic
    - task/bug/chore parent must be a story or feature
    """
    allowed = _VALID_PARENT.get(child_type)

    if allowed is None:
        # epic: must have no parent
        if parent_id:
            raise click.ClickException(
                f"Type '{child_type}' cannot have a parent."
            )
        return

    if not parent_id:
        # story/feature/task/bug/chore without parent is allowed (top-level)
        return

    # Find parent task
    parent_fm: dict[str, object] | None = None
    for t in all_tasks:
        if t.get("id") == parent_id:
            parent_fm = t
            break

    if parent_fm is None:
        raise click.ClickException(f"Parent task not found: {parent_id}")

    parent_type = str(parent_fm.get("type", ""))

    if isinstance(allowed, str):
        if parent_type != allowed:
            raise click.ClickException(
                f"Type '{child_type}' requires parent of type '{allowed}', "
                f"but '{parent_id}' is type '{parent_type}'."
            )
    elif isinstance(allowed, frozenset):
        if parent_type not in allowed:
            allowed_str = ", ".join(sorted(allowed))
            raise click.ClickException(
                f"Type '{child_type}' requires parent of type "
                f"{{{allowed_str}}}, but '{parent_id}' is type "
                f"'{parent_type}'."
            )


def _effective_type(task_type: str) -> str:
    """Normalize type for hierarchy comparisons ('feature' -> 'story')."""
    if task_type == "feature":
        return "story"
    return task_type


def _render_tree(
    tree: dict[str | None, list[dict[str, object]]],
    parent_key: str | None,
    prefix: str,
    is_last: bool,
    output_lines: list[str],
    *,
    is_root: bool = False,
) -> None:
    """Recursively render tree nodes with box-drawing characters."""
    children = tree.get(parent_key, [])

    # Sort children: by priority desc, then by id asc
    children.sort(
        key=lambda t: (
            -PRIORITY_ORDER.get(str(t.get("priority", "medium")), 0),
            str(t.get("id", "")),
        )
    )

    for i, task in enumerate(children):
        is_last_child = i == len(children) - 1
        tid = str(task.get("id", ""))
        ttype = str(task.get("type", ""))
        ttitle = str(task.get("title", ""))
        tstatus = str(task.get("status", ""))
        tpriority = str(task.get("priority", ""))

        if is_root:
            # Root-level items: no tree prefix
            line = (
                f"{tid} [{ttype}]  {ttitle:<30} {tstatus:<10} {tpriority}"
            )
        else:
            connector = "\u2514\u2500 " if is_last_child else "\u251c\u2500 "
            line = (
                f"{prefix}{connector}"
                f"{tid} [{ttype}]  {ttitle:<30} {tstatus:<10} {tpriority}"
            )

        output_lines.append(line)

        # Recurse into children of this node
        if is_root:
            child_prefix = ""
        else:
            child_prefix = prefix + ("\u2502  " if not is_last_child else "   ")

        _render_tree(
            tree,
            tid,
            child_prefix,
            is_last_child,
            output_lines,
        )


def _get_parent_chain(
    task_fm: dict[str, object],
    all_tasks: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return the chain of parent tasks from immediate parent to root."""
    by_id: dict[str, dict[str, object]] = {}
    for t in all_tasks:
        tid = t.get("id")
        if isinstance(tid, str):
            by_id[tid] = t

    chain: list[dict[str, object]] = []
    current = task_fm
    seen: set[str] = set()

    while True:
        parent_id = current.get("parent")
        if not parent_id or not isinstance(parent_id, str):
            break
        if parent_id in seen:
            break  # prevent cycles
        seen.add(parent_id)
        parent = by_id.get(parent_id)
        if parent is None:
            break
        chain.append(parent)
        current = parent

    return chain


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@click.group()
def task() -> None:
    """Manage tasks."""


@task.command()
@click.option("--project", "-p", required=True, help="Project name.")
@click.option("--title", "-t", required=True, help="Task title.")
@click.option(
    "--type", "task_type", default="task", help="Task type (default: task)."
)
@click.option(
    "--priority",
    default="medium",
    type=click.Choice(["high", "medium", "low"]),
    help="Priority (default: medium).",
)
@click.option("--depends", multiple=True, help="Task ID this depends on.")
@click.option("--parent", "parent_id", default=None, help="Parent task ID.")
def create(
    project: str,
    title: str,
    task_type: str,
    priority: str,
    depends: tuple[str, ...],
    parent_id: str | None,
) -> None:
    """Create a new task."""
    cfg, _data_path = _find_config()

    proj_cfg = cfg.get_project(project)
    if proj_cfg is None:
        raise click.ClickException(
            f"Project '{project}' not found in config. "
            "Add it with `hv init` or update .hivemind.json."
        )

    try:
        linked_path = linked_path_for(cfg, project)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    # Normalize user-supplied references (--parent / --depends) to their
    # canonical hash-suffixed form so the stored frontmatter survives
    # short-form aliasing across machines.
    if parent_id:
        parent_id = _resolve_to_canonical_id(cfg, parent_id)
    depends = tuple(_resolve_to_canonical_id(cfg, d) for d in depends)

    # Validate parent hierarchy
    all_tasks = _load_all_tasks(cfg)
    _validate_parent_hierarchy(task_type, parent_id, all_tasks)

    prefix: str = proj_cfg.get("prefix", project.upper())
    legacy_counter = int(proj_cfg.get("counter", 0) or 0)
    task_id = next_task_id(
        linked_path,
        prefix,
        legacy_counter=legacy_counter,
    )
    today = date.today().isoformat()

    fm: dict[str, object] = {
        "id": task_id,
        "title": title,
        "status": "pending",
        "priority": priority,
        "type": task_type,
        "depends_on": list(depends),
        "created": today,
        "updated": today,
    }

    if parent_id:
        fm["parent"] = parent_id

    tasks_dir = task_dir(linked_path)
    active = active_dir(tasks_dir)
    active.mkdir(parents=True, exist_ok=True)
    task_path = active / f"{task_id}.md"
    create_task_file(task_path, fm, "")

    # Update task index
    rel_path = task_path.relative_to(tasks_dir).as_posix()
    _update_task_index_entry(tasks_dir, task_id, fm, path=rel_path)

    auto_commit(linked_path, f"task: create {task_id}")

    click.echo(f"Created task: {task_id}")
    click.echo(f"  Title: {title}")
    click.echo(f"  File:  {task_path}")


@task.command(name="list")
@click.option("--project", "-p", default=None, help="Filter by project.")
@click.option("--status", "-s", default=None, help="Filter by status.")
@click.option(
    "--priority",
    default=None,
    type=click.Choice(["high", "medium", "low"]),
    help="Filter by priority.",
)
@click.option(
    "--flat", "flat_mode", is_flag=True, default=False, help="Flat list output."
)
@click.option(
    "--all-projects",
    "all_projects",
    is_flag=True,
    default=False,
    help="Show tasks from all projects (default: auto-detect current project).",
)
@click.option(
    "--all-tasks",
    "all_tasks",
    is_flag=True,
    default=False,
    help="Include done/cancelled tasks (and epics whose work is finished).",
)
def list_cmd(
    project: str | None,
    status: str | None,
    priority: str | None,
    flat_mode: bool,
    all_projects: bool,
    all_tasks: bool,
) -> None:
    if status is not None:
        validate_status(status)

    cfg, _data_path = _find_config()

    if all_projects:
        scan_project = None
    elif project:
        scan_project = project
    else:
        detected = _find_project_by_cwd(cfg)
        if detected:
            scan_project = detected
        else:
            raise click.ClickException(
                "No project linked to current directory. "
                "Use --project/-p to specify, or --all-projects to show all."
            )

    tasks = _scan_tasks(cfg, scan_project)

    if status is not None:
        tasks = [t for t in tasks if t[0].get("status") == status]
    if priority is not None:
        tasks = [t for t in tasks if t[0].get("priority") == priority]

    if not all_tasks:
        tasks = [
            (fm, body, path)
            for fm, body, path in tasks
            if fm.get("status") not in _TERMINAL_STATUSES
        ]

    if not tasks:
        click.echo("No tasks found.")
        return

    if flat_mode:
        # Original flat table output
        header = (
            f"{'ID':<14} {'Title':<30} {'Status':<12} "
            f"{'Priority':<10} {'Type':<10}"
        )
        click.echo(header)
        click.echo("-" * len(header))

        for fm, _body, _path in tasks:
            tid = str(fm.get("id", ""))
            ttitle = str(fm.get("title", ""))
            tstatus = str(fm.get("status", ""))
            tpriority = str(fm.get("priority", ""))
            ttype = str(fm.get("type", ""))
            click.echo(
                f"{tid:<14} {ttitle:<30} {tstatus:<12} "
                f"{tpriority:<10} {ttype:<10}"
            )
    else:
        # Tree output
        all_fm = [fm for fm, _body, _path in tasks]
        tree = _build_tree(all_fm)

        output_lines: list[str] = []
        roots = tree.get(None, [])

        # Sort roots by priority desc, then id asc
        roots.sort(
            key=lambda t: (
                -PRIORITY_ORDER.get(str(t.get("priority", "medium")), 0),
                str(t.get("id", "")),
            )
        )

        for i, root_task in enumerate(roots):
            tid = str(root_task.get("id", ""))
            ttype = str(root_task.get("type", ""))
            ttitle = str(root_task.get("title", ""))
            tstatus = str(root_task.get("status", ""))
            tpriority = str(root_task.get("priority", ""))

            line = (
                f"{tid} [{ttype}]  {ttitle:<30} {tstatus:<10} {tpriority}"
            )
            output_lines.append(line)

            # Render children
            _render_tree(
                tree,
                tid,
                "",
                i == len(roots) - 1,
                output_lines,
            )

        for line in output_lines:
            click.echo(line)


@task.command()
@click.argument("task_id")
@click.option(
    "--format", "fmt", default="text", type=click.Choice(["text", "json"])
)
def get(task_id: str, fmt: str) -> None:
    """Get details for a specific task."""
    cfg, _data_path = _find_config()
    task_path = _find_task_file(cfg, task_id)
    fm, body = parse_task(task_path)

    # Load parent chain
    all_tasks = _load_all_tasks(cfg)
    parent_chain = _get_parent_chain(fm, all_tasks)

    if fmt == "json":
        output: dict[str, Any] = dict(fm)
        output["body"] = body
        if parent_chain:
            output["parent_chain"] = [
                {
                    "id": str(p.get("id", "")),
                    "type": str(p.get("type", "")),
                    "title": str(p.get("title", "")),
                }
                for p in parent_chain
            ]
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        # Show parent chain if present
        if parent_chain:
            chain_parts: list[str] = []
            for p in reversed(parent_chain):
                pid = str(p.get("id", ""))
                ptype = str(p.get("type", ""))
                ptitle = str(p.get("title", ""))
                chain_parts.append(f"{pid} [{ptype}] {ptitle}")
            click.echo("Parent chain:")
            for part in chain_parts:
                click.echo(f"  -> {part}")
            click.echo("")

        for key, value in fm.items():
            click.echo(f"{key}: {value}")
        if body:
            click.echo("")
            click.echo(body)


@task.command()
@click.argument("task_id")
@click.option("--status", "-s", default=None, help="New status.")
@click.option(
    "--priority",
    default=None,
    type=click.Choice(["high", "medium", "low"]),
)
@click.option("--title", "-t", default=None, help="New title.")
@click.option("--reason", default=None, help="Reason for blocking or status change.")
def update(
    task_id: str,
    status: str | None,
    priority: str | None,
    title: str | None,
    reason: str | None,
) -> None:
    """Update an existing task."""
    cfg, _data_path = _find_config()
    task_path, _project_name, tasks_dir, canonical_id = _find_task_with_project(
        cfg, task_id
    )
    linked_path = tasks_dir.parent.parent  # <linked>/hivemind/tasks -> <linked>

    updates: dict[str, object] = {}
    if status is not None:
        updates["status"] = status
    if priority is not None:
        updates["priority"] = priority
    if title is not None:
        updates["title"] = title
    if reason is not None:
        updates["blocked_reason"] = reason

    if not updates:
        click.echo("Nothing to update. Provide --status, --priority, --title, or --reason.")
        return

    updates["updated"] = date.today().isoformat()

    if status in _TERMINAL_STATUSES:
        updates["completed_at"] = datetime.now().isoformat()

    update_frontmatter(task_path, updates)

    fm_after, _body_after = parse_task(task_path)

    # Relocate the file when the status transition crosses the
    # active/done boundary (or restores an archived task).
    new_status = fm_after.get("status")
    task_path = _move_task_to_status_dir(task_path, tasks_dir, new_status)
    rel_path = task_path.relative_to(tasks_dir).as_posix()
    _update_task_index_entry(
        tasks_dir, canonical_id, fm_after, path=rel_path
    )

    auto_commit(linked_path, f"task: update {canonical_id}")

    click.echo(f"Updated task: {canonical_id}")
    for key, value in updates.items():
        click.echo(f"  {key}: {value}")

    # Auto-complete parents when this task reaches a terminal status.
    if status in _TERMINAL_STATUSES:
        fm = fm_after
        all_tasks = _load_all_tasks(cfg)

        # Update the in-memory copy so sibling check uses current state
        for t in all_tasks:
            if t.get("id") == canonical_id:
                t["status"] = status
                break

        _auto_complete_parents(cfg, fm, all_tasks)


def _write_task_body(path: Path, body: str) -> None:
    """Rewrite *path* preserving frontmatter and replacing the body."""
    import frontmatter

    post = frontmatter.load(str(path))
    post.content = body
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def _read_stdin_or_file(content_file: str | None) -> str:
    """Read body text from --content FILE or stdin."""
    if content_file is not None:
        return Path(content_file).read_text(encoding="utf-8")
    if sys.stdin.isatty():
        click.echo("Enter text (Ctrl+D to finish):", err=True)
    return sys.stdin.read()


def _bump_updated(task_path: Path, tasks_dir: Path, task_id: str) -> None:
    """Touch the ``updated`` frontmatter field and refresh the index entry.

    The ``task_id`` argument is accepted for backward compatibility but the
    index entry is always keyed by the file's stem (the canonical full ID),
    so legacy short-form callers don't pollute the index.
    """
    update_frontmatter(task_path, {"updated": date.today().isoformat()})
    fm_after, _body = parse_task(task_path)
    _update_task_index_entry(tasks_dir, task_path.stem, fm_after)


@task.command(name="body-set")
@click.argument("task_id")
@click.option(
    "--content",
    "-c",
    "content_file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="File with body text (reads from stdin if omitted).",
)
def body_set_cmd(task_id: str, content_file: str | None) -> None:
    """Replace the body of a task from stdin (or --content FILE)."""
    cfg, _ = _find_config()
    task_path, _proj, tasks_dir, canonical_id = _find_task_with_project(cfg, task_id)
    body = _read_stdin_or_file(content_file)
    _write_task_body(task_path, body)
    _bump_updated(task_path, tasks_dir, canonical_id)
    linked_path = tasks_dir.parent.parent
    auto_commit(linked_path, f"task: body-set {canonical_id}")
    click.echo(f"Wrote: {task_path}")


@task.command(name="body-append")
@click.argument("task_id")
@click.option(
    "--content",
    "-c",
    "content_file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="File with body text (reads from stdin if omitted).",
)
def body_append_cmd(task_id: str, content_file: str | None) -> None:
    """Append to the body of a task from stdin (or --content FILE)."""
    cfg, _ = _find_config()
    task_path, _proj, tasks_dir, canonical_id = _find_task_with_project(cfg, task_id)
    addition = _read_stdin_or_file(content_file)
    _fm, body = parse_task(task_path)
    if body and not body.endswith("\n"):
        body += "\n"
    new_body = body + addition
    _write_task_body(task_path, new_body)
    _bump_updated(task_path, tasks_dir, canonical_id)
    linked_path = tasks_dir.parent.parent
    auto_commit(linked_path, f"task: body-append {canonical_id}")
    click.echo(f"Wrote: {task_path}")


_CRITERIA_HEADER = "## Completion Criteria"


def _split_criteria(body: str) -> tuple[str, list[str], str]:
    """Split *body* into (head, criteria_lines, tail).

    The criteria section starts at ``## Completion Criteria`` and ends at the
    next ``## `` heading (or EOF). Each remaining `- [ ]`/`- [x]` line is one
    criterion. When the header is absent, returns (body, [], "").
    """
    lines = body.splitlines(keepends=False)
    start: int | None = None
    end: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == _CRITERIA_HEADER:
            start = i
            continue
        if start is not None and line.startswith("## ") and i > start:
            end = i
            break
    if start is None:
        return body, [], ""

    if end is None:
        end = len(lines)

    section_lines = lines[start + 1 : end]
    criteria = [
        line for line in section_lines
        if line.lstrip().startswith(("- [", "* ["))
    ]
    head = "\n".join(lines[: start + 1]) + "\n"
    tail_lines = lines[end:]
    tail = ("\n" + "\n".join(tail_lines)) if tail_lines else ""
    return head, criteria, tail


def _render_criteria(head: str, criteria: list[str], tail: str) -> str:
    body = head + ("\n".join(criteria) + ("\n" if criteria else ""))
    if tail:
        body = body.rstrip("\n") + "\n" + tail.lstrip("\n")
    return body


@task.command(name="criteria-add")
@click.argument("task_id")
@click.argument("text")
def criteria_add_cmd(task_id: str, text: str) -> None:
    """Append a ``- [ ] <text>`` line to ``## Completion Criteria``.

    Adds the section if it doesn't already exist.
    """
    cfg, _ = _find_config()
    task_path, _proj, tasks_dir, canonical_id = _find_task_with_project(cfg, task_id)
    _fm, body = parse_task(task_path)
    text = text.strip()
    if not text:
        raise click.ClickException("Empty criterion text.")

    head, criteria, tail = _split_criteria(body)
    line = f"- [ ] {text}"
    if head == body and not criteria and not tail:
        # No criteria section yet — append one.
        if body and not body.endswith("\n"):
            body += "\n"
        new_body = body + f"\n{_CRITERIA_HEADER}\n{line}\n"
    else:
        criteria.append(line)
        new_body = _render_criteria(head, criteria, tail)

    _write_task_body(task_path, new_body)
    _bump_updated(task_path, tasks_dir, canonical_id)
    linked_path = tasks_dir.parent.parent
    auto_commit(linked_path, f"task: criteria-add {canonical_id}")
    click.echo(f"Added: {line}")


@task.command(name="criteria-check")
@click.argument("task_id")
@click.argument("index", type=int)
def criteria_check_cmd(task_id: str, index: int) -> None:
    """Toggle ``- [ ]`` <-> ``- [x]`` at the 1-based *index*."""
    cfg, _ = _find_config()
    task_path, _proj, tasks_dir, canonical_id = _find_task_with_project(cfg, task_id)
    _fm, body = parse_task(task_path)
    head, criteria, tail = _split_criteria(body)
    if not criteria:
        raise click.ClickException("Task has no completion criteria.")
    if index < 1 or index > len(criteria):
        raise click.ClickException(
            f"Criterion index {index} out of range (1..{len(criteria)})."
        )

    line = criteria[index - 1]
    if "- [ ]" in line:
        criteria[index - 1] = line.replace("- [ ]", "- [x]", 1)
    elif "- [x]" in line:
        criteria[index - 1] = line.replace("- [x]", "- [ ]", 1)
    else:
        raise click.ClickException(
            f"Criterion line is not a checkbox: {line!r}"
        )

    new_body = _render_criteria(head, criteria, tail)
    _write_task_body(task_path, new_body)
    _bump_updated(task_path, tasks_dir, canonical_id)
    linked_path = tasks_dir.parent.parent
    auto_commit(linked_path, f"task: criteria-check {canonical_id}")
    click.echo(f"Toggled: {criteria[index - 1]}")


@task.command(name="next")
@click.option("--project", "-p", default=None, help="Filter by project.")
def next_cmd(project: str | None) -> None:
    """Get the next task to work on (leaf tasks only)."""
    cfg, _data_path = _find_config()
    all_tasks = _scan_tasks(cfg, project)

    # Build status lookup: id -> status
    status_map: dict[str, str] = {}
    for fm, _body, _path in all_tasks:
        tid = fm.get("id")
        st = fm.get("status")
        if isinstance(tid, str) and isinstance(st, str):
            status_map[tid] = st

    # Filter to pending leaf tasks whose dependencies are all done
    candidates: list[tuple[dict[str, object], str, Path]] = []
    for fm, body, path in all_tasks:
        if fm.get("status") != "pending":
            continue

        # Only leaf types (task, bug, chore)
        task_type = _effective_type(str(fm.get("type", "")))
        if task_type not in _LEAF_TYPES:
            continue

        # Check depends_on
        deps = fm.get("depends_on")
        if isinstance(deps, list) and deps:
            all_done = all(status_map.get(str(d)) == "done" for d in deps)
            if not all_done:
                continue

        # Skip tasks whose parent is already in a terminal state (done or
        # cancelled) — no point recommending work under a closed-out story
        # or epic.
        parent_id = fm.get("parent")
        if parent_id and isinstance(parent_id, str):
            parent_status = status_map.get(parent_id)
            if parent_status in _TERMINAL_STATUSES:
                continue

        candidates.append((fm, body, path))

    if not candidates:
        click.echo("No actionable tasks found.")
        return

    # Sort by priority (high > medium > low) then by created (oldest first)
    def sort_key(
        item: tuple[dict[str, object], str, Path],
    ) -> tuple[int, str]:
        fm = item[0]
        p = str(fm.get("priority", "medium"))
        priority_val = PRIORITY_ORDER.get(p, 0)
        created = str(fm.get("created", ""))
        return (-priority_val, created)

    candidates.sort(key=sort_key)

    # Return top 1
    fm, body, path = candidates[0]
    click.echo(f"Next task: {fm.get('id')}")
    click.echo(f"  Title:    {fm.get('title')}")
    click.echo(f"  Priority: {fm.get('priority')}")
    click.echo(f"  Created:  {fm.get('created')}")


def _parse_age_spec(spec: str) -> timedelta:
    """Parse an age spec like ``'14d'``, ``'24h'``, or a bare integer (days).

    Raises :class:`ValueError` on bad input; the CLI wraps it into a
    user-facing :class:`click.ClickException`.
    """
    s = spec.strip().lower()
    if not s:
        raise ValueError("empty age spec")
    if s.endswith("d"):
        return timedelta(days=int(s[:-1]))
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    return timedelta(days=int(s))


def _bucket_dt_for(fm: dict[str, object], fallback: datetime) -> datetime:
    """Pick the datetime that decides which archive/{YYYY-MM}/ bucket a task lands in.

    Prefers ``completed_at`` (set when status reaches a terminal state),
    falls back to ``updated`` (set on every mutation), then to *fallback*
    (caller-supplied "now") when neither is parseable.
    """
    for key in ("completed_at", "updated"):
        raw = fm.get(key)
        if isinstance(raw, str) and raw:
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                continue
    return fallback


@task.command()
@click.option("--project", "-p", default=None, help="Limit to one project.")
@click.option(
    "--older-than",
    "older_than",
    default="14d",
    show_default=True,
    help="Age threshold: '14d', '24h', or a bare integer (days).",
)
@click.option(
    "--all",
    "archive_all",
    is_flag=True,
    default=False,
    help="Archive every done task regardless of age (overrides --older-than).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be moved without touching the filesystem.",
)
def archive(
    project: str | None,
    older_than: str,
    archive_all: bool,
    dry_run: bool,
) -> None:
    """Move long-finished tasks from ``done/`` to ``archive/{YYYY-MM}/``.

    Uses ``completed_at`` (or ``updated``) to decide both the age cutoff
    and which monthly bucket a task lands in. Tasks without a parseable
    timestamp fall back to file mtime for the age check and to "now" for
    the bucket.
    """
    cfg, _data_path = _find_config()
    try:
        cutoff_delta = _parse_age_spec(older_than)
    except (ValueError, TypeError) as exc:
        raise click.ClickException(f"Invalid --older-than {older_than!r}: {exc}")
    now = datetime.now()

    total_moved = 0
    total_skipped = 0
    for proj_name, tasks_dir in _iter_project_task_dirs(cfg, project):
        done = done_dir(tasks_dir)
        if not done.is_dir():
            continue
        moved_in_proj = 0
        for md_file in sorted(done.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                fm, _body = parse_task(md_file)
            except Exception:
                total_skipped += 1
                continue

            if not archive_all:
                bucket_for_age = _bucket_dt_for(
                    fm, datetime.fromtimestamp(md_file.stat().st_mtime)
                )
                if (now - bucket_for_age) < cutoff_delta:
                    total_skipped += 1
                    continue

            bucket = _bucket_dt_for(fm, now)
            yyyy_mm = bucket.strftime("%Y-%m")
            target_dir = archive_dir(tasks_dir, yyyy_mm)
            target = target_dir / md_file.name
            rel = target.relative_to(tasks_dir).as_posix()

            if dry_run:
                click.echo(
                    f"[dry-run] {proj_name}: "
                    f"{md_file.relative_to(tasks_dir).as_posix()} -> {rel}"
                )
                total_moved += 1
                continue

            target_dir.mkdir(parents=True, exist_ok=True)
            md_file.rename(target)
            task_id = fm.get("id")
            if isinstance(task_id, str) and task_id:
                _update_task_index_entry(tasks_dir, task_id, fm, path=rel)
            click.echo(f"Archived: {task_id} -> {rel}")
            total_moved += 1
            moved_in_proj += 1

        if not dry_run and moved_in_proj > 0:
            linked_path = tasks_dir.parent.parent
            auto_commit(
                linked_path, f"task: archive {proj_name} ({moved_in_proj})"
            )

    click.echo(
        f"Total: {total_moved} archived, {total_skipped} skipped"
        + (" (dry-run)" if dry_run else "")
    )
