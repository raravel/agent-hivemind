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
from hivemind.core.config import (
    HivemindConfig,
    default_config,
    expand_target_selection,
)
from hivemind.installer.codex_plugin import install_codex_plugin
from hivemind.installer.profiles import install_profiles
from hivemind.installer.skills import install_claude_plugin


_IMPORTANT_FRONTMATTER = "---\nhits: {}\n---\n"

# Package-level directories for bundled assets.
_PKG_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_DIR = _PKG_ROOT / "plugin"


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
    target: str = "claude",
    plugin_source: Path | None = None,
) -> dict[str, object]:
    """Run runtime installers and return a summary.

    Parameters
    ----------
    config_path:
        Path to ``.hivemind.json`` in the data directory.
    skills_source:
        Override for the plugin source directory.

    Returns
    -------
    dict
        Keys: ``targets`` (list[str]), runtime sections, and ``profiles`` (bool).
    """
    summary: dict[str, object] = {"targets": expand_target_selection(target)}

    src = plugin_source if plugin_source is not None else _PLUGIN_DIR
    for runtime in expand_target_selection(target):
        manifest_dir = src / f".{runtime}-plugin" / "plugin.json"
        installed: list[str] = []
        skipped = True
        if src.is_dir() and manifest_dir.exists():
            if runtime == "claude":
                installed = install_claude_plugin(src)
            elif runtime == "codex":
                installed = install_codex_plugin(src)
            skipped = False
        summary[runtime] = {
            "installed": installed,
            "skipped": skipped,
        }

    # --- Profiles ------------------------------------------------------------
    summary["profiles"] = install_profiles(config_path)

    return summary


def _print_runtime_section(
    label: str, runtime_summary: dict[str, object] | None
) -> None:
    """Print one runtime installer summary."""
    click.echo(f"{label} integration:")
    if runtime_summary is None:
        click.echo("  Plugin: not requested")
        return

    installed = runtime_summary.get("installed", [])
    skipped = runtime_summary.get("skipped")
    if skipped:
        click.echo("  Plugin: skipped (source manifest not found)")
        return
    if isinstance(installed, list) and installed:
        click.echo(f"  Components: {len(installed)} installed")
        for item in installed:
            click.echo(f"    - {item}")
    else:
        click.echo("  Components: none to install")


def _print_installer_summary(summary: dict[str, object]) -> None:
    """Print a human-readable summary of what the installers did."""
    click.echo("")
    _print_runtime_section(
        "Claude Code",
        summary.get("claude") if isinstance(summary.get("claude"), dict) else None,
    )
    click.echo("")
    _print_runtime_section(
        "Codex",
        summary.get("codex") if isinstance(summary.get("codex"), dict) else None,
    )

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
@click.option(
    "--target",
    type=click.Choice(["claude", "codex", "both"]),
    default="claude",
    show_default=True,
    help="Install integrations for Claude Code, Codex, or both.",
)
def init_cmd(path: str | None, *, use_git: bool, target: str) -> None:
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
    cfg = HivemindConfig.load(config_path)
    enabled_targets = expand_target_selection(target)
    cfg.set_runtime_targets(
        default_target=enabled_targets[0],
        enabled_targets=enabled_targets,
    )
    cfg.save()

    summary = run_installers(config_path, target=target)
    _print_installer_summary(summary)

    # --- Git -----------------------------------------------------------------
    if use_git:
        click.echo("")
        if _init_git(data_path, config_path):
            click.echo("Git repository initialized in data directory.")
        else:
            click.echo("Git initialization failed.")

    click.echo("\nDone.")
