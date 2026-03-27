"""BM25 indexing for L2 documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frontmatter
from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    """Simple whitespace tokenizer with lowercasing."""
    return text.lower().split()


def build_index(data_path: Path) -> dict[str, Any]:
    """Scan level2/ files and build a BM25 index.

    Returns a dict with:
      - docs: list of {path, title, tokens}
      - corpus: list of token lists (for BM25 reconstruction)
    """
    level2_dir = data_path / "level2"
    docs: list[dict[str, Any]] = []

    if not level2_dir.exists():
        return {"docs": docs}

    for md_file in sorted(level2_dir.rglob("*.md")):
        try:
            post = frontmatter.load(str(md_file))
        except Exception:  # noqa: BLE001
            continue
        title = str(post.metadata.get("title", md_file.stem))
        body: str = post.content
        text = f"{title} {body}"
        tokens = _tokenize(text)
        rel_path = str(md_file.relative_to(data_path))
        docs.append({"path": rel_path, "title": title, "tokens": tokens})

    return {"docs": docs}


def save_index(index_data: dict[str, Any], path: Path) -> None:
    """Save index to index.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_index(path: Path) -> dict[str, Any]:
    """Load index from index.json."""
    if not path.exists():
        return {"docs": []}
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    if "docs" not in data:
        data["docs"] = []
    return data


def _token_overlap_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """Simple token overlap scoring for small corpora where BM25 fails."""
    if not doc_tokens:
        return 0.0
    query_set = set(query_tokens)
    matches = sum(1 for t in doc_tokens if t in query_set)
    return matches / len(doc_tokens)


def search(
    query: str, index_data: dict[str, Any], top_k: int = 5
) -> list[tuple[str, float]]:
    """BM25 search over indexed docs.

    Falls back to token overlap scoring when the corpus is too small
    for BM25 to produce meaningful scores (BM25 IDF goes negative with
    very few documents).

    Returns list of (doc_path, score) pairs, sorted by score descending.
    """
    docs: list[dict[str, Any]] = index_data.get("docs", [])
    if not docs:
        return []

    corpus: list[list[str]] = [doc["tokens"] for doc in docs]
    query_tokens = _tokenize(query)

    # BM25 needs 3+ docs for meaningful IDF; fall back for small corpora
    if len(docs) >= 3:
        bm25 = BM25Okapi(corpus)
        scores: list[float] = list(bm25.get_scores(query_tokens))
    else:
        scores = [_token_overlap_score(query_tokens, d) for d in corpus]

    results: list[tuple[str, float]] = []
    for i, score in enumerate(scores):
        if score > 0:
            results.append((docs[i]["path"], float(score)))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]
