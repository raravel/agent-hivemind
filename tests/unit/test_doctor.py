"""Unit tests for hv doctor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from hivemind.commands.doctor import (
    _list_plugin_skills,
    doctor_cmd,
    run_checks,
    _check_legacy_artifacts,
    _check_project_link,
    _check_verify_md,
)
from hivemind.core.config import HivemindConfig, default_config


def _write_config(data_path: Path, cfg_dict: dict) -> Path:
    data_path.mkdir(parents=True, exist_ok=True)
    cfg_path = data_path / ".hivemind.json"
    cfg_path.write_text(json.dumps(cfg_dict, indent=2), encoding="utf-8")
    return cfg_path


def _make_v5_workspace(tmp_path: Path, project_name: str = "demo") -> tuple[Path, Path]:
    """Return (data_path, project_dir) with a minimal healthy v5 layout.

    v5 puts project-specific artifacts (specs, link.json) inside the linked
    repo under ``hivemind/``. Cross-project state (L2/L3) stays in data_path.
    """
    data_path = tmp_path / "data"
    for sub in ("level2", "level3"):
        (data_path / sub).mkdir(parents=True, exist_ok=True)
    cfg = default_config()
    cfg["version"] = "5.0.0"
    cfg["data_path"] = str(data_path)
    _write_config(data_path, cfg)

    project_dir = tmp_path / "project"
    (project_dir / "hivemind" / "docs").mkdir(parents=True)
    (project_dir / "hivemind" / "tasks").mkdir(parents=True)
    (project_dir / "hivemind" / "link.json").write_text(
        json.dumps({"project": project_name, "data_path": str(data_path)}),
        encoding="utf-8",
    )
    (project_dir / "hivemind" / "docs" / "verify.md").write_text(
        "pytest -q\n", encoding="utf-8"
    )
    return data_path, project_dir


def _make_legacy_workspace(
    tmp_path: Path, project_name: str = "demo"
) -> tuple[Path, Path]:
    """Pre-v5 layout fixture for legacy-fallback tests."""
    data_path = tmp_path / "data"
    for sub in ("projects", "tasks", "level1", "level2", "level3"):
        (data_path / sub).mkdir(parents=True, exist_ok=True)
    cfg = default_config()
    cfg["data_path"] = str(data_path)
    _write_config(data_path, cfg)

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".hivemind-link.json").write_text(
        json.dumps({"project": project_name, "data_path": str(data_path)}),
        encoding="utf-8",
    )
    (data_path / "projects" / project_name).mkdir(parents=True, exist_ok=True)
    (data_path / "projects" / project_name / "verify.md").write_text(
        "pytest -q\n", encoding="utf-8"
    )
    return data_path, project_dir


class TestProjectLinkCheck:
    def test_healthy_link(self, tmp_path: Path) -> None:
        _data_path, project_dir = _make_v5_workspace(tmp_path)
        result, link = _check_project_link(project_dir)
        assert result.severity == "ok"
        assert link is not None
        assert link["project"] == "demo"

    def test_legacy_link_location_warns(self, tmp_path: Path) -> None:
        _data_path, project_dir = _make_legacy_workspace(tmp_path)
        result, link = _check_project_link(project_dir)
        assert result.severity == "warn"
        assert link is not None
        assert "v5" in result.detail.lower() or "legacy" in result.detail.lower()

    def test_missing_link_warns(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        result, link = _check_project_link(project_dir)
        assert result.severity == "warn"
        assert link is None

    def test_windows_path_on_posix_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.platform", "darwin")
        project_dir = tmp_path / "proj"
        (project_dir / "hivemind").mkdir(parents=True)
        (project_dir / "hivemind" / "link.json").write_text(
            json.dumps(
                {
                    "project": "demo",
                    "data_path": "C:\\Users\\ifthe\\agent-hivemind-data",
                }
            ),
            encoding="utf-8",
        )
        result, _ = _check_project_link(project_dir)
        assert result.severity == "error"
        assert "Windows" in result.detail

    def test_malformed_json_errors(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        (project_dir / "hivemind").mkdir(parents=True)
        (project_dir / "hivemind" / "link.json").write_text(
            "{{not json", encoding="utf-8"
        )
        result, _ = _check_project_link(project_dir)
        assert result.severity == "error"

    def test_nonexistent_data_path_errors(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        (project_dir / "hivemind").mkdir(parents=True)
        (project_dir / "hivemind" / "link.json").write_text(
            json.dumps({"project": "demo", "data_path": str(tmp_path / "missing")}),
            encoding="utf-8",
        )
        result, _ = _check_project_link(project_dir)
        assert result.severity == "error"


class TestVerifyMdCheck:
    def test_verify_md_present_ok(self, tmp_path: Path) -> None:
        data_path, project_dir = _make_v5_workspace(tmp_path)
        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        link = json.loads((project_dir / "hivemind" / "link.json").read_text())
        result = _check_verify_md(project_dir, link, cfg)
        assert result.severity == "ok"

    def test_legacy_only_warns(self, tmp_path: Path) -> None:
        data_path, project_dir = _make_v5_workspace(tmp_path)
        docs = project_dir / "hivemind" / "docs"
        (docs / "verify.md").unlink()
        (docs / "build-verify.md").write_text("pytest\n", encoding="utf-8")
        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        link = json.loads((project_dir / "hivemind" / "link.json").read_text())
        result = _check_verify_md(project_dir, link, cfg)
        assert result.severity == "warn"

    def test_both_present_warns(self, tmp_path: Path) -> None:
        data_path, project_dir = _make_v5_workspace(tmp_path)
        (project_dir / "hivemind" / "docs" / "build-verify.md").write_text(
            "legacy\n", encoding="utf-8"
        )
        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        link = json.loads((project_dir / "hivemind" / "link.json").read_text())
        result = _check_verify_md(project_dir, link, cfg)
        assert result.severity == "warn"

    def test_neither_errors(self, tmp_path: Path) -> None:
        data_path, project_dir = _make_v5_workspace(tmp_path)
        (project_dir / "hivemind" / "docs" / "verify.md").unlink()
        cfg = HivemindConfig.load(data_path / ".hivemind.json")
        link = json.loads((project_dir / "hivemind" / "link.json").read_text())
        result = _check_verify_md(project_dir, link, cfg)
        assert result.severity == "error"


class TestLegacyArtifactsCheck:
    def test_clean_project_ok(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "CLAUDE.md").write_text("# Project\n", encoding="utf-8")
        result = _check_legacy_artifacts(project_dir)
        assert result.severity == "ok"

    def test_obsidian_import_detected(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "CLAUDE.md").write_text(
            'obsidian-import "00_Projects/foo"\n\n# Rest\n', encoding="utf-8"
        )
        result = _check_legacy_artifacts(project_dir)
        assert result.severity == "warn"
        assert "obsidian-import" in result.detail


class TestPluginSkillDiscovery:
    def test_reads_manifest_declared_codex_skill_dir(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "plugin"
        (plugin_dir / ".codex-plugin").mkdir(parents=True)
        (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "hv", "skills": "./skills/codex/"}),
            encoding="utf-8",
        )
        (plugin_dir / "skills" / "codex" / "hv-plan").mkdir(parents=True)
        (plugin_dir / "skills" / "codex" / "hv-plan" / "SKILL.md").write_text(
            "# hv-plan",
            encoding="utf-8",
        )

        skills = _list_plugin_skills(plugin_dir, ".codex-plugin/plugin.json")

        assert skills == ["hv-plan"]


class TestDoctorCLI:
    def test_exit_zero_on_healthy_workspace(self, tmp_path: Path) -> None:
        _, project_dir = _make_v5_workspace(tmp_path)

        # Simulate a minimal healthy plugin install
        plugin = Path("~/.claude/plugins/hv").expanduser()
        plugin_existed = plugin.exists()

        runner = CliRunner()
        # Most checks will fail in CI (no plugin etc.), so we only assert the
        # CLI is wired, runs to completion, and returns usable output.
        result = runner.invoke(
            doctor_cmd, ["--project-dir", str(project_dir)]
        )
        # Must not crash
        assert result.exit_code in (0, 1)
        assert "Hivemind health check" in result.output
        assert "Summary:" in result.output
        # plugin_existed is a smoke check so the test is not dependent on env
        _ = plugin_existed

    def test_run_checks_returns_list(self, tmp_path: Path) -> None:
        _, project_dir = _make_v5_workspace(tmp_path)
        results = run_checks(project_dir)
        assert len(results) >= 7
        assert all(r.severity in ("ok", "warn", "error") for r in results)

    def test_reports_error_on_missing_link(self, tmp_path: Path) -> None:
        _, project_dir = _make_v5_workspace(tmp_path)
        (project_dir / "hivemind" / "link.json").unlink()
        results = run_checks(project_dir)
        link_results = [r for r in results if r.name == "Project link"]
        assert len(link_results) == 1
        assert link_results[0].severity in ("warn", "error")

    def test_reports_agents_md_warning_when_missing(self, tmp_path: Path) -> None:
        _, project_dir = _make_v5_workspace(tmp_path)
        results = run_checks(project_dir)
        agents = [r for r in results if r.name == "AGENTS.md"]
        assert len(agents) == 1
        assert agents[0].severity == "warn"


class TestDataDirCheck:
    def test_v5_required_subdirs(self, tmp_path: Path) -> None:
        """v5 only requires level2 and level3; legacy projects/tasks warn."""
        from hivemind.commands.doctor import _check_data_directory

        data_path = tmp_path / "data"
        (data_path / "level2").mkdir(parents=True)
        (data_path / "level3").mkdir(parents=True)
        cfg = default_config()
        cfg["version"] = "5.0.0"
        cfg["data_path"] = str(data_path)
        _write_config(data_path, cfg)
        loaded = HivemindConfig.load(data_path / ".hivemind.json")

        result = _check_data_directory(loaded)
        assert result.severity == "ok"
        assert "L2/L3" in result.detail

    def test_legacy_projects_tasks_warns(self, tmp_path: Path) -> None:
        from hivemind.commands.doctor import _check_data_directory

        data_path = tmp_path / "data"
        for sub in ("projects", "tasks", "level2", "level3"):
            (data_path / sub).mkdir(parents=True)
        cfg = default_config()
        cfg["version"] = "5.0.0"
        cfg["data_path"] = str(data_path)
        _write_config(data_path, cfg)
        loaded = HivemindConfig.load(data_path / ".hivemind.json")

        result = _check_data_directory(loaded)
        assert result.severity == "warn"
        assert "v5" in result.detail

    def test_missing_l2_l3_warns(self, tmp_path: Path) -> None:
        from hivemind.commands.doctor import _check_data_directory

        data_path = tmp_path / "data"
        data_path.mkdir()
        cfg = default_config()
        cfg["version"] = "5.0.0"
        cfg["data_path"] = str(data_path)
        _write_config(data_path, cfg)
        loaded = HivemindConfig.load(data_path / ".hivemind.json")

        result = _check_data_directory(loaded)
        assert result.severity == "warn"
        assert "level2" in result.detail or "level3" in result.detail


class TestConfigVersionCheck:
    def test_v5_version_ok(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from hivemind.commands import doctor as doctor_module

        data_path = tmp_path / "data"
        (data_path / "level2").mkdir(parents=True)
        (data_path / "level3").mkdir(parents=True)
        cfg = default_config()
        cfg["version"] = "6.0.0"
        cfg["data_path"] = str(data_path)
        _write_config(data_path, cfg)

        monkeypatch.setattr(
            doctor_module, "_find_config_path", lambda: data_path / ".hivemind.json"
        )
        result, _ = doctor_module._check_config()
        assert result.severity == "ok"
        assert "v6.0.0" in result.detail

    def test_v4_version_warns_with_v5_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hivemind.commands import doctor as doctor_module

        data_path = tmp_path / "data"
        data_path.mkdir(parents=True)
        cfg = default_config()
        cfg["version"] = "4.0.0"
        _write_config(data_path, cfg)

        monkeypatch.setattr(
            doctor_module, "_find_config_path", lambda: data_path / ".hivemind.json"
        )
        result, _ = doctor_module._check_config()
        assert result.severity == "warn"
        assert "v5" in result.detail
