#!/usr/bin/env python3
"""PreToolUse hook (Bash matcher).

Intercepts ``git commit`` calls. When the cwd contains a hivemind link file
(v5: ``hivemind/link.json``; legacy: ``.hivemind-link.json``), injects a
spec-sync reminder listing the staged files so the agent remembers to update
harness docs.

Input:  JSON on stdin: ``{tool_name, tool_input, cwd, ...}``
Output: JSON on stdout: ``{status: "approve", additionalContext?}``
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _approve(context: str | None = None) -> None:
    payload: dict[str, object] = {"status": "approve"}
    if context:
        payload["additionalContext"] = context
    sys.stdout.write(json.dumps(payload))


def _read_input() -> dict[str, object] | None:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else None
    except (OSError, json.JSONDecodeError):
        return None


def main() -> None:
    data = _read_input()
    if data is None:
        _approve()
        return

    if data.get("tool_name") != "Bash":
        _approve()
        return

    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        _approve()
        return
    command = str(tool_input.get("command", ""))
    if "git commit" not in command:
        _approve()
        return

    cwd = Path(str(data.get("cwd") or Path.cwd()))
    link_file = cwd / "hivemind" / "link.json"
    if not link_file.exists():
        legacy = cwd / ".hivemind-link.json"
        if not legacy.exists():
            _approve()
            return
        link_file = legacy

    try:
        link = json.loads(link_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _approve()
        return

    project = link.get("project") or "unknown"

    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _approve()
        return

    staged = result.stdout.strip()
    if not staged:
        _approve()
        return

    file_list = ", ".join(staged.splitlines())
    reminder = (
        f"Remember to update harness specs in projects/{project}/ "
        f"if these code changes affect documented architecture or features: "
        f"{file_list}"
    )
    _approve(reminder)


if __name__ == "__main__":
    main()
