"""Unit tests for search command and index rebuild."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter
import pytest

from hivemind.commands.search import (
    PROMOTION_THRESHOLD,
    _get_doc_hits,
    _get_doc_title,
    _increment_hits,
    _is_promoted,
)
from hivemind.core.indexer import (
    build_index,
    load_index,
    save_index,
    search as bm25_search,
)


def _make_data_dir(tmp_path: Path) -> Path:
    """Create a minimal hivemind data directory."""
    data_path = tmp_path / "data"
    for subdir in ("frontend", "backend", "infra", "general"):
        (data_path / "level2" / subdir).mkdir(parents=True, exist_ok=True)
    return data_path


def _create_l2_doc(
    data_path: Path,
    category: str,
    filename: str,
    title: str,
    body: str,
    hits: int = 1,
    promoted: bool = False,
) -> Path:
    """Create an L2 document for testing."""
    doc_path = data_path / "level2" / category / filename
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    fm: dict[str, Any] = {
        "title": title,
        "category": category,
        "hits": hits,
        "sources": [],
        "promoted": promoted,
        "created": "2026-03-26",
    }
    post = frontmatter.Post(body, **fm)
    doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return doc_path


class TestSearchReturnsResultsAndIncrementsHits:
    """Test that search returns results and increments hits."""

    def test_search_finds_matching_doc_and_increments_hits(
        self, tmp_path: Path
    ) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication",
            "always validate api tokens before processing requests",
            hits=1,
        )
        _create_l2_doc(
            data_path,
            "frontend",
            "css-tips.md",
            "CSS Tips",
            "use css grid for responsive layouts and flexbox for alignment",
            hits=1,
        )
        _create_l2_doc(
            data_path,
            "infra",
            "docker-tips.md",
            "Docker Tips",
            "use docker compose for local development kubernetes production",
            hits=1,
        )

        index_data = build_index(data_path)
        results = bm25_search("api tokens validation", index_data, top_k=5)

        assert len(results) >= 1
        top_path = results[0][0]
        assert "api-auth" in top_path.replace("\\", "/")

        # Increment hits on the top result
        new_hits = _increment_hits(data_path, top_path)
        assert new_hits == 2

        # Verify it persisted
        current_hits = _get_doc_hits(data_path, top_path)
        assert current_hits == 2

    def test_increment_hits_multiple_times(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "general",
            "lesson.md",
            "Test Lesson",
            "something important to learn",
            hits=0,
        )

        rel_path = "level2/general/lesson.md"
        for expected in range(1, 6):
            new_hits = _increment_hits(data_path, rel_path)
            assert new_hits == expected

    def test_get_doc_title(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "backend",
            "auth.md",
            "Auth Best Practices",
            "body text",
        )
        title = _get_doc_title(data_path, "level2/backend/auth.md")
        assert title == "Auth Best Practices"


class TestPromotionSuggestion:
    """Test that hits >= 3 triggers promotion suggestion."""

    def test_hits_below_threshold_not_promoted(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "general",
            "lesson.md",
            "Test Lesson",
            "test content",
            hits=1,
        )
        # After increment, hits = 2, still below threshold
        new_hits = _increment_hits(data_path, "level2/general/lesson.md")
        assert new_hits < PROMOTION_THRESHOLD

    def test_hits_at_threshold_triggers_promotion(
        self, tmp_path: Path
    ) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "general",
            "lesson.md",
            "Test Lesson",
            "test content",
            hits=2,
            promoted=False,
        )
        # After increment, hits = 3, at threshold
        new_hits = _increment_hits(data_path, "level2/general/lesson.md")
        assert new_hits >= PROMOTION_THRESHOLD
        assert not _is_promoted(data_path, "level2/general/lesson.md")

    def test_already_promoted_no_suggestion(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "general",
            "lesson.md",
            "Test Lesson",
            "test content",
            hits=5,
            promoted=True,
        )
        # Already promoted, so no suggestion even though hits >= 3
        assert _is_promoted(data_path, "level2/general/lesson.md")

    def test_promotion_suggestion_message_in_cli(
        self, tmp_path: Path
    ) -> None:
        """Integration-style test: search with a doc at hits=2 should
        trigger promotion suggestion after the search increments it to 3.
        """
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication",
            "always validate api tokens before processing requests",
            hits=2,
            promoted=False,
        )
        _create_l2_doc(
            data_path,
            "frontend",
            "css-tips.md",
            "CSS Tips",
            "use css grid for responsive layouts and flexbox",
            hits=0,
        )
        _create_l2_doc(
            data_path,
            "infra",
            "docker-tips.md",
            "Docker Tips",
            "use docker compose for local development kubernetes",
            hits=0,
        )

        # Build index and search
        index_data = build_index(data_path)
        results = bm25_search("api tokens validation", index_data, top_k=5)

        assert len(results) >= 1
        top_path = results[0][0]
        assert "api-auth" in top_path.replace("\\", "/")

        # Increment hits -- this simulates what the search command does
        new_hits = _increment_hits(data_path, top_path)
        assert new_hits >= PROMOTION_THRESHOLD
        assert not _is_promoted(data_path, top_path)
        # The CLI would print the promotion suggestion here


class TestIndexRebuild:
    """Test that index rebuild creates index.json."""

    def test_rebuild_creates_index_json(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication",
            "validate api tokens",
        )
        _create_l2_doc(
            data_path,
            "frontend",
            "css.md",
            "CSS Tips",
            "use grid layout",
        )

        index_data = build_index(data_path)
        index_path = data_path / "index.json"
        save_index(index_data, index_path)

        assert index_path.exists()
        loaded = load_index(index_path)
        assert len(loaded["docs"]) == 2

    def test_rebuild_from_scratch_resets_index(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        index_path = data_path / "index.json"

        # Create initial doc and index
        _create_l2_doc(
            data_path, "general", "a.md", "A", "content a"
        )
        index_data = build_index(data_path)
        save_index(index_data, index_path)
        assert len(load_index(index_path)["docs"]) == 1

        # Add another doc and rebuild
        _create_l2_doc(
            data_path, "general", "b.md", "B", "content b"
        )
        index_data = build_index(data_path)
        save_index(index_data, index_path)
        assert len(load_index(index_path)["docs"]) == 2

    def test_rebuild_empty_data_dir(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        index_data = build_index(data_path)
        index_path = data_path / "index.json"
        save_index(index_data, index_path)

        assert index_path.exists()
        loaded = load_index(index_path)
        assert len(loaded["docs"]) == 0
