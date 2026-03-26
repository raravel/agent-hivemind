"""Plugin installer — copies the hv plugin into ~/.claude/plugins/."""

from __future__ import annotations

import shutil
from pathlib import Path


def install_plugin(
    source_dir: Path,
    target_dir: Path | None = None,
) -> list[str]:
    """Install the hv plugin from *source_dir* to *target_dir*.

    Copies the entire plugin directory (including ``.claude-plugin/``,
    ``skills/``, ``hooks/``, ``agents/``) to the Claude Code plugins
    location.  Claude Code discovers plugins via the
    ``.claude-plugin/plugin.json`` manifest and registers skills as
    ``/hv:<skill-name>``.

    Parameters
    ----------
    source_dir:
        The plugin root directory containing ``.claude-plugin/plugin.json``
        (e.g. ``src/hivemind/plugin/``).
    target_dir:
        Destination directory.  Defaults to ``~/.claude/plugins/hv/``.

    Returns
    -------
    list[str]
        Names of components installed (skills, hooks, agents).
    """
    if target_dir is None:
        target_dir = Path("~/.claude/plugins/hv").expanduser()

    # Remove old installation if present.
    if target_dir.exists():
        shutil.rmtree(target_dir)

    shutil.copytree(source_dir, target_dir)

    # Collect installed component names.
    installed: list[str] = []

    skills_dir = target_dir / "skills"
    if skills_dir.exists():
        for skill in sorted(skills_dir.iterdir()):
            if skill.is_dir() and (skill / "SKILL.md").exists():
                installed.append(f"skill:hv:{skill.name}")

    hooks_json = target_dir / "hooks" / "hooks.json"
    if hooks_json.exists():
        installed.append("hooks:hv-pre-commit")

    agents_dir = target_dir / "agents"
    if agents_dir.exists():
        for agent in sorted(agents_dir.iterdir()):
            if agent.suffix == ".md":
                installed.append(f"agent:{agent.stem}")

    return installed


# Backward-compatible alias for existing callers.
install_skills = install_plugin
