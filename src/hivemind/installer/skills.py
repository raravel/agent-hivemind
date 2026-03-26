"""Skill installer — copies .md skill files into ~/.claude/skills/hv/."""

from __future__ import annotations

import shutil
from pathlib import Path


def install_skills(
    source_dir: Path,
    target_dir: Path | None = None,
) -> list[str]:
    """Copy all .md files from *source_dir* to *target_dir*.

    Recursively walks *source_dir*, preserving the relative directory structure.
    Existing files are overwritten (update semantics).

    Parameters
    ----------
    source_dir:
        Directory containing skill ``.md`` files.
    target_dir:
        Destination directory.  Defaults to ``~/.claude/skills/hv/``.

    Returns
    -------
    list[str]
        Filenames (relative to *source_dir*) that were installed.
    """
    if target_dir is None:
        target_dir = Path("~/.claude/skills/hv").expanduser()

    target_dir.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    for md_file in sorted(source_dir.rglob("*.md")):
        rel = md_file.relative_to(source_dir)
        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md_file, dest)
        installed.append(str(rel))

    return installed
