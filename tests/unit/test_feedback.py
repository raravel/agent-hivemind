"""Unit tests for feedback save command, indexer, and similarity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frontmatter
import pytest

from hivemind.commands.feedback import detect_category, _create_new_doc, _slugify
from hivemind.core.indexer import build_index, load_index, save_index, search
from hivemind.core.similarity import find_similar


def _make_data_dir(tmp_path: Path) -> Path:
    """Create a minimal hivemind data directory."""
    data_path = tmp_path / "data"
    for subdir in ("frontend", "backend", "infra", "general"):
        (data_path / "level2" / subdir).mkdir(parents=True, exist_ok=True)
    (data_path / "index.json").write_text("{}\n", encoding="utf-8")
    return data_path


def _create_l2_doc(
    data_path: Path,
    category: str,
    filename: str,
    title: str,
    body: str,
    hits: int = 1,
) -> Path:
    """Create an L2 document for testing."""
    doc_path = data_path / "level2" / category / filename
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    fm: dict[str, Any] = {
        "title": title,
        "category": category,
        "hits": hits,
        "sources": [],
        "promoted": False,
        "created": "2026-03-26",
    }
    post = frontmatter.Post(body, **fm)
    doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return doc_path


class TestBuildIndex:
    """Tests for indexer.build_index()."""

    def test_empty_data_dir(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        index = build_index(data_path)
        assert index["docs"] == []

    def test_indexes_l2_files(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path, "general", "lesson.md", "Test Lesson", "some content"
        )
        index = build_index(data_path)
        assert len(index["docs"]) == 1
        assert index["docs"][0]["title"] == "Test Lesson"
        assert "path" in index["docs"][0]
        assert "tokens" in index["docs"][0]

    def test_indexes_multiple_categories(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path, "frontend", "ui.md", "UI Lesson", "react component"
        )
        _create_l2_doc(
            data_path, "backend", "api.md", "API Lesson", "rest endpoint"
        )
        index = build_index(data_path)
        assert len(index["docs"]) == 2

    def test_no_level2_dir(self, tmp_path: Path) -> None:
        data_path = tmp_path / "data"
        data_path.mkdir()
        index = build_index(data_path)
        assert index["docs"] == []


class TestSaveLoadIndex:
    """Tests for save_index and load_index."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        index_path = tmp_path / "index.json"
        index_data: dict[str, Any] = {
            "docs": [{"path": "level2/general/test.md", "title": "T", "tokens": ["a"]}]
        }
        save_index(index_data, index_path)
        loaded = load_index(index_path)
        assert loaded["docs"] == index_data["docs"]

    def test_load_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        index_path = tmp_path / "nonexistent.json"
        loaded = load_index(index_path)
        assert loaded["docs"] == []

    def test_saved_file_is_valid_json(self, tmp_path: Path) -> None:
        index_path = tmp_path / "index.json"
        save_index({"docs": []}, index_path)
        raw = index_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)


class TestSearch:
    """Tests for indexer.search()."""

    def test_finds_matching_doc(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication",
            "always validate api tokens before processing requests",
        )
        # BM25 needs multiple docs for meaningful IDF scores
        _create_l2_doc(
            data_path,
            "frontend",
            "css-tips.md",
            "CSS Tips",
            "use css grid for responsive layouts and flexbox for alignment",
        )
        _create_l2_doc(
            data_path,
            "infra",
            "docker-tips.md",
            "Docker Tips",
            "use docker compose for local development and kubernetes for production",
        )
        index = build_index(data_path)
        results = search("api tokens validation", index)
        assert len(results) >= 1
        assert results[0][0].replace("\\", "/") == "level2/backend/api-auth.md"
        assert results[0][1] > 0

    def test_empty_index_returns_empty(self) -> None:
        results = search("anything", {"docs": []})
        assert results == []

    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "frontend",
            "css.md",
            "CSS Grid Layout",
            "use css grid for responsive layouts",
        )
        index = build_index(data_path)
        results = search("kubernetes deployment helm chart", index)
        # Results may be empty or have very low scores
        high_score_results = [(p, s) for p, s in results if s >= 0.7]
        assert len(high_score_results) == 0

    def test_top_k_limits_results(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        for i in range(10):
            _create_l2_doc(
                data_path,
                "general",
                f"lesson-{i}.md",
                f"Lesson about testing {i}",
                f"testing is important for quality {i}",
            )
        index = build_index(data_path)
        results = search("testing quality", index, top_k=3)
        assert len(results) <= 3


class TestFindSimilar:
    """Tests for similarity.find_similar()."""

    def test_finds_similar_above_threshold(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "backend",
            "auth.md",
            "API Authentication",
            "always validate api tokens before processing requests authentication",
        )
        # BM25 needs multiple docs for meaningful IDF scores
        _create_l2_doc(
            data_path,
            "frontend",
            "css-tips.md",
            "CSS Grid Tips",
            "use css grid for responsive layouts and flexbox for alignment",
        )
        _create_l2_doc(
            data_path,
            "infra",
            "docker-tips.md",
            "Docker Tips",
            "use docker compose for local development and kubernetes for production",
        )
        # Query with overlapping terms should score well
        results = find_similar(
            "validate api tokens authentication", data_path, threshold=0.1
        )
        assert len(results) >= 1

    def test_no_similar_with_high_threshold(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path, "general", "test.md", "A Lesson", "short text"
        )
        results = find_similar("completely different topic", data_path, threshold=100.0)
        assert len(results) == 0

    def test_empty_data_returns_empty(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        results = find_similar("any query", data_path)
        assert results == []


class TestDetectCategory:
    """Tests for category auto-detection."""

    def test_frontend_detection(self) -> None:
        text = "Use React components with proper CSS styling for the UI"
        assert detect_category(text) == "frontend"

    def test_backend_detection(self) -> None:
        text = "The API endpoint should validate auth tokens using middleware"
        assert detect_category(text) == "backend"

    def test_infra_detection(self) -> None:
        text = "Deploy the Docker container to Kubernetes using Helm charts"
        assert detect_category(text) == "infra"

    def test_general_fallback(self) -> None:
        text = "Always write clear documentation for your team"
        assert detect_category(text) == "general"

    def test_mixed_content_picks_highest(self) -> None:
        text = "The React component calls the API endpoint"
        category = detect_category(text)
        assert category in ("frontend", "backend")


class TestCreateNewDoc:
    """Tests for creating new L2 documents."""

    def test_creates_file(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        doc_path = _create_new_doc(
            data_path,
            "My Lesson",
            "This is the lesson body.",
            "general",
            "2026-03-26",
        )
        assert doc_path.exists()

    def test_correct_frontmatter(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        doc_path = _create_new_doc(
            data_path,
            "Test Title",
            "Body content here.",
            "backend",
            "2026-03-26",
        )
        post = frontmatter.load(str(doc_path))
        assert post.metadata["title"] == "Test Title"
        assert post.metadata["category"] == "backend"
        assert post.metadata["hits"] == 1
        assert post.metadata["sources"] == []
        assert post.metadata["promoted"] is False
        assert post.metadata["created"] == "2026-03-26"
        assert post.content == "Body content here."

    def test_creates_in_correct_category_dir(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        doc_path = _create_new_doc(
            data_path,
            "Frontend Tip",
            "Use React hooks.",
            "frontend",
            "2026-03-26",
        )
        assert "level2/frontend" in str(doc_path).replace("\\", "/")

    def test_avoids_overwrite(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        doc1 = _create_new_doc(
            data_path, "Same Title", "Body 1", "general", "2026-03-26"
        )
        doc2 = _create_new_doc(
            data_path, "Same Title", "Body 2", "general", "2026-03-26"
        )
        assert doc1 != doc2
        assert doc1.exists()
        assert doc2.exists()


class TestIndexUpdateAfterSave:
    """Tests for index update after L2 document creation."""

    def test_index_reflects_new_doc(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path,
            "general",
            "new-lesson.md",
            "New Lesson",
            "something important",
        )
        index = build_index(data_path)
        index_path = data_path / "index.json"
        save_index(index, index_path)

        loaded = load_index(index_path)
        paths = [doc["path"] for doc in loaded["docs"]]
        assert "level2/general/new-lesson.md" in [
            p.replace("\\", "/") for p in paths
        ]

    def test_index_reflects_multiple_docs(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        _create_l2_doc(
            data_path, "frontend", "a.md", "A", "react component"
        )
        _create_l2_doc(
            data_path, "backend", "b.md", "B", "api endpoint"
        )
        index = build_index(data_path)
        save_index(index, data_path / "index.json")

        loaded = load_index(data_path / "index.json")
        assert len(loaded["docs"]) == 2


class TestSlugify:
    """Tests for the slugify helper."""

    def test_basic(self) -> None:
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self) -> None:
        result = _slugify("API Auth: Best Practices!")
        assert ":" not in result
        assert "!" not in result

    def test_truncates_long_strings(self) -> None:
        long_title = "a" * 100
        result = _slugify(long_title)
        assert len(result) <= 60
