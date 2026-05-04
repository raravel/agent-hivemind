"""Implementation of `hv important` command group."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import frontmatter

from hivemind.core.config import HivemindConfig
from hivemind.core.git import auto_commit
from hivemind.core.indexer import build_index, search


def _resolve_data_path() -> Path:
    """Resolve the data path from the config (canonical or legacy candidate)."""
    try:
        return HivemindConfig.find_for_command().data_path
    except FileNotFoundError:
        return Path("~/agent-hivemind-data").expanduser()


def _scan_promoted(data_path: Path) -> list[dict[str, Any]]:
    """Scan all L2 docs and return those with promoted: true."""
    level2_dir = data_path / "level2"
    promoted: list[dict[str, Any]] = []

    if not level2_dir.exists():
        return promoted

    for md_file in sorted(level2_dir.rglob("*.md")):
        try:
            post = frontmatter.load(str(md_file))
        except Exception:  # noqa: BLE001
            continue

        if post.metadata.get("promoted") is True:
            rel_path = str(md_file.relative_to(data_path))
            promoted.append(
                {
                    "title": str(post.metadata.get("title", md_file.stem)),
                    "path": rel_path,
                    "hits": int(post.metadata.get("hits", 0)),
                    "body": post.content,
                }
            )

    return promoted


def generate_important_md(data_path: Path) -> Path:
    """Generate level1/important.md from all promoted L2 docs.

    Returns the path to the generated file.
    """
    promoted = _scan_promoted(data_path)
    # Sort by hits descending
    promoted.sort(key=lambda d: d["hits"], reverse=True)

    now = datetime.now(timezone.utc).isoformat()
    fm: dict[str, Any] = {
        "generated": now,
        "count": len(promoted),
    }

    sections: list[str] = []
    sections.append("# Important Lessons")

    for doc in promoted:
        section = (
            f"\n## {doc['title']}\n"
            f"Source: {doc['path']}\n"
            f"Hits: {doc['hits']}\n"
            f"\n{doc['body']}\n"
            f"\n---"
        )
        sections.append(section)

    body = "\n".join(sections)
    if not body.endswith("\n"):
        body += "\n"

    post = frontmatter.Post(body, **fm)
    important_path = data_path / "level1" / "important.md"
    important_path.parent.mkdir(parents=True, exist_ok=True)
    important_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return important_path


@click.group()
def important() -> None:
    """Manage important items (L1 promoted lessons)."""


@important.command()
@click.argument("path")
def promote(path: str) -> None:
    """Promote an L2 document to important.

    PATH is relative to the data directory (e.g. level2/backend/api-auth.md).
    """
    data_path = _resolve_data_path()
    doc_path = data_path / path

    if not doc_path.exists():
        click.echo(f"Error: File not found: {doc_path}", err=True)
        raise SystemExit(1)

    post = frontmatter.load(str(doc_path))

    if post.metadata.get("promoted") is True:
        click.echo(f"Already promoted: {path}")
    else:
        post.metadata["promoted"] = True
        doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
        click.echo(f"Promoted: {path}")

    # Auto-generate important.md
    important_path = generate_important_md(data_path)
    click.echo(f"Generated: {important_path}")

    auto_commit(data_path, f"important: promote {path}")


@important.command()
@click.argument("query")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation.")
def demote(query: str, yes: bool) -> None:
    """Demote a promoted L2 document by searching for it.

    QUERY is a search string to find the promoted doc to demote.
    """
    data_path = _resolve_data_path()

    # Build index only from promoted docs
    promoted = _scan_promoted(data_path)
    if not promoted:
        click.echo("No promoted documents found.")
        return

    # Build a mini-index from promoted docs only
    index_data = build_index(data_path)
    # Filter index to only promoted paths
    promoted_paths = {doc["path"].replace("\\", "/") for doc in promoted}
    filtered_docs = [
        doc
        for doc in index_data.get("docs", [])
        if doc["path"].replace("\\", "/") in promoted_paths
    ]
    filtered_index: dict[str, Any] = {"docs": filtered_docs}

    results = search(query, filtered_index, top_k=1)
    if not results:
        click.echo(f"No promoted document matched query: {query}")
        return

    match_path, score = results[0]
    click.echo(f"Top match: {match_path} (score: {score:.2f})")

    if not yes:
        confirmed = click.confirm("Demote this document?")
        if not confirmed:
            click.echo("Cancelled.")
            return

    doc_path = data_path / match_path
    post = frontmatter.load(str(doc_path))
    post.metadata["promoted"] = False
    doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    click.echo(f"Demoted: {match_path}")

    # Auto-generate important.md
    important_path = generate_important_md(data_path)
    click.echo(f"Generated: {important_path}")

    auto_commit(data_path, "important: demote")


@important.command()
def generate() -> None:
    """Generate level1/important.md from all promoted L2 docs."""
    data_path = _resolve_data_path()
    important_path = generate_important_md(data_path)
    post = frontmatter.load(str(important_path))
    count = post.metadata.get("count", 0)
    click.echo(f"Generated: {important_path}")
    click.echo(f"Promoted lessons: {count}")

    auto_commit(data_path, "important: regenerate")
