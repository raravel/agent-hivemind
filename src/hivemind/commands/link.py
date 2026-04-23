"""Implementation of `hv link` command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click

from hivemind.core.config import HivemindConfig, data_path_for_storage, expand_target_selection
from hivemind.core.git import auto_commit
from hivemind.core.instructions import write_codex_hooks_file, write_instruction_files

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
    target: str = "claude",
    config_finder: object = None,
) -> str:
    """Link a project directory to the hivemind data repo.

    Returns the resolved project name.
    """
    link_file = project_dir / ".hivemind-link.json"

    # Detect name early so an existing link can still be refreshed.
    resolved_name = _detect_name(name, project_dir)

    existing_targets: list[str] = []

    # Already linked?
    if link_file.exists():
        existing = json.loads(link_file.read_text(encoding="utf-8"))
        proj_name = existing.get("project")
        if isinstance(proj_name, str) and proj_name:
            resolved_name = proj_name
        raw_targets = existing.get("targets")
        if isinstance(raw_targets, list):
            existing_targets = [
                item
                for item in raw_targets
                if isinstance(item, str) and item in {"claude", "codex"}
            ]
        click.echo(f"Refreshing existing link for '{resolved_name}'.")

    # Load hivemind config
    cfg, data_path = _find_config()
    requested_targets = expand_target_selection(target)
    if existing_targets:
        merged_targets = sorted(set(existing_targets).union(requested_targets))
    else:
        merged_targets = requested_targets

    # 1. Create .hivemind-link.json in project root
    link_data = {
        "project": resolved_name,
        "data_path": data_path_for_storage(data_path),
        "targets": merged_targets,
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

    changed = write_instruction_files(
        project_dir,
        project=resolved_name,
        data_path=data_path_for_storage(data_path),
        targets=merged_targets,
    )
    for file_name in changed:
        click.echo(f"Updated {file_name}.")
    if "codex" in merged_targets and write_codex_hooks_file(project_dir):
        click.echo("Updated .codex/hooks.json.")

    auto_commit(data_path, f"link: {resolved_name}")

    return resolved_name


@click.command("link")
@click.option("--name", default=None, help="Project name (auto-detected if omitted).")
@click.option(
    "--target",
    type=click.Choice(["claude", "codex", "both"]),
    default="claude",
    show_default=True,
    help="Configure project instructions for Claude Code, Codex, or both.",
)
def link_cmd(name: str | None, target: str) -> None:
    """Link current directory to the hivemind data repo."""
    project_dir = Path.cwd()
    resolved = link_project(project_dir, name, target=target)
    click.echo(f"Linked project: {resolved}")
