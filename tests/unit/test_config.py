"""Unit tests for hivemind.core.config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hivemind.core.config import HivemindConfig, default_config


class TestDefaultConfig:
    """Tests for default_config()."""

    def test_returns_dict(self) -> None:
        cfg = default_config()
        assert isinstance(cfg, dict)

    def test_version(self) -> None:
        cfg = default_config()
        assert cfg["version"] == "2.0.0"

    def test_has_all_top_level_keys(self) -> None:
        cfg = default_config()
        expected_keys = {
            "version",
            "data_path",
            "git_enabled",
            "auto_commit",
            "model_profile",
            "profiles",
            "projects",
            "filter_patterns",
        }
        assert set(cfg.keys()) == expected_keys

    def test_profiles_contain_three(self) -> None:
        cfg = default_config()
        assert set(cfg["profiles"].keys()) == {"quality", "balanced", "budget"}

    def test_each_profile_has_roles(self) -> None:
        cfg = default_config()
        for name, profile in cfg["profiles"].items():
            assert "planner" in profile, f"{name} missing planner"
            assert "executor" in profile, f"{name} missing executor"
            assert "reviewer" in profile, f"{name} missing reviewer"

    def test_projects_empty(self) -> None:
        cfg = default_config()
        assert cfg["projects"] == {}

    def test_filter_patterns_empty(self) -> None:
        cfg = default_config()
        assert cfg["filter_patterns"] == []


class TestHivemindConfigLoadSave:
    """Tests for load/save roundtrip."""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".hivemind.json"
        cfg = HivemindConfig(config_path, default_config())
        cfg.save()
        assert config_path.exists()

    def test_load_reads_saved_data(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".hivemind.json"
        original = default_config()
        cfg = HivemindConfig(config_path, original)
        cfg.save()

        loaded = HivemindConfig.load(config_path)
        assert loaded.raw == original

    def test_roundtrip_preserves_data(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".hivemind.json"
        original = default_config()
        original["model_profile"] = "quality"

        cfg = HivemindConfig(config_path, original)
        cfg.save()

        loaded = HivemindConfig.load(config_path)
        assert loaded.get("model_profile") == "quality"

    def test_saved_file_is_valid_json(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".hivemind.json"
        cfg = HivemindConfig(config_path, default_config())
        cfg.save()

        raw_text = config_path.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)
        assert isinstance(parsed, dict)


class TestGetSet:
    """Tests for get/set with dot notation."""

    def _make_config(self, tmp_path: Path) -> HivemindConfig:
        return HivemindConfig(tmp_path / ".hivemind.json", default_config())

    def test_get_top_level(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        assert cfg.get("version") == "2.0.0"

    def test_get_nested(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        result = cfg.get("profiles.balanced")
        assert isinstance(result, dict)
        assert result["executor"] == "sonnet"

    def test_get_deeply_nested(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        assert cfg.get("profiles.balanced.planner") == "opus"

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        assert cfg.get("nonexistent") is None

    def test_get_missing_nested_returns_none(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        assert cfg.get("profiles.nonexistent.foo") is None

    def test_set_top_level(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        cfg.set("git_enabled", True)
        assert cfg.get("git_enabled") is True

    def test_set_nested(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        cfg.set("profiles.balanced.executor", "opus")
        assert cfg.get("profiles.balanced.executor") == "opus"

    def test_set_creates_intermediate_keys(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        cfg.set("new.nested.key", "value")
        assert cfg.get("new.nested.key") == "value"


class TestProjectManagement:
    """Tests for get_project and set_project."""

    def _make_config(self, tmp_path: Path) -> HivemindConfig:
        return HivemindConfig(tmp_path / ".hivemind.json", default_config())

    def test_get_project_empty(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        assert cfg.get_project("myproject") is None

    def test_set_project_then_get(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        cfg.set_project("myproject", "MP", "/home/user/myproject")
        proj = cfg.get_project("myproject")
        assert proj is not None
        assert proj["prefix"] == "MP"
        assert proj["linked_path"] == "/home/user/myproject"

    def test_set_project_updates_existing(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        cfg.set_project("proj", "P1", "/path/one")
        cfg.set_project("proj", "P2", "/path/two")
        proj = cfg.get_project("proj")
        assert proj is not None
        assert proj["prefix"] == "P2"
        assert proj["linked_path"] == "/path/two"

    def test_multiple_projects(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        cfg.set_project("alpha", "A", "/alpha")
        cfg.set_project("beta", "B", "/beta")
        assert cfg.get_project("alpha") is not None
        assert cfg.get_project("beta") is not None
        assert cfg.get_project("alpha")["prefix"] == "A"  # type: ignore[index]

    def test_project_persists_through_save_load(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".hivemind.json"
        cfg = HivemindConfig(config_path, default_config())
        cfg.set_project("myproject", "MP", "/home/user/myproject")
        cfg.save()

        loaded = HivemindConfig.load(config_path)
        proj = loaded.get_project("myproject")
        assert proj is not None
        assert proj["prefix"] == "MP"


class TestDataPath:
    """Tests for data_path property."""

    def test_expands_tilde(self, tmp_path: Path) -> None:
        cfg = HivemindConfig(tmp_path / ".hivemind.json", default_config())
        result = cfg.data_path
        assert "~" not in str(result)
        assert result.is_absolute()

    def test_custom_data_path(self, tmp_path: Path) -> None:
        data = default_config()
        data["data_path"] = str(tmp_path / "custom-data")
        cfg = HivemindConfig(tmp_path / ".hivemind.json", data)
        assert cfg.data_path == tmp_path / "custom-data"

    def test_default_data_path(self, tmp_path: Path) -> None:
        cfg = HivemindConfig(tmp_path / ".hivemind.json", default_config())
        assert cfg.data_path.name == "agent-hivemind-data"
