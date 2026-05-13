"""Unit tests for hivemind.commands.migrate (v1 -> v2 migration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hivemind.commands.migrate import (
    detect_v1,
    migrate_v1_to_v2,
    migrate_v2_to_v3,
    print_migration_summary,
)
from hivemind.core.config import SUPPORTED_TARGETS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(data_path: Path, data: dict) -> Path:  # type: ignore[type-arg]
    """Write a .hivemind.json into *data_path* and return its path."""
    data_path.mkdir(parents=True, exist_ok=True)
    config_path = data_path / ".hivemind.json"
    config_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return config_path


def _make_v1_dir(tmp_path: Path) -> Path:
    """Create a minimal v1-style data directory."""
    data = tmp_path / "data"
    data.mkdir()

    # v1 config: no version field
    _write_config(data, {"data_path": str(data), "git_enabled": False})

    # important.md at root (v1 convention)
    (data / "important.md").write_text("# Important\n", encoding="utf-8")

    # Some existing L2/L3 content
    (data / "level2").mkdir()
    (data / "level2" / "backend").mkdir()
    (data / "level2" / "backend" / "api.md").write_text(
        "# API Notes\n", encoding="utf-8"
    )
    (data / "level3").mkdir()
    (data / "level3" / "deep.md").write_text("# Deep\n", encoding="utf-8")

    return data


def _make_v2_dir(tmp_path: Path) -> Path:
    """Create a minimal v2-style data directory."""
    data = tmp_path / "data"
    data.mkdir()

    _write_config(
        data,
        {
            "version": "2.0.0",
            "data_path": str(data),
            "profiles": {},
            "projects": {},
        },
    )

    (data / "level1").mkdir()
    (data / "level1" / "important.md").write_text(
        "---\nhits: {}\n---\n", encoding="utf-8"
    )
    for d in ("projects", "tasks", "level2", "level3"):
        (data / d).mkdir(exist_ok=True)

    return data


# ---------------------------------------------------------------------------
# detect_v1
# ---------------------------------------------------------------------------


class TestDetectV1:
    """Tests for detect_v1()."""

    def test_detects_v1_no_version_field(self, tmp_path: Path) -> None:
        data = _make_v1_dir(tmp_path)
        assert detect_v1(data) is True

    def test_detects_v1_version_1x(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        _write_config(data, {"version": "1.3.0"})
        assert detect_v1(data) is True

    def test_returns_false_for_v2(self, tmp_path: Path) -> None:
        data = _make_v2_dir(tmp_path)
        assert detect_v1(data) is False

    def test_returns_false_when_no_config(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        data.mkdir()
        assert detect_v1(data) is False

    def test_detects_root_important_without_level1(
        self, tmp_path: Path
    ) -> None:
        """Even with version 2.0.0, if important.md is only at root, flag it."""
        data = tmp_path / "data"
        _write_config(data, {"version": "2.0.0"})
        (data / "important.md").write_text("# Important\n", encoding="utf-8")
        assert detect_v1(data) is True

    def test_no_flag_when_level1_exists(self, tmp_path: Path) -> None:
        """Root important.md should NOT trigger if level1 copy already exists."""
        data = tmp_path / "data"
        _write_config(data, {"version": "2.0.0"})
        (data / "important.md").write_text("# Important\n", encoding="utf-8")
        (data / "level1").mkdir()
        (data / "level1" / "important.md").write_text(
            "# Important\n", encoding="utf-8"
        )
        assert detect_v1(data) is False


# ---------------------------------------------------------------------------
# migrate_v1_to_v2
# ---------------------------------------------------------------------------


class TestMigrateV1ToV2:
    """Tests for migrate_v1_to_v2()."""

    def test_preserves_existing_l2_l3_files(self, tmp_path: Path) -> None:
        data = _make_v1_dir(tmp_path)
        migrate_v1_to_v2(data)

        # Existing files must still exist
        assert (data / "level2" / "backend" / "api.md").exists()
        assert (
            data / "level2" / "backend" / "api.md"
        ).read_text(encoding="utf-8") == "# API Notes\n"
        assert (data / "level3" / "deep.md").exists()
        assert (
            data / "level3" / "deep.md"
        ).read_text(encoding="utf-8") == "# Deep\n"

    def test_moves_important_md_to_level1(self, tmp_path: Path) -> None:
        data = _make_v1_dir(tmp_path)
        summary = migrate_v1_to_v2(data)

        assert (data / "level1" / "important.md").exists()
        assert (
            data / "level1" / "important.md"
        ).read_text(encoding="utf-8") == "# Important\n"
        # Original should still exist (copy, not move)
        assert (data / "important.md").exists()
        assert any("important.md" in m for m in summary["moved"])

    def test_creates_missing_v2_directories(self, tmp_path: Path) -> None:
        data = _make_v1_dir(tmp_path)
        summary = migrate_v1_to_v2(data)

        for dirname in ("projects", "tasks", "level1", "level2", "level3"):
            assert (data / dirname).is_dir()

        # projects and tasks were missing in v1
        assert "projects/" in summary["created"]
        assert "tasks/" in summary["created"]

    def test_creates_level2_subdirectories(self, tmp_path: Path) -> None:
        data = _make_v1_dir(tmp_path)
        migrate_v1_to_v2(data)

        for subdir in ("frontend", "backend", "infra", "general"):
            assert (data / "level2" / subdir).is_dir()

    def test_updates_hivemind_json_version(self, tmp_path: Path) -> None:
        data = _make_v1_dir(tmp_path)
        summary = migrate_v1_to_v2(data)

        config_path = data / ".hivemind.json"
        with config_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)

        assert cfg["version"] == "2.0.0"
        assert "profiles" in cfg
        assert "projects" in cfg
        assert ".hivemind.json" in summary["updated"]

    def test_idempotent(self, tmp_path: Path) -> None:
        data = _make_v1_dir(tmp_path)

        # First run
        summary1 = migrate_v1_to_v2(data)
        assert any(summary1.values())  # should have done something

        # Second run -- nothing left to do
        summary2 = migrate_v1_to_v2(data)
        assert summary2["moved"] == []
        assert summary2["created"] == []
        assert summary2["updated"] == []

    def test_preserves_existing_config_fields(self, tmp_path: Path) -> None:
        """Existing v1 config fields (like git_enabled) should survive."""
        data = _make_v1_dir(tmp_path)
        migrate_v1_to_v2(data)

        config_path = data / ".hivemind.json"
        with config_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)

        assert cfg["data_path"] == str(data)
        assert cfg["git_enabled"] is False


# ---------------------------------------------------------------------------
# print_migration_summary
# ---------------------------------------------------------------------------


class TestPrintMigrationSummary:
    """Tests for print_migration_summary()."""

    def test_prints_nothing_to_do(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_migration_summary({"moved": [], "created": [], "updated": []})
        captured = capsys.readouterr()
        assert "nothing to do" in captured.out

    def test_prints_moved(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_migration_summary({
            "moved": ["important.md -> level1/important.md"],
            "created": [],
            "updated": [],
        })
        captured = capsys.readouterr()
        assert "Moved:" in captured.out
        assert "important.md" in captured.out

    def test_prints_created(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_migration_summary({
            "moved": [],
            "created": ["projects/", "tasks/"],
            "updated": [],
        })
        captured = capsys.readouterr()
        assert "Created:" in captured.out
        assert "projects/" in captured.out

    def test_prints_updated(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_migration_summary({
            "moved": [],
            "created": [],
            "updated": [".hivemind.json"],
        })
        captured = capsys.readouterr()
        assert "Updated:" in captured.out
        assert ".hivemind.json" in captured.out


# ---------------------------------------------------------------------------
# v2 -> v3 migration
# ---------------------------------------------------------------------------


def _make_v2_data(tmp_path: Path) -> Path:
    """Create a minimal v2 data directory (version 2.0.0)."""
    data = tmp_path / "data"
    data.mkdir()
    _write_config(
        data,
        {
            "version": "2.0.0",
            "data_path": str(data),
            "profiles": {
                "quality": {"planner": "opus", "executor": "opus", "reviewer": "opus"},
                "balanced": {"planner": "opus", "executor": "sonnet", "reviewer": "sonnet"},
                "budget": {"planner": "sonnet", "executor": "sonnet", "reviewer": "haiku"},
            },
            "projects": {"demo": {"prefix": "DM", "linked_path": str(tmp_path / "demo")}},
        },
    )
    (data / "level1").mkdir()
    (data / "level2").mkdir()
    (data / "level3" / "demo").mkdir(parents=True)
    (data / "projects" / "demo").mkdir(parents=True)
    (data / "tasks" / "demo").mkdir(parents=True)
    # Legacy build-verify.md
    (data / "projects" / "demo" / "build-verify.md").write_text(
        "npm test\n", encoding="utf-8"
    )
    # Per-prompt L3 log
    (data / "level3" / "demo" / "20260101_abc123.md").write_text(
        "# Session Log\n", encoding="utf-8"
    )
    return data


class TestMigrateV3Config:
    """Tests for the .hivemind.json portion of the v3 migration."""

    def test_version_bumped(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        migrate_v2_to_v3(data, backup=False, claude_settings=tmp_path / "none.json")
        cfg = json.loads((data / ".hivemind.json").read_text(encoding="utf-8"))
        assert cfg["version"] == "3.0.0"

    def test_short_model_aliases_upgraded(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        migrate_v2_to_v3(data, backup=False, claude_settings=tmp_path / "none.json")
        cfg = json.loads((data / ".hivemind.json").read_text(encoding="utf-8"))
        assert cfg["profiles"]["balanced"]["executor"] == "claude-sonnet-4-6"
        assert cfg["profiles"]["budget"]["reviewer"] == "claude-haiku-4-5"

    def test_pricing_added(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        migrate_v2_to_v3(data, backup=False, claude_settings=tmp_path / "none.json")
        cfg = json.loads((data / ".hivemind.json").read_text(encoding="utf-8"))
        assert "pricing" in cfg
        assert "claude-opus-4-7" in cfg["pricing"]

    def test_parallel_section_seeded(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        migrate_v2_to_v3(data, backup=False, claude_settings=tmp_path / "none.json")
        cfg = json.loads((data / ".hivemind.json").read_text(encoding="utf-8"))
        assert cfg["parallel"]["max_concurrency"] == 2

    def test_runtime_models_seeded(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        migrate_v2_to_v3(data, backup=False, claude_settings=tmp_path / "none.json")
        cfg = json.loads((data / ".hivemind.json").read_text(encoding="utf-8"))
        assert cfg["runtime_models"]["codex"]["profiles"]["balanced"]["executor"] == "gpt-5.1-codex"

    def test_idempotent(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        migrate_v2_to_v3(data, backup=False, claude_settings=tmp_path / "none.json")
        summary = migrate_v2_to_v3(
            data, backup=False, claude_settings=tmp_path / "none.json"
        )
        assert summary["config"] == [] or summary["config"] == [
            # verify_md / link normalization may have minor no-op output; config itself is stable
        ]


class TestMigrateV3VerifyMd:
    """Tests for build-verify.md -> verify.md rename."""

    def test_renamed(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        summary = migrate_v2_to_v3(
            data, backup=False, claude_settings=tmp_path / "none.json"
        )
        assert not (data / "projects" / "demo" / "build-verify.md").exists()
        assert (data / "projects" / "demo" / "verify.md").exists()
        assert any("verify.md" in x for x in summary["verify_md_renamed"])

    def test_no_clobber_when_verify_md_exists(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        (data / "projects" / "demo" / "verify.md").write_text(
            "pre-existing verify\n", encoding="utf-8"
        )
        migrate_v2_to_v3(data, backup=False, claude_settings=tmp_path / "none.json")
        # build-verify.md stays put if verify.md was already there
        assert (data / "projects" / "demo" / "build-verify.md").exists()
        # verify.md content preserved
        content = (data / "projects" / "demo" / "verify.md").read_text(encoding="utf-8")
        assert "pre-existing verify" in content


class TestMigrateV3L3Archive:
    """Tests for L3 per-prompt log archival."""

    def test_archived(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        summary = migrate_v2_to_v3(
            data, backup=False, claude_settings=tmp_path / "none.json"
        )
        assert summary["l3_archived"] >= 1
        archive = data / "level3" / "_archive_v2" / "demo"
        assert archive.exists()
        assert any(archive.iterdir())


class TestMigrateV3LinkFile:
    """Tests for .hivemind-link.json path normalization."""

    def test_windows_path_normalized(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        project_dir = tmp_path / "demo"
        project_dir.mkdir()
        # Simulate a Windows-style stored path on a POSIX machine
        (project_dir / ".hivemind-link.json").write_text(
            json.dumps(
                {
                    "project": "demo",
                    "data_path": "C:\\Users\\ifthe\\agent-hivemind-data",
                }
            ),
            encoding="utf-8",
        )
        migrate_v2_to_v3(
            data,
            project_dirs=[project_dir],
            backup=False,
            claude_settings=tmp_path / "none.json",
        )
        link = json.loads(
            (project_dir / ".hivemind-link.json").read_text(encoding="utf-8")
        )
        assert "C:" not in link["data_path"]
        assert "\\" not in link["data_path"]
        assert link["targets"] == ["claude"]

    def test_invalid_targets_normalized_out(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        project_dir = tmp_path / "demo"
        project_dir.mkdir()
        (project_dir / ".hivemind-link.json").write_text(
            json.dumps(
                {
                    "project": "demo",
                    "data_path": str(data),
                    "targets": ["codex", "invalid", "claude", "codex"],
                }
            ),
            encoding="utf-8",
        )
        migrate_v2_to_v3(
            data,
            project_dirs=[project_dir],
            backup=False,
            claude_settings=tmp_path / "none.json",
        )
        link = json.loads(
            (project_dir / ".hivemind-link.json").read_text(encoding="utf-8")
        )
        assert link["targets"] == sorted(SUPPORTED_TARGETS)


class TestMigrateV3ClaudeMd:
    """Tests for CLAUDE.md legacy cleanup + @import insertion."""

    def test_obsidian_import_removed(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        project_dir = tmp_path / "demo"
        project_dir.mkdir()
        (project_dir / ".hivemind-link.json").write_text(
            json.dumps({"project": "demo", "data_path": str(data)}), encoding="utf-8"
        )
        (project_dir / "CLAUDE.md").write_text(
            'obsidian-import "00_Projects/foo"\n\n# Hivemind Project\n',
            encoding="utf-8",
        )
        migrate_v2_to_v3(
            data,
            project_dirs=[project_dir],
            backup=False,
            claude_settings=tmp_path / "none.json",
        )
        content = (project_dir / "CLAUDE.md").read_text(encoding="utf-8")
        assert "obsidian-import" not in content
        assert (project_dir / "AGENTS.md").exists()

    def test_at_imports_added(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        project_dir = tmp_path / "demo"
        project_dir.mkdir()
        (project_dir / ".hivemind-link.json").write_text(
            json.dumps({"project": "demo", "data_path": str(data)}), encoding="utf-8"
        )
        (project_dir / "CLAUDE.md").write_text(
            "# Hivemind Project\n- project: demo\n", encoding="utf-8"
        )
        migrate_v2_to_v3(
            data,
            project_dirs=[project_dir],
            backup=False,
            claude_settings=tmp_path / "none.json",
        )
        content = (project_dir / "CLAUDE.md").read_text(encoding="utf-8")
        assert "@" in content
        assert "architecture.md" in content
        assert "rules.md" in content

    def test_codex_hooks_created_for_codex_target(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        project_dir = tmp_path / "demo"
        project_dir.mkdir()
        (project_dir / ".hivemind-link.json").write_text(
            json.dumps(
                {"project": "demo", "data_path": str(data), "targets": ["codex"]},
            ),
            encoding="utf-8",
        )
        migrate_v2_to_v3(
            data,
            project_dirs=[project_dir],
            backup=False,
            claude_settings=tmp_path / "none.json",
        )
        hooks = json.loads((project_dir / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        assert "UserPromptSubmit" in hooks["hooks"]


class TestMigrateV3NodeHooks:
    """Tests for legacy JS hook removal from settings.json."""

    def test_js_entries_removed(self, tmp_path: Path) -> None:
        data = _make_v2_data(tmp_path)
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "node ~/.claude/hooks/hv-pre-commit.js",
                                    }
                                ],
                            }
                        ],
                        "UserPromptSubmit": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "node ~/.claude/hooks/hv-session-log.js",
                                    }
                                ],
                            }
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )
        summary = migrate_v2_to_v3(data, backup=False, claude_settings=settings)
        assert summary["node_hook_entries_removed"] == 2
        after = json.loads(settings.read_text(encoding="utf-8"))
        assert after["hooks"]["PreToolUse"] == []
        assert after["hooks"]["UserPromptSubmit"] == []


class TestMigrateCLIToV4:
    """Tests for the `hv migrate --to v4` CLI dispatch."""

    def test_v4_dispatch_migrates_and_reports(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from hivemind.commands.migrate import migrate_cmd

        data = tmp_path / "data"
        data.mkdir()
        config = data / ".hivemind.json"
        config.write_text(
            json.dumps(
                {
                    "version": "3.0.0",
                    "data_path": str(data),
                    "projects": {},
                }
            ),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            migrate_cmd,
            ["--to", "v4", "--path", str(data), "--no-backup"],
        )
        assert result.exit_code == 0, result.output
        assert "Migrated" in result.output
        parsed = json.loads(config.read_text(encoding="utf-8"))
        assert parsed["version"] == "4.0.0"
        assert "data_path" not in parsed

    def test_v4_dispatch_idempotent(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from hivemind.commands.migrate import migrate_cmd

        data = tmp_path / "data"
        data.mkdir()
        (data / ".hivemind.json").write_text(
            json.dumps({"version": "4.0.0", "projects": {}}),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            migrate_cmd, ["--to", "v4", "--path", str(data), "--no-backup"]
        )
        assert result.exit_code == 0, result.output
        assert "Already on v4" in result.output

    def test_v4_dispatch_errors_when_config_missing(
        self, tmp_path: Path
    ) -> None:
        from click.testing import CliRunner

        from hivemind.commands.migrate import migrate_cmd

        data = tmp_path / "data"
        data.mkdir()  # data dir exists but no .hivemind.json inside

        runner = CliRunner()
        result = runner.invoke(
            migrate_cmd, ["--to", "v4", "--path", str(data), "--no-backup"]
        )
        assert result.exit_code != 0
        assert "hv init" in result.output


# ---------------------------------------------------------------------------
# v4 -> v5
# ---------------------------------------------------------------------------


def _make_v4_with_project(tmp_path: Path) -> tuple[Path, Path]:
    """Build a v4 data dir + a linked project repo. Returns (data, linked)."""
    data = tmp_path / "data"
    data.mkdir()
    linked = tmp_path / "my-project"
    linked.mkdir()

    # v4 config registers the project.
    _write_config(
        data,
        {
            "version": "4.0.0",
            "projects": {
                "demo": {
                    "prefix": "DEMO",
                    "linked_path": str(linked),
                }
            },
        },
    )

    # Legacy specs at <data>/projects/demo/
    specs = data / "projects" / "demo"
    specs.mkdir(parents=True)
    (specs / "architecture.md").write_text("# arch\n", encoding="utf-8")
    (specs / "rules.md").write_text("# rules\n", encoding="utf-8")
    (specs / "_harness_scores.jsonl").write_text(
        '{"overall": 30}\n', encoding="utf-8"
    )

    # Legacy tasks at <data>/tasks/demo/
    tasks = data / "tasks" / "demo"
    tasks.mkdir(parents=True)
    (tasks / "DEMO-001.md").write_text(
        "---\nid: DEMO-001\nstatus: done\n---\n", encoding="utf-8"
    )
    (tasks / "_counter.json").write_text('{"value": 1}\n', encoding="utf-8")

    # Legacy link file at <linked>/.hivemind-link.json
    (linked / ".hivemind-link.json").write_text(
        json.dumps({"project": "demo", "prefix": "DEMO"}), encoding="utf-8"
    )

    return data, linked


class TestMigrateV4ToV5:
    """Tests for migrate_v4_to_v5()."""

    def test_moves_specs_tasks_scores_and_link(self, tmp_path: Path) -> None:
        from hivemind.commands.migrate import SCHEMA_V5, migrate_v4_to_v5

        data, linked = _make_v4_with_project(tmp_path)

        summary = migrate_v4_to_v5(data)

        # Specs moved to <linked>/hivemind/docs/
        assert (linked / "hivemind" / "docs" / "architecture.md").exists()
        assert (linked / "hivemind" / "docs" / "rules.md").exists()
        assert not (data / "projects" / "demo" / "architecture.md").exists()

        # Scores renamed and relocated.
        scores = linked / "hivemind" / "harness-scores.jsonl"
        assert scores.exists()
        assert not (data / "projects" / "demo" / "_harness_scores.jsonl").exists()

        # Tasks moved to <linked>/hivemind/tasks/
        assert (linked / "hivemind" / "tasks" / "DEMO-001.md").exists()
        assert (linked / "hivemind" / "tasks" / "_counter.json").exists()
        assert not (data / "tasks" / "demo" / "DEMO-001.md").exists()

        # Link file relocated.
        assert (linked / "hivemind" / "link.json").exists()
        assert not (linked / ".hivemind-link.json").exists()

        # Schema bumped.
        cfg = json.loads((data / ".hivemind.json").read_text(encoding="utf-8"))
        assert cfg["version"] == SCHEMA_V5

        # Summary covers the project.
        names = [p["project"] for p in summary["projects"]]
        assert names == ["demo"]
        assert summary["version_updated"] is True

    def test_idempotent(self, tmp_path: Path) -> None:
        from hivemind.commands.migrate import migrate_v4_to_v5

        data, linked = _make_v4_with_project(tmp_path)

        first = migrate_v4_to_v5(data)
        second = migrate_v4_to_v5(data)

        # Second run finds nothing left to move.
        proj = second["projects"][0]
        assert proj["specs_moved"] == 0
        assert proj["tasks_moved"] == 0
        assert proj["scores_moved"] is False
        assert proj["link_file_moved"] is False
        assert second["version_updated"] is False
        # First run did the work.
        assert first["projects"][0]["specs_moved"] >= 2

    def test_skips_project_with_missing_linked_path(self, tmp_path: Path) -> None:
        from hivemind.commands.migrate import migrate_v4_to_v5

        data = tmp_path / "data"
        data.mkdir()
        _write_config(
            data,
            {
                "version": "4.0.0",
                "projects": {
                    "gone": {
                        "prefix": "G",
                        "linked_path": str(tmp_path / "does-not-exist"),
                    }
                },
            },
        )

        summary = migrate_v4_to_v5(data)
        assert summary["projects"] == []
        assert any(s["project"] == "gone" for s in summary["skipped"])

    def test_cli_dispatch(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from hivemind.commands.migrate import migrate_cmd

        data, linked = _make_v4_with_project(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            migrate_cmd,
            ["--to", "v5", "--path", str(data), "--no-backup", "--no-commit"],
        )
        assert result.exit_code == 0, result.output
        assert "v4 -> v5" in result.output
        assert (linked / "hivemind" / "docs" / "architecture.md").exists()


def _init_git(repo: Path) -> None:
    """Initialize a git repo with a baseline commit (for migrate auto-commit tests)."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=str(repo), check=True
    )
    # Stage everything pre-existing and commit so subsequent changes can be diffed.
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True
    )


def _git_log(repo: Path) -> list[str]:
    import subprocess

    result = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


class TestMigrateV5AutoCommit:
    """Tests for the v5 migration's force-commit behaviour."""

    def test_commits_linked_repo_by_default(self, tmp_path: Path) -> None:
        from hivemind.commands.migrate import migrate_v4_to_v5

        data, linked = _make_v4_with_project(tmp_path)
        _init_git(linked)

        summary = migrate_v4_to_v5(data)

        proj = summary["projects"][0]
        assert proj["committed"] is True
        log = _git_log(linked)
        assert any("migrate to v5 layout" in m for m in log)

    def test_skips_commit_when_not_requested(self, tmp_path: Path) -> None:
        from hivemind.commands.migrate import migrate_v4_to_v5

        data, linked = _make_v4_with_project(tmp_path)
        _init_git(linked)

        summary = migrate_v4_to_v5(data, commit=False)

        proj = summary["projects"][0]
        assert "committed" not in proj
        # No migration commit landed.
        assert not any("migrate to v5 layout" in m for m in _git_log(linked))

    def test_silent_skip_when_linked_is_not_git(self, tmp_path: Path) -> None:
        from hivemind.commands.migrate import migrate_v4_to_v5

        data, linked = _make_v4_with_project(tmp_path)
        # linked is NOT a git repo

        summary = migrate_v4_to_v5(data)

        proj = summary["projects"][0]
        assert proj["committed"] is False  # nothing committed but no error
        # Migration still moved files.
        assert (linked / "hivemind" / "docs" / "architecture.md").exists()

    def test_ignores_global_auto_commit_toggle(self, tmp_path: Path) -> None:
        """Explicit migrate commit should land even when auto_commit=false."""
        from hivemind.commands.migrate import migrate_v4_to_v5

        data, linked = _make_v4_with_project(tmp_path)
        _init_git(linked)

        # Patch the config so auto_commit is explicitly false.
        config_path = data / ".hivemind.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        cfg["auto_commit"] = False
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        import os

        old_cwd = os.getcwd()
        try:
            os.chdir(data)  # so find_for_command picks this config
            summary = migrate_v4_to_v5(data)
        finally:
            os.chdir(old_cwd)

        assert summary["projects"][0]["committed"] is True
        assert any("migrate to v5 layout" in m for m in _git_log(linked))
