"""Implementation of `hv audit` command — detect drift between code and harness specs."""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import click

from hivemind.core.config import HivemindConfig
from hivemind.core.parser import parse_task

STALE_DAYS = 30


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
    raise click.ClickException("No .hivemind.json found. Run `hv init` first.")


def _git_ls_files(linked_path: str) -> list[str]:
    """Run `git ls-files` in the linked project path and return file list."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            cwd=linked_path,
            timeout=15,
        )
        if result.returncode != 0:
            return []
        return [f for f in result.stdout.strip().splitlines() if f]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def _load_spec_files(data_path: Path, project: str) -> list[Path]:
    """Load harness spec docs from projects/{name}/ in the data repo."""
    spec_dir = data_path / "projects" / project
    if not spec_dir.exists():
        return []
    return sorted(spec_dir.rglob("*.md"))


def _extract_referenced_modules(spec_path: Path) -> list[str]:
    """Extract module references from a spec file.

    Looks for patterns like backtick-wrapped paths (e.g. `src/foo.py`)
    and common path-like references in the body text.
    """
    import re

    try:
        content = spec_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    # Match backtick-wrapped paths that look like code files
    backtick_refs = re.findall(r"`([^`]*?\.\w{1,4})`", content)

    # Match bare path-like references (word/word.ext patterns)
    bare_refs = re.findall(r"(?<!\w)([\w/\\.-]+\.(?:py|js|ts|rs|go|java|rb|cpp|c|h))\b", content)

    all_refs: list[str] = []
    for ref in backtick_refs + bare_refs:
        # Normalise backslashes to forward slashes
        normalised = ref.replace("\\", "/")
        if normalised not in all_refs:
            all_refs.append(normalised)
    return all_refs


def _load_tasks(
    data_path: Path, project: str
) -> list[tuple[dict[str, object], str, Path]]:
    """Load task files for a project."""
    tasks_root = data_path / "tasks" / project
    if not tasks_root.exists():
        return []
    results: list[tuple[dict[str, object], str, Path]] = []
    for md_file in sorted(tasks_root.glob("*.md")):
        try:
            fm, body = parse_task(md_file)
            results.append((fm, body, md_file))
        except Exception:  # noqa: BLE001
            continue
    return results


def _find_stale_tasks(
    tasks: list[tuple[dict[str, object], str, Path]],
    today: date | None = None,
) -> list[tuple[str, int]]:
    """Find done tasks that are stale (done > STALE_DAYS with no recent update).

    Returns list of (task_id, days_since_done).
    """
    if today is None:
        today = date.today()

    stale: list[tuple[str, int]] = []
    for fm, _body, _path in tasks:
        if fm.get("status") != "done":
            continue
        # Use 'updated' date as proxy for when task was marked done
        updated_raw = fm.get("updated")
        if not isinstance(updated_raw, (str, date)):
            continue
        try:
            if isinstance(updated_raw, date):
                updated_date = updated_raw
            else:
                updated_date = date.fromisoformat(str(updated_raw))
        except ValueError:
            continue

        days_ago = (today - updated_date).days
        if days_ago > STALE_DAYS:
            task_id = str(fm.get("id", "unknown"))
            stale.append((task_id, days_ago))
    return stale


def run_audit(
    project: str,
    fix: bool,
    config_finder: object = None,
) -> str:
    """Execute the audit and return the drift report as a string.

    Separated from the Click command for testability.
    """
    cfg, data_path = _find_config()

    proj_cfg = cfg.get_project(project)
    if proj_cfg is None:
        raise click.ClickException(
            f"Project '{project}' not found in config. "
            "Add it with `hv link` or update .hivemind.json."
        )

    linked_path = proj_cfg.get("linked_path", "")
    if not isinstance(linked_path, str) or not linked_path:
        raise click.ClickException(
            f"Project '{project}' has no linked_path in config."
        )

    # Step 1-2: Get code files from linked project
    code_files = _git_ls_files(linked_path)

    # Step 3: Load spec files
    spec_files = _load_spec_files(data_path, project)

    # Step 4: Cross-reference
    code_without_spec: list[str] = []
    spec_without_code: list[tuple[str, str]] = []

    # Build a set of all referenced modules across all specs
    all_referenced: set[str] = set()
    for spec_path in spec_files:
        refs = _extract_referenced_modules(spec_path)
        all_referenced.update(refs)

    # Code files not mentioned in any spec
    for code_file in code_files:
        normalised = code_file.replace("\\", "/")
        # Check if any spec references this file (exact or suffix match)
        found = False
        for ref in all_referenced:
            if normalised == ref or normalised.endswith("/" + ref) or ref.endswith("/" + normalised):
                found = True
                break
        if not found:
            code_without_spec.append(code_file)

    # Spec references pointing to files not in code
    for spec_path in spec_files:
        refs = _extract_referenced_modules(spec_path)
        for ref in refs:
            found = False
            for code_file in code_files:
                normalised_code = code_file.replace("\\", "/")
                if normalised_code == ref or normalised_code.endswith("/" + ref) or ref.endswith("/" + normalised_code):
                    found = True
                    break
            if not found:
                rel_spec = spec_path.name
                spec_without_code.append((rel_spec, ref))

    # Step 5: Stale tasks
    tasks = _load_tasks(data_path, project)
    stale_tasks = _find_stale_tasks(tasks)

    # Step 6: Build report
    lines: list[str] = []
    lines.append(f"=== Drift Report: {project} ===")
    lines.append("")

    issue_count = 0

    if code_without_spec:
        lines.append("Code without spec:")
        for f in code_without_spec:
            lines.append(f"  - {f}")
            issue_count += 1
        lines.append("")

    if spec_without_code:
        lines.append("Spec without code:")
        for spec_name, ref in spec_without_code:
            lines.append(f"  - {spec_name} → referenced module not found: {ref}")
            issue_count += 1
        lines.append("")

    if stale_tasks:
        lines.append("Stale tasks:")
        for task_id, days_ago in stale_tasks:
            lines.append(f"  - {task_id} (done {days_ago} days ago, no recent activity)")
            issue_count += 1
        lines.append("")

    if issue_count == 0:
        lines.append("No issues found. Code and specs are in sync.")
        lines.append("")

    lines.append(f"Total: {issue_count} issues found")

    # Step 7: Fix suggestions
    if fix and issue_count > 0:
        lines.append("")
        lines.append("=== Fix Suggestions ===")
        lines.append("")
        if code_without_spec:
            lines.append("Code without spec:")
            for f in code_without_spec:
                lines.append(f"  → Create spec documentation for {f}")
        if spec_without_code:
            lines.append("Spec without code:")
            for spec_name, ref in spec_without_code:
                lines.append(f"  → Update {spec_name}: remove or update reference to {ref}")
        if stale_tasks:
            lines.append("Stale tasks:")
            for task_id, days_ago in stale_tasks:
                lines.append(f"  → Review {task_id} — archive or reopen if still relevant")

    return "\n".join(lines)


@click.command("audit")
@click.option("--project", "-p", required=True, help="Project to audit.")
@click.option("--fix", is_flag=True, default=False, help="Print fix suggestions.")
def audit(project: str, fix: bool) -> None:
    """Audit a project for drift between code and harness specs."""
    report = run_audit(project, fix)
    click.echo(report)
