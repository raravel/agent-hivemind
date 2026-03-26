"""Unit tests for hivemind.installer (skills, hooks, profiles)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hivemind.installer.skills import install_skills
from hivemind.installer.hooks import install_hooks
from hivemind.installer.profiles import install_profiles
from hivemind.core.config import HivemindConfig, default_config


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


class TestInstallSkills:
    """Tests for install_skills()."""

    def test_copies_md_files(self, tmp_path: Path) -> None:
        source = tmp_path / "skills_src"
        source.mkdir()
        (source / "a.md").write_text("skill-a", encoding="utf-8")
        (source / "b.md").write_text("skill-b", encoding="utf-8")

        target = tmp_path / "skills_dst"
        result = install_skills(source, target)

        assert sorted(result) == ["a.md", "b.md"]
        assert (target / "a.md").read_text(encoding="utf-8") == "skill-a"
        assert (target / "b.md").read_text(encoding="utf-8") == "skill-b"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        source = tmp_path / "skills_src"
        source.mkdir()
        (source / "a.md").write_text("v2", encoding="utf-8")

        target = tmp_path / "skills_dst"
        target.mkdir()
        (target / "a.md").write_text("v1", encoding="utf-8")

        install_skills(source, target)
        assert (target / "a.md").read_text(encoding="utf-8") == "v2"

    def test_preserves_subdirectory_structure(self, tmp_path: Path) -> None:
        source = tmp_path / "skills_src"
        sub = source / "sub"
        sub.mkdir(parents=True)
        (sub / "deep.md").write_text("deep", encoding="utf-8")

        target = tmp_path / "skills_dst"
        result = install_skills(source, target)

        # On Windows the separator might be backslash; normalise.
        normalised = [r.replace("\\", "/") for r in result]
        assert "sub/deep.md" in normalised
        assert (target / "sub" / "deep.md").exists()

    def test_ignores_non_md_files(self, tmp_path: Path) -> None:
        source = tmp_path / "skills_src"
        source.mkdir()
        (source / "readme.txt").write_text("ignore", encoding="utf-8")
        (source / "keep.md").write_text("keep", encoding="utf-8")

        target = tmp_path / "skills_dst"
        result = install_skills(source, target)

        assert result == ["keep.md"]
        assert not (target / "readme.txt").exists()

    def test_creates_target_dir(self, tmp_path: Path) -> None:
        source = tmp_path / "skills_src"
        source.mkdir()
        (source / "a.md").write_text("a", encoding="utf-8")

        target = tmp_path / "nonexistent" / "nested"
        install_skills(source, target)
        assert target.is_dir()

    def test_empty_source_returns_empty(self, tmp_path: Path) -> None:
        source = tmp_path / "empty"
        source.mkdir()
        target = tmp_path / "out"
        result = install_skills(source, target)
        assert result == []


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


class TestInstallHooks:
    """Tests for install_hooks()."""

    def _make_source(self, tmp_path: Path) -> Path:
        source = tmp_path / "hook_src"
        source.mkdir()
        (source / "hv-pre-commit.js").write_text(
            "// hook", encoding="utf-8"
        )
        return source

    def test_adds_hooks_to_empty_settings(self, tmp_path: Path) -> None:
        source = self._make_source(tmp_path)
        settings = tmp_path / "settings.json"

        result = install_hooks(source, settings)

        assert result is True
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "hooks" in data
        assert "PreToolUse" in data["hooks"]
        entries = data["hooks"]["PreToolUse"]
        assert len(entries) == 1
        assert entries[0]["matcher"] == "Bash"
        assert "~/.claude/hooks/hv-pre-commit.js" in entries[0]["hooks"]

    def test_preserves_existing_hooks(self, tmp_path: Path) -> None:
        source = self._make_source(tmp_path)
        settings = tmp_path / "settings.json"

        # Pre-existing setting with a user hook
        existing = {
            "theme": "dark",
            "hooks": {
                "PostToolUse": [
                    {"matcher": "Write", "hooks": ["/user/hook.js"]}
                ]
            },
        }
        settings.write_text(
            json.dumps(existing, indent=2), encoding="utf-8"
        )

        install_hooks(source, settings)

        data = json.loads(settings.read_text(encoding="utf-8"))
        # User hook still present
        assert data["theme"] == "dark"
        assert "PostToolUse" in data["hooks"]
        assert len(data["hooks"]["PostToolUse"]) == 1
        # Hivemind hook added
        assert "PreToolUse" in data["hooks"]

    def test_skips_duplicate_hooks(self, tmp_path: Path) -> None:
        source = self._make_source(tmp_path)
        settings = tmp_path / "settings.json"

        # First install
        assert install_hooks(source, settings) is True
        # Second install should detect duplicate and skip
        assert install_hooks(source, settings) is False

    def test_copies_js_files(self, tmp_path: Path) -> None:
        source = self._make_source(tmp_path)
        settings = tmp_path / "settings.json"

        install_hooks(source, settings)

        hooks_dir = tmp_path / "hooks"
        assert (hooks_dir / "hv-pre-commit.js").exists()
        assert (
            (hooks_dir / "hv-pre-commit.js").read_text(encoding="utf-8")
            == "// hook"
        )

    def test_no_js_files_returns_false(self, tmp_path: Path) -> None:
        source = tmp_path / "empty_hooks"
        source.mkdir()
        settings = tmp_path / "settings.json"

        result = install_hooks(source, settings)
        assert result is False

    def test_creates_settings_if_missing(self, tmp_path: Path) -> None:
        source = self._make_source(tmp_path)
        settings = tmp_path / "settings.json"
        assert not settings.exists()

        install_hooks(source, settings)
        assert settings.exists()


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


class TestInstallProfiles:
    """Tests for install_profiles()."""

    def _make_config(self, tmp_path: Path, data: dict | None = None) -> Path:
        config_path = tmp_path / ".hivemind.json"
        if data is None:
            data = default_config()
            # Remove profiles to simulate missing
            data.pop("profiles", None)
        cfg = HivemindConfig(config_path, data)
        cfg.save()
        return config_path

    def test_adds_default_profiles(self, tmp_path: Path) -> None:
        config_path = self._make_config(tmp_path)
        result = install_profiles(config_path)

        assert result is True
        loaded = HivemindConfig.load(config_path)
        profiles = loaded.get("profiles")
        assert isinstance(profiles, dict)
        assert set(profiles.keys()) == {"quality", "balanced", "budget"}

    def test_skips_if_profiles_exist(self, tmp_path: Path) -> None:
        # Use full default config which already has profiles
        config_path = self._make_config(tmp_path, data=default_config())
        result = install_profiles(config_path)
        assert result is False

    def test_profiles_have_correct_roles(self, tmp_path: Path) -> None:
        config_path = self._make_config(tmp_path)
        install_profiles(config_path)

        loaded = HivemindConfig.load(config_path)
        for name in ("quality", "balanced", "budget"):
            profile = loaded.get(f"profiles.{name}")
            assert isinstance(profile, dict)
            assert "planner" in profile
            assert "executor" in profile
            assert "reviewer" in profile

    def test_preserves_other_config_keys(self, tmp_path: Path) -> None:
        data = default_config()
        data.pop("profiles", None)
        data["model_profile"] = "quality"
        config_path = self._make_config(tmp_path, data=data)

        install_profiles(config_path)

        loaded = HivemindConfig.load(config_path)
        assert loaded.get("model_profile") == "quality"
        assert loaded.get("version") == "2.0.0"
