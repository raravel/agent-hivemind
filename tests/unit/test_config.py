"""Unit tests for hivemind.core.config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hivemind.core.config import (
    CLAUDE_DEFAULT_PRICING,
    CONFIG_FILENAME,
    DEFAULT_PRICING,
    SCHEMA_VERSION,
    HivemindConfig,
    data_path_for_storage,
    default_config,
    default_config_path,
    expand_target_selection,
    normalize_data_path,
)


class TestDefaultConfig:
    """Tests for default_config()."""

    def test_returns_dict(self) -> None:
        cfg = default_config()
        assert isinstance(cfg, dict)

    def test_version(self) -> None:
        cfg = default_config()
        assert cfg["version"] == SCHEMA_VERSION
        assert cfg["version"] == "5.0.0"

    def test_has_all_top_level_keys(self) -> None:
        cfg = default_config()
        expected_keys = {
            "version",
            "git_enabled",
            "auto_commit",
            "model_profile",
            "profiles",
            "pricing",
            "parallel",
            "projects",
            "filter_patterns",
            "runtime",
            "runtime_models",
        }
        assert set(cfg.keys()) == expected_keys

    def test_no_top_level_data_path(self) -> None:
        cfg = default_config()
        assert "data_path" not in cfg

    def test_profiles_use_concrete_model_ids(self) -> None:
        cfg = default_config()
        for profile in cfg["profiles"].values():
            for role in ("planner", "executor", "reviewer"):
                model_id = profile[role]
                assert model_id.startswith("claude-"), model_id
                assert "-4-" in model_id, model_id

    def test_pricing_has_all_models(self) -> None:
        cfg = default_config()
        # Every model ID referenced in profiles must have pricing defined
        pricing_models = set(cfg["pricing"].keys())
        for profile in cfg["profiles"].values():
            for role in ("planner", "executor", "reviewer"):
                assert profile[role] in pricing_models

    def test_parallel_default_concurrency(self) -> None:
        cfg = default_config()
        assert cfg["parallel"]["max_concurrency"] == 2

    def test_profiles_contain_three(self) -> None:
        cfg = default_config()
        assert set(cfg["profiles"].keys()) == {"quality", "balanced", "budget"}

    def test_each_profile_has_roles(self) -> None:
        cfg = default_config()
        for name, profile in cfg["profiles"].items():
            assert "planner" in profile, f"{name} missing planner"
            assert "executor" in profile, f"{name} missing executor"
            assert "reviewer" in profile, f"{name} missing reviewer"

    def test_balanced_uses_sonnet_executor(self) -> None:
        cfg = default_config()
        assert cfg["profiles"]["balanced"]["executor"] == "claude-sonnet-4-6"

    def test_budget_uses_haiku(self) -> None:
        cfg = default_config()
        assert cfg["profiles"]["budget"]["reviewer"] == "claude-haiku-4-5"

    def test_projects_empty(self) -> None:
        cfg = default_config()
        assert cfg["projects"] == {}

    def test_filter_patterns_empty(self) -> None:
        cfg = default_config()
        assert cfg["filter_patterns"] == []

    def test_runtime_defaults_to_claude(self) -> None:
        cfg = default_config()
        assert cfg["runtime"]["default_target"] == "claude"
        assert cfg["runtime"]["enabled_targets"] == ["claude"]

    def test_runtime_models_include_codex(self) -> None:
        cfg = default_config()
        codex_profiles = cfg["runtime_models"]["codex"]["profiles"]
        assert codex_profiles["balanced"]["executor"] == "gpt-5.1-codex"
        assert cfg["runtime_models"]["codex"]["pricing"]["codex-mini-latest"]["output"] == 6.0

    def test_default_pricing_alias_is_not_shared_reference(self) -> None:
        assert DEFAULT_PRICING == CLAUDE_DEFAULT_PRICING
        assert DEFAULT_PRICING is not CLAUDE_DEFAULT_PRICING


class TestTargetExpansion:
    """Tests for runtime target parsing helpers."""

    def test_expand_single_target(self) -> None:
        assert expand_target_selection("claude") == ["claude"]

    def test_expand_both_targets(self) -> None:
        assert expand_target_selection("both") == ["claude", "codex"]

    def test_expand_invalid_target_raises(self) -> None:
        with pytest.raises(ValueError):
            expand_target_selection("invalid")


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
        assert cfg.get("version") == "5.0.0"

    def test_get_nested(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        result = cfg.get("profiles.balanced")
        assert isinstance(result, dict)
        assert result["executor"] == "claude-sonnet-4-6"

    def test_get_deeply_nested(self, tmp_path: Path) -> None:
        cfg = self._make_config(tmp_path)
        assert cfg.get("profiles.balanced.planner") == "claude-opus-4-7"

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
        cfg.set("profiles.balanced.executor", "claude-opus-4-7")
        assert cfg.get("profiles.balanced.executor") == "claude-opus-4-7"

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

    def test_runtime_targets_persist(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".hivemind.json"
        cfg = HivemindConfig(config_path, default_config())
        cfg.set_runtime_targets(
            default_target="codex",
            enabled_targets=["claude", "codex"],
        )
        cfg.save()

        loaded = HivemindConfig.load(config_path)
        assert loaded.default_target == "codex"
        assert loaded.enabled_targets == ["claude", "codex"]

    def test_runtime_profile_helpers(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".hivemind.json"
        cfg = HivemindConfig(config_path, default_config())
        cfg.set_runtime_targets(default_target="codex", enabled_targets=["codex"])
        cfg.save()

        loaded = HivemindConfig.load(config_path)
        assert loaded.runtime_model_profile() == "balanced"
        assert loaded.runtime_profile()["executor"] == "gpt-5.1-codex"
        assert loaded.runtime_pricing()["gpt-5.2-codex"]["input"] == 1.75


class TestDataPath:
    """Tests for data_path property — derived from config file location."""

    def test_data_path_is_config_parent(self, tmp_path: Path) -> None:
        cfg = HivemindConfig(tmp_path / ".hivemind.json", default_config())
        assert cfg.data_path == tmp_path.resolve()

    def test_data_path_absolute(self, tmp_path: Path) -> None:
        cfg = HivemindConfig(tmp_path / ".hivemind.json", default_config())
        assert cfg.data_path.is_absolute()
        assert "~" not in str(cfg.data_path)

    def test_legacy_data_path_field_wins_during_transition(
        self, tmp_path: Path
    ) -> None:
        """v3 fixtures with an explicit ``data_path`` field still resolve.

        The v4 schema drops the field, but until ``hv migrate --to v4``
        rewrites a config the runtime honours the legacy value so
        existing data layouts keep working.
        """
        data = default_config()
        legacy = tmp_path / "legacy-data"
        legacy.mkdir()
        data["data_path"] = str(legacy)
        cfg = HivemindConfig(tmp_path / ".hivemind.json", data)
        assert cfg.data_path == legacy.resolve()


class TestGlobalConfig:
    """Tests for canonical-path resolver and load_global."""

    def test_default_config_path(self) -> None:
        path = default_config_path()
        assert path.name == CONFIG_FILENAME
        assert path.parent.name == "agent-hivemind-data"
        assert path.is_absolute()

    def test_load_global_missing_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Redirect HOME so the canonical path lives under a clean tmp dir.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        with pytest.raises(FileNotFoundError):
            HivemindConfig.load_global()

    def test_load_global_returns_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        target_dir = tmp_path / "agent-hivemind-data"
        target_dir.mkdir()
        target_path = target_dir / ".hivemind.json"
        HivemindConfig(target_path, default_config()).save()

        loaded = HivemindConfig.load_global()
        assert loaded.path == target_path.resolve()
        assert loaded.data_path == target_dir.resolve()

    def test_load_global_auto_migrates_v3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_global silently migrates a v3 config on first read."""
        import json as _json

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        target_dir = tmp_path / "agent-hivemind-data"
        target_dir.mkdir()
        target_path = target_dir / ".hivemind.json"
        target_path.write_text(
            _json.dumps(
                {
                    "version": "3.0.0",
                    "data_path": str(target_dir),
                    "projects": {},
                }
            ),
            encoding="utf-8",
        )

        loaded = HivemindConfig.load_global()
        assert loaded.get("version") == "4.0.0"
        on_disk = _json.loads(target_path.read_text(encoding="utf-8"))
        assert on_disk["version"] == "4.0.0"
        assert "data_path" not in on_disk


class TestFindForCommand:
    """Tests for the consolidated find_for_command CLI helper."""

    def test_raises_when_no_candidate_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            HivemindConfig.find_for_command()

    def test_finds_canonical_and_auto_migrates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as _json

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        # Use a separate cwd so the cwd candidate doesn't shadow the canonical one.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        canonical_dir = tmp_path / "agent-hivemind-data"
        canonical_dir.mkdir()
        (canonical_dir / ".hivemind.json").write_text(
            _json.dumps(
                {"version": "3.0.0", "data_path": str(canonical_dir), "projects": {}}
            ),
            encoding="utf-8",
        )

        cfg = HivemindConfig.find_for_command()
        assert cfg.get("version") == "4.0.0"
        on_disk = _json.loads(
            (canonical_dir / ".hivemind.json").read_text(encoding="utf-8")
        )
        assert on_disk["version"] == "4.0.0"
        assert "data_path" not in on_disk

    def test_non_canonical_candidate_is_not_auto_migrated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as _json

        # Redirect HOME so the canonical path lives under a clean tmp dir
        # but does not exist on disk; the cwd candidate must be picked instead.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()
        monkeypatch.chdir(cwd_dir)

        cwd_config = cwd_dir / ".hivemind.json"
        v3_payload = {
            "version": "3.0.0",
            "data_path": str(cwd_dir),
            "projects": {},
        }
        cwd_config.write_text(_json.dumps(v3_payload), encoding="utf-8")
        before = cwd_config.read_text(encoding="utf-8")

        cfg = HivemindConfig.find_for_command()
        # Picked the cwd candidate, version stays at v3 — the non-canonical
        # path is left alone so test fixtures and one-off layouts don't get
        # rewritten on every CLI invocation.
        assert cfg.get("version") == "3.0.0"
        assert cwd_config.read_text(encoding="utf-8") == before

    def test_cwd_candidate_takes_precedence_over_canonical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as _json

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()
        monkeypatch.chdir(cwd_dir)

        # Both layouts exist; cwd should win.
        canonical_dir = tmp_path / "agent-hivemind-data"
        canonical_dir.mkdir()
        (canonical_dir / ".hivemind.json").write_text(
            _json.dumps({"version": "4.0.0", "projects": {"canonical": {}}}),
            encoding="utf-8",
        )
        (cwd_dir / ".hivemind.json").write_text(
            _json.dumps({"version": "4.0.0", "projects": {"cwd": {}}}),
            encoding="utf-8",
        )

        cfg = HivemindConfig.find_for_command()
        assert "cwd" in cfg.raw["projects"]
        assert "canonical" not in cfg.raw["projects"]


class TestNormalizeDataPath:
    """Tests for the normalize_data_path helper."""

    def test_expands_tilde(self) -> None:
        result = normalize_data_path("~/agent-hivemind-data")
        assert "~" not in str(result)
        assert result.is_absolute()

    def test_none_returns_default(self) -> None:
        result = normalize_data_path(None)
        assert result.name == "agent-hivemind-data"

    def test_empty_returns_default(self) -> None:
        result = normalize_data_path("")
        assert result.name == "agent-hivemind-data"

    def test_foreign_windows_on_posix_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.platform", "linux")
        result = normalize_data_path("C:\\Users\\x\\agent-hivemind-data")
        assert "C:" not in str(result)


class TestDataPathForStorage:
    """Tests for data_path_for_storage()."""

    def test_posix_separator(self, tmp_path: Path) -> None:
        result = data_path_for_storage(tmp_path / "sub" / "data")
        assert "\\" not in result

    def test_home_relative_prefix(self) -> None:
        home = Path.home()
        inside = home / "agent-hivemind-data"
        result = data_path_for_storage(inside)
        assert result.startswith("~/")

    def test_outside_home_is_absolute(self, tmp_path: Path) -> None:
        # tmp_path is typically outside home; if it happens to be inside, skip
        if tmp_path.resolve().is_relative_to(Path.home().resolve()):
            pytest.skip("tmp_path resides under HOME on this runner")
        result = data_path_for_storage(tmp_path / "data")
        assert not result.startswith("~/")
