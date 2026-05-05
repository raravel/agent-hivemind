"""End-to-end integration tests for the agent-hivemind CLI workflow.

Each test uses a fresh tmp_path for full data isolation.
Commands are invoked through Click's CliRunner, and data_path resolution
is handled by placing .hivemind.json in the test working directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import frontmatter
from click.testing import CliRunner

from hivemind.__main__ import cli
from hivemind.commands.init import init_data_dir
from hivemind.core.config import HivemindConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_installers(config_path: Path, **kwargs: Any) -> dict[str, Any]:
    """Stub for ``run_installers`` that skips real Claude Code integration."""
    return {
        "skills": [],
        "skills_skipped": True,
        "hooks": False,
        "profiles": False,
    }


def _init_workspace(data_path: Path) -> Path:
    """Create a fully initialised hivemind data directory.

    Returns the path to .hivemind.json (inside data_path).
    """
    init_data_dir(data_path)
    config_path = data_path / ".hivemind.json"
    assert config_path.exists()
    return config_path


def _register_project(
    data_path: Path,
    project: str,
    *,
    prefix: str = "TST",
    linked_path: str = "",
) -> None:
    """Register a project in .hivemind.json and create its directories."""
    config_path = data_path / ".hivemind.json"
    cfg = HivemindConfig.load(config_path)
    cfg.set_project(project, prefix, linked_path)
    cfg.save()

    for d in (
        data_path / "projects" / project,
        data_path / "tasks" / project,
        data_path / "tasks" / project / "_reports",
        data_path / "level3" / project,
    ):
        d.mkdir(parents=True, exist_ok=True)


def _invoke(
    args: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
) -> Any:
    """Invoke the top-level ``cli`` group with cwd set to *cwd*.

    This ensures commands that search for ``.hivemind.json`` in ``Path.cwd()``
    find the right file.
    """
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(cwd)
        return runner.invoke(cli, args, input=input_text, catch_exceptions=False)
    finally:
        os.chdir(old_cwd)


def _create_l2_doc(
    data_path: Path,
    category: str,
    filename: str,
    title: str,
    body: str,
    *,
    hits: int = 1,
    promoted: bool = False,
) -> Path:
    """Create an L2 document with frontmatter."""
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


# ---------------------------------------------------------------------------
# a. Init + Link flow
# ---------------------------------------------------------------------------


class TestInitAndLink:
    """Verify ``hv init`` creates directories and ``hv link`` registers a project."""

    def test_init_creates_structure(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        with patch(
            "hivemind.commands.init.run_installers",
            side_effect=_noop_installers,
        ):
            result = _invoke(["init", "--path", str(data_path)], cwd=tmp_path)

        assert result.exit_code == 0, result.output

        # Core directories
        for d in ("projects", "tasks", "level1", "level2", "level3"):
            assert (data_path / d).is_dir(), f"Missing directory: {d}"

        # level2 subdirectories
        for sub in ("frontend", "backend", "infra", "general"):
            assert (data_path / "level2" / sub).is_dir()

        # Files
        assert (data_path / "level1" / "important.md").is_file()
        assert (data_path / "index.json").is_file()
        assert (data_path / ".hivemind.json").is_file()

    def test_link_registers_project(self, tmp_path: Path) -> None:
        # 1. Init data directory
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)

        # 2. Create a fake project directory
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        # Place .hivemind.json in the project dir so _find_config finds it
        # (by copying from data_path or writing a pointer)
        cfg_source = data_path / ".hivemind.json"
        cfg_data = json.loads(cfg_source.read_text(encoding="utf-8"))
        cfg_data["data_path"] = str(data_path)
        (project_dir / ".hivemind.json").write_text(
            json.dumps(cfg_data, indent=2), encoding="utf-8"
        )

        result = _invoke(["link", "--name", "test-project"], cwd=project_dir)
        assert result.exit_code == 0, result.output
        assert "test-project" in result.output

        # Verify .hivemind-link.json was created
        link_file = project_dir / ".hivemind-link.json"
        assert link_file.exists()
        link_data = json.loads(link_file.read_text(encoding="utf-8"))
        assert link_data["project"] == "test-project"

        # Verify project directories created in data repo
        assert (data_path / "projects" / "test-project").is_dir()
        assert (data_path / "tasks" / "test-project").is_dir()

        # Verify project registered in .hivemind.json
        # link_cmd writes to the config it found (in project_dir cwd)
        cfg = HivemindConfig.load(project_dir / ".hivemind.json")
        assert cfg.get_project("test-project") is not None


# ---------------------------------------------------------------------------
# b. Task lifecycle
# ---------------------------------------------------------------------------


class TestTaskLifecycle:
    """Create, list, get, update, and next operations on tasks."""

    def test_full_task_lifecycle(self, tmp_path: Path) -> None:
        # Setup workspace
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)
        _register_project(data_path, "test-project")

        # Set data_path in config so _find_config resolves correctly
        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        cfg.set("data_path", str(data_path))
        cfg.save()

        # --- Create task ---
        result = _invoke(
            [
                "task", "create",
                "--project", "test-project",
                "--title", "Test task",
                "--type", "task",
                "--priority", "high",
            ],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "Created task:" in result.output
        # Extract task ID from output (e.g. "Created task: TST-001")
        task_id = result.output.split("Created task:")[1].strip().split("\n")[0].strip()

        # --- List tasks ---
        result = _invoke(
            ["task", "list", "--project", "test-project"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert task_id in result.output
        assert "Test task" in result.output

        # --- Get task ---
        result = _invoke(
            ["task", "get", task_id],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "Test task" in result.output
        assert "pending" in result.output

        # --- Update task ---
        result = _invoke(
            ["task", "update", task_id, "--status", "in_progress"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "Updated task:" in result.output
        assert "in_progress" in result.output

        # Verify update persisted
        result = _invoke(
            ["task", "get", task_id, "--format", "json"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        task_data = json.loads(result.output)
        assert task_data["status"] == "in_progress"

        # --- Next task (reset to pending first) ---
        result = _invoke(
            ["task", "update", task_id, "--status", "pending"],
            cwd=data_path,
        )
        assert result.exit_code == 0

        result = _invoke(
            ["task", "next", "--project", "test-project"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert task_id in result.output
        assert "Next task:" in result.output


# ---------------------------------------------------------------------------
# c. Run flow
# ---------------------------------------------------------------------------


class TestRunFlow:
    """Verify ``hv run`` returns task content for the pipeline."""

    def test_run_returns_task_json(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)
        _register_project(data_path, "test-project")

        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        cfg.set("data_path", str(data_path))
        cfg.save()

        # Create a task
        result = _invoke(
            [
                "task", "create",
                "--project", "test-project",
                "--title", "Run test task",
                "--type", "task",
                "--priority", "high",
            ],
            cwd=data_path,
        )
        assert result.exit_code == 0

        # Run with JSON format
        result = _invoke(
            ["run", "--project", "test-project", "--format", "json"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        run_data = json.loads(result.output)
        assert "id" in run_data
        assert "frontmatter" in run_data
        assert run_data["frontmatter"]["title"] == "Run test task"

    def test_run_text_format(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)
        _register_project(data_path, "test-project")

        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        cfg.set("data_path", str(data_path))
        cfg.save()

        _invoke(
            [
                "task", "create",
                "--project", "test-project",
                "--title", "Text format task",
                "--type", "task",
                "--priority", "medium",
            ],
            cwd=data_path,
        )

        result = _invoke(
            ["run", "--project", "test-project"],
            cwd=data_path,
        )
        assert result.exit_code == 0
        assert "Text format task" in result.output
        assert "---" in result.output


# ---------------------------------------------------------------------------
# d. Feedback flow
# ---------------------------------------------------------------------------


class TestFeedbackFlow:
    """Verify ``hv feedback save`` creates L2 documents and updates the index."""

    def test_feedback_save_creates_l2_doc(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)
        _register_project(data_path, "test-project")

        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        cfg.set("data_path", str(data_path))
        cfg.save()

        # Create a content file
        content_file = tmp_path / "lesson.txt"
        content_file.write_text(
            "Always validate API input before processing server requests",
            encoding="utf-8",
        )

        result = _invoke(
            [
                "feedback", "save",
                "--project", "test-project",
                "--content", str(content_file),
                "--title", "API input validation",
            ],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "Created new lesson:" in result.output or "Updated existing lesson:" in result.output
        assert "Index updated." in result.output

        # Verify index.json was updated (non-empty)
        index_path = data_path / "index.json"
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
        assert "docs" in index_data
        assert len(index_data["docs"]) > 0

        # Verify an L2 file exists
        l2_files = list((data_path / "level2").rglob("*.md"))
        assert len(l2_files) >= 1


# ---------------------------------------------------------------------------
# e. Search flow
# ---------------------------------------------------------------------------


class TestSearchFlow:
    """Verify ``hv search`` returns results and increments hits."""

    def test_search_returns_results(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)

        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        cfg.set("data_path", str(data_path))
        cfg.save()

        # BM25 requires multiple documents to produce positive IDF scores.
        # Create at least 3 L2 docs so the target doc scores positively.
        _create_l2_doc(
            data_path,
            "general",
            "test-lesson.md",
            "Testing lesson about validation",
            "Always validate inputs in integration tests.",
        )
        _create_l2_doc(
            data_path,
            "general",
            "unrelated-cooking.md",
            "Cooking tips",
            "Use fresh ingredients when cooking meals.",
        )
        _create_l2_doc(
            data_path,
            "general",
            "unrelated-gardening.md",
            "Gardening guide",
            "Water your plants regularly for best growth.",
        )

        # Build index first
        result = _invoke(["index", "rebuild"], cwd=data_path)
        assert result.exit_code == 0

        # Search with --auto-read (high relevance docs get read + hits incremented)
        result = _invoke(
            ["search", "--auto-read", "validate inputs"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "test-lesson" in result.output or "validation" in result.output.lower()

        # Verify hits incremented (auto-read increments hits)
        doc_path = data_path / "level2" / "general" / "test-lesson.md"
        post = frontmatter.load(str(doc_path))
        assert post.metadata["hits"] >= 2  # was 1, now incremented by auto-read


# ---------------------------------------------------------------------------
# f. Important flow
# ---------------------------------------------------------------------------


class TestImportantFlow:
    """Verify promote, generate, and demote operations."""

    def test_promote_and_generate(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)

        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        cfg.set("data_path", str(data_path))
        cfg.save()

        # Create an L2 doc
        _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication Patterns",
            "Always use JWT tokens for stateless API auth.",
            hits=5,
        )

        # Use forward-slash relative path for the promote command
        l2_rel = "level2/backend/api-auth.md"

        # --- Promote ---
        result = _invoke(
            ["important", "promote", l2_rel],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "Promoted:" in result.output

        # Verify promoted flag set
        doc_path = data_path / "level2" / "backend" / "api-auth.md"
        post = frontmatter.load(str(doc_path))
        assert post.metadata["promoted"] is True

        # --- Generate ---
        result = _invoke(
            ["important", "generate"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "Generated:" in result.output

        # Verify level1/important.md exists and contains our lesson
        important_path = data_path / "level1" / "important.md"
        assert important_path.exists()
        content = important_path.read_text(encoding="utf-8")
        assert "API Authentication Patterns" in content

    def test_demote(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)

        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        cfg.set("data_path", str(data_path))
        cfg.save()

        # BM25 needs multiple documents for positive scores.
        # Create several promoted L2 docs so the demote search works.
        _create_l2_doc(
            data_path,
            "backend",
            "api-auth.md",
            "API Authentication Patterns",
            "Always use JWT tokens for stateless API auth.",
            hits=5,
            promoted=True,
        )
        _create_l2_doc(
            data_path,
            "frontend",
            "react-hooks.md",
            "React Hooks Best Practices",
            "Use custom hooks for reusable stateful logic in React.",
            hits=3,
            promoted=True,
        )
        _create_l2_doc(
            data_path,
            "infra",
            "docker-tips.md",
            "Docker Container Tips",
            "Use multi-stage builds to reduce Docker image size.",
            hits=4,
            promoted=True,
        )

        # Build index
        _invoke(["index", "rebuild"], cwd=data_path)

        # --- Demote the API auth doc ---
        result = _invoke(
            ["important", "demote", "--yes", "API Authentication JWT"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "Demoted:" in result.output

        # Verify promoted flag unset on the target doc
        doc_path = data_path / "level2" / "backend" / "api-auth.md"
        post = frontmatter.load(str(doc_path))
        assert post.metadata["promoted"] is False


# ---------------------------------------------------------------------------
# g. Config flow
# ---------------------------------------------------------------------------


class TestConfigFlow:
    """Verify ``hv config`` get and set operations."""

    def test_config_get_and_set(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)

        config_path = data_path / ".hivemind.json"

        # Patch _resolve_config_path to use our test path
        with patch(
            "hivemind.commands.config_cmd._resolve_config_path",
            return_value=config_path,
        ):
            # Get current model_profile (both providers)
            result = _invoke(["config", "model_profile"], cwd=data_path)
            assert result.exit_code == 0, result.output
            assert "[claude]" in result.output
            assert "[codex]" in result.output
            assert "balanced" in result.output

            # Set model_profile to quality for claude only
            result = _invoke(
                ["config", "model_profile", "quality", "--target", "claude"],
                cwd=data_path,
            )
            assert result.exit_code == 0, result.output
            assert "quality" in result.output

            # Verify persisted: claude=quality, codex untouched
            result = _invoke(
                ["config", "model_profile", "--target", "claude"],
                cwd=data_path,
            )
            assert result.exit_code == 0
            assert result.output.strip() == "quality"

            result = _invoke(
                ["config", "model_profile", "--target", "codex"],
                cwd=data_path,
            )
            assert result.exit_code == 0
            assert result.output.strip() == "balanced"

            # Setting without --target must error
            result = _invoke(
                ["config", "model_profile", "budget"],
                cwd=data_path,
            )
            assert result.exit_code != 0
            assert "--target" in result.output

    def test_config_dump_full(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)
        config_path = data_path / ".hivemind.json"

        with patch(
            "hivemind.commands.config_cmd._resolve_config_path",
            return_value=config_path,
        ):
            result = _invoke(["config"], cwd=data_path)
            assert result.exit_code == 0
            parsed = json.loads(result.output)
            assert parsed["version"] == "4.0.0"
            assert "profiles" in parsed


# ---------------------------------------------------------------------------
# h. Stats flow
# ---------------------------------------------------------------------------


class TestStatsFlow:
    """Verify ``hv stats`` aggregates report data."""

    def test_stats_with_reports(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)
        _register_project(data_path, "test-project")

        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        cfg.set("data_path", str(data_path))
        cfg.save()

        # Create sample report files
        reports_dir = data_path / "tasks" / "test-project" / "_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        for i, (dur, retries, review, lint) in enumerate(
            [
                (30, 1, True, False),
                (45, 0, True, False),
                (60, 2, False, True),
            ],
            start=1,
        ):
            fm: dict[str, Any] = {
                "task_id": f"TST-{i:03d}",
                "status": "completed",
                "duration_minutes": dur,
                "retries": retries,
                "review_passed": review,
                "lint_failed": lint,
                "completed_at": f"2026-03-{20 + i:02d}T12:00:00",
            }
            post = frontmatter.Post("", **fm)
            report_path = reports_dir / f"TST-{i:03d}.md"
            report_path.write_text(frontmatter.dumps(post), encoding="utf-8")

        result = _invoke(
            ["stats", "--project", "test-project"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "Stats: test-project" in result.output
        assert "Total tasks" in result.output
        # 3 reports
        assert "3" in result.output

    def test_stats_no_reports(self, tmp_path: Path) -> None:
        data_path = tmp_path / "hv-data"
        _init_workspace(data_path)
        _register_project(data_path, "empty-project")

        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        cfg.set("data_path", str(data_path))
        cfg.save()

        result = _invoke(
            ["stats", "--project", "empty-project"],
            cwd=data_path,
        )
        assert result.exit_code == 0, result.output
        assert "No execution reports found" in result.output
