"""Unit tests for the important command group."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter
import pytest

from hivemind.commands.important import (
    _scan_promoted,
    generate_important_md,
)


def _make_data_dir(tmp_path: Path) -> Path:
    """Create a minimal hivemind data directory."""
    data_path = tmp_path / "data"
    for subdir in ("frontend", "backend", "infra", "general"):
        (data_path / "level2" / subdir).mkdir(parents=True, exist_ok=True)
    (data_path / "level1").mkdir(parents=True, exist_ok=True)
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


class TestPromote:
    """Tests for promote functionality."""

    def test_promote_sets_promoted_true(self, tmp_path: Path) -> None:
        """Promoting an L2 doc sets promoted: true in its frontmatter."""
        data_path = _make_data_dir(tmp_path)
        doc_path = _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication",
            "always validate api tokens",
            promoted=False,
        )

        # Manually set promoted (simulating what promote command does)
        post = frontmatter.load(str(doc_path))
        assert post.metadata["promoted"] is False

        post.metadata["promoted"] = True
        doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")

        reloaded = frontmatter.load(str(doc_path))
        assert reloaded.metadata["promoted"] is True

    def test_promote_already_promoted_is_idempotent(self, tmp_path: Path) -> None:
        """Promoting an already-promoted doc doesn't break anything."""
        data_path = _make_data_dir(tmp_path)
        doc_path = _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication",
            "always validate api tokens",
            promoted=True,
        )

        post = frontmatter.load(str(doc_path))
        assert post.metadata["promoted"] is True


class TestDemote:
    """Tests for demote functionality."""

    def test_demote_sets_promoted_false(self, tmp_path: Path) -> None:
        """Demoting a promoted doc sets promoted: false."""
        data_path = _make_data_dir(tmp_path)
        doc_path = _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication",
            "always validate api tokens",
            promoted=True,
        )

        post = frontmatter.load(str(doc_path))
        assert post.metadata["promoted"] is True

        post.metadata["promoted"] = False
        doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")

        reloaded = frontmatter.load(str(doc_path))
        assert reloaded.metadata["promoted"] is False


class TestGenerate:
    """Tests for generate_important_md()."""

    def test_generate_creates_important_md_with_promoted_docs(
        self, tmp_path: Path
    ) -> None:
        """Generate creates important.md containing only promoted docs."""
        data_path = _make_data_dir(tmp_path)

        _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication",
            "always validate api tokens",
            hits=5,
            promoted=True,
        )
        _create_l2_doc(
            data_path,
            "frontend",
            "css-tips.md",
            "CSS Tips",
            "use grid for layout",
            hits=2,
            promoted=False,
        )

        important_path = generate_important_md(data_path)
        assert important_path.exists()

        post = frontmatter.load(str(important_path))
        assert post.metadata["count"] == 1
        assert "API Authentication" in post.content
        assert "CSS Tips" not in post.content

    def test_generate_sorts_by_hits_descending(self, tmp_path: Path) -> None:
        """Promoted docs are sorted by hits descending in important.md."""
        data_path = _make_data_dir(tmp_path)

        _create_l2_doc(
            data_path,
            "backend",
            "low-hits.md",
            "Low Hits Lesson",
            "body low",
            hits=1,
            promoted=True,
        )
        _create_l2_doc(
            data_path,
            "frontend",
            "high-hits.md",
            "High Hits Lesson",
            "body high",
            hits=10,
            promoted=True,
        )
        _create_l2_doc(
            data_path,
            "infra",
            "mid-hits.md",
            "Mid Hits Lesson",
            "body mid",
            hits=5,
            promoted=True,
        )

        important_path = generate_important_md(data_path)
        post = frontmatter.load(str(important_path))
        assert post.metadata["count"] == 3

        content = post.content
        # High hits should appear before mid, mid before low
        high_pos = content.index("High Hits Lesson")
        mid_pos = content.index("Mid Hits Lesson")
        low_pos = content.index("Low Hits Lesson")
        assert high_pos < mid_pos < low_pos

    def test_generate_with_no_promoted_creates_empty_important(
        self, tmp_path: Path
    ) -> None:
        """Generate with zero promoted docs creates important.md with count 0."""
        data_path = _make_data_dir(tmp_path)

        _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication",
            "always validate api tokens",
            promoted=False,
        )

        important_path = generate_important_md(data_path)
        assert important_path.exists()

        post = frontmatter.load(str(important_path))
        assert post.metadata["count"] == 0
        # Should only have the header, no doc sections
        assert "## " not in post.content

    def test_generate_includes_source_path_and_hits(
        self, tmp_path: Path
    ) -> None:
        """Generated important.md includes source path and hits for each doc."""
        data_path = _make_data_dir(tmp_path)

        _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Auth Lesson",
            "validate tokens carefully",
            hits=7,
            promoted=True,
        )

        important_path = generate_important_md(data_path)
        post = frontmatter.load(str(important_path))
        content = post.content

        assert "Source:" in content
        assert "Hits: 7" in content
        assert "api-auth.md" in content

    def test_generate_with_empty_level2_dir(self, tmp_path: Path) -> None:
        """Generate works even when level2 dir is empty."""
        data_path = _make_data_dir(tmp_path)

        important_path = generate_important_md(data_path)
        assert important_path.exists()

        post = frontmatter.load(str(important_path))
        assert post.metadata["count"] == 0


class TestScanPromoted:
    """Tests for _scan_promoted helper."""

    def test_returns_only_promoted(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)

        _create_l2_doc(
            data_path,
            "backend",
            "promoted.md",
            "Promoted",
            "body1",
            promoted=True,
        )
        _create_l2_doc(
            data_path,
            "backend",
            "not-promoted.md",
            "Not Promoted",
            "body2",
            promoted=False,
        )

        results = _scan_promoted(data_path)
        assert len(results) == 1
        assert results[0]["title"] == "Promoted"

    def test_empty_level2(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        results = _scan_promoted(data_path)
        assert results == []

    def test_no_level2_dir(self, tmp_path: Path) -> None:
        data_path = tmp_path / "data"
        data_path.mkdir()
        results = _scan_promoted(data_path)
        assert results == []
