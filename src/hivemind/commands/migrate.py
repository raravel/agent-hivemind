"""Migration logic for v1 -> v2 data directory upgrade."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import click

from hivemind.core.config import default_config


def detect_v1(data_path: Path) -> bool:
    """Check if *data_path* looks like a v1 hivemind data directory.

    A directory is considered v1 when:
    - ``.hivemind.json`` exists but has no ``version`` field, **or**
      the version starts with ``"1."``.
    - ``important.md`` exists at the data-root level (not inside ``level1/``).
    """
    config_path = data_path / ".hivemind.json"
    if not config_path.exists():
        return False

    try:
        with config_path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    version = data.get("version")
    if version is None:
        # No version field at all -> v1
        return True
    if isinstance(version, str) and version.startswith("1."):
        return True

    # Also check for root-level important.md without level1 copy
    root_important = data_path / "important.md"
    level1_important = data_path / "level1" / "important.md"
    if root_important.exists() and not level1_important.exists():
        return True

    return False


def migrate_v1_to_v2(data_path: Path) -> dict[str, list[str]]:
    """Migrate a v1 data directory to v2 format in-place.

    This function is designed to be **idempotent** -- running it multiple
    times on the same directory will not duplicate work or lose data.

    Returns a summary dict with keys ``moved``, ``created``, ``updated``.
    """
    summary: dict[str, list[str]] = {
        "moved": [],
        "created": [],
        "updated": [],
    }

    # ------------------------------------------------------------------
    # 1. Move important.md -> level1/important.md (copy, keep original)
    # ------------------------------------------------------------------
    root_important = data_path / "important.md"
    level1_dir = data_path / "level1"
    level1_important = level1_dir / "important.md"

    if root_important.exists() and not level1_important.exists():
        level1_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(root_important), str(level1_important))
        summary["moved"].append("important.md -> level1/important.md")

    # ------------------------------------------------------------------
    # 2. Create missing v2 directories
    # ------------------------------------------------------------------
    for dirname in ("projects", "tasks", "level1", "level2", "level3"):
        dir_path = data_path / dirname
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            summary["created"].append(f"{dirname}/")

    # level2 subdirectories
    for subdir in ("frontend", "backend", "infra", "general"):
        sub_path = data_path / "level2" / subdir
        if not sub_path.exists():
            sub_path.mkdir(parents=True, exist_ok=True)
            summary["created"].append(f"level2/{subdir}/")

    # ------------------------------------------------------------------
    # 3. Update .hivemind.json to v2 schema
    # ------------------------------------------------------------------
    config_path = data_path / ".hivemind.json"
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}

        changed = False
        defaults = default_config()

        # Set version
        if data.get("version") != "2.0.0":
            data["version"] = "2.0.0"
            changed = True

        # Ensure profiles field exists
        if "profiles" not in data:
            data["profiles"] = defaults["profiles"]
            changed = True

        # Ensure projects field exists
        if "projects" not in data:
            data["projects"] = defaults["projects"]
            changed = True

        if changed:
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            summary["updated"].append(".hivemind.json")

    return summary


def print_migration_summary(summary: dict[str, list[str]]) -> None:
    """Print a human-readable migration summary to the terminal."""
    has_changes = any(summary.values())

    if not has_changes:
        click.echo("Migration: nothing to do (already v2 format).")
        return

    click.echo("Migration summary (v1 -> v2):")

    if summary["moved"]:
        click.echo("  Moved:")
        for item in summary["moved"]:
            click.echo(f"    {item}")

    if summary["created"]:
        click.echo("  Created:")
        for item in summary["created"]:
            click.echo(f"    {item}")

    if summary["updated"]:
        click.echo("  Updated:")
        for item in summary["updated"]:
            click.echo(f"    {item}")
