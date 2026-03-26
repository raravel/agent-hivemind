"""Implementation of `hv config` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import click

from hivemind.core.config import HivemindConfig


def _resolve_config_path() -> Path:
    """Find .hivemind.json by checking the default data path."""
    return Path("~/agent-hivemind-data").expanduser() / ".hivemind.json"


def _load_config() -> HivemindConfig:
    """Load the hivemind config, raising a click error if not found."""
    config_path = _resolve_config_path()
    if not config_path.exists():
        raise click.ClickException(
            f"Config not found at {config_path}. Run 'hv init' first."
        )
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
        cfg.set("model_profile", profile)
        cfg.save()
        click.echo(f"model_profile = {profile}")
        return

    # No args: dump full config
    if key is None:
        click.echo(json.dumps(cfg.raw, indent=2, ensure_ascii=False))
        return

    # Key only: get value
    if value is None:
        result = cfg.get(key)
        if result is None:
            raise click.ClickException(f"Key not found: {key}")
        click.echo(_format_value(result))
        return

    # Key + value: set
    parsed = _parse_value(value)
    cfg.set(key, parsed)
    cfg.save()
    click.echo(f"{key} = {_format_value(parsed)}")
