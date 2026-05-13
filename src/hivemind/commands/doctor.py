"""Implementation of `hv doctor` -- installation and project health check."""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from hivemind.core.config import HivemindConfig, normalize_data_path
from hivemind.core.instructions import normalize_targets
from hivemind.installer.plugin_bundle import resolve_manifest_skills_dir

_PRIMARY_CODEX_PLUGIN_DIR = Path("~/plugins/hv").expanduser()
_LEGACY_CODEX_PLUGIN_DIR = Path("~/.codex/plugins/hv").expanduser()
_PRIMARY_CODEX_MARKETPLACE_PATH = Path(
    "~/.agents/plugins/marketplace.json"
).expanduser()
_LEGACY_CODEX_MARKETPLACE_PATH = Path(
    "~/.codex/plugins/marketplace.json"
).expanduser()

Severity = str  # "ok" | "warn" | "error"


@dataclass(frozen=True)
class CheckResult:
    name: str
    severity: Severity
    detail: str


def _ok(name: str, detail: str = "") -> CheckResult:
    return CheckResult(name, "ok", detail)


def _warn(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "warn", detail)


def _err(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "error", detail)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_cli_on_path() -> CheckResult:
    path = shutil.which("hv")
    if path is None:
        return _err("hv CLI on PATH", "hv not found via shutil.which")
    return _ok("hv CLI on PATH", path)


def _find_config_path() -> Path | None:
    for candidate in (
        Path.cwd() / ".hivemind.json",
        Path("~/.hivemind.json").expanduser(),
        Path("~/agent-hivemind-data/.hivemind.json").expanduser(),
    ):
        if candidate.exists():
            return candidate
    return None


_EXPECTED_SCHEMA_VERSION = "5.0.0"


def _check_config() -> tuple[CheckResult, HivemindConfig | None]:
    config_path = _find_config_path()
    if config_path is None:
        return (
            _err(
                "Config .hivemind.json",
                "not found in cwd, ~, or ~/agent-hivemind-data/ — run `hv init`",
            ),
            None,
        )
    try:
        cfg = HivemindConfig.load(config_path)
    except (OSError, json.JSONDecodeError) as e:
        return _err("Config .hivemind.json", f"malformed at {config_path}: {e}"), None

    version = cfg.get("version")
    if version != _EXPECTED_SCHEMA_VERSION:
        return (
            _warn(
                "Config .hivemind.json",
                f"found at {config_path} but version={version!r} "
                f"(v{_EXPECTED_SCHEMA_VERSION} expected — run `hv migrate --to v5`)",
            ),
            cfg,
        )
    return (
        _ok("Config .hivemind.json", f"{config_path} (v{_EXPECTED_SCHEMA_VERSION})"),
        cfg,
    )


def _check_data_directory(cfg: HivemindConfig | None) -> CheckResult:
    if cfg is None:
        return _err("Data directory", "no config, cannot resolve data_path")
    data_path = cfg.data_path
    if not data_path.exists():
        return _err("Data directory", f"{data_path} does not exist")

    # v5: only L2/L3 are cross-project state. `projects/` and `tasks/` moved
    # into each linked repo under `hivemind/`. `level1/` is a regenerable cache
    # for important.md, so we don't require it.
    required = ("level2", "level3")
    missing = [d for d in required if not (data_path / d).is_dir()]
    if missing:
        return _warn(
            "Data directory",
            f"{data_path} missing subdirs: {', '.join(missing)} — run `hv init`",
        )

    legacy = [d for d in ("projects", "tasks") if (data_path / d).is_dir()]
    if legacy:
        return _warn(
            "Data directory",
            f"{data_path} still has legacy subdirs: {', '.join(legacy)} "
            "— run `hv migrate --to v5`",
        )
    return _ok("Data directory", f"{data_path} (L2/L3 present)")


def _check_claude_plugin_installed() -> CheckResult:
    plugin_dir = Path("~/.claude/plugins/hv").expanduser()
    if not plugin_dir.exists():
        return _err(
            "Claude Code plugin",
            f"not installed at {plugin_dir} — run `hv init`",
        )

    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    if not manifest.exists():
        return _err(
            "Claude Code plugin",
            f"{plugin_dir} exists but missing .claude-plugin/plugin.json",
        )

    skills = _list_plugin_skills(plugin_dir, ".claude-plugin/plugin.json")

    hooks_dir = plugin_dir / "hooks"
    hook_files = sorted(p.name for p in hooks_dir.glob("hv_*.py")) if hooks_dir.exists() else []
    js_leftover = sorted(p.name for p in hooks_dir.glob("hv-*.js")) if hooks_dir.exists() else []

    detail = f"{plugin_dir} ({len(skills)} skills, {len(hook_files)} python hooks)"
    if js_leftover:
        return _warn(
            "Claude Code plugin",
            f"{detail} but legacy JS hooks present: {', '.join(js_leftover)} — run `hv init`",
        )
    if not skills:
        return _warn("Claude Code plugin", f"{detail} — no skills found")
    if not hook_files:
        return _warn(
            "Claude Code plugin",
            f"{detail} — no python hooks found (session logging disabled)",
        )
    return _ok("Claude Code plugin", detail)


def _check_codex_plugin_installed() -> CheckResult:
    plugin_dir = None
    for candidate in (_PRIMARY_CODEX_PLUGIN_DIR, _LEGACY_CODEX_PLUGIN_DIR):
        if candidate.exists():
            plugin_dir = candidate
            break
    if plugin_dir is None:
        return _err(
            "Codex plugin",
            (
                "not installed at "
                f"{_PRIMARY_CODEX_PLUGIN_DIR} or {_LEGACY_CODEX_PLUGIN_DIR}"
                " — run `hv init --target codex`"
            ),
        )

    manifest = plugin_dir / ".codex-plugin" / "plugin.json"
    if not manifest.exists():
        return _err(
            "Codex plugin",
            f"{plugin_dir} exists but missing .codex-plugin/plugin.json",
        )

    skills = _list_plugin_skills(plugin_dir, ".codex-plugin/plugin.json")
    marketplace_note = "marketplace missing"
    for marketplace in (
        _PRIMARY_CODEX_MARKETPLACE_PATH,
        _LEGACY_CODEX_MARKETPLACE_PATH,
    ):
        if marketplace.exists():
            marketplace_note = str(marketplace)
            break

    detail = f"{plugin_dir} ({len(skills)} skills, {marketplace_note})"
    if not skills:
        return _warn("Codex plugin", f"{detail} — no skills found")
    return _ok("Codex plugin", detail)


def _check_project_link(project_dir: Path) -> tuple[CheckResult, dict[str, Any] | None]:
    from hivemind.core.paths import resolve_link_file

    link_file = resolve_link_file(project_dir)
    if link_file is None:
        return (
            _warn(
                "Project link",
                f"{project_dir} is not linked (no hivemind/link.json) — run `hv link`",
            ),
            None,
        )
    try:
        link = json.loads(link_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return _err("Project link", f"{link_file} is malformed: {e}"), None

    raw_path = str(link.get("data_path") or "")
    if sys.platform != "win32" and len(raw_path) >= 2 and raw_path[1] == ":" and raw_path[0].isalpha():
        return (
            _err(
                "Project link",
                f"data_path {raw_path!r} is a Windows path on {sys.platform} — run `hv migrate --to v5`",
            ),
            link,
        )

    resolved = normalize_data_path(raw_path)
    if not resolved.exists():
        return (
            _err(
                "Project link",
                f"data_path {resolved} does not exist on disk",
            ),
            link,
        )

    project = link.get("project") or "?"
    # Flag legacy link-file location so users know to migrate.
    if link_file.name == ".hivemind-link.json":
        return (
            _warn(
                "Project link",
                f"{project} -> {resolved} (legacy {link_file.name}; run `hv migrate --to v5`)",
            ),
            link,
        )
    return _ok("Project link", f"{project} -> {resolved}"), link


def _list_plugin_skills(plugin_dir: Path, manifest_relpath: str) -> list[str]:
    """Return actual skill directory names from the manifest-declared skills path."""
    try:
        skills_dir = resolve_manifest_skills_dir(plugin_dir, manifest_relpath)
    except (OSError, json.JSONDecodeError):
        return []
    if not skills_dir.exists():
        return []
    return [
        d.name
        for d in sorted(skills_dir.iterdir())
        if d.is_dir() and (d / "SKILL.md").exists()
    ]


def _determine_targets(
    link: dict[str, Any] | None,
    cfg: HivemindConfig | None,
) -> list[str]:
    """Resolve active targets from link metadata or global config."""
    if isinstance(link, dict):
        raw = link.get("targets")
        if isinstance(raw, list):
            values = normalize_targets(raw)
            if values:
                return values
    if cfg is not None:
        return cfg.enabled_targets
    return ["claude"]


def _check_verify_md(
    project_dir: Path,
    link: dict[str, Any] | None,
    cfg: HivemindConfig | None,
) -> CheckResult:
    if link is None or cfg is None:
        return _warn("Project verify.md", "skipped (no link or config)")

    project = link.get("project")
    if not project:
        return _warn("Project verify.md", "skipped (link has no project name)")

    # v5: specs live under <project_dir>/hivemind/docs. Pre-v5 fallback to
    # <data_path>/projects/<name>/ if the v5 location doesn't exist yet.
    from hivemind.core.paths import harness_spec_dir
    v5_spec_dir = harness_spec_dir(project_dir)
    legacy_spec_dir = cfg.data_path / "projects" / str(project)
    project_spec_dir = v5_spec_dir if v5_spec_dir.exists() else legacy_spec_dir
    verify_md = project_spec_dir / "verify.md"
    legacy = project_spec_dir / "build-verify.md"

    if verify_md.exists():
        if legacy.exists():
            return _warn(
                "Project verify.md",
                f"{verify_md} exists but legacy build-verify.md also present — delete the latter",
            )
        return _ok("Project verify.md", str(verify_md))
    if legacy.exists():
        return _warn(
            "Project verify.md",
            f"only legacy build-verify.md at {legacy} — run `hv migrate --to v5`",
        )
    return _err(
        "Project verify.md",
        f"neither verify.md nor build-verify.md in {project_spec_dir}"
        " — use the create-verify skill to generate one",
    )


def _check_instruction_files(
    project_dir: Path,
    targets: list[str],
) -> list[CheckResult]:
    """Check managed instruction files for active runtimes."""
    results: list[CheckResult] = []

    agents_md = project_dir / "AGENTS.md"
    if agents_md.exists():
        results.append(_ok("AGENTS.md", str(agents_md)))
    else:
        results.append(
            _warn(
                "AGENTS.md",
                f"missing in {project_dir} — run `hv link --target {'both' if 'claude' in targets and 'codex' in targets else targets[0]}`",
            )
        )

    if "claude" in targets:
        claude_md = project_dir / "CLAUDE.md"
        if not claude_md.exists():
            results.append(
                _warn("CLAUDE.md", f"missing in {project_dir} for Claude target")
            )
        else:
            try:
                text = claude_md.read_text(encoding="utf-8")
            except OSError:
                text = ""
            if "@AGENTS.md" not in text:
                results.append(
                    _warn("CLAUDE.md", "exists but missing @AGENTS.md shim import")
                )
            else:
                results.append(_ok("CLAUDE.md", str(claude_md)))

    if "codex" in targets:
        hooks_json = project_dir / ".codex" / "hooks.json"
        if hooks_json.exists():
            results.append(_ok("Codex hooks", str(hooks_json)))
        else:
            results.append(
                _warn(
                    "Codex hooks",
                    f"missing {hooks_json} — run `hv link --target codex`",
                )
            )

    return results


_OBSIDIAN_RE = re.compile(r"^\s*obsidian-import\b")


def _check_legacy_artifacts(project_dir: Path) -> CheckResult:
    issues: list[str] = []

    claude_md = project_dir / "CLAUDE.md"
    if claude_md.exists():
        try:
            text = claude_md.read_text(encoding="utf-8")
        except OSError:
            text = ""
        for line in text.splitlines():
            if _OBSIDIAN_RE.match(line):
                issues.append("CLAUDE.md has legacy obsidian-import line")
                break

    installed_hooks = Path("~/.claude/hooks").expanduser()
    if installed_hooks.exists():
        js = sorted(p.name for p in installed_hooks.glob("hv-*.js"))
        if js:
            issues.append(f"~/.claude/hooks has legacy JS: {', '.join(js)}")

    settings = Path("~/.claude/settings.json").expanduser()
    if settings.exists():
        try:
            raw = json.loads(settings.read_text(encoding="utf-8"))
            hook_blob = json.dumps(raw.get("hooks", {}), ensure_ascii=False)
            if re.search(r"hv-[a-z-]+\.js", hook_blob):
                issues.append("~/.claude/settings.json still references hv-*.js")
        except (OSError, json.JSONDecodeError):
            pass

    if issues:
        return _warn("Legacy artifacts", "; ".join(issues) + " — run `hv migrate --to v5`")
    return _ok("Legacy artifacts", "none found")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


_SEVERITY_GLYPH = {"ok": "[OK]", "warn": "[!!]", "error": "[XX]"}


def _format_result(result: CheckResult, use_color: bool) -> str:
    glyph = _SEVERITY_GLYPH[result.severity]
    if use_color:
        color = {"ok": "green", "warn": "yellow", "error": "red"}[result.severity]
        glyph = click.style(glyph, fg=color, bold=True)
    suffix = f"  {result.detail}" if result.detail else ""
    return f"  {glyph} {result.name}{suffix}"


def run_checks(project_dir: Path) -> list[CheckResult]:
    """Run all doctor checks and return their results."""
    results: list[CheckResult] = []

    results.append(_check_cli_on_path())

    cfg_result, cfg = _check_config()
    results.append(cfg_result)

    results.append(_check_data_directory(cfg))

    link_result, link = _check_project_link(project_dir)
    results.append(link_result)
    targets = _determine_targets(link, cfg)

    if "claude" in targets:
        results.append(_check_claude_plugin_installed())
    if "codex" in targets:
        results.append(_check_codex_plugin_installed())

    results.append(_check_verify_md(project_dir, link, cfg))
    results.extend(_check_instruction_files(project_dir, targets))
    results.append(_check_legacy_artifacts(project_dir))

    return results


@click.command("doctor")
@click.option(
    "--project-dir",
    type=click.Path(),
    default=None,
    help="Project directory to check (default: cwd).",
)
def doctor_cmd(project_dir: str | None) -> None:
    """Run install + project health checks."""
    target = Path(project_dir).expanduser().resolve() if project_dir else Path.cwd()

    use_color = sys.stdout.isatty()

    click.echo("Hivemind health check")
    click.echo("=====================")
    click.echo(f"Project: {target}")
    click.echo("")

    results = run_checks(target)
    for r in results:
        click.echo(_format_result(r, use_color))

    errors = sum(1 for r in results if r.severity == "error")
    warnings = sum(1 for r in results if r.severity == "warn")
    passes = sum(1 for r in results if r.severity == "ok")

    click.echo("")
    click.echo(
        f"Summary: {passes} pass, {warnings} warn, {errors} error "
        f"({len(results)} total)"
    )

    if errors:
        sys.exit(1)
    if warnings:
        sys.exit(0)
