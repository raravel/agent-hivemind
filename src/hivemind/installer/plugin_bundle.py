"""Helpers to stage runtime-specific plugin bundles."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path


def stage_runtime_plugin_bundle(source_dir: Path, runtime: str) -> Path:
    """Return a temporary plugin bundle containing only one runtime skill tree."""
    temp_dir = Path(tempfile.mkdtemp(prefix=f"hv-{runtime}-plugin-"))
    shutil.copytree(
        source_dir,
        temp_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )

    skills_root = temp_dir / "skills"
    runtime_skills_dir = skills_root / runtime
    if runtime_skills_dir.exists():
        for child in list(skills_root.iterdir()):
            if child.name != runtime:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
    return temp_dir


def cleanup_staged_plugin_bundle(bundle_dir: Path) -> None:
    """Remove a temporary plugin bundle directory."""
    shutil.rmtree(bundle_dir, ignore_errors=True)


def resolve_manifest_skills_dir(plugin_dir: Path, manifest_relpath: str) -> Path:
    """Resolve the skills directory declared in a plugin manifest."""
    manifest = plugin_dir / manifest_relpath
    data = json.loads(manifest.read_text(encoding="utf-8"))
    skills_rel = data.get("skills") or "./skills/"
    return (manifest.parent.parent / str(skills_rel)).resolve()
