"""Unit tests for hv config command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from hivemind.commands.config_cmd import (
    _format_value,
    _is_runtime_aware,
    _parse_value,
    config_cmd,
)
from hivemind.core.config import HivemindConfig, default_config


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    """Create a .hivemind.json in tmp_path and return its path."""
    p = tmp_path / ".hivemind.json"
    cfg = HivemindConfig(p, default_config())
    cfg.save()
    return p


def _patch_resolve(config_path: Path):  # type: ignore[no-untyped-def]
    """Return a patch that makes _resolve_config_path return config_path."""
    return patch(
        "hivemind.commands.config_cmd._resolve_config_path",
        return_value=config_path,
    )


class TestConfigNoArgs:
    """hv config (no arguments) prints full config as JSON."""

    def test_prints_full_config(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, [])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["version"] == "4.0.0"
        assert "profiles" in parsed

    def test_output_is_valid_json(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, [])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)


class TestConfigGetCommonKey:
    """Reading non-runtime-aware keys is unaffected by --target."""

    def test_get_boolean_value(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["git_enabled"])
        assert result.exit_code == 0
        assert result.output.strip() == "False"

    def test_get_missing_key_errors(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["nonexistent.key"])
        assert result.exit_code != 0
        assert "Key not found" in result.output

    def test_target_ignored_for_non_runtime_key(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd, ["git_enabled", "--target", "codex"]
            )
        assert result.exit_code == 0
        assert result.output.strip() == "False"


class TestConfigGetRuntimeAwareNoTarget:
    """Reading runtime-aware keys without --target shows both providers."""

    def test_profiles_balanced_two_sections(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["profiles.balanced"])
        assert result.exit_code == 0
        assert "[claude]" in result.output
        assert "[codex]" in result.output
        assert "claude-sonnet-4-6" in result.output
        assert "gpt-5.1-codex" in result.output

    def test_model_profile_two_sections(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["model_profile"])
        assert result.exit_code == 0
        assert "[claude]" in result.output
        assert "[codex]" in result.output
        assert "balanced" in result.output

    def test_pricing_two_sections(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["pricing"])
        assert result.exit_code == 0
        assert "[claude]" in result.output
        assert "[codex]" in result.output

    def test_format_json_returns_provider_map(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd, ["profiles.balanced", "--format", "json"]
            )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert set(parsed.keys()) == {"claude", "codex"}
        assert parsed["claude"]["executor"] == "claude-sonnet-4-6"
        assert parsed["codex"]["executor"] == "gpt-5.1-codex"

    def test_missing_runtime_key_errors(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["profiles.nonexistent"])
        assert result.exit_code != 0
        assert "Key not found" in result.output


class TestConfigGetRuntimeAwareWithTarget:
    """--target filters runtime-aware reads to one provider."""

    def test_get_profiles_balanced_claude(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd, ["profiles.balanced.executor", "--target", "claude"]
            )
        assert result.exit_code == 0
        assert result.output.strip() == "claude-sonnet-4-6"

    def test_get_profiles_balanced_codex(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd, ["profiles.balanced.executor", "--target", "codex"]
            )
        assert result.exit_code == 0
        assert result.output.strip() == "gpt-5.1-codex"

    def test_get_dict_value_as_json(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd, ["profiles.balanced", "--target", "claude"]
            )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["executor"] == "claude-sonnet-4-6"

    def test_get_model_profile_per_target(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd, ["model_profile", "--target", "codex"]
            )
        assert result.exit_code == 0
        assert result.output.strip() == "balanced"


class TestConfigSetRuntimeAware:
    """Setting runtime-aware keys requires --target."""

    def test_set_model_profile_without_target_errors(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["model_profile", "quality"])
        assert result.exit_code != 0
        assert "--target" in result.output

    def test_set_profiles_nested_without_target_errors(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd, ["profiles.balanced.executor", "opus"]
            )
        assert result.exit_code != 0
        assert "--target" in result.output

    def test_set_model_profile_for_codex_only(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd,
                ["model_profile", "quality", "--target", "codex"],
            )
        assert result.exit_code == 0
        assert "[codex]" in result.output
        reloaded = HivemindConfig.load(config_path)
        assert reloaded.runtime_model_profile("codex") == "quality"
        assert reloaded.runtime_model_profile("claude") == "balanced"

    def test_set_model_profile_for_claude_only(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd,
                ["model_profile", "quality", "--target", "claude"],
            )
        assert result.exit_code == 0
        assert "[claude]" in result.output
        reloaded = HivemindConfig.load(config_path)
        assert reloaded.runtime_model_profile("claude") == "quality"
        assert reloaded.runtime_model_profile("codex") == "balanced"

    def test_set_nested_profile_value_per_target(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd,
                [
                    "profiles.balanced.executor",
                    "opus",
                    "--target",
                    "claude",
                ],
            )
        assert result.exit_code == 0
        reloaded = HivemindConfig.load(config_path)
        assert (
            reloaded.runtime_profiles("claude")["balanced"]["executor"]
            == "opus"
        )
        assert (
            reloaded.runtime_profiles("codex")["balanced"]["executor"]
            == "gpt-5.1-codex"
        )


class TestConfigSetCommonKey:
    """Non-runtime-aware keys do not require --target."""

    def test_set_boolean_value(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["git_enabled", "true"])
        assert result.exit_code == 0
        cfg = HivemindConfig.load(config_path)
        assert cfg.get("git_enabled") is True

    def test_set_numeric_value(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["max_retries", "5"])
        assert result.exit_code == 0
        cfg = HivemindConfig.load(config_path)
        assert cfg.get("max_retries") == 5


class TestConfigProfileShortcut:
    """hv config --profile <name> shortcut."""

    def test_profile_without_target_errors(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["--profile", "quality"])
        assert result.exit_code != 0
        assert "--target" in result.output

    def test_profile_switch_for_claude(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd,
                ["--profile", "quality", "--target", "claude"],
            )
        assert result.exit_code == 0
        cfg = HivemindConfig.load(config_path)
        assert cfg.runtime_model_profile("claude") == "quality"
        assert cfg.runtime_model_profile("codex") == "balanced"

    def test_profile_switch_for_codex(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd,
                ["--profile", "budget", "--target", "codex"],
            )
        assert result.exit_code == 0
        cfg = HivemindConfig.load(config_path)
        assert cfg.runtime_model_profile("codex") == "budget"
        assert cfg.runtime_model_profile("claude") == "balanced"


class TestConfigMissingFile:
    """Error when config file does not exist."""

    def test_missing_config_errors(self, runner: CliRunner, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent" / ".hivemind.json"
        with _patch_resolve(missing):
            result = runner.invoke(config_cmd, [])
        assert result.exit_code != 0
        assert "Config not found" in result.output


class TestIsRuntimeAware:
    """Runtime-aware key classification."""

    @pytest.mark.parametrize(
        "key",
        [
            "profiles",
            "pricing",
            "model_profile",
            "profiles.balanced",
            "profiles.balanced.executor",
            "pricing.opus.input",
        ],
    )
    def test_runtime_aware_keys(self, key: str) -> None:
        assert _is_runtime_aware(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "git_enabled",
            "data_path",
            "default_target",
            "max_retries",
            "parallel.max_concurrency",
        ],
    )
    def test_common_keys(self, key: str) -> None:
        assert _is_runtime_aware(key) is False


class TestParseValue:
    """Tests for the _parse_value helper."""

    def test_parse_true(self) -> None:
        assert _parse_value("true") is True

    def test_parse_false(self) -> None:
        assert _parse_value("false") is False

    def test_parse_int(self) -> None:
        assert _parse_value("42") == 42

    def test_parse_float(self) -> None:
        assert _parse_value("3.14") == 3.14

    def test_parse_string(self) -> None:
        assert _parse_value("hello") == "hello"

    def test_parse_json_list(self) -> None:
        assert _parse_value('["a","b"]') == ["a", "b"]

    def test_parse_json_object(self) -> None:
        assert _parse_value('{"k":"v"}') == {"k": "v"}


class TestFormatValue:
    """Tests for the _format_value helper."""

    def test_format_string(self) -> None:
        assert _format_value("hello") == "hello"

    def test_format_dict(self) -> None:
        result = _format_value({"a": 1})
        parsed = json.loads(result)
        assert parsed == {"a": 1}

    def test_format_list(self) -> None:
        result = _format_value([1, 2, 3])
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def test_format_bool(self) -> None:
        assert _format_value(True) == "True"

    def test_format_int(self) -> None:
        assert _format_value(42) == "42"
