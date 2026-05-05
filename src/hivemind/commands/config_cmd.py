"""Implementation of `hv config` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import click

from hivemind.core.config import HivemindConfig

_RUNTIME_TARGETS: tuple[str, ...] = ("claude", "codex")
_RUNTIME_AWARE_PREFIXES: tuple[str, ...] = ("profiles.", "pricing.")
_RUNTIME_AWARE_KEYS: frozenset[str] = frozenset(
    {"profiles", "pricing", "model_profile"}
)


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


def _is_runtime_aware(key: str) -> bool:
    """Whether a config key is per-provider (claude/codex)."""
    if key in _RUNTIME_AWARE_KEYS:
        return True
    return any(key.startswith(prefix) for prefix in _RUNTIME_AWARE_PREFIXES)


def _get_for_target(cfg: HivemindConfig, key: str, target: str) -> Any:
    """Read a runtime-aware value scoped to a specific target."""
    if key == "model_profile":
        return cfg.runtime_model_profile(target)
    if key == "profiles":
        return cfg.runtime_profiles(target)
    if key.startswith("profiles."):
        return _walk_nested(cfg.runtime_profiles(target), key.split(".")[1:])
    if key == "pricing":
        return cfg.runtime_pricing(target)
    if key.startswith("pricing."):
        return _walk_nested(cfg.runtime_pricing(target), key.split(".")[1:])
    return cfg.get(key)


def _set_for_target(
    cfg: HivemindConfig, key: str, value: Any, target: str
) -> None:
    """Write a runtime-aware value scoped to a specific target."""
    if key == "model_profile":
        cfg.set_runtime_model_profile(str(value), target=target)
        return
    if key == "profiles":
        if not isinstance(value, dict):
            raise click.ClickException("profiles must be a JSON object")
        cfg.set_runtime_profiles(value, target=target)
        return
    if key.startswith("profiles."):
        cfg.ensure_runtime_models()
        cfg.set(f"runtime_models.{target}.{key}", value)
        if target == "claude":
            cfg.set(key, value)
        return
    if key == "pricing":
        if not isinstance(value, dict):
            raise click.ClickException("pricing must be a JSON object")
        cfg.set_runtime_pricing(value, target=target)
        return
    if key.startswith("pricing."):
        cfg.ensure_runtime_models()
        cfg.set(f"runtime_models.{target}.{key}", value)
        if target == "claude":
            cfg.set(key, value)
        return
    cfg.set(key, value)


def _format_both_targets(
    cfg: HivemindConfig, key: str, fmt: str
) -> tuple[str, bool]:
    """Render a runtime-aware key for all providers.

    Returns ``(rendered_text, any_value_found)``. ``any_value_found`` is
    False when neither runtime has the key set.
    """
    values: dict[str, Any] = {
        target: _get_for_target(cfg, key, target) for target in _RUNTIME_TARGETS
    }
    any_value = any(v is not None for v in values.values())

    if fmt == "json":
        return json.dumps(values, indent=2, ensure_ascii=False), any_value

    sections: list[str] = []
    for target in _RUNTIME_TARGETS:
        v = values[target]
        body = _format_value(v) if v is not None else "(not set)"
        sections.append(f"[{target}]\n{body}")
    return "\n\n".join(sections), any_value


@click.command("config")
@click.argument("key", required=False, default=None)
@click.argument("value", required=False, default=None)
@click.option(
    "--profile",
    default=None,
    help="Shortcut to set model_profile (requires --target).",
)
@click.option(
    "--target",
    type=click.Choice(list(_RUNTIME_TARGETS)),
    default=None,
    help="Runtime target for runtime-aware keys (profiles, pricing, model_profile).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format when reading runtime-aware keys without --target.",
)
def config_cmd(
    key: Optional[str],
    value: Optional[str],
    profile: Optional[str],
    target: Optional[str],
    fmt: str,
) -> None:
    """View or set configuration values.

    \b
    Runtime-aware keys (profiles.*, pricing.*, model_profile) are
    stored per provider (claude/codex). Reads without --target print
    both providers as labeled sections. Writes always require --target.

    \b
    Examples:
      hv config                                       # full config (JSON)
      hv config profiles.balanced                     # both providers
      hv config profiles.balanced --target codex      # one provider
      hv config profiles.balanced --format json       # both, JSON map
      hv config model_profile quality --target codex  # set per provider
      hv config git_enabled true                      # non-runtime keys
      hv config --profile quality --target claude     # shortcut
    """
    cfg = _load_config()

    # --profile shortcut: requires --target.
    if profile is not None:
        if target is None:
            raise click.ClickException(
                "--profile requires --target {claude|codex}"
            )
        cfg.set_runtime_model_profile(profile, target=target)
        cfg.save()
        click.echo(f"[{target}] model_profile = {profile}")
        return

    # No args: dump full config.
    if key is None:
        click.echo(json.dumps(cfg.raw, indent=2, ensure_ascii=False))
        return

    runtime_aware = _is_runtime_aware(key)

    # Read.
    if value is None:
        if runtime_aware and target is None:
            rendered, any_value = _format_both_targets(cfg, key, fmt)
            if not any_value:
                raise click.ClickException(f"Key not found: {key}")
            click.echo(rendered)
            return

        if runtime_aware:
            result = _get_for_target(cfg, key, target)  # type: ignore[arg-type]
        else:
            result = cfg.get(key)
        if result is None:
            raise click.ClickException(f"Key not found: {key}")
        click.echo(_format_value(result))
        return

    # Write.
    parsed = _parse_value(value)
    if runtime_aware:
        if target is None:
            raise click.ClickException(
                f"Setting '{key}' requires --target {{claude|codex}}"
            )
        _set_for_target(cfg, key, parsed, target)
        cfg.save()
        click.echo(f"[{target}] {key} = {_format_value(parsed)}")
        return

    cfg.set(key, parsed)
    cfg.save()
    click.echo(f"{key} = {_format_value(parsed)}")
