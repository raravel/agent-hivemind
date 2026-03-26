"""Unit tests for hivemind.commands.migrate (v1 -> v2 migration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hivemind.commands.migrate import detect_v1, migrate_v1_to_v2, print_migration_summary


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
