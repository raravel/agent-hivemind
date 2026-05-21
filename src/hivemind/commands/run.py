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
    _effective_type,
    _find_config,
    _find_project_by_cwd,
    _find_task_file,
    _scan_tasks,
)
from hivemind.core.config import HivemindConfig
from hivemind.core.parser import parse_task
from hivemind.core.scope import ConflictReport, pack_non_conflicting


def _find_in_progress(
    cfg: HivemindConfig,
    project: str | None,
) -> tuple[dict[str, object], str, Path] | None:
    """Find the first in_progress task, or None."""
    tasks = _scan_tasks(cfg, project)
    for fm, body, path in tasks:
        if fm.get("status") == "in_progress":
            return fm, body, path
    return None


def _find_ready_tasks(
    cfg: HivemindConfig,
    project: str | None,
    leaf_only: bool = True,
) -> list[tuple[dict[str, object], str, Path]]:
    """Return all pending tasks with resolved deps, sorted by priority+age."""
    all_tasks = _scan_tasks(cfg, project)

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
    cfg: HivemindConfig,
    project: str | None,
) -> tuple[dict[str, object], str, Path] | None:
    """Find the next pending leaf task with resolved deps, sorted by priority.

    Epics and stories are containers, not implementation targets, so they are
    excluded — auto-detect always drills down to leaves.
    """
    ready = _find_ready_tasks(cfg, project, leaf_only=True)
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


def _output_ready_batch(
    selected_items: list[tuple[dict[str, object], str, Path]],
    deferred_reports: list[ConflictReport],
    fmt: str,
) -> None:
    """Output the packed ready-only batch.

    The contract (AGE-005-07ca):

    - JSON mode emits a single object ``{"tasks": [...], "deferred": [...]}``
      where each task entry has the same ``{"id", "frontmatter", "body",
      "path"}`` shape used elsewhere, and each deferred entry is
      ``{"id", "reason", "conflict_with", "overlap"}`` with ``reason``
      fixed to ``"scope conflict"``.
    - Text mode prints selected one-liners to stdout (one per line) and
      deferred entries to stderr — one ``deferred <id>  (conflict_with=
      <peer_id>, overlap=<comma-joined>)`` line per loser.
    """
    if fmt == "json":
        tasks_payload: list[dict[str, object]] = [
            {
                "id": fm.get("id", ""),
                "frontmatter": fm,
                "body": body,
                "path": str(path),
            }
            for fm, body, path in selected_items
        ]
        deferred_payload: list[dict[str, object]] = [
            {
                "id": report.id,
                "reason": "scope conflict",
                "conflict_with": report.conflict_with,
                "overlap": list(report.overlap),
            }
            for report in deferred_reports
        ]
        click.echo(
            json.dumps(
                {"tasks": tasks_payload, "deferred": deferred_payload},
                indent=2,
                default=str,
            )
        )
    else:
        for i, (fm, _body, _path) in enumerate(selected_items):
            if i > 0:
                click.echo("")
                click.echo("---")
            click.echo(f"{fm.get('id', '')}  [{fm.get('type', '')}]  {fm.get('title', '')}")
        for report in deferred_reports:
            overlap_str = ",".join(report.overlap)
            click.echo(
                f"deferred {report.id}  "
                f"(conflict_with={report.conflict_with}, overlap={overlap_str})",
                err=True,
            )


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
    "--all-projects",
    "all_projects",
    is_flag=True,
    default=False,
    help="Scan tasks from all projects (default: auto-detect current project).",
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
    all_projects: bool,
    fmt: str,
) -> None:
    """Fetch task content for the run-task pipeline."""
    cfg, _data_path = _find_config()

    if task_id is not None:
        task_path = _find_task_file(cfg, task_id)
        fm, body = parse_task(task_path)
        _output_task(fm, body, task_path, fmt)
        return

    if all_projects:
        scan_project: str | None = None
    elif project:
        scan_project = project
    else:
        detected = _find_project_by_cwd(cfg)
        if detected:
            scan_project = detected
        else:
            raise click.ClickException(
                "No project linked to current directory. "
                "Use --project/-p to specify, or --all-projects to scan all."
            )

    if ready_only:
        ready = _find_ready_tasks(cfg, scan_project, leaf_only=True)

        # Build (id, scope) tuples for the packer, mapping each id back to
        # its full (fm, body, path) entry for later assembly.
        ready_by_id: dict[str, tuple[dict[str, object], str, Path]] = {}
        candidates_for_pack: list[tuple[str, list[str]]] = []
        for fm, body, path in ready:
            tid = str(fm.get("id", ""))
            raw_scope = fm.get("scope")
            scope_list: list[str] = (
                [str(x) for x in raw_scope] if isinstance(raw_scope, list) else []
            )
            ready_by_id[tid] = (fm, body, path)
            candidates_for_pack.append((tid, scope_list))

        pack_limit = (
            limit if (limit is not None and limit > 0) else len(candidates_for_pack)
        )
        selected_ids, deferred_reports = pack_non_conflicting(
            candidates_for_pack, pack_limit
        )

        selected_items: list[tuple[dict[str, object], str, Path]] = [
            ready_by_id[sid] for sid in selected_ids if sid in ready_by_id
        ]

        if not selected_items and not deferred_reports:
            if fmt == "json":
                click.echo(json.dumps({"tasks": [], "deferred": []}, indent=2))
            else:
                click.echo("No ready tasks available")
            sys.exit(1)

        _output_ready_batch(selected_items, deferred_reports, fmt)
        return

    # Auto-detect: first look for in_progress
    result = _find_in_progress(cfg, scan_project)
    if result is not None:
        fm, body, path = result
        _output_task(fm, body, path, fmt)
        return

    # Fallback to next pending
    result = _find_next_pending(cfg, scan_project)
    if result is not None:
        fm, body, path = result
        _output_task(fm, body, path, fmt)
        return

    click.echo("No tasks available")
    sys.exit(1)
