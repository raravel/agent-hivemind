"""Implementation of `hv task` command group."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import click

from hivemind.core.config import HivemindConfig
from hivemind.core.git import auto_commit
from hivemind.core.parser import create_task_file, parse_task, update_frontmatter, validate_status

PRIORITY_ORDER: dict[str, int] = {"high": 3, "medium": 2, "low": 1}


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


def _scan_tasks(
    data_path: Path,
    project: str | None = None,
) -> list[tuple[dict[str, object], str, Path]]:
    """Scan task files and return list of (frontmatter, body, path)."""
    tasks_root = data_path / "tasks"
    if not tasks_root.exists():
        return []

    results: list[tuple[dict[str, object], str, Path]] = []

    if project:
        dirs = [tasks_root / project]
    else:
        dirs = [d for d in tasks_root.iterdir() if d.is_dir()]

    for d in dirs:
        if not d.exists():
            continue
        for md_file in sorted(d.glob("*.md")):
            try:
                fm, body = parse_task(md_file)
                results.append((fm, body, md_file))
            except Exception:
                continue

    return results


@click.group()
def task() -> None:
    """Manage tasks."""


@task.command()
@click.option("--project", "-p", required=True, help="Project name.")
@click.option("--title", "-t", required=True, help="Task title.")
@click.option("--type", "task_type", default="task", help="Task type (default: task).")
@click.option(
    "--priority",
    default="medium",
    type=click.Choice(["high", "medium", "low"]),
    help="Priority (default: medium).",
)
@click.option("--depends", multiple=True, help="Task ID this depends on.")
def create(
    project: str,
    title: str,
    task_type: str,
    priority: str,
    depends: tuple[str, ...],
) -> None:
    """Create a new task."""
    cfg, data_path = _find_config()

    proj_cfg = cfg.get_project(project)
    if proj_cfg is None:
        raise click.ClickException(
            f"Project '{project}' not found in config. "
            "Add it with `hv init` or update .hivemind.json."
        )

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

    task_path = data_path / "tasks" / project / f"{task_id}.md"
    create_task_file(task_path, fm, "")

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
def list_cmd(
    project: str | None, status: str | None, priority: str | None
) -> None:
    """List tasks."""
    if status is not None:
        validate_status(status)

    _cfg, data_path = _find_config()
    tasks = _scan_tasks(data_path, project)

    # Apply filters
    if status is not None:
        tasks = [t for t in tasks if t[0].get("status") == status]
    if priority is not None:
        tasks = [t for t in tasks if t[0].get("priority") == priority]

    if not tasks:
        click.echo("No tasks found.")
        return

    # Print table header
    header = f"{'ID':<14} {'Title':<30} {'Status':<12} {'Priority':<10} {'Type':<10}"
    click.echo(header)
    click.echo("-" * len(header))

    for fm, _body, _path in tasks:
        tid = str(fm.get("id", ""))
        ttitle = str(fm.get("title", ""))
        tstatus = str(fm.get("status", ""))
        tpriority = str(fm.get("priority", ""))
        ttype = str(fm.get("type", ""))
        click.echo(
            f"{tid:<14} {ttitle:<30} {tstatus:<12} {tpriority:<10} {ttype:<10}"
        )


@task.command()
@click.argument("task_id")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def get(task_id: str, fmt: str) -> None:
    """Get details for a specific task."""
    _cfg, data_path = _find_config()
    task_path = _find_task_file(data_path, task_id)
    fm, body = parse_task(task_path)

    if fmt == "json":
        output: dict[str, Any] = dict(fm)
        output["body"] = body
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        for key, value in fm.items():
            click.echo(f"{key}: {value}")
        if body:
            click.echo("")
            click.echo(body)


@task.command()
@click.argument("task_id")
@click.option("--status", "-s", default=None, help="New status.")
@click.option("--priority", default=None, type=click.Choice(["high", "medium", "low"]))
@click.option("--title", "-t", default=None, help="New title.")
def update(
    task_id: str,
    status: str | None,
    priority: str | None,
    title: str | None,
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

    if not updates:
        click.echo("Nothing to update. Provide --status, --priority, or --title.")
        return

    updates["updated"] = date.today().isoformat()
    update_frontmatter(task_path, updates)

    auto_commit(data_path, f"task: update {task_id}")

    click.echo(f"Updated task: {task_id}")
    for key, value in updates.items():
        click.echo(f"  {key}: {value}")


@task.command(name="next")
@click.option("--project", "-p", default=None, help="Filter by project.")
def next_cmd(project: str | None) -> None:
    """Get the next task to work on."""
    _cfg, data_path = _find_config()
    all_tasks = _scan_tasks(data_path, project)

    # Build status lookup: id -> status
    status_map: dict[str, str] = {}
    for fm, _body, _path in all_tasks:
        tid = fm.get("id")
        st = fm.get("status")
        if isinstance(tid, str) and isinstance(st, str):
            status_map[tid] = st

    # Filter to pending tasks whose dependencies are all done
    candidates: list[tuple[dict[str, object], str, Path]] = []
    for fm, body, path in all_tasks:
        if fm.get("status") != "pending":
            continue

        deps = fm.get("depends_on")
        if isinstance(deps, list) and deps:
            all_done = all(status_map.get(str(d)) == "done" for d in deps)
            if not all_done:
                continue

        candidates.append((fm, body, path))

    if not candidates:
        click.echo("No actionable tasks found.")
        return

    # Sort by priority (high > medium > low) then by created (oldest first)
    def sort_key(item: tuple[dict[str, object], str, Path]) -> tuple[int, str]:
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
