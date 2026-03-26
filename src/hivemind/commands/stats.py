"""Implementation of `hv stats` command -- aggregate execution reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import click
import frontmatter

from hivemind.commands.audit import _find_config


def _parse_report(path: Path) -> dict[str, object] | None:
    """Parse a report markdown file and return its frontmatter dict.

    Returns None if the file cannot be parsed.
    """
    try:
        post = frontmatter.load(str(path))
        return dict(post.metadata)
    except Exception:  # noqa: BLE001
        return None


def _collect_reports(
    data_path: Path,
    project: str,
    since: datetime | None = None,
) -> list[dict[str, object]]:
    """Scan tasks/{project}/_reports/*.md and return parsed frontmatter dicts.

    If *since* is given, only reports whose ``completed_at`` >= *since* are
    included.
    """
    reports_dir = data_path / "tasks" / project / "_reports"
    if not reports_dir.exists():
        return []

    results: list[dict[str, object]] = []
    for md_file in sorted(reports_dir.glob("*.md")):
        fm = _parse_report(md_file)
        if fm is None:
            continue

        if since is not None:
            completed_raw = fm.get("completed_at")
            if completed_raw is None:
                continue
            try:
                completed_dt = datetime.fromisoformat(str(completed_raw))
            except (ValueError, TypeError):
                continue
            if completed_dt < since:
                continue

        results.append(fm)
    return results


def _compute_stats(reports: list[dict[str, object]]) -> dict[str, object]:
    """Aggregate statistics from a list of report frontmatter dicts.

    Returns a dict with:
      total_tasks, avg_duration, avg_retries, review_pass_rate, lint_fail_rate
    """
    total = len(reports)
    if total == 0:
        return {
            "total_tasks": 0,
            "avg_duration": 0.0,
            "avg_retries": 0.0,
            "review_pass_rate": 0.0,
            "lint_fail_rate": 0.0,
        }

    durations: list[float] = []
    retries: list[float] = []
    review_passed_count = 0
    lint_failed_count = 0

    for fm in reports:
        dur = fm.get("duration_minutes")
        if isinstance(dur, (int, float)):
            durations.append(float(dur))

        ret = fm.get("retries")
        if isinstance(ret, (int, float)):
            retries.append(float(ret))

        if fm.get("review_passed") is True:
            review_passed_count += 1

        if fm.get("lint_failed") is True:
            lint_failed_count += 1

    avg_dur = sum(durations) / len(durations) if durations else 0.0
    avg_ret = sum(retries) / len(retries) if retries else 0.0
    review_rate = (review_passed_count / total) * 100.0
    lint_rate = (lint_failed_count / total) * 100.0

    return {
        "total_tasks": total,
        "avg_duration": round(avg_dur, 1),
        "avg_retries": round(avg_ret, 1),
        "review_pass_rate": round(review_rate, 1),
        "lint_fail_rate": round(lint_rate, 1),
    }


def _format_table(project: str, stats: dict[str, object]) -> str:
    """Format aggregated stats as a readable table string."""
    lines: list[str] = []
    lines.append(f"=== Stats: {project} ===")
    lines.append("")
    lines.append(f"  {'Metric':<25} {'Value':>10}")
    lines.append(f"  {'-' * 25} {'-' * 10}")
    lines.append(f"  {'Total tasks':<25} {stats['total_tasks']:>10}")
    lines.append(f"  {'Avg duration (min)':<25} {stats['avg_duration']:>10}")
    lines.append(f"  {'Avg retries':<25} {stats['avg_retries']:>10}")
    lines.append(f"  {'Review pass rate (%)':<25} {stats['review_pass_rate']:>10}")
    lines.append(f"  {'Lint fail rate (%)':<25} {stats['lint_fail_rate']:>10}")
    return "\n".join(lines)


def run_stats(project: str, since: str | None = None) -> str:
    """Execute stats aggregation and return the formatted report string.

    Separated from the Click command for testability.
    """
    _cfg, data_path = _find_config()

    since_dt: datetime | None = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise click.ClickException(
                f"Invalid --since date: '{since}'. Use ISO format (YYYY-MM-DD)."
            ) from exc

    reports = _collect_reports(data_path, project, since_dt)
    if not reports:
        return "No execution reports found"

    stats = _compute_stats(reports)
    return _format_table(project, stats)


@click.command("stats")
@click.option("--project", "-p", required=True, help="Project to show stats for.")
@click.option("--since", default=None, help="Start date (ISO format) for filtering.")
def stats(project: str, since: Optional[str]) -> None:
    """Show aggregated execution statistics for a project."""
    report = run_stats(project, since)
    click.echo(report)
