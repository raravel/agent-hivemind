"""Implementation of `hv projects` -- list configured projects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from hivemind.commands.task import _find_config
from hivemind.core.config import HivemindConfig
from hivemind.core.paths import resolve_link_file, task_dir


def _count_tasks(linked_path: Path) -> int | None:
    """Count task files under ``<linked>/hivemind/tasks/``.

    Returns None when the tasks directory does not exist (e.g., a project
    that was registered but never had any task created yet).
    """
    tdir = task_dir(linked_path)
    if not tdir.is_dir():
        return None
    return sum(
        1
        for entry in tdir.iterdir()
        if entry.is_file()
        and entry.suffix == ".md"
        and not entry.name.startswith("_")
    )


def _status_for(linked_path: Path) -> str:
    """Resolve a project's link status from disk state."""
    if not linked_path.exists():
        return "missing"
    if resolve_link_file(linked_path) is None:
        return "unlinked"
    return "linked"


def _collect_rows(cfg: HivemindConfig) -> list[dict[str, Any]]:
    projects = cfg.raw.get("projects", {})
    rows: list[dict[str, Any]] = []
    if not isinstance(projects, dict):
        return rows
    for name in sorted(projects):
        proj = projects.get(name)
        if not isinstance(proj, dict):
            continue
        prefix = str(proj.get("prefix") or "-")
        linked_raw = proj.get("linked_path")
        if not isinstance(linked_raw, str) or not linked_raw:
            rows.append(
                {
                    "name": name,
                    "prefix": prefix,
                    "linked_path": None,
                    "status": "no-linked-path",
                    "tasks": None,
                }
            )
            continue
        linked = Path(linked_raw).expanduser()
        status = _status_for(linked)
        tasks = _count_tasks(linked) if status == "linked" else None
        rows.append(
            {
                "name": name,
                "prefix": prefix,
                "linked_path": str(linked),
                "status": status,
                "tasks": tasks,
            }
        )
    return rows


_HEADERS = ("NAME", "PREFIX", "LINKED", "STATUS", "TASKS")


def _format_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No projects configured. Run `hv link` to register one."
    matrix = [
        (
            r["name"],
            r["prefix"],
            r["linked_path"] or "(missing linked_path)",
            r["status"],
            "-" if r["tasks"] is None else str(r["tasks"]),
        )
        for r in rows
    ]
    cols = list(zip(*([_HEADERS, *matrix])))
    widths = [max(len(s) for s in col) for col in cols]
    lines = ["  ".join(h.ljust(w) for h, w in zip(_HEADERS, widths))]
    for row in matrix:
        lines.append("  ".join(v.ljust(w) for v, w in zip(row, widths)))
    return "\n".join(lines)


@click.command("projects")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def projects_cmd(as_json: bool) -> None:
    """List configured projects with their link status and task counts."""
    cfg, _ = _find_config()
    rows = _collect_rows(cfg)
    if as_json:
        click.echo(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    click.echo(_format_table(rows))
