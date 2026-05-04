"""Implementation of `hv config` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import click

from hivemind.core.config import HivemindConfig


def _resolve_config_path() -> Path:
    """Find .hivemind.json at the canonical v4 location."""
    from hivemind.core.config import default_config_path

    return default_config_path()


def _load_config() -> HivemindConfig:
    """Load the hivemind config, raising a click error if not found.

    Triggers the idempotent v3→v4 migration on first read after upgrade.
    The path is resolved via :func:`_resolve_config_path` so tests can
    patch the lookup to a tmp directory.
    """
    config_path = _resolve_config_path()
    if not config_path.exists():
        raise click.ClickException(
            f"Config not found at {config_path}. Run 'hv init' first."
        )
    from hivemind.core.migration import migrate_v3_to_v4

    migrate_v3_to_v4(config_path)
    return HivemindConfig.load(config_path)


def _format_value(value: Any) -> str:
    """Format a config value for display."""
    if isinstance(value, dict | list):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)


def _parse_value(raw: str) -> Any:
    """Parse a string value into a typed Python value.

    Attempts JSON parsing first (for booleans, numbers, objects, arrays),
    then falls back to plain string.
    """
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def _walk_nested(value: Any, parts: list[str]) -> Any:
    """Read a nested value from a dict using split key parts."""
    current = value
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _get_effective_value(cfg: HivemindConfig, key: str) -> Any:
    """Get a config value with runtime-aware aliases for model settings."""
    if key == "data_path":
        # v4: data_path is derived from the config file's parent dir,
        # not stored as a JSON field. Surface it via the property so
        # callers (skills, scripts) can rely on `hv config data_path`.
        return str(cfg.data_path)
    if key == "model_profile":
        return cfg.runtime_model_profile()
    if key == "profiles":
        return cfg.runtime_profiles()
    if key.startswith("profiles."):
        return _walk_nested(cfg.runtime_profiles(), key.split(".")[1:])
    if key == "pricing":
        return cfg.runtime_pricing()
    if key.startswith("pricing."):
        return _walk_nested(cfg.runtime_pricing(), key.split(".")[1:])
    return cfg.get(key)


def _set_effective_value(cfg: HivemindConfig, key: str, value: Any) -> None:
    """Set a config value with runtime-aware aliases for model settings."""
    if key == "model_profile":
        cfg.set_runtime_model_profile(str(value))
        return
    if key == "profiles":
        if not isinstance(value, dict):
            raise click.ClickException("profiles must be a JSON object")
        cfg.set_runtime_profiles(value)
        return
    if key.startswith("profiles."):
        cfg.ensure_runtime_models()
        cfg.set(f"runtime_models.{cfg.default_target}.{key}", value)
        if cfg.default_target == "claude":
            cfg.set(key, value)
        return
    if key == "pricing":
        if not isinstance(value, dict):
            raise click.ClickException("pricing must be a JSON object")
        cfg.set_runtime_pricing(value)
        return
    if key.startswith("pricing."):
        cfg.ensure_runtime_models()
        cfg.set(f"runtime_models.{cfg.default_target}.{key}", value)
        if cfg.default_target == "claude":
            cfg.set(key, value)
        return
    cfg.set(key, value)


@click.command("config")
@click.argument("key", required=False, default=None)
@click.argument("value", required=False, default=None)
@click.option(
    "--profile",
    default=None,
    help="Shortcut to set model_profile.",
)
def config_cmd(
    key: Optional[str],
    value: Optional[str],
    profile: Optional[str],
) -> None:
    """View or set configuration values.

    \b
    Examples:
      hv config                          # print full config
      hv config model_profile            # print one value
      hv config profiles.balanced        # dot-notation access
      hv config git_enabled true         # set a value
      hv config --profile quality        # shortcut for model_profile
    """
    cfg = _load_config()

    # --profile shortcut
    if profile is not None:
        cfg.set_runtime_model_profile(profile)
        cfg.save()
        click.echo(f"model_profile = {profile}")
        return

    # No args: dump full config
    if key is None:
        click.echo(json.dumps(cfg.raw, indent=2, ensure_ascii=False))
        return

    # Key only: get value
    if value is None:
        result = _get_effective_value(cfg, key)
        if result is None:
            raise click.ClickException(f"Key not found: {key}")
        click.echo(_format_value(result))
        return

    # Key + value: set
    parsed = _parse_value(value)
    _set_effective_value(cfg, key, parsed)
    cfg.save()
    click.echo(f"{key} = {_format_value(parsed)}")
