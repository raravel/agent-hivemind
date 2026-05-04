"""Idempotent v3 → v4 schema migration.

The v4 schema removes:
  - top-level ``data_path`` field in ``.hivemind.json`` (derived from the
    config file's parent directory),
  - ``data_path`` and ``targets`` fields in each project's
    ``.hivemind-link.json`` (data_path is derivable; targets live in
    ``runtime.enabled_targets``),
  - ``prefix`` from each ``.hivemind.json:projects[<name>]`` entry
    (moved into the committed ``.hivemind-link.json`` so every machine
    agrees),
  - ``counter`` from each ``.hivemind.json:projects[<name>]`` entry
    (moved into ``<data_path>/tasks/<name>/_counter.json``).

This module exposes :func:`migrate_v3_to_v4` which the CLI command
``hv migrate --to v4`` invokes explicitly and which
:meth:`HivemindConfig.load_global` invokes implicitly on first read after
a v4 upgrade.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from hivemind.core.config import normalize_data_path

SCHEMA_V4 = "4.0.0"


def migrate_v3_to_v4(config_path: Path) -> bool:
    """Migrate ``config_path`` (and reachable link files / counter files) to v4.

    Idempotent — running on an already-migrated workspace is a no-op.
    Returns ``True`` iff any on-disk change was made.
    """
    if not config_path.exists():
        return False

    try:
        data: dict[str, Any] = json.loads(
            config_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(data, dict):
        return False

    if data.get("version") == SCHEMA_V4:
        return False

    changed = False

    legacy_data_path_raw = data.get("data_path")
    if isinstance(legacy_data_path_raw, str) and legacy_data_path_raw:
        data_path = normalize_data_path(legacy_data_path_raw)
    else:
        data_path = config_path.parent.resolve()

    if data.pop("data_path", None) is not None:
        changed = True

    projects = data.get("projects")
    if isinstance(projects, dict):
        for name, proj in projects.items():
            if not isinstance(proj, dict):
                continue
            legacy_prefix = proj.get("prefix")
            legacy_counter = proj.get("counter")
            linked_path_raw = proj.get("linked_path")

            if isinstance(linked_path_raw, str) and linked_path_raw:
                link_file = (
                    Path(linked_path_raw).expanduser() / ".hivemind-link.json"
                )
                fallback_prefix = (
                    legacy_prefix
                    if isinstance(legacy_prefix, str) and legacy_prefix
                    else None
                )
                if _migrate_link_file(link_file, name, fallback_prefix):
                    changed = True

            if isinstance(legacy_counter, int) and legacy_counter > 0:
                counter_file = data_path / "tasks" / name / "_counter.json"
                if _seed_counter_file(counter_file, legacy_counter):
                    changed = True

            if "prefix" in proj:
                proj.pop("prefix")
                changed = True
            if "counter" in proj:
                proj.pop("counter")
                changed = True

    if data.get("version") != SCHEMA_V4:
        data["version"] = SCHEMA_V4
        changed = True

    if changed:
        config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(
            f"hivemind: migrated {config_path} to schema {SCHEMA_V4}.",
            file=sys.stderr,
        )

    return changed


def _migrate_link_file(
    link_file: Path,
    project: str,
    fallback_prefix: str | None,
) -> bool:
    """Strip legacy fields and seed prefix in ``.hivemind-link.json``.

    Idempotent. Returns True iff the file was rewritten.
    """
    if not link_file.exists():
        return False
    try:
        data = json.loads(link_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    new_data: dict[str, Any] = {}
    name_raw = data.get("project")
    new_data["project"] = (
        name_raw if isinstance(name_raw, str) and name_raw else project
    )

    existing_prefix = data.get("prefix")
    if isinstance(existing_prefix, str) and existing_prefix:
        new_data["prefix"] = existing_prefix
    elif fallback_prefix:
        new_data["prefix"] = fallback_prefix

    if new_data == data:
        return False
    link_file.write_text(
        json.dumps(new_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def _seed_counter_file(counter_file: Path, value: int) -> bool:
    """Seed a per-project counter file from the legacy global counter.

    Never downgrades an existing counter file. Returns True iff written.
    """
    counter_file.parent.mkdir(parents=True, exist_ok=True)
    current = 0
    if counter_file.exists():
        try:
            payload = json.loads(counter_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                raw = payload.get("value")
                if type(raw) is int and raw >= 0:
                    current = raw
        except (OSError, json.JSONDecodeError):
            pass
    if current >= value:
        return False
    counter_file.write_text(
        json.dumps({"value": value}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True
