"""Implementation of `hv run` command — fetch task content for execution."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from hivemind.commands.task import (
    PRIORITY_ORDER,
    _LEAF_TYPES,
    _find_config,
    _find_task_file,
    _scan_tasks,
    _effective_type,
)
from hivemind.core.parser import parse_task


def _find_in_progress(
    data_path: Path,
    project: str | None,
) -> tuple[dict[str, object], str, Path] | None:
    """Find the first in_progress task, or None."""
    tasks = _scan_tasks(data_path, project)
    for fm, body, path in tasks:
        if fm.get("status") == "in_progress":
            return fm, body, path
    return None


def _find_ready_tasks(
    data_path: Path,
    project: str | None,
    leaf_only: bool = True,
) -> list[tuple[dict[str, object], str, Path]]:
    """Return all pending tasks with resolved deps, sorted by priority+age."""
    all_tasks = _scan_tasks(data_path, project)

    status_map: dict[str, str] = {}
    for fm, _body, _path in all_tasks:
        tid = fm.get("id")
        st = fm.get("status")
        if isinstance(tid, str) and isinstance(st, str):
            status_map[tid] = st

    candidates: list[tuple[dict[str, object], str, Path]] = []
    for fm, body, path in all_tasks:
        if fm.get("status") != "pending":
            continue

        if leaf_only:
            ttype = _effective_type(str(fm.get("type", "")))
            if ttype not in _LEAF_TYPES:
                continue

        deps = fm.get("depends_on")
        if isinstance(deps, list) and deps:
            all_done = all(status_map.get(str(d)) == "done" for d in deps)
            if not all_done:
                continue

        parent_id = fm.get("parent")
        if parent_id and isinstance(parent_id, str):
            if status_map.get(parent_id) == "done":
                continue

        candidates.append((fm, body, path))

    def sort_key(item: tuple[dict[str, object], str, Path]) -> tuple[int, str]:
        fm = item[0]
        p = str(fm.get("priority", "medium"))
        priority_val = PRIORITY_ORDER.get(p, 0)
        created = str(fm.get("created", ""))
        return (-priority_val, created)

    candidates.sort(key=sort_key)
    return candidates


def _find_next_pending(
    data_path: Path,
    project: str | None,
) -> tuple[dict[str, object], str, Path] | None:
    """Find the next pending task with resolved deps, sorted by priority."""
    ready = _find_ready_tasks(data_path, project, leaf_only=False)
    return ready[0] if ready else None


def _output_task(
    fm: dict[str, object],
    body: str,
    path: Path,
    fmt: str,
) -> None:
    """Output the task in the requested format."""
    if fmt == "json":
        output: dict[str, object] = {
            "id": fm.get("id", ""),
            "frontmatter": fm,
            "body": body,
            "path": str(path),
        }
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        # Default: YAML frontmatter block, then body
        click.echo("---")
        for key, value in fm.items():
            click.echo(f"{key}: {value}")
        click.echo("---")
        if body:
            click.echo("")
            click.echo(body)


def _output_tasks_array(
    items: list[tuple[dict[str, object], str, Path]],
    fmt: str,
) -> None:
    """Output multiple ready tasks. JSON-only mode prints a JSON array."""
    if fmt == "json":
        payload = [
            {
                "id": fm.get("id", ""),
                "frontmatter": fm,
                "body": body,
                "path": str(path),
            }
            for fm, body, path in items
        ]
        click.echo(json.dumps(payload, indent=2, default=str))
    else:
        for i, (fm, _body, _path) in enumerate(items):
            if i > 0:
                click.echo("")
                click.echo("---")
            click.echo(f"{fm.get('id', '')}  [{fm.get('type', '')}]  {fm.get('title', '')}")


@click.command()
@click.option("--project", "-p", default=None, help="Project name.")
@click.option("--task", "-t", "task_id", default=None, help="Task ID.")
@click.option(
    "--ready-only",
    "ready_only",
    is_flag=True,
    default=False,
    help="Return all ready tasks (for --parallel orchestration), not just the next one.",
)
@click.option(
    "--limit",
    "limit",
    type=int,
    default=None,
    help="With --ready-only, cap the number of tasks returned.",
)
@click.option(
    "--format",
    "fmt",
    default="text",
    type=click.Choice(["text", "json"]),
    help="Output format.",
)
def run(
    project: Optional[str],
    task_id: Optional[str],
    ready_only: bool,
    limit: Optional[int],
    fmt: str,
) -> None:
    """Fetch task content for the run-task pipeline."""
    _cfg, data_path = _find_config()

    if task_id is not None:
        task_path = _find_task_file(data_path, task_id)
        fm, body = parse_task(task_path)
        _output_task(fm, body, task_path, fmt)
        return

    if ready_only:
        ready = _find_ready_tasks(data_path, project, leaf_only=True)
        if limit is not None and limit > 0:
            ready = ready[:limit]
        if not ready:
            if fmt == "json":
                click.echo("[]")
            else:
                click.echo("No ready tasks available")
            sys.exit(1)
        _output_tasks_array(ready, fmt)
        return

    # Auto-detect: first look for in_progress
    result = _find_in_progress(data_path, project)
    if result is not None:
        fm, body, path = result
        _output_task(fm, body, path, fmt)
        return

    # Fallback to next pending
    result = _find_next_pending(data_path, project)
    if result is not None:
        fm, body, path = result
        _output_task(fm, body, path, fmt)
        return

    click.echo("No tasks available")
    sys.exit(1)
