"""Implementation of `hv spec` — CLI write gateway for harness docs.

The plan/task skills create spec files via this command instead of writing
to the filesystem directly. The CLI is the single audit point: it resolves
the v5 location, writes atomically, and returns the resolved path on
stdout so the agent can re-read the file if it needs the post-write state.

Read paths stay direct — ``@import`` and ``Read`` keep working on the
files this command writes.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import click

from hivemind.commands.task import _find_config, _find_project_by_cwd
from hivemind.core.paths import harness_spec_dir, linked_path_for


def _resolve_project(project: str | None) -> tuple[Path, str]:
    """Return (linked_path, project_name) for the selected project.

    Falls back to ``_find_project_by_cwd`` when ``--project`` is omitted.
    """
    cfg, _ = _find_config()
    if project is None:
        project = _find_project_by_cwd(cfg)
        if project is None:
            raise click.ClickException(
                "No project linked to current directory. "
                "Pass --project/-p to specify."
            )
    try:
        return linked_path_for(cfg, project), project
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc


def _next_feature_path(features_dir: Path, slug: str) -> Path:
    """Return ``features/NN_<slug>.md``, auto-numbering NN.

    If a file containing the same slug already exists, overwrite it
    (keeping its number). Otherwise pick ``(max existing NN) + 1``.
    """
    slug_norm = slug.strip().lower().replace(" ", "-")
    if not slug_norm:
        raise click.ClickException("Empty feature slug.")

    features_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(features_dir.glob("*.md"))

    for path in existing:
        if slug_norm in path.stem.lower():
            return path

    max_n = 0
    for path in existing:
        head = path.stem.split("_", 1)[0]
        if head.isdigit():
            n = int(head)
            if n > max_n:
                max_n = n
    return features_dir / f"{max_n + 1:02d}_{slug_norm}.md"


def _resolve_spec_path(linked_path: Path, name: str) -> Path:
    """Map a logical spec name to its on-disk path inside ``hivemind/docs/``.

    Supported names:
      - ``architecture``, ``architecture.md``
      - ``rules``, ``rules.md``
      - ``tech-stack``, ``tech_stack``, ``tech-stack.md``
      - ``verify``, ``verify.md``
      - ``features/<slug>`` — auto-numbered to ``features/NN_<slug>.md``
      - any other ``foo`` -> ``docs/foo.md``
    """
    docs = harness_spec_dir(linked_path)

    if name.startswith("features/"):
        slug = name[len("features/"):]
        return _next_feature_path(docs / "features", slug)

    # Canonical short names
    aliases = {
        "architecture": "architecture.md",
        "rules": "rules.md",
        "tech-stack": "tech-stack.md",
        "tech_stack": "tech-stack.md",
        "techstack": "tech-stack.md",
        "verify": "verify.md",
    }
    canonical = aliases.get(name.lower(), None)
    if canonical is not None:
        return docs / canonical

    # Fall through: treat name as a filename relative to docs/
    if not name.endswith(".md"):
        name = f"{name}.md"
    return docs / name


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically (tmpfile + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


@click.group()
def spec() -> None:
    """Read/write harness spec files."""


@spec.command(name="list")
@click.option("--project", "-p", default=None, help="Project name.")
def list_cmd(project: str | None) -> None:
    """List spec files for a project."""
    linked_path, _name = _resolve_project(project)
    docs = harness_spec_dir(linked_path)
    if not docs.exists():
        click.echo("No specs found.")
        return
    paths: list[Path] = []
    for p in sorted(docs.rglob("*.md")):
        if p.is_file():
            paths.append(p)
    if not paths:
        click.echo("No specs found.")
        return
    for p in paths:
        rel = p.relative_to(docs)
        click.echo(str(rel))


@spec.command(name="write")
@click.argument("name")
@click.option("--project", "-p", default=None, help="Project name.")
@click.option(
    "--content",
    "-c",
    "content_file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="File with spec content (reads from stdin if omitted).",
)
def write_cmd(name: str, project: str | None, content_file: str | None) -> None:
    """Write a spec file from stdin (or --content FILE).

    The resolved absolute path is printed on stdout. A stale-import note is
    emitted on stderr so agents know to re-Read the file if they had it via
    ``@import``.
    """
    if content_file is not None:
        text = Path(content_file).read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            click.echo("Enter spec content (Ctrl+D to finish):", err=True)
        text = sys.stdin.read()
    if not text.strip():
        raise click.ClickException("Empty content — refusing to write.")

    linked_path, _proj = _resolve_project(project)
    target = _resolve_spec_path(linked_path, name)
    _atomic_write(target, text)

    click.echo(f"Wrote: {target}")
    click.echo(
        "Note: reload via Read tool — @import content is now stale.",
        err=True,
    )
