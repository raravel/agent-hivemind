"""Migration logic for v1 -> v2 and v2 -> v3 data directory upgrades."""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import questionary

from hivemind.commands.task import _rebuild_task_index
from hivemind.core.config import (
    SUPPORTED_TARGETS,
    data_path_for_storage,
    default_config,
    normalize_data_path,
)
from hivemind.core.instructions import (
    normalize_targets,
    write_codex_hooks_file,
    write_instruction_files,
)
from hivemind.core.parser import parse_task, update_frontmatter


def detect_v1(data_path: Path) -> bool:
    """Check if *data_path* looks like a v1 hivemind data directory.

    A directory is considered v1 when:
    - ``.hivemind.json`` exists but has no ``version`` field, **or**
      the version starts with ``"1."``.
    - ``important.md`` exists at the data-root level (not inside ``level1/``).
    """
    config_path = data_path / ".hivemind.json"
    if not config_path.exists():
        return False

    try:
        with config_path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    version = data.get("version")
    if version is None:
        # No version field at all -> v1
        return True
    if isinstance(version, str) and version.startswith("1."):
        return True

    # Also check for root-level important.md without level1 copy
    root_important = data_path / "important.md"
    level1_important = data_path / "level1" / "important.md"
    if root_important.exists() and not level1_important.exists():
        return True

    return False


def migrate_v1_to_v2(data_path: Path) -> dict[str, list[str]]:
    """Migrate a v1 data directory to v2 format in-place.

    This function is designed to be **idempotent** -- running it multiple
    times on the same directory will not duplicate work or lose data.

    Returns a summary dict with keys ``moved``, ``created``, ``updated``.
    """
    summary: dict[str, list[str]] = {
        "moved": [],
        "created": [],
        "updated": [],
    }

    # ------------------------------------------------------------------
    # 1. Move important.md -> level1/important.md (copy, keep original)
    # ------------------------------------------------------------------
    root_important = data_path / "important.md"
    level1_dir = data_path / "level1"
    level1_important = level1_dir / "important.md"

    if root_important.exists() and not level1_important.exists():
        level1_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(root_important), str(level1_important))
        summary["moved"].append("important.md -> level1/important.md")

    # ------------------------------------------------------------------
    # 2. Create missing v2 directories
    # ------------------------------------------------------------------
    for dirname in ("projects", "tasks", "level1", "level2", "level3"):
        dir_path = data_path / dirname
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            summary["created"].append(f"{dirname}/")

    # level2 subdirectories
    for subdir in ("frontend", "backend", "infra", "general"):
        sub_path = data_path / "level2" / subdir
        if not sub_path.exists():
            sub_path.mkdir(parents=True, exist_ok=True)
            summary["created"].append(f"level2/{subdir}/")

    # ------------------------------------------------------------------
    # 3. Update .hivemind.json to v2 schema
    # ------------------------------------------------------------------
    config_path = data_path / ".hivemind.json"
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}

        changed = False
        defaults = default_config()

        # Set version
        if data.get("version") != "2.0.0":
            data["version"] = "2.0.0"
            changed = True

        # Ensure profiles field exists
        if "profiles" not in data:
            data["profiles"] = defaults["profiles"]
            changed = True

        # Ensure projects field exists
        if "projects" not in data:
            data["projects"] = defaults["projects"]
            changed = True

        if changed:
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            summary["updated"].append(".hivemind.json")

    return summary


def print_migration_summary(summary: dict[str, list[str]]) -> None:
    """Print a human-readable migration summary to the terminal."""
    has_changes = any(summary.values())

    if not has_changes:
        click.echo("Migration: nothing to do (already v2 format).")
        return

    click.echo("Migration summary (v1 -> v2):")

    if summary["moved"]:
        click.echo("  Moved:")
        for item in summary["moved"]:
            click.echo(f"    {item}")

    if summary["created"]:
        click.echo("  Created:")
        for item in summary["created"]:
            click.echo(f"    {item}")

    if summary["updated"]:
        click.echo("  Updated:")
        for item in summary["updated"]:
            click.echo(f"    {item}")


# ---------------------------------------------------------------------------
# v2 -> v3 migration
# ---------------------------------------------------------------------------


def _backup_tree(data_path: Path) -> Path | None:
    """Create a timestamped backup of the data directory.

    Copies into ``{data_path}/.backups/v2_to_v3_{timestamp}/``.
    Skips the backup directory itself to avoid recursion.
    """
    if not data_path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = data_path / ".backups" / f"v2_to_v3_{stamp}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src=str(data_path),
        dst=str(dest),
        ignore=shutil.ignore_patterns(".backups", ".git"),
        dirs_exist_ok=False,
    )
    return dest


def _fix_link_json(project_dir: Path, data_path: Path) -> bool:
    """Normalize path format in .hivemind-link.json. Return True if changed."""
    link_file = project_dir / ".hivemind-link.json"
    if not link_file.exists():
        return False
    try:
        link = json.loads(link_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    current = str(link.get("data_path", ""))
    desired = data_path_for_storage(data_path)
    changed = False
    if current != desired:
        link["data_path"] = desired
        changed = True

    raw_targets = link.get("targets")
    desired_targets = ["claude"]
    if isinstance(raw_targets, list):
        values = normalize_targets(raw_targets)
        if values:
            desired_targets = values
    if link.get("targets") != desired_targets:
        link["targets"] = desired_targets
        changed = True

    if not changed:
        return False
    link_file.write_text(
        json.dumps(link, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def _strip_claude_md_legacy(claude_md: Path) -> list[str]:
    """Remove legacy lines from CLAUDE.md. Return list of removed lines."""
    if not claude_md.exists():
        return []
    text = claude_md.read_text(encoding="utf-8")
    removed: list[str] = []
    new_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("obsidian-import"):
            removed.append(stripped)
            continue
        new_lines.append(line)
    if removed:
        claude_md.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    return removed


def _ensure_claude_md_imports(
    claude_md: Path, project: str, data_path_str: str
) -> bool:
    """Ensure CLAUDE.md contains @import lines to architecture.md / rules.md.

    Adds them right after the Hivemind Project block if missing. Returns
    True if the file was changed.
    """
    if not claude_md.exists():
        return False
    text = claude_md.read_text(encoding="utf-8")
    arch_line = f"@{data_path_str}/projects/{project}/architecture.md"
    rules_line = f"@{data_path_str}/projects/{project}/rules.md"
    added: list[str] = []
    if arch_line not in text:
        added.append(arch_line)
    if rules_line not in text:
        added.append(rules_line)
    if not added:
        return False
    if not text.endswith("\n"):
        text += "\n"
    text += "\n" + "\n".join(added) + "\n"
    claude_md.write_text(text, encoding="utf-8")
    return True


def _rename_build_verify(data_path: Path) -> list[str]:
    """Rename projects/{*}/build-verify.md -> verify.md. Return renamed paths."""
    renamed: list[str] = []
    projects_dir = data_path / "projects"
    if not projects_dir.exists():
        return renamed
    for proj_dir in projects_dir.iterdir():
        if not proj_dir.is_dir():
            continue
        old = proj_dir / "build-verify.md"
        new = proj_dir / "verify.md"
        if old.exists() and not new.exists():
            old.rename(new)
            renamed.append(f"projects/{proj_dir.name}/verify.md")
    return renamed


def _archive_per_prompt_l3(data_path: Path) -> int:
    """Move v2-era L3 logs under level3/_archive_v2/. Return count."""
    level3 = data_path / "level3"
    if not level3.exists():
        return 0
    archive = level3 / "_archive_v2"
    moved = 0
    for project_dir in level3.iterdir():
        if not project_dir.is_dir() or project_dir.name == "_archive_v2":
            continue
        for md in project_dir.glob("*.md"):
            archive_project = archive / project_dir.name
            archive_project.mkdir(parents=True, exist_ok=True)
            md.rename(archive_project / md.name)
            moved += 1
    return moved


def _update_config_v3(config_path: Path) -> list[str]:
    """Upgrade .hivemind.json to v3: model IDs, pricing, parallel section.

    Returns a list of human-readable change strings.
    """
    if not config_path.exists():
        return []
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    changes: list[str] = []
    defaults = default_config()

    if data.get("version") != "3.0.0":
        data["version"] = "3.0.0"
        changes.append("version -> 3.0.0")

    # Reseed profiles with concrete model IDs. Preserve user overrides keyed by
    # non-standard names; only rewrite the canonical three if they still use
    # short aliases ('opus'/'sonnet'/'haiku').
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        data["profiles"] = profiles
    for pname, pdata in defaults["profiles"].items():
        existing = profiles.get(pname)
        if not isinstance(existing, dict):
            profiles[pname] = pdata
            changes.append(f"profiles.{pname} seeded")
            continue
        for role, model_id in pdata.items():
            cur = existing.get(role)
            if not isinstance(cur, str) or cur in {"opus", "sonnet", "haiku"}:
                existing[role] = model_id
                changes.append(f"profiles.{pname}.{role} -> {model_id}")

    if "pricing" not in data or not isinstance(data["pricing"], dict):
        data["pricing"] = copy.deepcopy(defaults["pricing"])
        changes.append("pricing seeded")
    if "parallel" not in data or not isinstance(data["parallel"], dict):
        data["parallel"] = {"max_concurrency": 2}
        changes.append("parallel.max_concurrency = 2")
    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        data["runtime"] = copy.deepcopy(defaults["runtime"])
        changes.append("runtime seeded")
    else:
        if runtime.get("default_target") not in SUPPORTED_TARGETS:
            runtime["default_target"] = "claude"
            changes.append("runtime.default_target = claude")
        enabled = runtime.get("enabled_targets")
        if not isinstance(enabled, list) or not enabled:
            runtime["enabled_targets"] = ["claude"]
            changes.append("runtime.enabled_targets = ['claude']")
    runtime_models = data.get("runtime_models")
    if not isinstance(runtime_models, dict):
        data["runtime_models"] = copy.deepcopy(defaults["runtime_models"])
        changes.append("runtime_models seeded")
    else:
        if not isinstance(runtime_models.get("claude"), dict):
            runtime_models["claude"] = copy.deepcopy(
                defaults["runtime_models"]["claude"]
            )
            changes.append("runtime_models.claude seeded")
        if not isinstance(runtime_models.get("codex"), dict):
            runtime_models["codex"] = copy.deepcopy(
                defaults["runtime_models"]["codex"]
            )
            changes.append("runtime_models.codex seeded")

    raw_path = data.get("data_path")
    if isinstance(raw_path, str):
        posix = data_path_for_storage(normalize_data_path(raw_path))
        if posix != raw_path:
            data["data_path"] = posix
            changes.append(f"data_path normalized -> {posix}")

    if changes:
        with config_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    return changes


def _remove_node_hooks_from_settings(settings_path: Path) -> int:
    """Remove legacy JS hook entries from ~/.claude/settings.json.

    Returns the number of entries removed.
    """
    if not settings_path.exists():
        return 0
    try:
        with settings_path.open("r", encoding="utf-8") as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0

    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0

    node_pattern = re.compile(r"\bhv-[a-z-]+\.js\b")
    removed = 0
    for event_name, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept: list[Any] = []
        for entry in entries:
            entry_str = json.dumps(entry, ensure_ascii=False)
            if node_pattern.search(entry_str):
                removed += 1
                continue
            kept.append(entry)
        hooks[event_name] = kept

    if removed:
        with settings_path.open("w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return removed


def _remove_installed_node_hook_files() -> list[str]:
    """Delete hv-*.js files from ~/.claude/hooks/. Return names removed."""
    hooks_dir = Path("~/.claude/hooks").expanduser()
    if not hooks_dir.exists():
        return []
    removed: list[str] = []
    for js in hooks_dir.glob("hv-*.js"):
        try:
            js.unlink()
            removed.append(js.name)
        except OSError:
            pass
    return removed


def migrate_v2_to_v3(
    data_path: Path,
    *,
    project_dirs: list[Path] | None = None,
    backup: bool = True,
    claude_settings: Path | None = None,
) -> dict[str, Any]:
    """Upgrade a v2 hivemind installation to v3.

    Idempotent: running twice leaves the tree unchanged on the second pass.
    Returns a structured summary of changes.
    """
    summary: dict[str, Any] = {
        "backup": None,
        "config": [],
        "link_files_normalized": [],
        "claude_md_cleaned": [],
        "claude_md_imports_added": [],
        "instruction_files_updated": [],
        "codex_hooks_updated": [],
        "verify_md_renamed": [],
        "l3_archived": 0,
        "node_hook_entries_removed": 0,
        "node_hook_files_removed": [],
    }

    if backup and data_path.exists():
        try:
            summary["backup"] = str(_backup_tree(data_path))
        except (OSError, shutil.Error) as e:
            summary["backup"] = f"FAILED: {e}"

    summary["config"] = _update_config_v3(data_path / ".hivemind.json")
    summary["verify_md_renamed"] = _rename_build_verify(data_path)
    summary["l3_archived"] = _archive_per_prompt_l3(data_path)

    if claude_settings is None:
        claude_settings = Path("~/.claude/settings.json").expanduser()
    summary["node_hook_entries_removed"] = _remove_node_hooks_from_settings(
        claude_settings
    )
    summary["node_hook_files_removed"] = _remove_installed_node_hook_files()

    if project_dirs:
        posix_data_path = data_path_for_storage(data_path)
        for proj_dir in project_dirs:
            if _fix_link_json(proj_dir, data_path):
                summary["link_files_normalized"].append(str(proj_dir))

            claude_md = proj_dir / "CLAUDE.md"
            removed = _strip_claude_md_legacy(claude_md)
            if removed:
                summary["claude_md_cleaned"].append(
                    f"{proj_dir}: removed {len(removed)} legacy line(s)"
                )

            link_file = proj_dir / ".hivemind-link.json"
            project = None
            targets = ["claude"]
            if link_file.exists():
                try:
                    link = json.loads(link_file.read_text(encoding="utf-8"))
                    project = link.get("project")
                    raw_targets = link.get("targets")
                    if isinstance(raw_targets, list):
                        values = normalize_targets(raw_targets)
                        if values:
                            targets = values
                except (OSError, json.JSONDecodeError):
                    project = None
            if project and _ensure_claude_md_imports(
                claude_md, str(project), posix_data_path
            ):
                summary["claude_md_imports_added"].append(str(proj_dir))
            if project:
                changed = write_instruction_files(
                    proj_dir,
                    project=str(project),
                    targets=targets,
                )
                if changed:
                    summary["instruction_files_updated"].append(
                        f"{proj_dir}: {', '.join(changed)}"
                    )
                if "codex" in targets and write_codex_hooks_file(proj_dir):
                    summary["codex_hooks_updated"].append(str(proj_dir))

    return summary


def print_v3_migration_summary(summary: dict[str, Any]) -> None:
    """Print a human-readable v2 -> v3 migration report."""
    click.echo("Migration summary (v2 -> v3):")
    backup = summary.get("backup")
    if backup:
        click.echo(f"  Backup: {backup}")

    cfg = summary.get("config", [])
    if cfg:
        click.echo("  Config:")
        for line in cfg:
            click.echo(f"    {line}")

    normalized = summary.get("link_files_normalized", [])
    if normalized:
        click.echo("  Link files normalized:")
        for line in normalized:
            click.echo(f"    {line}")

    cleaned = summary.get("claude_md_cleaned", [])
    if cleaned:
        click.echo("  CLAUDE.md cleanup:")
        for line in cleaned:
            click.echo(f"    {line}")

    imports_added = summary.get("claude_md_imports_added", [])
    if imports_added:
        click.echo("  CLAUDE.md @import references added:")
        for line in imports_added:
            click.echo(f"    {line}")

    instruction_files = summary.get("instruction_files_updated", [])
    if instruction_files:
        click.echo("  Instruction files updated:")
        for line in instruction_files:
            click.echo(f"    {line}")

    codex_hooks = summary.get("codex_hooks_updated", [])
    if codex_hooks:
        click.echo("  Codex hooks updated:")
        for line in codex_hooks:
            click.echo(f"    {line}")

    renamed = summary.get("verify_md_renamed", [])
    if renamed:
        click.echo("  Renamed:")
        for line in renamed:
            click.echo(f"    {line}")

    archived = summary.get("l3_archived", 0)
    if archived:
        click.echo(f"  L3 files archived: {archived}")

    n_entries = summary.get("node_hook_entries_removed", 0)
    if n_entries:
        click.echo(f"  Legacy JS hook entries removed from settings: {n_entries}")

    n_files = summary.get("node_hook_files_removed", [])
    if n_files:
        click.echo(f"  Legacy JS hook files removed: {', '.join(n_files)}")

    # Always say something
    any_change = any(
        bool(summary.get(k))
        for k in (
            "config",
            "link_files_normalized",
            "claude_md_cleaned",
            "claude_md_imports_added",
            "instruction_files_updated",
            "codex_hooks_updated",
            "verify_md_renamed",
            "l3_archived",
            "node_hook_entries_removed",
            "node_hook_files_removed",
        )
    )
    if not any_change:
        click.echo("  Nothing to do — already on v3.")


def _migrate_completed_at(data_path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {"tasks_migrated": 0, "projects_scanned": 0}
    tasks_root = data_path / "tasks"
    if not tasks_root.exists():
        return summary

    for project_dir in tasks_root.iterdir():
        if not project_dir.is_dir():
            continue
        summary["projects_scanned"] += 1
        for md_file in sorted(project_dir.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                fm, _body = parse_task(md_file)
                if fm.get("status") == "done" and not fm.get("completed_at"):
                    updated = str(fm.get("updated", ""))
                    completed_at = (
                        f"{updated}T00:00:00"
                        if updated
                        else datetime.now().isoformat()
                    )
                    update_frontmatter(md_file, {"completed_at": completed_at})
                    summary["tasks_migrated"] += 1
            except Exception:
                continue
        _rebuild_task_index(data_path, project_dir.name)

    return summary


def print_completed_at_migration_summary(summary: dict[str, Any]) -> None:
    click.echo("Migration summary (completed_at backfill):")
    click.echo(f"  Projects scanned: {summary.get('projects_scanned', 0)}")
    click.echo(f"  Tasks migrated: {summary.get('tasks_migrated', 0)}")


def _detect_current_version(data_path: Path) -> str | None:
    config_path = data_path / ".hivemind.json"
    if not config_path.exists():
        return None
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        version = data.get("version")
        if version is None:
            return "v1"
        if isinstance(version, str):
            if version.startswith("1."):
                return "v1"
            if version == "2.0.0":
                return "v2"
            if version == "3.0.0":
                return "v3"
            if version == "4.0.0":
                return "v4"
        return "v3"
    except Exception:
        return None


@click.command("migrate")
@click.option(
    "--to",
    "target",
    type=click.Choice(["v2", "v3", "v3.1", "v4"]),
    default=None,
    help="Target schema version (prompts if omitted).",
)
@click.option(
    "--path",
    default=None,
    type=click.Path(),
    help="Data directory path (default: ~/agent-hivemind-data).",
)
@click.option(
    "--project",
    "projects",
    multiple=True,
    type=click.Path(),
    help="Linked project directory to update. Repeatable; defaults to cwd if any .hivemind-link.json is present.",
)
@click.option(
    "--no-backup",
    is_flag=True,
    default=False,
    help="Skip the automatic data directory backup.",
)
def migrate_cmd(
    target: str | None,
    path: str | None,
    projects: tuple[str, ...],
    no_backup: bool,
) -> None:
    data_path = (
        Path(path).expanduser().resolve()
        if path
        else Path("~/agent-hivemind-data").expanduser().resolve()
    )

    if target is None:
        current = _detect_current_version(data_path)
        choices = ["v2", "v3", "v3.1", "v4"]
        if current == "v1":
            default = "v2"
        elif current == "v2":
            default = "v3"
        elif current == "v3":
            default = "v4"
        else:
            default = "v4"

        target = questionary.select(
            "Select target version",
            choices=choices,
            default=default,
        ).unsafe_ask()

    if target == "v2":
        if not detect_v1(data_path):
            click.echo("Already on v2 or newer. Nothing to do.")
            return
        summary = migrate_v1_to_v2(data_path)
        print_migration_summary(summary)
        return

    if target == "v3.1":
        summary = _migrate_completed_at(data_path)
        print_completed_at_migration_summary(summary)
        return

    if target == "v4":
        from hivemind.core.migration import migrate_v3_to_v4

        config_path = data_path / ".hivemind.json"
        if not config_path.exists():
            raise click.ClickException(
                f"No config at {config_path}. Run `hv init` first."
            )
        if migrate_v3_to_v4(config_path):
            click.echo(f"Migrated {config_path} to v4.")
        else:
            click.echo("Already on v4. Nothing to do.")
        return

    # target == "v3"
    cwd_link = Path.cwd() / ".hivemind-link.json"
    project_paths: list[Path] = [Path(p).expanduser().resolve() for p in projects]
    if not project_paths and cwd_link.exists():
        project_paths = [Path.cwd()]

    summary = migrate_v2_to_v3(
        data_path,
        project_dirs=project_paths,
        backup=not no_backup,
    )
    print_v3_migration_summary(summary)

    # Propagate backup failures as warnings
    backup_info = summary.get("backup")
    if isinstance(backup_info, str) and backup_info.startswith("FAILED"):
        click.echo(
            f"Warning: backup failed ({backup_info}). Data was still migrated.",
            err=True,
        )
        sys.exit(0)
