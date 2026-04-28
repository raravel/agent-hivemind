"""Implementation of `hv task` command group."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import click

from hivemind.core.config import HivemindConfig
from hivemind.core.git import auto_commit
from hivemind.core.parser import (
    create_task_file,
    parse_task,
    update_frontmatter,
    validate_status,
)

_log = logging.getLogger(__name__)

PRIORITY_ORDER: dict[str, int] = {"high": 3, "medium": 2, "low": 1}

# Types that behave like "story" for hierarchy purposes
_STORY_TYPES: frozenset[str] = frozenset({"story", "feature"})

# Leaf types that can be assigned as actual work items
_LEAF_TYPES: frozenset[str] = frozenset({"task", "bug", "chore"})

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
_INDEX_VERSION: int = 1

# Frontmatter keys stored in the index
_INDEX_FIELDS: list[str] = [
    "status",
    "priority",
    "type",
    "parent",
    "depends_on",
    "title",
    "updated",
    "completed_at",
]


def _index_path(data_path: Path, project: str) -> Path:
    """Return the path to a project's task index file."""
    return data_path / "tasks" / project / "_index.json"


def _load_task_index(
    data_path: Path, project: str
) -> dict[str, Any] | None:
    """Load ``_index.json`` for *project*.

    Returns the parsed dict or ``None`` if the file is missing, corrupt,
    or has an incompatible version.
    """
    path = _index_path(data_path, project)
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


def _save_task_index(
    data_path: Path, project: str, index_data: dict[str, Any]
) -> None:
    """Write *index_data* to ``_index.json``."""
    path = _index_path(data_path, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(index_data, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _fm_to_index_entry(fm: dict[str, object]) -> dict[str, object]:
    """Extract the subset of frontmatter fields stored in the index."""
    entry: dict[str, object] = {}
    for key in _INDEX_FIELDS:
        value = fm.get(key)
        # Normalise None / missing to a sensible default
        if key == "depends_on":
            entry[key] = list(value) if isinstance(value, list) else []
        elif key == "parent":
            entry[key] = str(value) if value else None
        else:
            entry[key] = value
    return entry


def _rebuild_task_index(
    data_path: Path, project: str
) -> dict[str, Any]:
    """Scan all ``.md`` files for *project* and build a fresh index."""
    project_dir = data_path / "tasks" / project
    tasks: dict[str, dict[str, object]] = {}

    if project_dir.exists():
        for md_file in sorted(project_dir.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                fm, _body = parse_task(md_file)
                task_id = fm.get("id")
                if isinstance(task_id, str):
                    tasks[task_id] = _fm_to_index_entry(fm)
            except Exception:
                continue

    index_data: dict[str, Any] = {
        "version": _INDEX_VERSION,
        "tasks": tasks,
    }
    _save_task_index(data_path, project, index_data)
    return index_data


def _update_task_index_entry(
    data_path: Path,
    project: str,
    task_id: str,
    fm_dict: dict[str, object],
) -> None:
    """Update a single entry in the index, creating the index if needed."""
    index_data = _load_task_index(data_path, project)
    if index_data is None:
        index_data = _rebuild_task_index(data_path, project)
        return  # rebuild already includes the new/updated entry

    index_data["tasks"][task_id] = _fm_to_index_entry(fm_dict)
    _save_task_index(data_path, project, index_data)


def _find_config() -> tuple[HivemindConfig, Path]:
    """Locate .hivemind.json and return (config, data_path)."""
    candidates = [
        Path.cwd() / ".hivemind.json",
        Path("~/.hivemind.json").expanduser(),
        Path("~/agent-hivemind-data/.hivemind.json").expanduser(),
    ]
    for p in candidates:
        if p.exists():
            cfg = HivemindConfig.load(p)
            return cfg, cfg.data_path
    raise click.ClickException(
        "No .hivemind.json found. Run `hv init` first."
    )


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
                    return name
            except Exception:
                continue
    return None


def _find_task_file(data_path: Path, task_id: str) -> Path:
    """Find a task markdown file by its ID across all project dirs."""
    tasks_root = data_path / "tasks"
    if not tasks_root.exists():
        raise click.ClickException(f"Tasks directory not found: {tasks_root}")

    for project_dir in tasks_root.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{task_id}.md"
        if candidate.exists():
            return candidate

    raise click.ClickException(f"Task not found: {task_id}")


def _scan_tasks_from_index(
    data_path: Path,
    project: str,
) -> list[tuple[dict[str, object], str, Path]] | None:
    """Try to build the scan result from the index for one project.

    Returns ``None`` if the index is unavailable and a full scan is needed.
    Body is always ``""`` because the index does not store bodies.
    """
    index_data = _load_task_index(data_path, project)
    if index_data is None:
        return None

    tasks_dir = data_path / "tasks" / project
    results: list[tuple[dict[str, object], str, Path]] = []
    for task_id, entry in index_data["tasks"].items():
        fm: dict[str, object] = {"id": task_id, **entry}
        path = tasks_dir / f"{task_id}.md"
        results.append((fm, "", path))
    return results


def _scan_tasks_glob(
    data_path: Path,
    dirs: list[Path],
) -> list[tuple[dict[str, object], str, Path]]:
    """Original glob+parse fallback for scanning task files."""
    results: list[tuple[dict[str, object], str, Path]] = []
    for d in dirs:
        if not d.exists():
            continue
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
    data_path: Path,
    project: str | None = None,
) -> list[tuple[dict[str, object], str, Path]]:
    """Scan task files and return list of (frontmatter, body, path).

    Reads from ``_index.json`` when available for better performance.
    Falls back to glob+parse and rebuilds the index on a miss.
    """
    tasks_root = data_path / "tasks"
    if not tasks_root.exists():
        return []

    if project:
        dirs = [tasks_root / project]
    else:
        dirs = [d for d in tasks_root.iterdir() if d.is_dir()]

    results: list[tuple[dict[str, object], str, Path]] = []

    for d in dirs:
        if not d.exists():
            continue
        proj_name = d.name
        indexed = _scan_tasks_from_index(data_path, proj_name)
        if indexed is not None:
            results.extend(indexed)
        else:
            # Fallback: glob+parse, then rebuild index for next time
            scanned = _scan_tasks_glob(data_path, [d])
            results.extend(scanned)
            _rebuild_task_index(data_path, proj_name)

    return results


# ---------------------------------------------------------------------------
# Helpers for hierarchical tasks
# ---------------------------------------------------------------------------


def _load_all_tasks(
    data_path: Path, project: str | None = None
) -> list[dict[str, object]]:
    """Load all tasks as a flat list of frontmatter dicts."""
    scanned = _scan_tasks(data_path, project)
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
    data_path: Path,
    task_fm: dict[str, object],
    all_tasks: list[dict[str, object]],
) -> None:
    """Walk up the hierarchy and auto-complete parents when appropriate.

    When all children of a parent are ``done``, mark the parent ``done``
    and recurse upward.
    """
    parent_id = task_fm.get("parent")
    if not parent_id or not isinstance(parent_id, str):
        return

    # Build id -> fm lookup
    by_id: dict[str, dict[str, object]] = {}
    for t in all_tasks:
        tid = t.get("id")
        if isinstance(tid, str):
            by_id[tid] = t

    parent_fm = by_id.get(parent_id)
    if parent_fm is None:
        return

    # Already done? Nothing to do.
    if parent_fm.get("status") == "done":
        return

    # Check if all sibling tasks (children of same parent) are done.
    siblings = [t for t in all_tasks if str(t.get("parent", "")) == parent_id]
    if not siblings:
        return

    all_done = all(t.get("status") == "done" for t in siblings)
    if not all_done:
        return

    # Auto-complete the parent
    parent_path = _find_task_file(data_path, parent_id)
    today = date.today().isoformat()
    now_iso = datetime.now().isoformat()
    update_frontmatter(
        parent_path,
        {"status": "done", "updated": today, "completed_at": now_iso},
    )

    # Update task index for the auto-completed parent
    project_name = parent_path.parent.name
    parent_fm_fresh, _ = parse_task(parent_path)
    _update_task_index_entry(data_path, project_name, parent_id, parent_fm_fresh)

    parent_type = str(parent_fm.get("type", ""))
    click.echo(f"Auto-completed: {parent_id} [{parent_type}]")

    # Update the in-memory record so recursive check works
    parent_fm["status"] = "done"

    # Recurse: if the parent itself has a parent, check that too
    _auto_complete_parents(data_path, parent_fm, all_tasks)


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
    cfg, data_path = _find_config()

    proj_cfg = cfg.get_project(project)
    if proj_cfg is None:
        raise click.ClickException(
            f"Project '{project}' not found in config. "
            "Add it with `hv init` or update .hivemind.json."
        )

    # Validate parent hierarchy
    all_tasks = _load_all_tasks(data_path)
    _validate_parent_hierarchy(task_type, parent_id, all_tasks)

    prefix: str = proj_cfg.get("prefix", project.upper())
    counter: int = proj_cfg.get("counter", 0)
    counter += 1

    task_id = f"{prefix}-{counter:03d}"
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

    task_path = data_path / "tasks" / project / f"{task_id}.md"
    create_task_file(task_path, fm, "")

    # Update task index
    _update_task_index_entry(data_path, project, task_id, fm)

    # Update counter in config
    cfg.set(f"projects.{project}.counter", counter)
    cfg.save()

    auto_commit(data_path, f"task: create {task_id}")

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
    help="Include completed tasks older than 3 days.",
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

    cfg, data_path = _find_config()

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

    tasks = _scan_tasks(data_path, scan_project)

    if status is not None:
        tasks = [t for t in tasks if t[0].get("status") == status]
    if priority is not None:
        tasks = [t for t in tasks if t[0].get("priority") == priority]

    if not all_tasks:
        cutoff = datetime.now() - timedelta(days=3)
        filtered: list[tuple[dict[str, object], str, Path]] = []
        for fm, body, path in tasks:
            if fm.get("status") != "done":
                filtered.append((fm, body, path))
                continue
            completed_at = fm.get("completed_at")
            if completed_at:
                try:
                    completed_dt = datetime.fromisoformat(str(completed_at))
                    if completed_dt >= cutoff:
                        filtered.append((fm, body, path))
                except ValueError:
                    filtered.append((fm, body, path))
            else:
                filtered.append((fm, body, path))
        tasks = filtered

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
    _cfg, data_path = _find_config()
    task_path = _find_task_file(data_path, task_id)
    fm, body = parse_task(task_path)

    # Load parent chain
    all_tasks = _load_all_tasks(data_path)
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
    _cfg, data_path = _find_config()
    task_path = _find_task_file(data_path, task_id)

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

    if status == "done":
        updates["completed_at"] = datetime.now().isoformat()

    update_frontmatter(task_path, updates)

    # Update task index — the project name is the parent directory name
    project_name = task_path.parent.name
    fm_after, _body_after = parse_task(task_path)
    _update_task_index_entry(data_path, project_name, task_id, fm_after)

    auto_commit(data_path, f"task: update {task_id}")

    click.echo(f"Updated task: {task_id}")
    for key, value in updates.items():
        click.echo(f"  {key}: {value}")

    # Auto-complete parents if status changed to "done"
    if status == "done":
        fm = fm_after
        all_tasks = _load_all_tasks(data_path)

        # Update the in-memory copy so sibling check uses current state
        for t in all_tasks:
            if t.get("id") == task_id:
                t["status"] = "done"
                break

        _auto_complete_parents(data_path, fm, all_tasks)


@task.command(name="next")
@click.option("--project", "-p", default=None, help="Filter by project.")
def next_cmd(project: str | None) -> None:
    """Get the next task to work on (leaf tasks only)."""
    _cfg, data_path = _find_config()
    all_tasks = _scan_tasks(data_path, project)

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

        # Check that parent (if any) is not done (shouldn't work on tasks
        # under a completed parent).  Also ensure parent is not blocked.
        parent_id = fm.get("parent")
        if parent_id and isinstance(parent_id, str):
            parent_status = status_map.get(parent_id)
            if parent_status == "done":
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
