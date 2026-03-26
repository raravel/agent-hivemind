"""Implementation of `hv search` and `hv index` command groups."""

from __future__ import annotations

from pathlib import Path

import click
import frontmatter

from hivemind.core.config import HivemindConfig
from hivemind.core.indexer import (
    build_index,
    load_index,
    save_index,
    search as bm25_search,
)


def _resolve_data_path() -> Path:
    """Resolve the data path from config or default."""
    config_candidates = [
        Path.cwd() / ".hivemind.json",
        Path("~/.hivemind.json").expanduser(),
        Path("~/agent-hivemind-data/.hivemind.json").expanduser(),
    ]

    for config_path in config_candidates:
        if config_path.exists():
            cfg = HivemindConfig.load(config_path)
            return cfg.data_path

    return Path("~/agent-hivemind-data").expanduser()


def _increment_hits(data_path: Path, doc_rel_path: str) -> int:
    """Increment the hits counter in an L2 doc's frontmatter.

    Returns the new hits value.
    """
    doc_path = data_path / doc_rel_path
    post = frontmatter.load(str(doc_path))

    hits = post.metadata.get("hits", 0)
    if not isinstance(hits, int):
        hits = 0
    new_hits = hits + 1
    post.metadata["hits"] = new_hits

    doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return new_hits


def _get_doc_title(data_path: Path, doc_rel_path: str) -> str:
    """Read the title from a doc's frontmatter."""
    doc_path = data_path / doc_rel_path
    post = frontmatter.load(str(doc_path))
    return str(post.metadata.get("title", doc_path.stem))


def _get_doc_hits(data_path: Path, doc_rel_path: str) -> int:
    """Read the current hits value from a doc's frontmatter."""
    doc_path = data_path / doc_rel_path
    post = frontmatter.load(str(doc_path))
    hits = post.metadata.get("hits", 0)
    return hits if isinstance(hits, int) else 0


def _is_promoted(data_path: Path, doc_rel_path: str) -> bool:
    """Check if a doc is already promoted."""
    doc_path = data_path / doc_rel_path
    post = frontmatter.load(str(doc_path))
    return post.metadata.get("promoted") is True


PROMOTION_THRESHOLD = 3


@click.command()
@click.argument("query")
@click.option("--project", "-p", default=None, help="Project to search in.")
def search(query: str, project: str | None) -> None:
    """Search the knowledge base."""
    data_path = _resolve_data_path()
    index_path = data_path / "index.json"

    # Build or load index
    if index_path.exists():
        index_data = load_index(index_path)
        if not index_data.get("docs"):
            index_data = build_index(data_path)
            save_index(index_data, index_path)
    else:
        index_data = build_index(data_path)
        save_index(index_data, index_path)

    results = bm25_search(query, index_data, top_k=5)

    if not results:
        click.echo("No results found.")
        return

    # Increment hits and collect display data
    rows: list[tuple[float, str, str, int]] = []
    promotion_suggestions: list[str] = []

    for doc_path, score in results:
        new_hits = _increment_hits(data_path, doc_path)
        title = _get_doc_title(data_path, doc_path)
        rows.append((score, doc_path, title, new_hits))

        if new_hits >= PROMOTION_THRESHOLD and not _is_promoted(
            data_path, doc_path
        ):
            promotion_suggestions.append(
                f"  Promote candidate: {doc_path} "
                f"(hits={new_hits}, title={title})"
            )

    # Print results table
    click.echo(f"{'Score':<10} {'Path':<40} {'Title':<30} {'Hits':<5}")
    click.echo("-" * 85)
    for score, path, title, hits in rows:
        click.echo(f"{score:<10.2f} {path:<40} {title:<30} {hits:<5}")

    # Print promotion suggestions
    if promotion_suggestions:
        click.echo("")
        click.echo(
            "Promotion suggestion: the following docs have "
            f">= {PROMOTION_THRESHOLD} hits and are not yet promoted:"
        )
        for suggestion in promotion_suggestions:
            click.echo(suggestion)
        click.echo(
            "Run `hv important promote <path>` to promote them to L1."
        )

    # Update index after hit changes
    updated_index = build_index(data_path)
    save_index(updated_index, index_path)


@click.group()
def index() -> None:
    """Manage search index."""


@index.command()
def rebuild() -> None:
    """Rebuild the search index."""
    data_path = _resolve_data_path()
    index_data = build_index(data_path)
    index_path = data_path / "index.json"
    save_index(index_data, index_path)

    doc_count = len(index_data.get("docs", []))
    click.echo(f"Index rebuilt: {doc_count} documents indexed.")
    click.echo(f"Saved to: {index_path}")
