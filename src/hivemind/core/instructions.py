"""Shared helpers for managed instruction and hook files."""

from __future__ import annotations

import json
from pathlib import Path

from hivemind.core.config import SUPPORTED_TARGETS, expand_target_selection

BLOCK_START = "<!-- hivemind:start -->"
BLOCK_END = "<!-- hivemind:end -->"


def normalize_targets(targets: list[str] | tuple[str, ...] | str) -> list[str]:
    """Normalize a target selector or collection to a stable target list."""
    if isinstance(targets, str):
        return expand_target_selection(targets)
    values = [
        item for item in targets if isinstance(item, str) and item in SUPPORTED_TARGETS
    ]
    return sorted(dict.fromkeys(values))


def replace_managed_block(existing: str, block: str) -> str:
    """Replace or append the managed hivemind block in a markdown file."""
    managed = f"{BLOCK_START}\n{block.rstrip()}\n{BLOCK_END}\n"
    if BLOCK_START in existing and BLOCK_END in existing:
        start = existing.index(BLOCK_START)
        end = existing.index(BLOCK_END) + len(BLOCK_END)
        prefix = existing[:start].rstrip()
        suffix = existing[end:].lstrip("\n")
        parts = [part for part in (prefix, managed.rstrip(), suffix) if part]
        return "\n\n".join(parts) + "\n"

    if existing.strip():
        return existing.rstrip() + "\n\n" + managed
    return managed


def build_agents_block(*, project: str, data_path: str, targets: list[str]) -> str:
    """Build the managed AGENTS.md content block.

    The block now carries only the project name. ``data_path`` is still
    accepted to anchor the spec @-import paths but is no longer printed
    as a metadata line — it lives in the global config under v4. The
    ``targets`` argument is accepted for API stability but unused; the
    runtime reads ``runtime.enabled_targets`` from the global config.
    """
    del targets  # rendered targets line removed in v4
    project_spec_root = f"{data_path}/projects/{project}"
    return (
        "# Hivemind Project\n"
        f"- project: {project}\n\n"
        "When planning or executing tracked work, consult the linked hivemind "
        "project docs under:\n"
        f"- {project_spec_root}/\n\n"
        "Prioritize these files when they exist:\n"
        "- architecture.md\n"
        "- rules.md\n"
        "- tech-stack.md\n"
        "- verify.md\n"
        "- features/\n"
    )


def build_claude_block(*, project: str, data_path: str, targets: list[str]) -> str:
    """Build the managed CLAUDE.md import block.

    See :func:`build_agents_block` — the same v4 cleanup applies here.
    """
    del targets
    project_spec_root = f"{data_path}/projects/{project}"
    return (
        "# Hivemind Project\n"
        f"- project: {project}\n\n"
        "@AGENTS.md\n"
        f"@{project_spec_root}/architecture.md\n"
        f"@{project_spec_root}/rules.md\n"
    )


def write_instruction_files(
    project_dir: Path,
    *,
    project: str,
    data_path: str,
    targets: list[str],
) -> list[str]:
    """Write managed AGENTS.md / CLAUDE.md files for the linked project."""
    changed: list[str] = []

    agents_md = project_dir / "AGENTS.md"
    agents_content = (
        agents_md.read_text(encoding="utf-8") if agents_md.exists() else ""
    )
    new_agents = replace_managed_block(
        agents_content,
        build_agents_block(project=project, data_path=data_path, targets=targets),
    )
    if new_agents != agents_content:
        agents_md.write_text(new_agents, encoding="utf-8")
        changed.append("AGENTS.md")

    if "claude" in targets:
        claude_md = project_dir / "CLAUDE.md"
        claude_content = (
            claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        )
        new_claude = replace_managed_block(
            claude_content,
            build_claude_block(project=project, data_path=data_path, targets=targets),
        )
        if new_claude != claude_content:
            claude_md.write_text(new_claude, encoding="utf-8")
            changed.append("CLAUDE.md")

    return changed


def build_codex_hooks_config() -> dict[str, object]:
    """Return repo-local Codex hooks config for hivemind."""
    command_root = "~/.codex/plugins/hv/hooks"
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {command_root}/hv_pre_commit.py",
                            "timeout": 10,
                        }
                    ],
                }
            ],
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {command_root}/hv_session_log.py",
                            "timeout": 10,
                            "async": True,
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {command_root}/hv_session_log.py",
                            "timeout": 10,
                            "async": True,
                        }
                    ],
                }
            ],
        }
    }


def write_codex_hooks_file(project_dir: Path) -> bool:
    """Write a repo-local Codex hooks.json file."""
    codex_dir = project_dir / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    hooks_path = codex_dir / "hooks.json"
    rendered = json.dumps(build_codex_hooks_config(), indent=2, ensure_ascii=False) + "\n"
    before = hooks_path.read_text(encoding="utf-8") if hooks_path.exists() else ""
    if before == rendered:
        return False
    hooks_path.write_text(rendered, encoding="utf-8")
    return True
