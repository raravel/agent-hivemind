"""`hv harness-score` subcommand group — record / show / history.

The LLM judgment lives in the /hv:score-harness skill. This module is the
thin, deterministic I/O layer the skill pipes results into.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import timedelta

import click

from hivemind.commands.task import _find_config
from hivemind.core.harness_quality import (
    RUBRIC_VERSION,
    HarnessScore,
    append_score,
    build_score_from_payload,
    harness_spec_dir,
    hash_harness,
    is_fresh,
    latest_score,
    load_scores,
)


def _parse_age(spec: str) -> timedelta:
    """Parse '7d', '24h', '30m' into a timedelta."""
    m = re.fullmatch(r"(\d+)([dhm])", spec.strip())
    if not m:
        raise click.ClickException(
            f"Invalid --if-fresh '{spec}'. Use forms like 7d, 24h, 30m."
        )
    n = int(m.group(1))
    unit = m.group(2)
    return timedelta(days=n) if unit == "d" else (
        timedelta(hours=n) if unit == "h" else timedelta(minutes=n)
    )


def _format_score(score: HarnessScore) -> str:
    lines: list[str] = []
    lines.append(f"Harness score: {score.timestamp} (model={score.model})")
    lines.append(f"  rubric v{score.rubric_version}  hash {score.hash[:19]}...")
    lines.append("")
    width = max((len(name) for name in score.axes), default=0)
    for name, ax in score.axes.items():
        head = f"  {name.ljust(width)}   {ax.score}/{ax.max_score}"
        if ax.rationale:
            head = f"{head}   {ax.rationale}"
        lines.append(head)
        for rec in ax.recommendations:
            lines.append(f"    - {rec}")
    lines.append("")
    pct = (
        round(100 * score.overall / score.overall_max, 1)
        if score.overall_max
        else 0.0
    )
    lines.append(f"  overall   {score.overall}/{score.overall_max}  ({pct}%)")
    return "\n".join(lines)


@click.group("harness-score")
def harness_score_cmd() -> None:
    """Record and inspect harness design-quality scores."""


@harness_score_cmd.command("record")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option(
    "--from-stdin",
    "from_stdin",
    is_flag=True,
    default=False,
    help="Read score JSON payload from stdin.",
)
@click.option(
    "--model",
    default=None,
    help="Model ID that produced the score (defaults to profile reviewer).",
)
def record(project: str, from_stdin: bool, model: str | None) -> None:
    """Record a harness score from a JSON payload.

    Payload shape:
      {"axes": {"architecture": {"score": 8, "rationale": "...", "recommendations": [...]}, ...}}

    Hash of the current harness doc set is computed locally and stored with the
    record — LLM output does not need to (and should not) supply the hash.
    """
    if not from_stdin:
        raise click.ClickException(
            "--from-stdin is required; pipe the score JSON via stdin."
        )

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"invalid JSON on stdin: {e}")

    cfg, data_path = _find_config()
    spec_dir = harness_spec_dir(data_path, project)
    if not spec_dir.exists():
        raise click.ClickException(
            f"no harness spec dir for project: {spec_dir} — run /hv:plan first"
        )

    resolved_model = model
    if not resolved_model:
        profile_name = str(cfg.get("model_profile") or "balanced")
        profile = cfg.get(f"profiles.{profile_name}") or {}
        if isinstance(profile, dict):
            resolved_model = str(profile.get("reviewer") or "unknown")
        else:
            resolved_model = "unknown"

    try:
        score = build_score_from_payload(
            payload,
            hash_str=hash_harness(spec_dir),
            model=resolved_model,
        )
    except ValueError as e:
        raise click.ClickException(str(e))

    path = append_score(data_path, project, score)
    click.echo(f"Recorded: {path}")
    click.echo(_format_score(score))


@harness_score_cmd.command("show")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option(
    "--if-fresh",
    "if_fresh",
    default=None,
    help="Exit 0 only if the latest score is this fresh (e.g. 7d, 24h). Exit 2 if stale.",
)
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
def show(project: str, if_fresh: str | None, fmt: str) -> None:
    """Show the latest score. With --if-fresh, emit a cache-validity status."""
    # Parse --if-fresh up front so a bad format fails fast regardless of state.
    max_age = _parse_age(if_fresh) if if_fresh is not None else None

    _cfg, data_path = _find_config()
    latest = latest_score(data_path, project)
    if latest is None:
        click.echo("No harness score recorded yet.")
        sys.exit(2 if if_fresh else 0)

    if max_age is not None:
        current_hash = hash_harness(harness_spec_dir(data_path, project))
        if not is_fresh(latest, current_hash, max_age):
            # Stale — tell the caller (skill) to re-score.
            click.echo(
                f"Stale: latest score does not match current harness "
                f"(rubric v{latest.rubric_version}, age exceeds {if_fresh}).",
                err=True,
            )
            sys.exit(2)

    if fmt == "json":
        click.echo(json.dumps(latest.to_dict(), indent=2, ensure_ascii=False))
    else:
        click.echo(_format_score(latest))


@harness_score_cmd.command("history")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
@click.option(
    "--limit", type=int, default=10, help="Max number of most-recent entries."
)
def history(project: str, fmt: str, limit: int) -> None:
    """Show harness score trend (most recent entries first)."""
    _cfg, data_path = _find_config()
    scores = load_scores(data_path, project)
    if not scores:
        click.echo("No harness scores recorded yet.")
        return

    recent = scores[-limit:]

    if fmt == "json":
        click.echo(
            json.dumps(
                [s.to_dict() for s in recent], indent=2, ensure_ascii=False
            )
        )
        return

    click.echo(f"Harness score trend: {project}  (last {len(recent)})")
    click.echo("")
    previous: int | None = None
    for s in recent:
        pct = (
            round(100 * s.overall / s.overall_max, 1) if s.overall_max else 0.0
        )
        arrow = ""
        if previous is not None:
            if s.overall > previous:
                arrow = " ↑"
            elif s.overall < previous:
                arrow = " ↓"
            else:
                arrow = " ="
        rubric_note = (
            "" if s.rubric_version == RUBRIC_VERSION else f"  [rubric v{s.rubric_version}]"
        )
        click.echo(
            f"  {s.timestamp}   {s.overall}/{s.overall_max} ({pct}%){arrow}{rubric_note}"
        )
        previous = s.overall
