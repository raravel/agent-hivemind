"""Similarity check for L2 documents using BM25."""

from __future__ import annotations

from pathlib import Path

from hivemind.core.indexer import build_index, search


def find_similar(
    query: str, data_path: Path, threshold: float = 0.7
) -> list[tuple[str, float]]:
    """Find L2 documents similar to the query above the given threshold.

    Returns list of (doc_path, score) pairs with score >= threshold,
    sorted by score descending.
    """
    index_data = build_index(data_path)
    results = search(query, index_data, top_k=10)
    return [(path, score) for path, score in results if score >= threshold]
