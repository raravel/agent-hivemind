"""Claude plugin installer — copies the hv plugin and registers it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _run_claude_cmd(args: list[str]) -> tuple[bool, str]:
    """Run a ``claude`` CLI command. Return (success, output)."""
    try:
        result = subprocess.run(
            ["claude", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output
    except FileNotFoundError:
        return False, "claude CLI not found"
    except subprocess.TimeoutExpired:
        return False, "timeout"


def install_claude_plugin(
    source_dir: Path,
    target_dir: Path | None = None,
) -> list[str]:
    """Install the hv plugin and register it with Claude Code.

    1. Copies the plugin directory to ``~/.claude/plugins/hv/``.
    2. Registers the local marketplace via ``claude plugin marketplace add``.
    3. Installs the plugin via ``claude plugin install hv@hv-local``.

    Parameters
    ----------
    source_dir:
        The plugin root directory containing ``.claude-plugin/plugin.json``.
    target_dir:
        Destination directory.  Defaults to ``~/.claude/plugins/hv/``.

    Returns
    -------
    list[str]
        Names of components installed (skills, hooks).
    """
    if target_dir is None:
        target_dir = Path("~/.claude/plugins/hv").expanduser()

    # --- Copy plugin files ---------------------------------------------------
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)

    # --- Register marketplace + install plugin -------------------------------
    _register_plugin(target_dir)

    # --- Collect installed component names -----------------------------------
    installed: list[str] = []

    skills_dir = target_dir / "skills"
    if skills_dir.exists():
        for skill in sorted(skills_dir.iterdir()):
            if skill.is_dir() and (skill / "SKILL.md").exists():
                installed.append(f"/hv:{skill.name}")

    hooks_dir = target_dir / "hooks"
    if (hooks_dir / "hooks.json").exists():
        for hook_py in sorted(hooks_dir.glob("hv_*.py")):
            installed.append(f"hook:{hook_py.stem}")

    return installed


def _register_plugin(plugin_dir: Path) -> None:
    """Register the hv plugin with Claude Code via CLI.

    Idempotent — safe to call multiple times.
    """
    # Add local marketplace (skip if already added).
    ok, out = _run_claude_cmd([
        "plugin", "marketplace", "add", str(plugin_dir),
    ])
    if not ok and "already" not in out.lower():
        # Not fatal — may already be registered or claude not available.
        pass

    # Install/enable the plugin.
    ok, out = _run_claude_cmd([
        "plugin", "install", "hv@hv-local", "--scope", "user",
    ])
    if not ok and "already" not in out.lower():
        pass


# Backward-compatible aliases for existing callers.
install_plugin = install_claude_plugin
install_skills = install_claude_plugin
