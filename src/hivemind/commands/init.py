"""Implementation of `hv init` command."""

from __future__ import annotations

from pathlib import Path

import click

from hivemind.core.config import HivemindConfig, default_config


_IMPORTANT_FRONTMATTER = "---\nhits: {}\n---\n"


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


@click.command("init")
@click.option(
    "--path",
    default=None,
    type=click.Path(),
    help="Data directory path (default: ~/agent-hivemind-data).",
)
def init_cmd(path: str | None) -> None:
    """Initialize a new hivemind workspace."""
    if path is not None:
        data_path = Path(path).expanduser().resolve()
    else:
        data_path = Path("~/agent-hivemind-data").expanduser().resolve()

    click.echo(f"Initializing hivemind data at: {data_path}")

    created = init_data_dir(data_path)

    if created:
        click.echo("Created:")
        for item in created:
            click.echo(item)
    else:
        click.echo("All directories and files already exist. Nothing to do.")

    click.echo("Done.")
