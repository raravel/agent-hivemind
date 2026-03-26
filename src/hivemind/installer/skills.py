"""Skill installer — copies skill directories into ~/.claude/skills/."""

from __future__ import annotations

import shutil
from pathlib import Path


def install_skills(
    source_dir: Path,
    target_dir: Path | None = None,
) -> list[str]:
    """Copy skill directories from *source_dir* to *target_dir*.

    Each subdirectory of *source_dir* that contains a ``SKILL.md`` is
    treated as a skill and copied as a top-level directory under
    *target_dir*.  Claude Code discovers skills at
    ``~/.claude/skills/<skill-name>/SKILL.md`` where the directory name
    becomes the ``/<skill-name>`` command.

    Parameters
    ----------
    source_dir:
        Directory containing skill subdirectories (e.g.
        ``src/hivemind/skills/`` with children ``hv-init/``, ``hv-task/``).
    target_dir:
        Destination directory.  Defaults to ``~/.claude/skills/``.

    Returns
    -------
    list[str]
        Skill directory names that were installed.
    """
    if target_dir is None:
        target_dir = Path("~/.claude/skills").expanduser()

    target_dir.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    for skill_dir in sorted(source_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        dest_dir = target_dir / skill_dir.name
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(skill_dir, dest_dir)
        installed.append(skill_dir.name)

    return installed
