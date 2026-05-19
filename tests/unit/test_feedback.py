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


# ---------------------------------------------------------------------------
# Quality gate + draft lifecycle
# ---------------------------------------------------------------------------


from hivemind.commands.feedback import (  # noqa: E402
    _draft_path,
    _load_draft_file,
    _save_draft_file,
    quality_gate,
)


class TestQualityGate:
    """Tests for the auto-draft quality gate."""

    def test_accepts_actionable_specific_lesson(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        ok, reason = quality_gate(
            "FastAPI CORS preflight needs OPTIONS handler",
            "When FastAPI returns 405 on OPTIONS requests, always add CORSMiddleware "
            "with allow_methods=['*'] before custom middleware. Preflight checks "
            "bypass the main routes and rely on the middleware chain.",
            data_path,
        )
        assert ok, reason

    def test_rejects_empty_title(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        ok, reason = quality_gate(
            "", "body must be long enough and contain actionable guidance for pytest fixtures.", data_path
        )
        assert not ok
        assert "title" in reason

    def test_rejects_too_short_content(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        ok, reason = quality_gate("Some title", "short", data_path)
        assert not ok
        assert "too vague" in reason

    def test_rejects_too_long_content(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        ok, reason = quality_gate(
            "Some title",
            "x " * 400 + "FastAPI use always",
            data_path,
        )
        assert not ok
        assert "split or shorten" in reason

    def test_rejects_no_action_verb(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        ok, reason = quality_gate(
            "Generic statement about FastAPI",
            "The FastAPI framework has a CORSMiddleware and the preflight requests "
            "might not work in certain circumstances sometimes maybe possibly.",
            data_path,
        )
        assert not ok
        assert "action verb" in reason

    def test_rejects_no_tech_token(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        ok, reason = quality_gate(
            "Generic advice",
            "Always add more stuff and use the thing and the other thing to ensure it works.",
            data_path,
        )
        assert not ok
        assert "tech token" in reason

    def test_rejects_near_duplicate(self, tmp_path: Path) -> None:
        data_path = _make_data_dir(tmp_path)
        body = (
            "When FastAPI returns 405 on OPTIONS requests, always add CORSMiddleware "
            "with allow_methods=['*'] before custom middleware. Preflight checks "
            "bypass the main routes and rely on the middleware chain."
        )
        _create_l2_doc(
            data_path, "backend", "fastapi-cors.md", "FastAPI CORS", body
        )
        # Rebuild index so find_similar sees the doc
        from hivemind.core.indexer import build_index, save_index

        idx = build_index(data_path)
        save_index(idx, data_path / "index.json")

        ok, reason = quality_gate(
            "FastAPI CORS preflight needs OPTIONS handler",
            body,
            data_path,
        )
        assert not ok
        assert "duplicate" in reason


class TestDraftStorage:
    """Tests for draft file load/save."""

    def test_draft_path_shape(self, tmp_path: Path) -> None:
        p = _draft_path(tmp_path, "PRJ-003")
        assert p.name == "PRJ-003-lessons-draft.json"
        assert "_reports" in p.parts

    def test_load_empty_returns_default(self, tmp_path: Path) -> None:
        p = _draft_path(tmp_path, "PRJ-001")
        data = _load_draft_file(p)
        assert data["drafts"] == []
        assert data["task_id"] == "PRJ-001"

    def test_roundtrip(self, tmp_path: Path) -> None:
        p = _draft_path(tmp_path, "PRJ-001")
        data = {
            "task_id": "PRJ-001",
            "created": "2026-04-21",
            "drafts": [{"title": "t", "category": "backend", "content": "c", "status": "pending"}],
        }
        _save_draft_file(p, data)
        loaded = _load_draft_file(p)
        assert loaded == data

    def test_malformed_file_returns_default(self, tmp_path: Path) -> None:
        p = _draft_path(tmp_path, "PRJ-001")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{{not json", encoding="utf-8")
        data = _load_draft_file(p)
        assert data["drafts"] == []


# ---------------------------------------------------------------------------
# CLI integration: draft-add and promote-drafts
# ---------------------------------------------------------------------------


from click.testing import CliRunner  # noqa: E402

from hivemind.commands.feedback import feedback as _feedback_group  # noqa: E402


def _setup_config(tmp_path: Path) -> Path:
    data_path = _make_data_dir(tmp_path)
    # v5: drafts live under <linked>/hivemind/tasks/_reports/
    (tmp_path / "hivemind" / "tasks" / "_reports").mkdir(parents=True, exist_ok=True)
    cfg = {
        "version": "3.0.0",
        "data_path": str(data_path),
        "projects": {"demo": {"prefix": "DM", "linked_path": str(tmp_path), "counter": 0}},
    }
    (tmp_path / ".hivemind.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8"
    )
    return data_path


def _v5_reports_dir(tmp_path: Path) -> Path:
    """Return the v5 drafts dir for the 'demo' project fixture."""
    return tmp_path / "hivemind" / "tasks" / "_reports"


class TestDraftAddCLI:
    """Deprecated stub: ``hv feedback draft-add`` redirects to ``save``."""

    def test_redirect_writes_via_save(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)

        content = (
            "When FastAPI returns 405 on OPTIONS requests, always add CORSMiddleware "
            "with allow_methods=['*'] before custom middleware. Preflight checks "
            "bypass the main routes and rely on the middleware chain."
        )
        content_file = tmp_path / "content.txt"
        content_file.write_text(content, encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            [
                "draft-add",
                "-p", "demo",
                "--task", "DM-001",
                "--title", "FastAPI CORS preflight handler",
                "-c", str(content_file),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "[deprecated]" in result.output
        # save creates the L2 doc directly (no draft file).
        l2_files = list((tmp_path / "data" / "level2").rglob("*.md"))
        assert l2_files, "save did not create an L2 document"

    def test_redirect_propagates_quality_gate_rejection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        content_file = tmp_path / "content.txt"
        content_file.write_text("short", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            [
                "draft-add",
                "-p", "demo",
                "--task", "DM-001",
                "--title", "T",
                "-c", str(content_file),
            ],
        )
        assert result.exit_code == 1
        assert "too vague" in result.output


class TestPromoteDraftsCLI:
    """Deprecated stub: drafts no longer exist; the command is a no-op."""

    def test_deprecated_banner_and_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            _feedback_group, ["promote-drafts", "-p", "demo", "--auto"]
        )
        assert result.exit_code == 0
        assert "[deprecated]" in result.output
        assert "Done. L2=0 harness=0" in result.output


# ---------------------------------------------------------------------------
# Target routing (A)
# ---------------------------------------------------------------------------


from hivemind.commands.feedback import (  # noqa: E402
    _append_to_harness_doc,
    _normalize_target,
    VALID_TARGETS,
)


class TestNormalizeTarget:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, "L2"),
            ("", "L2"),
            ("l2", "L2"),
            ("L2", "L2"),
            ("rules", "rules"),
            ("rules.md", "rules"),
            ("RULES", "rules"),
            ("tech-stack", "tech-stack"),
            ("tech_stack", "tech-stack"),
            ("techstack", "tech-stack"),
            ("architecture", "architecture"),
            ("arch", "architecture"),
            ("garbage", "L2"),
        ],
    )
    def test_normalization(self, raw: str | None, expected: str) -> None:
        assert _normalize_target(raw) == expected

    def test_all_valid_targets_declared(self) -> None:
        assert set(VALID_TARGETS) == {
            "L2",
            "rules",
            "tech-stack",
            "architecture",
            "features",
        }


class TestAppendToHarnessDoc:
    def _setup(self, tmp_path: Path, project: str = "demo") -> Path:
        """Return ``linked_path`` (v5: specs at linked_path/hivemind/docs/)."""
        spec = tmp_path / "hivemind" / "docs"
        spec.mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_creates_file_and_section_when_missing(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        path, appended = _append_to_harness_doc(
            linked, "rules", "NEVER write to /tmp", "DM-001", "2026-04-21"
        )
        assert appended is True
        text = path.read_text(encoding="utf-8")
        assert "## Learned rules" in text
        assert "- [LEARNED 2026-04-21 from DM-001] NEVER write to /tmp" in text

    def test_appends_under_existing_section(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        rules_path = linked / "hivemind" / "docs" / "rules.md"
        rules_path.write_text(
            "# Rules\n\n## Learned rules\n\n- previous entry\n", encoding="utf-8"
        )
        _, appended = _append_to_harness_doc(
            linked, "rules", "NEVER import legacy", "DM-002", "2026-04-22"
        )
        assert appended
        text = rules_path.read_text(encoding="utf-8")
        assert "- previous entry" in text
        assert "NEVER import legacy" in text

    def test_inserts_before_next_heading(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        rules_path = linked / "hivemind" / "docs" / "rules.md"
        rules_path.write_text(
            "# Rules\n\n## Learned rules\n\n- old\n\n## Other\n\nfollowup\n",
            encoding="utf-8",
        )
        _, appended = _append_to_harness_doc(
            linked, "rules", "NEVER commit secrets", "T1", "2026-01-01"
        )
        assert appended
        text = rules_path.read_text(encoding="utf-8")
        idx_bullet = text.index("NEVER commit secrets")
        idx_other = text.index("## Other")
        # New bullet inserted BEFORE the Other heading
        assert idx_bullet < idx_other

    def test_dedupes_exact_content(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        body = "NEVER import from legacy/"
        _, first = _append_to_harness_doc(
            linked, "rules", body, "DM-001", "2026-04-21"
        )
        _, second = _append_to_harness_doc(
            linked, "rules", body, "DM-002", "2026-04-22"
        )
        assert first is True
        assert second is False  # duplicate rejected

    def test_tech_stack_uses_patterns_section(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        path, _ = _append_to_harness_doc(
            linked,
            "tech-stack",
            "Pin python-frontmatter==1.1.0",
            "DM-003",
            "2026-04-21",
        )
        assert "## Learned patterns" in path.read_text(encoding="utf-8")

    def test_architecture_uses_constraints_section(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        path, _ = _append_to_harness_doc(
            linked,
            "architecture",
            "core must not import from commands",
            "DM-004",
            "2026-04-21",
        )
        assert "## Learned constraints" in path.read_text(encoding="utf-8")



# TestDraftAddWithTarget removed in v5: the draft queue is gone, so the
# target field is no longer persisted into a draft file. The equivalent
# behaviour — routing a save call to rules/architecture/tech-stack — is
# covered by TestSaveTargetRouting below.


class TestSaveTargetRouting:
    """``hv feedback save --target {rules,architecture,tech-stack}`` writes harness docs directly."""

    def _save(
        self,
        tmp_path: Path,
        task_id: str,
        title: str,
        content: str,
        target: str,
    ) -> Any:
        f = tmp_path / f"{title.replace(' ', '_')}.txt"
        f.write_text(content, encoding="utf-8")
        runner = CliRunner()
        return runner.invoke(
            _feedback_group,
            [
                "save",
                "-p", "demo",
                "--task", task_id,
                "--title", title,
                "-c", str(f),
                "--target", target,
            ],
        )

    def test_routes_to_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        (tmp_path / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)

        result = self._save(
            tmp_path,
            "DM-001",
            "never-import-legacy",
            "NEVER import from src/legacy/ in any FastAPI router — scheduled for Q3 removal.",
            "rules",
        )
        assert result.exit_code == 0, result.output
        rules_md = tmp_path / "hivemind" / "docs" / "rules.md"
        assert rules_md.exists()
        text = rules_md.read_text(encoding="utf-8")
        assert "## Learned rules" in text
        assert "NEVER import from src/legacy/" in text

    def test_routes_to_architecture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        (tmp_path / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)

        result = self._save(
            tmp_path,
            "DM-002",
            "core-isolation",
            "hivemind.core must not import from hivemind.commands — enforce one-way dependency.",
            "architecture",
        )
        assert result.exit_code == 0, result.output
        arch_md = tmp_path / "hivemind" / "docs" / "architecture.md"
        assert arch_md.exists()
        assert "## Learned constraints" in arch_md.read_text(encoding="utf-8")

    def test_duplicate_harness_append_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        (tmp_path / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)

        body = (
            "NEVER set DEBUG=True in production config.py — it leaks secret "
            "keys into error pages and bypasses auth middleware."
        )
        r1 = self._save(tmp_path, "DM-001", "no-debug-prod-a", body, "rules")
        r2 = self._save(tmp_path, "DM-002", "no-debug-prod-b", body, "rules")
        assert r1.exit_code == 0, r1.output
        assert r2.exit_code == 0, r2.output
        rules_md = tmp_path / "hivemind" / "docs" / "rules.md"
        occurrences = rules_md.read_text(encoding="utf-8").count(body)
        assert occurrences == 1  # deduped


# ---------------------------------------------------------------------------
# Binding sync (Phase 2): features target, section override, auto-promote
# ---------------------------------------------------------------------------


from hivemind.commands.feedback import (  # noqa: E402
    _BINDING_COMBOS,
    _is_binding,
    _normalize_section_heading,
    _resolve_feature_path,
)


class TestSectionAndBindingHelpers:
    def test_normalize_section_heading_adds_prefix(self) -> None:
        assert _normalize_section_heading("Active Dependencies") == "## Active Dependencies"

    def test_normalize_section_heading_keeps_existing_prefix(self) -> None:
        assert _normalize_section_heading("## Active Dependencies") == "## Active Dependencies"

    def test_normalize_section_heading_handles_none_and_empty(self) -> None:
        assert _normalize_section_heading(None) is None
        assert _normalize_section_heading("   ") is None

    def test_is_binding_features_always_true(self) -> None:
        assert _is_binding("features", None) is True
        assert _is_binding("features", "## Implementation") is True

    def test_is_binding_tech_stack_requires_active_deps_section(self) -> None:
        assert _is_binding("tech-stack", "## Active Dependencies") is True
        assert _is_binding("tech-stack", "Active Dependencies") is True
        assert _is_binding("tech-stack", None) is False
        assert _is_binding("tech-stack", "## Learned patterns") is False

    def test_is_binding_other_targets_false(self) -> None:
        assert _is_binding("rules", "## Anything") is False
        assert _is_binding("architecture", "## Active Dependencies") is False
        assert _is_binding("L2", None) is False

    def test_binding_combos_constant(self) -> None:
        assert ("features", "## Implementation") in _BINDING_COMBOS
        assert ("tech-stack", "## Active Dependencies") in _BINDING_COMBOS


class TestResolveFeaturePath:
    def _setup(self, tmp_path: Path) -> Path:
        """Return ``linked_path`` with hivemind/docs/features ready (v5)."""
        features = tmp_path / "hivemind" / "docs" / "features"
        features.mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_match_planner_convention(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        target = linked / "hivemind" / "docs" / "features" / "00_multi-assign.md"
        target.write_text("# Feature\n", encoding="utf-8")
        assert _resolve_feature_path(linked, "multi-assign") == target

    def test_match_plain_slug(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        target = linked / "hivemind" / "docs" / "features" / "deadlines.md"
        target.write_text("# Feature\n", encoding="utf-8")
        assert _resolve_feature_path(linked, "deadlines") == target

    def test_none_when_missing(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        assert _resolve_feature_path(linked, "ghost") is None

    def test_none_when_ambiguous(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        d = linked / "hivemind" / "docs" / "features"
        (d / "00_assign.md").write_text("", encoding="utf-8")
        (d / "01_assign-list.md").write_text("", encoding="utf-8")
        # slug "assign" matches both stems
        assert _resolve_feature_path(linked, "assign") is None


class TestAppendToHarnessDocWithBindingKwargs:
    def _setup(self, tmp_path: Path) -> Path:
        (tmp_path / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_section_override_changes_heading(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        path, appended = _append_to_harness_doc(
            linked,
            "tech-stack",
            "express ^5.1.0 — HTTP server",
            "DM-100",
            "2026-05-11",
            section="Active Dependencies",
            kind="BOUND",
        )
        assert appended
        text = path.read_text(encoding="utf-8")
        assert "## Active Dependencies" in text
        assert "## Learned patterns" not in text
        assert "[BOUND 2026-05-11 from DM-100]" in text

    def test_features_target_writes_to_resolved_feature(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        features = linked / "hivemind" / "docs" / "features"
        features.mkdir(parents=True)
        feature_file = features / "00_multi-assign.md"
        feature_file.write_text("# Feature\n", encoding="utf-8")

        path, appended = _append_to_harness_doc(
            linked,
            "features",
            "`views/target/js/assign.js` — primary UI",
            "DM-200",
            "2026-05-11",
            feature_slug="multi-assign",
            kind="BOUND",
        )
        assert appended
        assert path == feature_file
        text = feature_file.read_text(encoding="utf-8")
        assert "## Implementation" in text
        assert "[BOUND 2026-05-11 from DM-200]" in text
        assert "`views/target/js/assign.js`" in text

    def test_features_target_requires_slug(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        with pytest.raises(ValueError, match="feature_slug is required"):
            _append_to_harness_doc(
                linked, "features", "x", "DM-1", "2026-05-11"
            )

    def test_features_target_rejects_unresolved_slug(self, tmp_path: Path) -> None:
        linked = self._setup(tmp_path)
        (linked / "hivemind" / "docs" / "features").mkdir(parents=True)
        with pytest.raises(ValueError, match="did not match exactly one"):
            _append_to_harness_doc(
                linked,
                "features",
                "x",
                "DM-1",
                "2026-05-11",
                feature_slug="ghost",
            )


class TestSaveBindingCLI:
    """``hv feedback save`` auto-detects binding combinations and bypasses the quality gate."""

    def _write(self, tmp_path: Path, body: str) -> Path:
        f = tmp_path / "c.txt"
        f.write_text(body, encoding="utf-8")
        return f

    def test_features_requires_feature_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        content = self._write(tmp_path, "`src/foo.py` — primary impl")
        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            [
                "save",
                "-p", "demo",
                "--task", "DM-001",
                "--title", "Impl: foo.py",
                "-c", str(content),
                "--target", "features",
            ],
        )
        assert result.exit_code == 2
        assert "--feature is required" in result.output

    def test_feature_flag_outside_features_target_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        content = self._write(tmp_path, "some content")
        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            [
                "save",
                "-p", "demo",
                "--task", "DM-001",
                "--title", "x",
                "-c", str(content),
                "--target", "rules",
                "--feature", "foo",
            ],
        )
        assert result.exit_code == 2
        assert "--feature is only valid" in result.output

    def test_features_writes_to_feature_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        features = tmp_path / "hivemind" / "docs" / "features"
        features.mkdir(parents=True)
        feature_file = features / "00_multi-assign.md"
        feature_file.write_text("# Multi assign\n", encoding="utf-8")

        content = self._write(tmp_path, "`views/target/js/assign.js` — primary UI")
        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            [
                "save",
                "-p", "demo",
                "--task", "DM-001",
                "--title", "Impl: assign.js",
                "-c", str(content),
                "--target", "features",
                "--feature", "multi-assign",
            ],
        )
        assert result.exit_code == 0, result.output
        text = feature_file.read_text(encoding="utf-8")
        assert "## Implementation" in text
        assert "[BOUND" in text
        assert "`views/target/js/assign.js`" in text

    def test_tech_stack_active_deps_writes_correct_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        (tmp_path / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)

        content = self._write(tmp_path, "express ^5.1.0 — HTTP server")
        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            [
                "save",
                "-p", "demo",
                "--task", "DM-002",
                "--title", "Add dep: express",
                "-c", str(content),
                "--target", "tech-stack",
                "--section", "Active Dependencies",
            ],
        )
        assert result.exit_code == 0, result.output
        tech = (tmp_path / "hivemind" / "docs" / "tech-stack.md").read_text(
            encoding="utf-8"
        )
        assert "## Active Dependencies" in tech
        # The default Learned patterns section is NOT created for this binding write.
        assert "## Learned patterns" not in tech
        assert "express ^5.1.0" in tech

    def test_binding_skips_quality_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare file path lacks action verbs — would fail the lesson gate but binding bypasses."""
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        features = tmp_path / "hivemind" / "docs" / "features"
        features.mkdir(parents=True)
        (features / "00_things.md").write_text("# Things\n", encoding="utf-8")

        content = self._write(tmp_path, "`src/foo.py`")
        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            [
                "save",
                "-p", "demo",
                "--task", "DM-003",
                "--title", "Impl: src/foo.py",
                "-c", str(content),
                "--target", "features",
                "--feature", "things",
            ],
        )
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# New CLI surface: applied / rollback / lesson-log
# ---------------------------------------------------------------------------


from hivemind.commands.feedback import (  # noqa: E402
    _iter_lesson_log,
)
from hivemind.core.paths import lesson_log_path  # noqa: E402


class TestSaveAppendsLessonLog:
    """save records every successful write to ``hivemind/reflect/lesson-log.jsonl``."""

    def test_harness_target_logs_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        (tmp_path / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)

        content_file = tmp_path / "c.txt"
        content_file.write_text(
            "NEVER import from `src/legacy/` in any FastAPI router — scheduled for Q3 removal.",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            [
                "save",
                "-p", "demo",
                "--task", "DM-100",
                "--title", "NEVER import legacy",
                "-c", str(content_file),
                "--target", "rules",
            ],
        )
        assert result.exit_code == 0, result.output

        log_path = lesson_log_path(tmp_path)
        assert log_path.exists()
        lines = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        assert len(lines) == 1
        assert lines[0]["task_id"] == "DM-100"
        assert lines[0]["target"] == "rules"
        assert lines[0]["is_binding"] is False
        assert lines[0]["kind"] == "LEARNED"
        assert lines[0]["commit_repo"] == "linked"

    def test_binding_target_logs_bound_kind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        features = tmp_path / "hivemind" / "docs" / "features"
        features.mkdir(parents=True)
        (features / "00_things.md").write_text("# Things\n", encoding="utf-8")

        content_file = tmp_path / "c.txt"
        content_file.write_text("`src/foo.py`", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            [
                "save",
                "-p", "demo",
                "--task", "DM-200",
                "--title", "Impl: foo.py",
                "-c", str(content_file),
                "--target", "features",
                "--feature", "things",
            ],
        )
        assert result.exit_code == 0, result.output
        entries = _iter_lesson_log(tmp_path)
        assert len(entries) == 1
        assert entries[0]["is_binding"] is True
        assert entries[0]["kind"] == "BOUND"
        assert entries[0]["target"] == "features"


class TestAppliedCLI:
    """``hv feedback applied`` lists lesson-log entries."""

    def _seed_log(self, tmp_path: Path, count: int) -> None:
        log = lesson_log_path(tmp_path)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w", encoding="utf-8") as fh:
            for i in range(count):
                entry = {
                    "ts": f"2026-05-15T0{i}:00:00+00:00",
                    "task_id": f"DM-{i:03d}",
                    "title": f"lesson {i}",
                    "target": "rules",
                    "file_path": "x",
                    "commit_hash": f"abc{i:04d}deadbeef",
                    "commit_repo": "linked",
                    "is_binding": False,
                    "kind": "LEARNED",
                }
                fh.write(json.dumps(entry) + "\n")

    def test_default_limit_returns_last_n(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        self._seed_log(tmp_path, 15)

        runner = CliRunner()
        result = runner.invoke(
            _feedback_group, ["applied", "-p", "demo", "--limit", "3", "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert len(parsed) == 3
        assert parsed[-1]["task_id"] == "DM-014"

    def test_since_task_filters(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        self._seed_log(tmp_path, 5)

        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            ["applied", "-p", "demo", "--since-task", "DM-001", "--format", "json"],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert [e["task_id"] for e in parsed] == ["DM-002", "DM-003", "DM-004"]

    def test_no_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        runner = CliRunner()
        result = runner.invoke(_feedback_group, ["applied", "-p", "demo"])
        assert result.exit_code == 0
        assert "No applied lessons" in result.output


class TestRollbackCLI:
    """``hv feedback rollback`` resolves entries by --task or --commit."""

    def _seed_log(self, tmp_path: Path) -> dict[str, Any]:
        log = lesson_log_path(tmp_path)
        log.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": "2026-05-15T00:00:00+00:00",
            "task_id": "DM-999",
            "title": "test lesson",
            "target": "rules",
            "file_path": "x",
            "commit_hash": "deadbeefcafe",
            "commit_repo": "linked",
            "is_binding": False,
            "kind": "LEARNED",
        }
        log.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        return entry

    def test_requires_task_or_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        runner = CliRunner()
        result = runner.invoke(_feedback_group, ["rollback", "-p", "demo"])
        assert result.exit_code == 2
        assert "pass --task or --commit" in result.output

    def test_dry_run_matches_without_reverting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        self._seed_log(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            ["rollback", "-p", "demo", "--commit", "deadbeefcafe", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert "Match: deadbeefcafe" in result.output
        assert "dry-run" in result.output

        # rollback-log.jsonl should NOT have been written
        rb = tmp_path / "hivemind" / "reflect" / "rollback-log.jsonl"
        assert not rb.exists() or rb.read_text(encoding="utf-8").strip() == ""

    def test_unknown_commit_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_config(tmp_path)
        self._seed_log(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            _feedback_group,
            ["rollback", "-p", "demo", "--commit", "doesnotexist"],
        )
        assert result.exit_code == 1
        assert "No matching lesson-log entry" in result.output
