"""Implementation of `hv feedback` command group."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import click
import frontmatter

from hivemind.core.config import HivemindConfig
from hivemind.core.git import auto_commit
from hivemind.core.indexer import build_index, save_index
from hivemind.core.similarity import find_similar

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "frontend": [
        "react",
        "vue",
        "angular",
        "css",
        "html",
        "ui",
        "ux",
        "component",
        "browser",
        "dom",
        "layout",
        "style",
        "responsive",
        "javascript",
        "typescript",
        "jsx",
        "tsx",
    ],
    "backend": [
        "api",
        "server",
        "database",
        "sql",
        "rest",
        "graphql",
        "endpoint",
        "auth",
        "middleware",
        "orm",
        "migration",
        "python",
        "node",
        "django",
        "flask",
        "fastapi",
    ],
    "infra": [
        "docker",
        "kubernetes",
        "k8s",
        "ci",
        "cd",
        "deploy",
        "pipeline",
        "terraform",
        "aws",
        "gcp",
        "azure",
        "nginx",
        "monitoring",
        "logging",
        "helm",
        "container",
    ],
}


def detect_category(text: str) -> str:
    """Detect category from text using keyword matching.

    Returns one of: frontend, backend, infra, general.
    """
    text_lower = text.lower()
    scores: dict[str, int] = {"frontend": 0, "backend": 0, "infra": 0}

    for category, keywords in _CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword) + r"\b"
            matches = re.findall(pattern, text_lower)
            scores[category] += len(matches)

    best_category = max(scores, key=lambda k: scores[k])
    if scores[best_category] == 0:
        return "general"
    return best_category


def _slugify(text: str) -> str:
    """Create a filename-safe slug from text."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:60].strip("-")


def _resolve_data_path(project: str) -> Path:
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


def _update_existing_doc(
    data_path: Path, doc_rel_path: str, source_info: str
) -> Path:
    """Increment hits and add source link to an existing L2 doc."""
    doc_path = data_path / doc_rel_path
    post = frontmatter.load(str(doc_path))

    hits = post.metadata.get("hits", 1)
    if isinstance(hits, int):
        post.metadata["hits"] = hits + 1
    else:
        post.metadata["hits"] = 2

    sources = post.metadata.get("sources", [])
    if not isinstance(sources, list):
        sources = []
    sources.append(source_info)
    post.metadata["sources"] = sources

    doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return doc_path


def _create_new_doc(
    data_path: Path,
    title: str,
    body: str,
    category: str,
    today: str,
) -> Path:
    """Create a new L2 document with frontmatter."""
    slug = _slugify(title) if title else _slugify(body[:50])
    if not slug:
        slug = "lesson"

    cat_dir = data_path / "level2" / category
    cat_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{slug}.md"
    doc_path = cat_dir / filename

    # Avoid overwriting: add numeric suffix if needed
    counter = 1
    while doc_path.exists():
        counter += 1
        filename = f"{slug}-{counter}.md"
        doc_path = cat_dir / filename

    fm: dict[str, Any] = {
        "title": title,
        "category": category,
        "hits": 1,
        "sources": [],
        "promoted": False,
        "created": today,
    }

    post = frontmatter.Post(body, **fm)
    doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return doc_path


@click.group()
def feedback() -> None:
    """Manage feedback and lessons learned."""


@feedback.command()
@click.option("--project", "-p", required=True, help="Project name.")
@click.option(
    "--content",
    "-c",
    "content_file",
    type=click.Path(exists=True),
    default=None,
    help="File with lesson text (reads from stdin if omitted).",
)
@click.option("--title", "-t", default=None, help="Title for the lesson.")
def save(project: str, content_file: str | None, title: str | None) -> None:
    """Save a learning/lesson to L2 documents with BM25 similarity check."""
    # 1. Read lesson text
    if content_file is not None:
        text = Path(content_file).read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            click.echo("Enter lesson text (Ctrl+D to finish):")
        text = sys.stdin.read()

    text = text.strip()
    if not text:
        click.echo("Error: Empty lesson text.", err=True)
        raise SystemExit(1)

    # Use first line as title if not provided
    if title is None:
        first_line = text.split("\n")[0].strip()
        # Strip markdown heading prefix
        title = re.sub(r"^#+\s*", "", first_line)[:100]

    # 2. Resolve data path
    data_path = _resolve_data_path(project)

    # 3. Run BM25 similarity check
    similar = find_similar(text, data_path, threshold=0.7)

    today = date.today().isoformat()

    if similar:
        # 4a. Update existing doc
        best_path, best_score = similar[0]
        click.echo(
            f"Similar lesson found: {best_path} (score: {best_score:.2f})"
        )
        source_info = f"{project}:{today}"
        doc_path = _update_existing_doc(data_path, best_path, source_info)
        click.echo(f"Updated existing lesson: {doc_path}")
    else:
        # 4b. Create new doc
        category = detect_category(text)
        doc_path = _create_new_doc(data_path, title, text, category, today)
        click.echo(f"Created new lesson: {doc_path}")
        click.echo(f"Category: {category}")

    # 5. Update index
    index_data = build_index(data_path)
    index_path = data_path / "index.json"
    save_index(index_data, index_path)
    click.echo("Index updated.")

    # 6. Auto-commit
    auto_commit(data_path, f"feedback: {title}")
