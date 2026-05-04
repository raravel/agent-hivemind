"""Unit tests for hivemind.installer (plugin, hooks, profiles)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from hivemind.installer.codex_plugin import install_codex_plugin
from hivemind.installer.skills import install_plugin
from hivemind.installer.hooks import install_hooks
from hivemind.installer.profiles import install_profiles
from hivemind.core.config import HivemindConfig, default_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin_source(
    base: Path,
    *,
    skills: list[str] | None = None,
    hooks: bool = False,
) -> Path:
    """Create a minimal plugin directory structure.

    Parameters
    ----------
    base:
        Parent directory in which to create the plugin source.
    skills:
        List of skill names to create (each gets ``skills/<name>/SKILL.md``).
    hooks:
        If True, creates ``hooks/hooks.json`` and ``hooks/hv-pre-commit.js``.

    Returns
    -------
    Path
        The plugin source root directory.
    """
    src = base / "plugin_src"
    # .claude-plugin/plugin.json (required for install_plugin to detect the plugin)
    plugin_meta = src / ".claude-plugin"
    plugin_meta.mkdir(parents=True)
    (plugin_meta / "plugin.json").write_text(
        json.dumps(
            {"name": "hv", "version": "1.0.0", "skills": "./skills/claude/"}
        ),
        encoding="utf-8",
    )

    if skills:
        for name in skills:
            skill_dir = src / "skills" / "claude" / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}", encoding="utf-8")

    if hooks:
        hooks_dir = src / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "hooks.json").write_text("{}", encoding="utf-8")
        (hooks_dir / "hv_pre_commit.py").write_text(
            "#!/usr/bin/env python3\n", encoding="utf-8"
        )

    return src


def _make_codex_plugin_source(base: Path, *, skills: list[str] | None = None) -> Path:
    """Create a minimal Codex plugin source directory structure."""
    src = base / "codex_plugin_src"
    plugin_meta = src / ".codex-plugin"
    plugin_meta.mkdir(parents=True)
    (plugin_meta / "plugin.json").write_text(
        json.dumps({"name": "hv", "version": "1.0.0", "skills": "./skills/codex/"}),
        encoding="utf-8",
    )

    if skills:
        for name in skills:
            skill_dir = src / "skills" / "codex" / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}", encoding="utf-8")

    return src


# ---------------------------------------------------------------------------
# Plugin (skills + hooks via install_plugin)
# ---------------------------------------------------------------------------


@mock.patch("hivemind.installer.skills._run_claude_cmd", return_value=(True, "ok"))
class TestInstallPlugin:
    """Tests for install_plugin()."""

    def test_installs_skills(self, mock_cmd: mock.MagicMock, tmp_path: Path) -> None:
        source = _make_plugin_source(tmp_path, skills=["audit", "plan"])
        target = tmp_path / "target_plugin"

        result = install_plugin(source, target)

        assert "/hv:audit" in result
        assert "/hv:plan" in result
        assert (target / "skills" / "claude" / "audit" / "SKILL.md").exists()
        assert (target / "skills" / "claude" / "plan" / "SKILL.md").exists()
        assert not (target / "skills" / "codex").exists()

    def test_installs_hooks(self, mock_cmd: mock.MagicMock, tmp_path: Path) -> None:
        source = _make_plugin_source(tmp_path, hooks=True)
        target = tmp_path / "target_plugin"

        result = install_plugin(source, target)

        assert "hook:hv_pre_commit" in result
        assert (target / "hooks" / "hooks.json").exists()

    def test_installs_skills_and_hooks(self, mock_cmd: mock.MagicMock, tmp_path: Path) -> None:
        source = _make_plugin_source(tmp_path, skills=["search"], hooks=True)
        target = tmp_path / "target_plugin"

        result = install_plugin(source, target)

        assert "/hv:search" in result
        assert "hook:hv_pre_commit" in result

    def test_overwrites_existing_target(self, mock_cmd: mock.MagicMock, tmp_path: Path) -> None:
        source = _make_plugin_source(tmp_path, skills=["audit"])
        target = tmp_path / "target_plugin"

        # First install
        install_plugin(source, target)
        # Modify a file to verify overwrite
        (target / "skills" / "claude" / "audit" / "SKILL.md").write_text(
            "old", encoding="utf-8"
        )

        # Second install should overwrite
        install_plugin(source, target)
        content = (target / "skills" / "claude" / "audit" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert content == "# audit"

    def test_empty_plugin_returns_empty(self, mock_cmd: mock.MagicMock, tmp_path: Path) -> None:
        source = _make_plugin_source(tmp_path)
        target = tmp_path / "target_plugin"

        result = install_plugin(source, target)

        assert result == []

    def test_registers_plugin_with_claude_cli(self, mock_cmd: mock.MagicMock, tmp_path: Path) -> None:
        source = _make_plugin_source(tmp_path, skills=["audit"])
        target = tmp_path / "target_plugin"

        install_plugin(source, target)

        # _run_claude_cmd should be called at least twice (marketplace add + plugin install)
        assert mock_cmd.call_count >= 2


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


class TestInstallHooks:
    """Tests for install_hooks()."""

    def _make_source(self, tmp_path: Path) -> Path:
        source = tmp_path / "hook_src"
        source.mkdir()
        (source / "hv_pre_commit.py").write_text(
            "#!/usr/bin/env python3\n", encoding="utf-8"
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
        hook_item = entries[0]["hooks"][0]
        assert hook_item["type"] == "command"
        assert "hv_pre_commit.py" in hook_item["command"]
        assert hook_item["command"].startswith("python3 ")

    def test_preserves_existing_hooks(self, tmp_path: Path) -> None:
        source = self._make_source(tmp_path)
        settings = tmp_path / "settings.json"

        existing = {
            "theme": "dark",
            "hooks": {
                "PostToolUse": [
                    {"matcher": "Write", "hooks": ["/user/hook.py"]}
                ]
            },
        }
        settings.write_text(
            json.dumps(existing, indent=2), encoding="utf-8"
        )

        install_hooks(source, settings)

        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["theme"] == "dark"
        assert "PostToolUse" in data["hooks"]
        assert len(data["hooks"]["PostToolUse"]) == 1
        assert "PreToolUse" in data["hooks"]

    def test_skips_duplicate_hooks(self, tmp_path: Path) -> None:
        source = self._make_source(tmp_path)
        settings = tmp_path / "settings.json"

        assert install_hooks(source, settings) is True
        assert install_hooks(source, settings) is False

    def test_copies_py_files(self, tmp_path: Path) -> None:
        source = self._make_source(tmp_path)
        settings = tmp_path / "settings.json"

        install_hooks(source, settings)

        hooks_dir = tmp_path / "hooks"
        assert (hooks_dir / "hv_pre_commit.py").exists()
        assert (
            "python3"
            in (hooks_dir / "hv_pre_commit.py").read_text(encoding="utf-8")
            or "#!/usr/bin/env python3"
            in (hooks_dir / "hv_pre_commit.py").read_text(encoding="utf-8")
        )

    def test_no_py_files_returns_false(self, tmp_path: Path) -> None:
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


class TestInstallCodexPlugin:
    """Tests for Codex plugin installation."""

    def test_installs_skills(self, tmp_path: Path) -> None:
        source = _make_codex_plugin_source(tmp_path, skills=["hv-plan", "hv-task"])
        target = tmp_path / ".codex" / "plugins" / "hv"
        marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"

        result = install_codex_plugin(source, target, marketplace)

        assert "skill:hv-plan" in result
        assert "skill:hv-task" in result
        assert (target / "skills" / "codex" / "hv-plan" / "SKILL.md").exists()
        assert not (target / "skills" / "claude").exists()

    def test_upserts_personal_marketplace(self, tmp_path: Path) -> None:
        source = _make_codex_plugin_source(tmp_path, skills=["hv-plan"])
        target = tmp_path / "plugins" / "hv"
        marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"

        install_codex_plugin(source, target, marketplace)

        data = json.loads(marketplace.read_text(encoding="utf-8"))
        assert data["name"] == "agent-hivemind-local"
        assert any(
            plugin["name"] == "hv" and plugin["source"]["path"] == "./plugins/hv"
            for plugin in data["plugins"]
        )

    def test_updates_current_and_legacy_marketplaces(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        source = _make_codex_plugin_source(tmp_path, skills=["hv-plan"])
        primary_plugin_dir = tmp_path / "plugins" / "hv"
        legacy_plugin_dir = tmp_path / ".codex" / "plugins" / "hv"
        primary_marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"
        legacy_marketplace = tmp_path / ".codex" / "plugins" / "marketplace.json"
        monkeypatch.setattr(
            "hivemind.installer.codex_plugin._PRIMARY_CODEX_PLUGIN_DIR",
            primary_plugin_dir,
        )
        monkeypatch.setattr(
            "hivemind.installer.codex_plugin._LEGACY_CODEX_PLUGIN_DIR",
            legacy_plugin_dir,
        )
        monkeypatch.setattr(
            "hivemind.installer.codex_plugin._PRIMARY_CODEX_MARKETPLACE_PATH",
            primary_marketplace,
        )
        monkeypatch.setattr(
            "hivemind.installer.codex_plugin._LEGACY_CODEX_MARKETPLACE_PATH",
            legacy_marketplace,
        )

        install_codex_plugin(source)

        assert primary_plugin_dir.exists()
        assert legacy_plugin_dir.exists()
        assert primary_marketplace.exists()
        assert legacy_marketplace.exists()
        primary_data = json.loads(primary_marketplace.read_text(encoding="utf-8"))
        legacy_data = json.loads(legacy_marketplace.read_text(encoding="utf-8"))
        assert primary_data["plugins"][0]["source"]["path"] == "./plugins/hv"
        assert legacy_data["plugins"][0]["source"]["path"] == "./.codex/plugins/hv"

    def test_installs_skills_into_codex_skills_dir(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        source = _make_codex_plugin_source(tmp_path, skills=["hv-plan", "hv-task"])
        target = tmp_path / "plugins" / "hv"
        marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"
        skills_root = tmp_path / ".codex" / "skills"
        monkeypatch.setattr(
            "hivemind.installer.codex_plugin._CODEX_SKILLS_DIR",
            skills_root,
        )

        install_codex_plugin(source, target, marketplace)

        assert (skills_root / "hv-plan" / "SKILL.md").exists()
        assert (skills_root / "hv-task" / "SKILL.md").exists()


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
        assert loaded.get("version") == "4.0.0"

    def test_seeds_runtime_models_when_profiles_already_exist(self, tmp_path: Path) -> None:
        data = default_config()
        data.pop("runtime_models", None)
        config_path = self._make_config(tmp_path, data=data)

        result = install_profiles(config_path)

        assert result is True
        loaded = HivemindConfig.load(config_path)
        assert loaded.get("runtime_models.codex.profiles.balanced.executor") == "gpt-5.1-codex"
