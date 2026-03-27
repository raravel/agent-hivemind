"""Implementation of `hv push` command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from hivemind.core.config import HivemindConfig


def _resolve_data_path() -> Path:
    """Resolve the data path from config or default."""
    candidates = [
        Path.cwd() / ".hivemind.json",
        Path("~/.hivemind.json").expanduser(),
        Path("~/agent-hivemind-data/.hivemind.json").expanduser(),
    ]
    for p in candidates:
        if p.exists():
            cfg = HivemindConfig.load(p)
            return cfg.data_path
    return Path("~/agent-hivemind-data").expanduser()


def _run_git(data_path: Path, *args: str) -> tuple[int, str]:
    """Run a git command in the data directory."""
    try:
        result = subprocess.run(
            ["git", "-C", str(data_path), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output
    except FileNotFoundError:
        return 1, "git not found"
    except subprocess.TimeoutExpired:
        return 1, "timeout"


def _has_git_repo(data_path: Path) -> bool:
    """Check if data directory is a git repo."""
    code, _ = _run_git(data_path, "rev-parse", "--git-dir")
    return code == 0


def _has_remote(data_path: Path) -> bool:
    """Check if git remote 'origin' exists."""
    code, output = _run_git(data_path, "remote", "get-url", "origin")
    return code == 0 and bool(output.strip())


@click.command()
def push_cmd() -> None:
    """Push hivemind data to remote repository."""
    data_path = _resolve_data_path()

    if not data_path.exists():
        raise click.ClickException(
            f"Data directory not found: {data_path}\nRun `hv init` first."
        )

    # Ensure git repo exists
    if not _has_git_repo(data_path):
        click.echo(f"Initializing git repo in {data_path}...")
        code, output = _run_git(data_path, "init")
        if code != 0:
            raise click.ClickException(f"git init failed: {output}")

    # Ensure remote exists
    if not _has_remote(data_path):
        click.echo("No git remote configured for the data directory.")
        remote_url = click.prompt(
            "Enter remote URL (e.g. git@github.com:user/hivemind-data.git)"
        )
        remote_url = remote_url.strip()
        if not remote_url:
            raise click.ClickException("Remote URL cannot be empty.")

        code, output = _run_git(data_path, "remote", "add", "origin", remote_url)
        if code != 0:
            raise click.ClickException(f"Failed to add remote: {output}")
        click.echo(f"Remote set: {remote_url}")

    # Stage all changes
    _run_git(data_path, "add", "-A")

    # Check if there's anything to commit
    code, status = _run_git(data_path, "status", "--porcelain")
    if code == 0 and not status.strip():
        click.echo("Nothing to commit.")
    else:
        code, output = _run_git(data_path, "commit", "-m", "hv push: sync data")
        if code != 0 and "nothing to commit" not in output:
            raise click.ClickException(f"Commit failed: {output}")
        click.echo("Changes committed.")

    # Push
    click.echo("Pushing to remote...")
    code, output = _run_git(data_path, "push", "-u", "origin", "main")
    if code != 0:
        # Try master branch if main doesn't exist
        code, output = _run_git(data_path, "push", "-u", "origin", "master")
        if code != 0:
            raise click.ClickException(f"Push failed: {output}")

    click.echo("Done.")
