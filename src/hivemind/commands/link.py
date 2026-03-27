"""Implementation of `hv link` command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click

from hivemind.core.config import HivemindConfig
from hivemind.core.git import auto_commit


def _detect_name(name: str | None, project_dir: Path) -> str:
    """Detect project name: --name flag > git remote name > directory name."""
    if name:
        return name

    # Try git remote origin URL
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            # Extract repo name from URL: git@.../repo.git or https://.../repo.git
            repo = url.rstrip("/").rsplit("/", 1)[-1]
            if repo.endswith(".git"):
                repo = repo[:-4]
            if repo:
                return repo
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fall back to directory name
    return project_dir.name


def _generate_prefix(name: str) -> str:
    """Auto-generate prefix: first 2-3 uppercase chars of name.

    - 1-2 char names -> use all chars uppercased
    - 3+ char names -> first 2-3 consonant-heavy chars, uppercased
    """
    clean = name.replace("-", "").replace("_", "").replace(" ", "")
    if len(clean) <= 3:
        return clean.upper()
    return clean[:3].upper()


def _find_config() -> tuple[HivemindConfig, Path]:
    """Locate .hivemind.json and return (config, data_path)."""
    candidates = [
        Path.cwd() / ".hivemind.json",
        Path("~/.hivemind.json").expanduser(),
        Path("~/agent-hivemind-data/.hivemind.json").expanduser(),
    ]
    for p in candidates:
        if p.exists():
            cfg = HivemindConfig.load(p)
            return cfg, cfg.data_path
    raise click.ClickException(
        "No .hivemind.json found. Run `hv init` first."
    )


def link_project(
    project_dir: Path,
    name: str | None = None,
    config_finder: object = None,
) -> str:
    """Link a project directory to the hivemind data repo.

    Returns the resolved project name.
    """
    link_file = project_dir / ".hivemind-link.json"

    # Already linked?
    if link_file.exists():
        existing = json.loads(link_file.read_text(encoding="utf-8"))
        proj_name: str = existing.get("project", "unknown")
        click.echo(f"Already linked as '{proj_name}'. Skipping.")
        return proj_name

    # Detect name
    resolved_name = _detect_name(name, project_dir)

    # Load hivemind config
    cfg, data_path = _find_config()

    # 1. Create .hivemind-link.json in project root
    link_data = {
        "project": resolved_name,
        "data_path": str(data_path),
    }
    link_file.write_text(
        json.dumps(link_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    click.echo(f"Created {link_file}")

    # 2-5. Create directories in data repo
    dirs_to_create = [
        data_path / "projects" / resolved_name,
        data_path / "tasks" / resolved_name,
        data_path / "tasks" / resolved_name / "_reports",
        data_path / "level3" / resolved_name,
    ]
    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)
        click.echo(f"Created {d}")

    # 6-7. Register in .hivemind.json
    prefix = _generate_prefix(resolved_name)
    cfg.set_project(resolved_name, prefix, str(project_dir))
    cfg.save()
    click.echo(
        f"Registered project '{resolved_name}' (prefix={prefix}) in config."
    )

    # 8. Append hivemind project info to CLAUDE.md (create if needed)
    claude_md = project_dir / "CLAUDE.md"
    existing_content = ""
    if claude_md.exists():
        existing_content = claude_md.read_text(encoding="utf-8")

    hivemind_marker = "# Hivemind Project"
    if hivemind_marker not in existing_content:
        import_block = (
            f"\n\n{hivemind_marker}\n"
            f"- project: {resolved_name}\n"
            f"- data_path: {data_path}\n"
        )
        claude_md.write_text(
            existing_content + import_block, encoding="utf-8"
        )
        click.echo("Appended hivemind project info to CLAUDE.md.")

    auto_commit(data_path, f"link: {resolved_name}")

    return resolved_name


@click.command("link")
@click.option("--name", default=None, help="Project name (auto-detected if omitted).")
def link_cmd(name: str | None) -> None:
    """Link current directory to the hivemind data repo."""
    project_dir = Path.cwd()
    resolved = link_project(project_dir, name)
    click.echo(f"Linked project: {resolved}")
