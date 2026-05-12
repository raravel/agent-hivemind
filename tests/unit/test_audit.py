"""Unit tests for hivemind.commands.audit."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from hivemind.commands.audit import (
    _extract_referenced_modules,
    _find_stale_tasks,
    _load_spec_files,
    audit,
)
from hivemind.core.parser import create_task_file


def _make_workspace(
    tmp_path: Path,
    projects: dict[str, dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    """Create a minimal workspace with .hivemind.json and data dirs.

    Returns (config_path, data_path).
    """
    data_path = tmp_path / "data"
    data_path.mkdir(exist_ok=True)
    (data_path / "tasks").mkdir(exist_ok=True)
    (data_path / "projects").mkdir(exist_ok=True)

    if projects is None:
        projects = {
            "myproj": {
                "prefix": "MP",
                "linked_path": str(tmp_path / "code"),
                "counter": 0,
            }
        }

    config_data = {
        "version": "2.0.0",
        "data_path": str(data_path),
        "projects": projects,
    }

    config_path = tmp_path / ".hivemind.json"
    config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    return config_path, data_path


def _invoke(tmp_path: Path, args: list[str]) -> Any:
    """Invoke audit CLI with cwd set to tmp_path."""
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(audit, args)
    finally:
        os.chdir(old_cwd)


def _create_spec_file(data_path: Path, project: str, name: str, content: str) -> Path:
    """Create a spec markdown file at the v5 location: ``<linked>/hivemind/docs/``.

    Note: ``data_path`` arg is preserved for backward-compat with callers but
    the test fixtures need ``linked_path`` for v5. The fixture's linked_path
    is derived from data_path's parent (``tmp_path``) per ``_make_workspace``.
    """
    # _make_workspace puts linked_path at tmp_path/code; data_path at tmp_path/data
    linked_path = data_path.parent / "code"
    spec_dir = linked_path / "hivemind" / "docs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_file = spec_dir / name
    spec_file.write_text(content, encoding="utf-8")
    return spec_file


def _create_task_with_fm(
    data_path: Path,
    project: str,
    task_id: str,
    status: str = "pending",
    updated: str | None = None,
) -> Path:
    """Create a task file under the v5 location ``<linked>/hivemind/tasks/``.

    The ``project`` arg is retained for call-site clarity; the location is
    derived from the standard fixture (linked_path = ``data_path.parent/code``).
    """
    del project  # noqa: F841 — kept for call-site clarity
    if updated is None:
        updated = date.today().isoformat()
    fm: dict[str, object] = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": status,
        "priority": "medium",
        "type": "task",
        "created": updated,
        "updated": updated,
    }
    linked_path = data_path.parent / "code"
    task_path = linked_path / "hivemind" / "tasks" / f"{task_id}.md"
    create_task_file(task_path, fm, "")
    return task_path


class TestExtractReferencedModules:
    """Tests for _extract_referenced_modules."""

    def test_extracts_backtick_refs(self, tmp_path: Path) -> None:
        spec = tmp_path / "test.md"
        spec.write_text("Refer to `src/main.py` and `lib/utils.js`.", encoding="utf-8")
        refs = _extract_referenced_modules(spec)
        assert "src/main.py" in refs
        assert "lib/utils.js" in refs

    def test_extracts_bare_path_refs(self, tmp_path: Path) -> None:
        spec = tmp_path / "test.md"
        spec.write_text("The module src/core/engine.py handles this.", encoding="utf-8")
        refs = _extract_referenced_modules(spec)
        assert "src/core/engine.py" in refs

    def test_no_duplicates(self, tmp_path: Path) -> None:
        spec = tmp_path / "test.md"
        spec.write_text("`src/a.py` and src/a.py again.", encoding="utf-8")
        refs = _extract_referenced_modules(spec)
        assert refs.count("src/a.py") == 1

    def test_empty_file(self, tmp_path: Path) -> None:
        spec = tmp_path / "test.md"
        spec.write_text("", encoding="utf-8")
        refs = _extract_referenced_modules(spec)
        assert refs == []


class TestFindStaleTasks:
    """Tests for _find_stale_tasks."""

    def test_finds_stale_done_tasks(self, tmp_path: Path) -> None:
        today = date(2026, 3, 26)
        old_date = (today - timedelta(days=45)).isoformat()
        fm: dict[str, object] = {
            "id": "MP-001",
            "title": "Old task",
            "status": "done",
            "priority": "medium",
            "type": "task",
            "updated": old_date,
        }
        stale = _find_stale_tasks([(fm, "", tmp_path / "fake.md")], today=today)
        assert len(stale) == 1
        assert stale[0][0] == "MP-001"
        assert stale[0][1] == 45

    def test_ignores_recent_done_tasks(self, tmp_path: Path) -> None:
        today = date(2026, 3, 26)
        recent_date = (today - timedelta(days=10)).isoformat()
        fm: dict[str, object] = {
            "id": "MP-002",
            "title": "Recent task",
            "status": "done",
            "priority": "medium",
            "type": "task",
            "updated": recent_date,
        }
        stale = _find_stale_tasks([(fm, "", tmp_path / "fake.md")], today=today)
        assert len(stale) == 0

    def test_ignores_non_done_tasks(self, tmp_path: Path) -> None:
        today = date(2026, 3, 26)
        old_date = (today - timedelta(days=45)).isoformat()
        fm: dict[str, object] = {
            "id": "MP-003",
            "title": "In progress task",
            "status": "in_progress",
            "priority": "medium",
            "type": "task",
            "updated": old_date,
        }
        stale = _find_stale_tasks([(fm, "", tmp_path / "fake.md")], today=today)
        assert len(stale) == 0


class TestLoadSpecFiles:
    """Tests for _load_spec_files (v5: reads from linked_path/hivemind/docs)."""

    def test_loads_spec_files(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "hivemind" / "docs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "feature-a.md").write_text("content", encoding="utf-8")
        (spec_dir / "feature-b.md").write_text("content", encoding="utf-8")
        result = _load_spec_files(tmp_path)
        assert len(result) == 2

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        result = _load_spec_files(tmp_path)
        assert result == []


class TestAuditReport:
    """Integration tests for the full audit report."""

    def test_reports_code_without_spec(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)

        # Create project spec dir (empty — no specs)
        (data_path.parent / "code" / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)
        # Create tasks dir
        (data_path / "tasks" / "myproj").mkdir(parents=True, exist_ok=True)

        # Mock git ls-files to return some files
        with patch("hivemind.commands.audit._git_ls_files", return_value=["src/app.py", "src/utils.py"]):
            result = _invoke(tmp_path, ["-p", "myproj"])

        assert result.exit_code == 0, result.output
        assert "=== Drift Report: myproj ===" in result.output
        assert "Code without spec:" in result.output
        assert "src/app.py" in result.output
        assert "src/utils.py" in result.output
        assert "2 issues found" in result.output

    def test_reports_spec_without_code(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        (data_path / "tasks" / "myproj").mkdir(parents=True, exist_ok=True)

        # Create spec that references a module not in code
        _create_spec_file(
            data_path, "myproj", "feature.md",
            "This feature uses `src/missing_module.py` for processing.",
        )

        with patch("hivemind.commands.audit._git_ls_files", return_value=["src/app.py"]):
            result = _invoke(tmp_path, ["-p", "myproj"])

        assert result.exit_code == 0, result.output
        assert "Spec without code:" in result.output
        assert "referenced module not found: src/missing_module.py" in result.output

    def test_reports_stale_tasks(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        (data_path.parent / "code" / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)

        old_date = (date.today() - timedelta(days=45)).isoformat()
        _create_task_with_fm(data_path, "myproj", "MP-001", "done", old_date)

        with patch("hivemind.commands.audit._git_ls_files", return_value=[]):
            result = _invoke(tmp_path, ["-p", "myproj"])

        assert result.exit_code == 0, result.output
        assert "Stale tasks:" in result.output
        assert "MP-001" in result.output
        assert "45 days ago" in result.output

    def test_clean_report(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        (data_path.parent / "code" / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)
        (data_path / "tasks" / "myproj").mkdir(parents=True, exist_ok=True)

        # Spec references src/app.py which exists in code
        _create_spec_file(
            data_path, "myproj", "feature.md",
            "This feature uses `src/app.py`.",
        )

        with patch("hivemind.commands.audit._git_ls_files", return_value=["src/app.py"]):
            result = _invoke(tmp_path, ["-p", "myproj"])

        assert result.exit_code == 0, result.output
        assert "0 issues found" in result.output
        assert "No issues found" in result.output

    def test_fix_flag_shows_suggestions(self, tmp_path: Path) -> None:
        _config_path, data_path = _make_workspace(tmp_path)
        (data_path.parent / "code" / "hivemind" / "docs").mkdir(parents=True, exist_ok=True)
        (data_path / "tasks" / "myproj").mkdir(parents=True, exist_ok=True)

        with patch("hivemind.commands.audit._git_ls_files", return_value=["src/new.py"]):
            result = _invoke(tmp_path, ["-p", "myproj", "--fix"])

        assert result.exit_code == 0, result.output
        assert "=== Fix Suggestions ===" in result.output
        assert "Create spec documentation for src/new.py" in result.output

    def test_unknown_project_fails(self, tmp_path: Path) -> None:
        _config_path, _data_path = _make_workspace(tmp_path)

        result = _invoke(tmp_path, ["-p", "nonexistent"])
        assert result.exit_code != 0
        # v5: paths.linked_path_for raises a "not linked" message
        assert "not linked" in result.output or "not found" in result.output

    def test_combined_issues(self, tmp_path: Path) -> None:
        """Test report with all three issue types present."""
        _config_path, data_path = _make_workspace(tmp_path)

        # Spec referencing missing file
        _create_spec_file(
            data_path, "myproj", "spec.md",
            "Uses `src/gone.py` for logic.",
        )

        # Stale task
        old_date = (date.today() - timedelta(days=60)).isoformat()
        _create_task_with_fm(data_path, "myproj", "MP-010", "done", old_date)

        # Code file not in spec
        with patch("hivemind.commands.audit._git_ls_files", return_value=["src/new.py", "src/gone.py"]):
            result = _invoke(tmp_path, ["-p", "myproj"])

        assert result.exit_code == 0, result.output
        assert "Code without spec:" in result.output
        assert "src/new.py" in result.output
        assert "Stale tasks:" in result.output
        assert "MP-010" in result.output
        # src/gone.py IS in code, so it should NOT appear in spec-without-code
        assert "referenced module not found: src/gone.py" not in result.output


# ---------------------------------------------------------------------------
# Tech-stack drift (`hv audit --tech-stack`)
# ---------------------------------------------------------------------------


from hivemind.commands.audit import (  # noqa: E402
    _extract_active_dependencies,
    _read_manifest_deps,
    run_tech_stack_audit,
)


class TestReadManifestDeps:
    def test_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps(
                {
                    "dependencies": {"express": "^5.1.0", "ejs": "^3.1.10"},
                    "devDependencies": {"nodemon": "^3.1.10"},
                }
            ),
            encoding="utf-8",
        )
        result = _read_manifest_deps(tmp_path)
        assert "package.json" in result
        assert result["package.json"] == {"express", "ejs", "nodemon"}

    def test_pyproject_toml_pep621(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname="x"\ndependencies = [\n  "click >=8.1",\n  "frontmatter==1.1.0",\n]\n',
            encoding="utf-8",
        )
        result = _read_manifest_deps(tmp_path)
        assert "pyproject.toml" in result
        # Regex picks up names followed by version constraints
        assert "click" in result["pyproject.toml"]
        assert "frontmatter" in result["pyproject.toml"]

    def test_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text(
            "module example.com/x\n\ngo 1.22\n\nrequire (\n  github.com/foo/bar v1.0.0\n  github.com/baz/qux v2.3.4\n)\n",
            encoding="utf-8",
        )
        result = _read_manifest_deps(tmp_path)
        assert result["go.mod"] == {"github.com/foo/bar", "github.com/baz/qux"}

    def test_missing_manifests_skipped(self, tmp_path: Path) -> None:
        result = _read_manifest_deps(tmp_path)
        assert result == {}


class TestExtractActiveDependencies:
    def test_list_items_under_active_dependencies(self, tmp_path: Path) -> None:
        path = tmp_path / "tech-stack.md"
        path.write_text(
            "# Tech\n\n## Active Dependencies\n"
            "- express ^5.1.0 — HTTP server\n"
            "- ejs ^3.1.10 — templates\n\n"
            "## Project Structure\n- some/dir\n",
            encoding="utf-8",
        )
        out = _extract_active_dependencies(path)
        assert out == ["express", "ejs"]

    def test_section_absent_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "tech-stack.md"
        path.write_text("# Tech\n\n## Project Structure\n- foo\n", encoding="utf-8")
        assert _extract_active_dependencies(path) == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _extract_active_dependencies(tmp_path / "no.md") == []


class TestTechStackAudit:
    def _setup(self, tmp_path: Path) -> tuple[Path, Path]:
        config_path, data_path = _make_workspace(tmp_path)
        code_path = tmp_path / "code"
        code_path.mkdir(exist_ok=True)
        return data_path, code_path

    def test_doc_without_manifest_flagged(self, tmp_path: Path) -> None:
        data_path, code_path = self._setup(tmp_path)
        (code_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^5.1.0"}}),
            encoding="utf-8",
        )
        spec_dir = data_path.parent / "code" / "hivemind" / "docs"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tech-stack.md").write_text(
            "## Active Dependencies\n- express ^5.1.0\n- tailwindcss v3\n",
            encoding="utf-8",
        )
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            report = run_tech_stack_audit("myproj")
        finally:
            os.chdir(old_cwd)
        assert "Doc claims but manifest disagrees" in report
        assert "tailwindcss" in report

    def test_manifest_without_doc_flagged(self, tmp_path: Path) -> None:
        data_path, code_path = self._setup(tmp_path)
        (code_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^5.1.0", "ejs": "^3.1.10"}}),
            encoding="utf-8",
        )
        spec_dir = data_path.parent / "code" / "hivemind" / "docs"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tech-stack.md").write_text(
            "## Active Dependencies\n- express ^5.1.0\n",
            encoding="utf-8",
        )
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            report = run_tech_stack_audit("myproj")
        finally:
            os.chdir(old_cwd)
        assert "Manifest has but doc missing" in report
        assert "ejs" in report

    def test_in_sync_reports_no_drift(self, tmp_path: Path) -> None:
        data_path, code_path = self._setup(tmp_path)
        (code_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^5.1.0"}}),
            encoding="utf-8",
        )
        spec_dir = data_path.parent / "code" / "hivemind" / "docs"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tech-stack.md").write_text(
            "## Active Dependencies\n- express ^5.1.0\n",
            encoding="utf-8",
        )
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            report = run_tech_stack_audit("myproj")
        finally:
            os.chdir(old_cwd)
        assert "No tech-stack drift found" in report
        assert "Total: 0 issues" in report

    def test_cli_flag_routes_to_tech_stack_audit(self, tmp_path: Path) -> None:
        data_path, code_path = self._setup(tmp_path)
        (code_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^5.1.0"}}),
            encoding="utf-8",
        )
        spec_dir = data_path.parent / "code" / "hivemind" / "docs"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tech-stack.md").write_text(
            "## Active Dependencies\n- express ^5.1.0\n", encoding="utf-8"
        )
        result = _invoke(tmp_path, ["-p", "myproj", "--tech-stack"])
        assert result.exit_code == 0, result.output
        assert "Tech-Stack Drift" in result.output
        # Default code/spec drift output should NOT appear in --tech-stack mode
        assert "Drift Report" not in result.output
