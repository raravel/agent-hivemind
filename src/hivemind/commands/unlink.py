"""Implementation of `hv unlink` — reverse of `hv link`.

Removes every artifact `hv link` produced for one project:

- ``<linked>/hivemind/`` (docs, tasks, link.json, harness-scores.jsonl, _reports)
- The project entry in the global ``.hivemind.json``
- The managed ``<!-- hivemind:start --> ... <!-- hivemind:end -->`` block
  from ``CLAUDE.md`` and ``AGENTS.md`` (preserving any user content above
  or below the block)
- ``<project>/.codex/hooks.json`` (and the ``.codex`` dir if it becomes empty)
- ``<data>/level3/<project>/`` (cross-project graphs scoped to this project)
- Legacy ``<project>/.hivemind-link.json`` (v4)

Destructive — refuses to run without an interactive confirmation unless
``--force`` is passed. Auto-commits the result on both repos when
``auto_commit`` is enabled in the global config.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

from hivemind.core.config import HivemindConfig
from hivemind.core.git import auto_commit
from hivemind.core.instructions import strip_managed_block
from hivemind.core.paths import linked_path_for, resolve_link_file


def _find_config() -> tuple[HivemindConfig, Path]:
    try:
        cfg = HivemindConfig.find_for_command()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    return cfg, cfg.data_path


def _detect_project_from_cwd(cfg: HivemindConfig) -> str | None:
    """Return the registered project name whose linked_path is cwd, if any."""
    cwd = Path.cwd().resolve()
    projects = cfg.raw.get("projects", {})
    if not isinstance(projects, dict):
        return None
    for name, proj in projects.items():
        if not isinstance(proj, dict):
            continue
        linked = proj.get("linked_path")
        if not isinstance(linked, str) or not linked:
            continue
        try:
            if Path(linked).expanduser().resolve() == cwd:
                return name
        except Exception:
            continue
    return None


def _strip_block_in(file_path: Path) -> bool:
    """Strip the managed block from *file_path*. Returns True if changed.

    When the strip empties the file, the file is removed. Missing files are
    a no-op.
    """
    if not file_path.exists():
        return False
    before = file_path.read_text(encoding="utf-8")
    after = strip_managed_block(before)
    if after == before:
        return False
    if after.strip():
        file_path.write_text(after, encoding="utf-8")
    else:
        file_path.unlink()
    return True


def _confirm_or_abort(project: str) -> None:
    click.echo(
        f"This will permanently delete hivemind state for project '{project}'.\n"
        f"Type the project name to confirm: ",
        nl=False,
    )
    if sys.stdin.isatty():
        answer = input().strip()
    else:
        answer = sys.stdin.readline().strip()
    if answer != project:
        raise click.ClickException("Confirmation failed — aborted.")


def unlink_project(
    project: str | None = None,
    *,
    force: bool = False,
) -> dict[str, object]:
    """Run the unlink. Returns a summary dict.

    Auto-detects the project from cwd when ``project`` is None. Raises
    ``click.ClickException`` when nothing matches.
    """
    cfg, data_path = _find_config()

    if project is None:
        detected = _detect_project_from_cwd(cfg)
        if detected is None:
            raise click.ClickException(
                "No project linked to current directory. "
                "Pass --project/-p to specify."
            )
        project = detected

    try:
        linked = linked_path_for(cfg, project)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    if not force:
        _confirm_or_abort(project)

    summary: dict[str, object] = {
        "project": project,
        "linked_path": str(linked),
        "removed_hivemind_dir": False,
        "removed_legacy_link": False,
        "stripped_instruction_files": [],
        "removed_codex_hooks": False,
        "config_entry_removed": False,
        "removed_level3": False,
    }

    # 1. Wipe <linked>/hivemind/ entirely.
    hivemind_dir = linked / "hivemind"
    if hivemind_dir.exists():
        shutil.rmtree(hivemind_dir)
        summary["removed_hivemind_dir"] = True

    # 2. Legacy <linked>/.hivemind-link.json (only if a v4 install never migrated).
    legacy_link = resolve_link_file(linked)
    if legacy_link is not None and legacy_link.exists():
        legacy_link.unlink()
        summary["removed_legacy_link"] = True

    # 3. Strip managed blocks from CLAUDE.md / AGENTS.md.
    stripped: list[str] = []
    for name in ("CLAUDE.md", "AGENTS.md"):
        if _strip_block_in(linked / name):
            stripped.append(name)
    summary["stripped_instruction_files"] = stripped

    # 4. Drop .codex/hooks.json (and an empty .codex/).
    codex_dir = linked / ".codex"
    codex_hooks = codex_dir / "hooks.json"
    if codex_hooks.exists():
        codex_hooks.unlink()
        summary["removed_codex_hooks"] = True
    if codex_dir.exists():
        try:
            codex_dir.rmdir()  # only succeeds when empty
        except OSError:
            pass

    # 5. Unregister from global config.
    projects = cfg.raw.get("projects")
    if isinstance(projects, dict) and project in projects:
        projects.pop(project)
        cfg.save()
        summary["config_entry_removed"] = True

    # 6. Cross-project level3 graph dir scoped to this project.
    level3 = data_path / "level3" / project
    if level3.exists():
        shutil.rmtree(level3)
        summary["removed_level3"] = True

    # 7. Auto-commit both repos.
    auto_commit(linked, f"unlink: {project}")
    auto_commit(data_path, f"unlink: drop {project} from registry")

    return summary


def _print_summary(s: dict[str, object]) -> None:
    click.echo(f"Unlinked '{s['project']}' ({s['linked_path']}):")
    if s["removed_hivemind_dir"]:
        click.echo("  - removed hivemind/ directory")
    if s["removed_legacy_link"]:
        click.echo("  - removed legacy .hivemind-link.json")
    stripped = s.get("stripped_instruction_files") or []
    if isinstance(stripped, list) and stripped:
        click.echo(f"  - stripped managed block: {', '.join(stripped)}")
    if s["removed_codex_hooks"]:
        click.echo("  - removed .codex/hooks.json")
    if s["config_entry_removed"]:
        click.echo("  - removed project entry from global config")
    if s["removed_level3"]:
        click.echo("  - removed cross-project level3/ dir")


@click.command("unlink")
@click.option(
    "--project",
    "-p",
    default=None,
    help="Project name. Defaults to the project linked to the current directory.",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Skip the interactive confirmation.",
)
def unlink_cmd(project: str | None, force: bool) -> None:
    """Remove hivemind state for a linked project (reverse of `hv link`)."""
    summary = unlink_project(project, force=force)
    _print_summary(summary)
