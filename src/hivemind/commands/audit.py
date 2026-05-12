"""Implementation of `hv audit` command — detect drift between code and harness specs."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path

import click

from hivemind.core.config import HivemindConfig
from hivemind.core.parser import parse_task

STALE_DAYS = 30

# Manifest filenames inspected by `--tech-stack`. The mapping is to a parser
# function that returns a set of dependency names. Order does not matter.
_MANIFEST_PATTERNS: tuple[str, ...] = (
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
)


def _find_config() -> tuple[HivemindConfig, Path]:
    """Locate .hivemind.json and return (config, data_path)."""
    try:
        cfg = HivemindConfig.find_for_command()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    return cfg, cfg.data_path


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


def _load_spec_files(linked_path: Path) -> list[Path]:
    """Load harness spec docs from ``<linked_path>/hivemind/docs/`` (v5 layout)."""
    from hivemind.core.paths import harness_spec_dir
    spec_dir = harness_spec_dir(linked_path)
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
    linked_path: Path,
) -> list[tuple[dict[str, object], str, Path]]:
    """Load task files for a linked project (v5: ``<linked>/hivemind/tasks``)."""
    from hivemind.core.paths import task_dir
    tasks_root = task_dir(linked_path)
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


def _read_manifest_deps(linked_path: Path) -> dict[str, set[str]]:
    """Read direct-dependency names from manifest files at `linked_path`.

    Returns a dict of `{manifest_filename: {dep_name, ...}}`. Only the
    manifests in `_MANIFEST_PATTERNS` are inspected. Parsing is intentionally
    forgiving — malformed files contribute an empty set.
    """
    result: dict[str, set[str]] = {}
    for fname in _MANIFEST_PATTERNS:
        path = linked_path / fname
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            result[fname] = set()
            continue

        names: set[str] = set()
        try:
            if fname == "package.json":
                data = json.loads(text)
                for key in ("dependencies", "devDependencies", "peerDependencies"):
                    block = data.get(key) or {}
                    if isinstance(block, dict):
                        names.update(str(k) for k in block.keys())
            elif fname == "pyproject.toml":
                # Match both PEP 621 (`dependencies = [...]`) and poetry style.
                for m in re.finditer(
                    r"^\s*[\"']?([A-Za-z0-9._-]+)[\"']?\s*[=~<>!]",
                    text,
                    re.MULTILINE,
                ):
                    names.add(m.group(1))
                # poetry: [tool.poetry.dependencies] table — `name = "version"`
                in_poetry_deps = False
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("[") and stripped.endswith("]"):
                        in_poetry_deps = (
                            "tool.poetry.dependencies" in stripped
                            or "tool.poetry.dev-dependencies" in stripped
                        )
                        continue
                    if in_poetry_deps and "=" in stripped and not stripped.startswith("#"):
                        key = stripped.split("=", 1)[0].strip().strip("\"'")
                        if key and key.lower() != "python":
                            names.add(key)
            elif fname == "Cargo.toml":
                in_deps = False
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("[") and stripped.endswith("]"):
                        in_deps = stripped in (
                            "[dependencies]",
                            "[dev-dependencies]",
                            "[build-dependencies]",
                        )
                        continue
                    if in_deps and "=" in stripped and not stripped.startswith("#"):
                        key = stripped.split("=", 1)[0].strip().strip("\"'")
                        if key:
                            names.add(key)
            elif fname == "go.mod":
                in_require_block = False
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("require ("):
                        in_require_block = True
                        continue
                    if in_require_block and stripped.startswith(")"):
                        in_require_block = False
                        continue
                    if in_require_block and stripped and not stripped.startswith("//"):
                        names.add(stripped.split()[0])
                    elif stripped.startswith("require ") and not stripped.endswith("("):
                        # single-line require
                        parts = stripped.split()
                        if len(parts) >= 2:
                            names.add(parts[1])
            elif fname == "Gemfile":
                for m in re.finditer(r"^\s*gem\s+['\"]([^'\"]+)['\"]", text, re.MULTILINE):
                    names.add(m.group(1))
            elif fname == "composer.json":
                data = json.loads(text)
                for key in ("require", "require-dev"):
                    block = data.get(key) or {}
                    if isinstance(block, dict):
                        names.update(str(k) for k in block.keys())
        except (json.JSONDecodeError, ValueError):
            pass

        result[fname] = names
    return result


def _extract_active_dependencies(tech_stack_path: Path) -> list[str]:
    """Return library names listed under `## Active Dependencies` in tech-stack.md.

    Matches list-item entries (`- name version — note`) and table-row entries
    (`| name | version | ... |`). Empty result if the section is absent.
    """
    if not tech_stack_path.exists():
        return []
    try:
        text = tech_stack_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    lines = text.splitlines()
    in_section = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            # Treat any heading transition as section change.
            in_section = (
                stripped.lstrip("#").strip().lower() == "active dependencies"
            )
            continue
        if not in_section or not stripped:
            continue
        # List item: `- name ...`
        m = re.match(r"^[-*]\s+`?([A-Za-z0-9@._/+-]+)`?", stripped)
        if m:
            out.append(m.group(1).strip("`"))
            continue
        # Table row: `| name | ... |` (skip header/separator rows)
        if stripped.startswith("|") and "|" in stripped[1:]:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if cells and cells[0] and not set(cells[0]) <= {"-", ":", " "}:
                # Skip header rows by checking for any non-name-like first cell
                first = cells[0].strip("`")
                if re.match(r"^[A-Za-z0-9@._/+-]+$", first):
                    out.append(first)
    return out


def run_tech_stack_audit(project: str) -> str:
    """Compare `tech-stack.md ## Active Dependencies` to detected manifests.

    Detects two kinds of drift:
      - **doc-without-manifest**: a library in the doc but absent from every
        detected manifest. Strong drift signal — caps `tech_stack` rubric at 5.
      - **manifest-without-doc**: a direct dependency in a manifest but absent
        from the doc. Soft drift — newly-added deps the planner forgot to record.
    Vendored libraries belong in `## Legacy / Vendored`; they're exempt.
    """
    cfg, _data_path = _find_config()
    from hivemind.core.paths import harness_spec_dir, linked_path_for
    try:
        linked_path = linked_path_for(cfg, project)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))
    tech_stack_path = harness_spec_dir(linked_path) / "tech-stack.md"

    manifests = _read_manifest_deps(linked_path)
    doc_deps = _extract_active_dependencies(tech_stack_path)

    all_manifest_names: set[str] = set()
    for names in manifests.values():
        all_manifest_names.update(names)

    # Normalize for comparison — package.json names can have a scope; pyproject
    # may use dashes vs underscores. Compare lowercased + dash-normalized.
    def _norm(name: str) -> str:
        return name.strip("`").lower().replace("_", "-")

    norm_manifest = {_norm(n): n for n in all_manifest_names}
    norm_doc = {_norm(d): d for d in doc_deps}

    doc_without_manifest = sorted(
        norm_doc[k] for k in norm_doc.keys() - norm_manifest.keys()
    )
    manifest_without_doc = sorted(
        norm_manifest[k] for k in norm_manifest.keys() - norm_doc.keys()
    )

    lines: list[str] = []
    lines.append(f"=== Tech-Stack Drift: {project} ===")
    lines.append("")
    if not tech_stack_path.exists():
        lines.append(f"tech-stack.md missing at {tech_stack_path}")
        lines.append("")
        lines.append("Total: 1 issue")
        return "\n".join(lines)

    if not manifests:
        lines.append(
            f"No manifest files detected in {linked_path}. "
            "Nothing to cross-check."
        )
        return "\n".join(lines)

    lines.append("Detected manifests:")
    for fname, names in manifests.items():
        lines.append(f"  - {fname} ({len(names)} direct deps)")
    lines.append("")
    lines.append(f"## Active Dependencies entries in tech-stack.md: {len(doc_deps)}")
    lines.append("")

    issue_count = 0

    if doc_without_manifest:
        lines.append("Doc claims but manifest disagrees (caps rubric tech_stack at 5):")
        for n in doc_without_manifest:
            lines.append(f"  - {n}")
            issue_count += 1
        lines.append("")

    if manifest_without_doc:
        lines.append("Manifest has but doc missing (consider adding to Active Dependencies):")
        for n in manifest_without_doc:
            lines.append(f"  - {n}")
            issue_count += 1
        lines.append("")

    if issue_count == 0:
        lines.append("No tech-stack drift found.")
        lines.append("")

    lines.append(f"Total: {issue_count} issues found")
    return "\n".join(lines)


def run_audit(
    project: str,
    fix: bool,
    config_finder: object = None,
) -> str:
    """Execute the audit and return the drift report as a string.

    Separated from the Click command for testability.
    """
    cfg, data_path = _find_config()
    from hivemind.core.paths import linked_path_for
    try:
        linked_path_obj = linked_path_for(cfg, project)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))
    linked_path = str(linked_path_obj)

    # Step 1-2: Get code files from linked project
    code_files = _git_ls_files(linked_path)

    # Step 3: Load spec files
    spec_files = _load_spec_files(linked_path_obj)

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
    tasks = _load_tasks(linked_path_obj)
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
@click.option(
    "--tech-stack",
    "tech_stack_only",
    is_flag=True,
    default=False,
    help=(
        "Only check `tech-stack.md ## Active Dependencies` against detected "
        "manifests. Quick cross-check; skips code/spec drift and stale tasks."
    ),
)
def audit(project: str, fix: bool, tech_stack_only: bool) -> None:
    """Audit a project for drift between code and harness specs."""
    if tech_stack_only:
        report = run_tech_stack_audit(project)
    else:
        report = run_audit(project, fix)
    click.echo(report)
