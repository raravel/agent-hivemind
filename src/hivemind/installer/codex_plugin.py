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

_PRIMARY_CODEX_PLUGIN_DIR = Path("~/plugins/hv").expanduser()
_LEGACY_CODEX_PLUGIN_DIR = Path("~/.codex/plugins/hv").expanduser()
_PRIMARY_CODEX_MARKETPLACE_PATH = Path(
    "~/.agents/plugins/marketplace.json"
).expanduser()
_LEGACY_CODEX_MARKETPLACE_PATH = Path(
    "~/.codex/plugins/marketplace.json"
).expanduser()
_CODEX_SKILLS_DIR = Path("~/.codex/skills").expanduser()


def install_codex_plugin(
    source_dir: Path,
    target_dir: Path | None = None,
    marketplace_path: Path | None = None,
) -> list[str]:
    """Install the hv plugin for Codex and expose it via a local marketplace."""
    target_dirs = (
        [target_dir]
        if target_dir is not None
        else [_PRIMARY_CODEX_PLUGIN_DIR, _LEGACY_CODEX_PLUGIN_DIR]
    )
    marketplace_paths = (
        [marketplace_path]
        if marketplace_path is not None
        else [_PRIMARY_CODEX_MARKETPLACE_PATH, _LEGACY_CODEX_MARKETPLACE_PATH]
    )

    bundle_dir = stage_runtime_plugin_bundle(source_dir, "codex")
    try:
        for plugin_dir in target_dirs:
            if plugin_dir.exists():
                shutil.rmtree(plugin_dir)
            plugin_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundle_dir, plugin_dir)

        _install_codex_skills(bundle_dir / "skills" / "codex", _CODEX_SKILLS_DIR)
        _upsert_marketplace_entry(
            _PRIMARY_CODEX_MARKETPLACE_PATH
            if marketplace_path is None
            else marketplace_paths[0]
        )
        if marketplace_path is None:
            _upsert_marketplace_entry(
                _LEGACY_CODEX_MARKETPLACE_PATH,
                plugin_path="./.codex/plugins/hv",
            )
        return _collect_components(target_dirs[0])
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


def _install_codex_skills(skills_source_dir: Path, skills_root: Path) -> None:
    """Install Codex skills directly into ~/.codex/skills for CLI discovery."""
    if not skills_source_dir.exists():
        return
    skills_root.mkdir(parents=True, exist_ok=True)
    for skill_dir in sorted(skills_source_dir.iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        dest = skills_root / skill_dir.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_dir, dest)


def _upsert_marketplace_entry(
    marketplace_path: Path, *, plugin_path: str = "./plugins/hv"
) -> None:
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
            "path": plugin_path,
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
