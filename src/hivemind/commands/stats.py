"""Implementation of `hv stats` command -- aggregate execution reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import click
import frontmatter

from hivemind.commands.audit import _find_config
from hivemind.core.harness_quality import RUBRIC_VERSION, load_scores
from hivemind.core.paths import linked_path_for


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


def _sum_retries(fm: dict[str, object]) -> float:
    """Best-effort retry count: v3 splits coding/verify/review, v2 used a single field."""
    total = 0.0
    for key in ("retries", "coding_retries", "verify_retries", "review_rounds"):
        val = fm.get(key)
        if isinstance(val, (int, float)):
            total += float(val)
    return total


def _compute_stats(reports: list[dict[str, object]]) -> dict[str, object]:
    """Aggregate statistics from a list of report frontmatter dicts.

    Returns a dict with totals, averages, review-score averages, and cost.
    """
    total = len(reports)
    if total == 0:
        return {
            "total_tasks": 0,
            "avg_duration": 0.0,
            "avg_retries": 0.0,
            "review_pass_rate": 0.0,
            "avg_correctness": 0.0,
            "avg_spec_compliance": 0.0,
            "avg_safety": 0.0,
            "avg_clarity": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "by_profile": {},
            "by_type": {},
        }

    durations: list[float] = []
    retries: list[float] = []
    review_passed = 0

    score_sums: dict[str, float] = defaultdict(float)
    score_counts: dict[str, int] = defaultdict(int)

    total_input = 0
    total_output = 0
    total_cost = 0.0

    by_profile: dict[str, dict[str, float]] = defaultdict(
        lambda: {"tasks": 0, "cost_usd": 0.0}
    )
    by_type: dict[str, dict[str, float]] = defaultdict(
        lambda: {"tasks": 0, "cost_usd": 0.0}
    )

    for fm in reports:
        dur = fm.get("duration_minutes")
        if isinstance(dur, (int, float)):
            durations.append(float(dur))

        retries.append(_sum_retries(fm))

        # v2 used review_passed bool; v3 uses blocking_issues + rubric
        if fm.get("review_passed") is True:
            review_passed += 1
        elif fm.get("blocking_issues") is False:
            review_passed += 1

        rubric = fm.get("review_scores")
        if isinstance(rubric, dict):
            for axis in ("correctness", "spec_compliance", "safety", "clarity"):
                val = rubric.get(axis)
                if isinstance(val, (int, float)):
                    score_sums[axis] += float(val)
                    score_counts[axis] += 1

        tokens = fm.get("tokens")
        if isinstance(tokens, dict):
            inp = tokens.get("input")
            outp = tokens.get("output")
            if isinstance(inp, (int, float)):
                total_input += int(inp)
            if isinstance(outp, (int, float)):
                total_output += int(outp)

        cost = fm.get("cost_usd")
        if isinstance(cost, (int, float)):
            total_cost += float(cost)

        profile = str(fm.get("profile", "unknown"))
        by_profile[profile]["tasks"] += 1
        if isinstance(cost, (int, float)):
            by_profile[profile]["cost_usd"] += float(cost)

        ttype = str(fm.get("task_type") or fm.get("type") or "unknown")
        by_type[ttype]["tasks"] += 1
        if isinstance(cost, (int, float)):
            by_type[ttype]["cost_usd"] += float(cost)

    def _avg(sum_val: float, count: int) -> float:
        return round(sum_val / count, 1) if count else 0.0

    return {
        "total_tasks": total,
        "avg_duration": _avg(sum(durations), len(durations)),
        "avg_retries": _avg(sum(retries), len(retries)),
        "review_pass_rate": round((review_passed / total) * 100.0, 1),
        "avg_correctness": _avg(score_sums["correctness"], score_counts["correctness"]),
        "avg_spec_compliance": _avg(
            score_sums["spec_compliance"], score_counts["spec_compliance"]
        ),
        "avg_safety": _avg(score_sums["safety"], score_counts["safety"]),
        "avg_clarity": _avg(score_sums["clarity"], score_counts["clarity"]),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 2),
        "by_profile": dict(by_profile),
        "by_type": dict(by_type),
    }


def _format_table(project: str, stats: dict[str, Any]) -> str:
    """Format aggregated stats as a readable table string."""
    lines: list[str] = []
    lines.append(f"=== Stats: {project} ===")
    lines.append("")
    lines.append(f"  {'Metric':<25} {'Value':>12}")
    lines.append(f"  {'-' * 25} {'-' * 12}")
    lines.append(f"  {'Total tasks':<25} {stats['total_tasks']:>12}")
    lines.append(f"  {'Avg duration (min)':<25} {stats['avg_duration']:>12}")
    lines.append(f"  {'Avg retries':<25} {stats['avg_retries']:>12}")
    lines.append(f"  {'Review pass rate (%)':<25} {stats['review_pass_rate']:>12}")
    lines.append("")
    lines.append("  Review rubric (avg / 10)")
    lines.append(f"  {'  correctness':<25} {stats['avg_correctness']:>12}")
    lines.append(f"  {'  spec_compliance':<25} {stats['avg_spec_compliance']:>12}")
    lines.append(f"  {'  safety':<25} {stats['avg_safety']:>12}")
    lines.append(f"  {'  clarity':<25} {stats['avg_clarity']:>12}")
    lines.append("")
    lines.append("  Usage")
    lines.append(f"  {'  Input tokens':<25} {stats['total_input_tokens']:>12,}")
    lines.append(f"  {'  Output tokens':<25} {stats['total_output_tokens']:>12,}")
    cost_str = f"${stats['total_cost_usd']:.2f}"
    lines.append(f"  {'  Total cost (USD)':<25} {cost_str:>12}")

    by_profile = stats.get("by_profile", {})
    if isinstance(by_profile, dict) and by_profile:
        lines.append("")
        lines.append("  By profile")
        lines.append(f"  {'Profile':<15} {'Tasks':>8} {'Cost (USD)':>14}")
        lines.append(f"  {'-' * 15} {'-' * 8} {'-' * 14}")
        for name, agg in sorted(by_profile.items()):
            tasks = int(agg.get("tasks", 0))
            cost = float(agg.get("cost_usd", 0.0))
            lines.append(f"  {name:<15} {tasks:>8} {'$' + f'{cost:.2f}':>14}")

    by_type = stats.get("by_type", {})
    if isinstance(by_type, dict) and by_type:
        lines.append("")
        lines.append("  By task type")
        lines.append(f"  {'Type':<15} {'Tasks':>8} {'Cost (USD)':>14}")
        lines.append(f"  {'-' * 15} {'-' * 8} {'-' * 14}")
        for name, agg in sorted(by_type.items()):
            tasks = int(agg.get("tasks", 0))
            cost = float(agg.get("cost_usd", 0.0))
            lines.append(f"  {name:<15} {tasks:>8} {'$' + f'{cost:.2f}':>14}")

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


def _render_harness_trend(project: str, limit: int) -> str:
    """Render the harness score trend as a text block."""
    cfg, _data_path = _find_config()
    try:
        linked = linked_path_for(cfg, project)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))
    scores = load_scores(linked)
    if not scores:
        return "No harness scores recorded yet (run the hv-score-harness skill)."

    recent = scores[-limit:]

    lines: list[str] = [f"=== Harness score trend: {project} ==="]
    lines.append("")
    lines.append(f"  {'Timestamp':<26} {'Overall':>10}  Trend")
    lines.append(f"  {'-' * 26} {'-' * 10}  -----")

    previous: int | None = None
    for s in recent:
        pct = round(100 * s.overall / s.overall_max, 1) if s.overall_max else 0.0
        arrow = ""
        if previous is not None:
            if s.overall > previous:
                arrow = "up"
            elif s.overall < previous:
                arrow = "down"
            else:
                arrow = "flat"
        rubric_note = ""
        if s.rubric_version != RUBRIC_VERSION:
            rubric_note = f"  [rubric v{s.rubric_version}]"
        value = f"{s.overall}/{s.overall_max}"
        lines.append(
            f"  {s.timestamp:<26} {value:>10}  {arrow}{rubric_note}  ({pct}%)"
        )
        previous = s.overall

    latest = recent[-1]
    lines.append("")
    lines.append("  Latest axis breakdown:")
    width = max((len(name) for name in latest.axes), default=0)
    for name, ax in latest.axes.items():
        lines.append(f"    {name.ljust(width)}   {ax.score}/{ax.max_score}")
    return "\n".join(lines)


@click.command("stats")
@click.option("--project", "-p", required=True, help="Project to show stats for.")
@click.option("--since", default=None, help="Start date (ISO format) for filtering.")
@click.option(
    "--harness",
    is_flag=True,
    default=False,
    help="Show harness design-quality trend instead of task execution stats.",
)
@click.option(
    "--limit",
    type=int,
    default=10,
    help="With --harness, max number of most-recent entries.",
)
def stats(
    project: str, since: Optional[str], harness: bool, limit: int
) -> None:
    """Show aggregated execution statistics for a project."""
    if harness:
        click.echo(_render_harness_trend(project, limit))
        return
    report = run_stats(project, since)
    click.echo(report)
