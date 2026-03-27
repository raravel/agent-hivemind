"""Implementation of `hv search`, `hv search read`, and `hv index` commands."""

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


def _read_doc_content(data_path: Path, doc_rel_path: str) -> str:
    """Read the full body content of an L2 document."""
    doc_path = data_path / doc_rel_path
    post = frontmatter.load(str(doc_path))
    return str(post.content)


PROMOTION_THRESHOLD = 3


def _ensure_index(data_path: Path) -> dict[str, list[dict[str, object]]]:
    """Load or build the BM25 index."""
    index_path = data_path / "index.json"
    if index_path.exists():
        index_data = load_index(index_path)
        if index_data.get("docs"):
            return index_data
    index_data = build_index(data_path)
    save_index(index_data, index_path)
    return index_data


@click.command()
@click.argument("query")
@click.option("--project", "-p", default=None, help="Project to search in.")
def search(query: str, project: str | None) -> None:
    """Search the knowledge base (does NOT increment hits).

    Returns results with relevance percentage. Use `hv search read <path>`
    to read a document and increment its hit counter.
    """
    data_path = _resolve_data_path()
    index_data = _ensure_index(data_path)

    results = bm25_search(query, index_data, top_k=10)

    if not results:
        click.echo("No results found.")
        return

    # Compute relevance as percentage of max score
    max_score = results[0][1] if results else 1.0
    if max_score <= 0:
        max_score = 1.0

    # Print results table — NO hits increment
    click.echo(
        f"{'Relevance':<12} {'Score':<10} {'Path':<50} {'Title':<30} {'Hits':<5}"
    )
    click.echo("-" * 107)
    for doc_path, score in results:
        relevance = (score / max_score) * 100
        title = _get_doc_title(data_path, doc_path)
        hits = _get_doc_hits(data_path, doc_path)
        click.echo(
            f"{relevance:>6.0f}%      {score:<10.4f}"
            f" {doc_path:<50} {title:<30} {hits:<5}"
        )


@click.command("read")
@click.argument("doc_path")
def search_read(doc_path: str) -> None:
    """Read an L2 document and increment its hit counter.

    DOC_PATH is the relative path to the document (from search results).
    """
    data_path = _resolve_data_path()
    full_path = data_path / doc_path

    if not full_path.exists():
        click.echo(f"Document not found: {full_path}")
        raise SystemExit(1)

    # Increment hits
    new_hits = _increment_hits(data_path, doc_path)
    title = _get_doc_title(data_path, doc_path)

    # Print content
    content = _read_doc_content(data_path, doc_path)
    click.echo(f"# {title}")
    click.echo(f"Hits: {new_hits}")
    click.echo("")
    click.echo(content)

    # Check promotion
    if new_hits >= PROMOTION_THRESHOLD and not _is_promoted(data_path, doc_path):
        click.echo("")
        click.echo(
            f"Promotion suggested: {doc_path} has {new_hits} hits. "
            f"Run `hv important promote {doc_path}` to promote to L1."
        )

    # Update index
    updated_index = build_index(data_path)
    save_index(updated_index, data_path / "index.json")


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
