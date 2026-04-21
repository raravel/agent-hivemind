"""Unit tests for hv config command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from hivemind.commands.config_cmd import config_cmd, _parse_value, _format_value
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
        assert parsed["version"] == "3.0.0"
        assert "profiles" in parsed

    def test_output_is_valid_json(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, [])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)


class TestConfigGet:
    """hv config <key> prints value for that key."""

    def test_get_top_level_key(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["model_profile"])
        assert result.exit_code == 0
        assert result.output.strip() == "balanced"

    def test_get_nested_key(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["profiles.balanced.executor"])
        assert result.exit_code == 0
        assert result.output.strip() == "claude-sonnet-4-6"

    def test_get_dict_value_as_json(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["profiles.balanced"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["executor"] == "claude-sonnet-4-6"

    def test_get_missing_key_errors(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["nonexistent.key"])
        assert result.exit_code != 0
        assert "Key not found" in result.output

    def test_get_boolean_value(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["git_enabled"])
        assert result.exit_code == 0
        assert result.output.strip() == "False"


class TestConfigSet:
    """hv config <key> <value> sets and persists value."""

    def test_set_string_value(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["model_profile", "quality"])
        assert result.exit_code == 0
        assert "quality" in result.output

        # Verify persistence
        cfg = HivemindConfig.load(config_path)
        assert cfg.get("model_profile") == "quality"

    def test_set_boolean_value(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["git_enabled", "true"])
        assert result.exit_code == 0

        cfg = HivemindConfig.load(config_path)
        assert cfg.get("git_enabled") is True

    def test_set_nested_value(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(
                config_cmd, ["profiles.balanced.executor", "opus"]
            )
        assert result.exit_code == 0

        cfg = HivemindConfig.load(config_path)
        assert cfg.get("profiles.balanced.executor") == "opus"

    def test_set_numeric_value(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["max_retries", "5"])
        assert result.exit_code == 0

        cfg = HivemindConfig.load(config_path)
        assert cfg.get("max_retries") == 5


class TestConfigProfile:
    """hv config --profile <name> shortcut."""

    def test_profile_switch(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["--profile", "quality"])
        assert result.exit_code == 0
        assert "quality" in result.output

        cfg = HivemindConfig.load(config_path)
        assert cfg.get("model_profile") == "quality"

    def test_profile_switch_to_budget(
        self, runner: CliRunner, config_path: Path
    ) -> None:
        with _patch_resolve(config_path):
            result = runner.invoke(config_cmd, ["--profile", "budget"])
        assert result.exit_code == 0

        cfg = HivemindConfig.load(config_path)
        assert cfg.get("model_profile") == "budget"


class TestConfigMissingFile:
    """Error when config file does not exist."""

    def test_missing_config_errors(self, runner: CliRunner, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent" / ".hivemind.json"
        with _patch_resolve(missing):
            result = runner.invoke(config_cmd, [])
        assert result.exit_code != 0
        assert "Config not found" in result.output


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
