"""Implementation of `hv init` command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from hivemind.commands.migrate import (
    detect_v1,
    migrate_v1_to_v2,
    print_migration_summary,
)
from hivemind.core.config import HivemindConfig, default_config
from hivemind.installer.hooks import install_hooks
from hivemind.installer.profiles import install_profiles
from hivemind.installer.skills import install_skills


_IMPORTANT_FRONTMATTER = "---\nhits: {}\n---\n"

# Package-level directories for bundled assets.
_PKG_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _PKG_ROOT / "skills"
_HOOKS_DIR = _PKG_ROOT / "hooks"


def _ensure_dir(path: Path) -> bool:
    """Create directory if it doesn't exist. Return True if created."""
    if path.exists():
        return False
    path.mkdir(parents=True, exist_ok=True)
    return True


def _ensure_file(path: Path, content: str) -> bool:
    """Create file with content if it doesn't exist. Return True if created."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def init_data_dir(data_path: Path) -> list[str]:
    """Create the hivemind data directory structure.

    If the directory already exists (v1 upgrade), only creates missing
    folders/files, preserving existing data.

    Returns a list of created items for reporting.
    """
    created: list[str] = []

    # Top-level directories
    for dirname in ("projects", "tasks", "level1", "level2", "level3"):
        if _ensure_dir(data_path / dirname):
            created.append(f"  {dirname}/")

    # level2 subdirectories
    for subdir in ("frontend", "backend", "infra", "general"):
        if _ensure_dir(data_path / "level2" / subdir):
            created.append(f"  level2/{subdir}/")

    # level1/important.md
    if _ensure_file(
        data_path / "level1" / "important.md", _IMPORTANT_FRONTMATTER
    ):
        created.append("  level1/important.md")

    # index.json
    if _ensure_file(data_path / "index.json", "{}\n"):
        created.append("  index.json")

    # .hivemind.json
    config_path = data_path / ".hivemind.json"
    if not config_path.exists():
        cfg = HivemindConfig(config_path, default_config())
        cfg.save()
        created.append("  .hivemind.json")

    return created


def run_installers(
    config_path: Path,
    *,
    skills_source: Path | None = None,
    hooks_source: Path | None = None,
) -> dict[str, list[str] | bool]:
    """Run all Claude Code installers and return a summary.

    Parameters
    ----------
    config_path:
        Path to ``.hivemind.json`` in the data directory.
    skills_source:
        Override for the package skills directory.
    hooks_source:
        Override for the package hooks directory.

    Returns
    -------
    dict
        Keys: ``skills`` (list[str]), ``hooks`` (bool), ``profiles`` (bool),
        ``skills_skipped`` (bool).
    """
    summary: dict[str, list[str] | bool] = {}

    # --- Skills --------------------------------------------------------------
    src = skills_source if skills_source is not None else _SKILLS_DIR
    if src.is_dir():
        installed = install_skills(src)
        summary["skills"] = installed
        summary["skills_skipped"] = False
    else:
        summary["skills"] = []
        summary["skills_skipped"] = True

    # --- Hooks ---------------------------------------------------------------
    hsrc = hooks_source if hooks_source is not None else _HOOKS_DIR
    summary["hooks"] = install_hooks(hsrc)

    # --- Profiles ------------------------------------------------------------
    summary["profiles"] = install_profiles(config_path)

    return summary


def _print_installer_summary(summary: dict[str, list[str] | bool]) -> None:
    """Print a human-readable summary of what the installers did."""
    click.echo("")
    click.echo("Claude Code integration:")

    # Skills
    skills = summary.get("skills", [])
    if summary.get("skills_skipped"):
        click.echo("  Skills: skipped (source directory not found)")
    elif isinstance(skills, list) and skills:
        click.echo(f"  Skills: {len(skills)} installed")
        for s in skills:
            click.echo(f"    - {s}")
    else:
        click.echo("  Skills: none to install")

    # Hooks
    if summary.get("hooks"):
        click.echo("  Hooks: installed")
    else:
        click.echo("  Hooks: already up to date")

    # Profiles
    if summary.get("profiles"):
        click.echo("  Profiles: default profiles added")
    else:
        click.echo("  Profiles: already configured")


def _init_git(data_path: Path, config_path: Path) -> bool:
    """Run ``git init`` in *data_path* and enable git in config.

    Returns True if git was initialized successfully.
    """
    try:
        subprocess.run(
            ["git", "init"],
            cwd=str(data_path),
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo("Warning: git init failed. Is git installed?")
        return False

    cfg = HivemindConfig.load(config_path)
    cfg.set("git_enabled", True)
    cfg.set("auto_commit", True)
    cfg.save()
    return True


@click.command("init")
@click.option(
    "--path",
    default=None,
    type=click.Path(),
    help="Data directory path (default: ~/agent-hivemind-data).",
)
@click.option(
    "--git",
    "use_git",
    is_flag=True,
    default=False,
    help="Initialize a git repo in the data directory and enable auto-commit.",
)
def init_cmd(path: str | None, *, use_git: bool) -> None:
    """Initialize a new hivemind workspace."""
    if path is not None:
        data_path = Path(path).expanduser().resolve()
    else:
        data_path = Path("~/agent-hivemind-data").expanduser().resolve()

    click.echo(f"Initializing hivemind data at: {data_path}")

    # --- v1 migration check ---------------------------------------------------
    if detect_v1(data_path):
        click.echo("Detected v1 data directory. Running migration...")
        migration_summary = migrate_v1_to_v2(data_path)
        print_migration_summary(migration_summary)
        click.echo("")

    created = init_data_dir(data_path)

    if created:
        click.echo("Created:")
        for item in created:
            click.echo(item)
    else:
        click.echo("All directories and files already exist. Nothing to do.")

    # --- Run installers ------------------------------------------------------
    config_path = data_path / ".hivemind.json"
    summary = run_installers(config_path)
    _print_installer_summary(summary)

    # --- Git -----------------------------------------------------------------
    if use_git:
        click.echo("")
        if _init_git(data_path, config_path):
            click.echo("Git repository initialized in data directory.")
        else:
            click.echo("Git initialization failed.")

    click.echo("\nDone.")
