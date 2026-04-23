"""Codex plugin installer for Agent Hivemind."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from hivemind.installer.plugin_bundle import (
    cleanup_staged_plugin_bundle,
    resolve_manifest_skills_dir,
    stage_runtime_plugin_bundle,
)


def install_codex_plugin(
    source_dir: Path,
    target_dir: Path | None = None,
    marketplace_path: Path | None = None,
) -> list[str]:
    """Install the hv plugin for Codex and expose it via a local marketplace."""
    if target_dir is None:
        target_dir = Path("~/.codex/plugins/hv").expanduser()
    if marketplace_path is None:
        marketplace_path = Path("~/.agents/plugins/marketplace.json").expanduser()

    bundle_dir = stage_runtime_plugin_bundle(source_dir, "codex")
    try:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle_dir, target_dir)

        _upsert_marketplace_entry(marketplace_path)
        return _collect_components(target_dir)
    finally:
        cleanup_staged_plugin_bundle(bundle_dir)


def _collect_components(plugin_dir: Path) -> list[str]:
    """Return installed component names for reporting."""
    installed: list[str] = []
    skills_dir = resolve_manifest_skills_dir(plugin_dir, ".codex-plugin/plugin.json")
    if skills_dir.exists():
        for skill in sorted(skills_dir.iterdir()):
            if skill.is_dir() and (skill / "SKILL.md").exists():
                installed.append(f"skill:{skill.name}")
    return installed


def _upsert_marketplace_entry(marketplace_path: Path) -> None:
    """Create or update the personal Codex marketplace entry for hv."""
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    root: dict[str, Any]
    if marketplace_path.exists():
        root = json.loads(marketplace_path.read_text(encoding="utf-8"))
    else:
        root = {
            "name": "agent-hivemind-local",
            "interface": {"displayName": "Agent Hivemind Local"},
            "plugins": [],
        }

    plugins = root.get("plugins")
    if not isinstance(plugins, list):
        plugins = []
        root["plugins"] = plugins

    entry = {
        "name": "hv",
        "source": {
            "source": "local",
            "path": "./.codex/plugins/hv",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }

    replaced = False
    for index, plugin in enumerate(plugins):
        if isinstance(plugin, dict) and plugin.get("name") == "hv":
            plugins[index] = entry
            replaced = True
            break
    if not replaced:
        plugins.append(entry)

    marketplace_path.write_text(
        json.dumps(root, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
