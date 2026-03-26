"""Hook installer — registers JS hooks in ~/.claude/settings.json."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

_HOOKS_DIR_DEFAULT = Path("~/.claude/hooks")
_SETTINGS_DEFAULT = Path("~/.claude/settings.json")

# Marker embedded in every hivemind hook path so we can detect duplicates.
_HV_HOOK_PREFIX = "~/.claude/hooks/hv-"


def _hook_ref_str(hook: str | dict[str, Any]) -> str:
    """Extract the hook path string regardless of format.

    Hook items in settings.json can be plain strings (``"path/to/hook.js"``)
    or dicts (``{"type": "command", "command": "node hook.js"}``).
    """
    if isinstance(hook, str):
        return hook
    if isinstance(hook, dict):
        # Try common dict keys that hold the path/command.
        for key in ("command", "path", "hooks"):
            val = hook.get(key, "")
            if isinstance(val, str):
                return val
    return ""


def _is_hivemind_hook_entry(entry: str | dict[str, Any]) -> bool:
    """Return True if *entry* contains a hivemind-managed hook path.

    Handles both dict entries (``{"matcher": ..., "hooks": [...]}``) and
    plain-string entries that some settings.json variants use.
    """
    if isinstance(entry, str):
        return entry.startswith(_HV_HOOK_PREFIX) or "/hv-" in entry
    hooks_list: list[str | dict[str, Any]] = entry.get("hooks", [])
    return any(_hook_ref_str(h).startswith(_HV_HOOK_PREFIX) or "/hv-" in _hook_ref_str(h) for h in hooks_list)


def _merge_hooks(
    existing: dict[str, Any],
    new_entries: dict[str, list[dict[str, Any]]],
) -> bool:
    """Merge *new_entries* into *existing* ``hooks`` dict in-place.

    Returns True if anything was actually added.
    """
    if "hooks" not in existing:
        existing["hooks"] = {}

    hooks: dict[str, list[dict[str, Any]]] = existing["hooks"]
    changed = False

    for event_name, entries in new_entries.items():
        if event_name not in hooks:
            hooks[event_name] = []
        event_list: list[dict[str, Any]] = hooks[event_name]

        # Check if hivemind hooks already present in this event list.
        already_present = any(_is_hivemind_hook_entry(e) for e in event_list)
        if already_present:
            continue

        event_list.extend(entries)
        changed = True

    return changed


def install_hooks(
    source_dir: Path,
    settings_path: Path | None = None,
) -> bool:
    """Install hivemind hook JS files and register them in settings.json.

    Parameters
    ----------
    source_dir:
        Directory containing ``.js`` hook files whose names start with
        ``hv-`` (e.g. ``hv-pre-commit.js``).
    settings_path:
        Path to Claude ``settings.json``.
        Defaults to ``~/.claude/settings.json``.

    Returns
    -------
    bool
        ``True`` if hooks were added to settings.json, ``False`` if
        hivemind hooks already existed (no change made).
    """
    if settings_path is None:
        settings_path = _SETTINGS_DEFAULT.expanduser()
    else:
        settings_path = settings_path  # caller already provides resolved path

    hooks_dir = settings_path.parent / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # --- Copy JS files -------------------------------------------------------
    js_files: list[Path] = sorted(source_dir.glob("hv-*.js"))
    for js_file in js_files:
        dest = hooks_dir / js_file.name
        shutil.copy2(js_file, dest)

    # --- Build new hook entries from copied files ----------------------------
    new_entries: dict[str, list[dict[str, Any]]] = {}
    for js_file in js_files:
        hook_ref = f"~/.claude/hooks/{js_file.name}"
        # Derive event name from filename convention: hv-pre-commit.js -> PreToolUse
        # For now, all hooks are registered under PreToolUse with Bash matcher.
        event = "PreToolUse"
        if event not in new_entries:
            new_entries[event] = []
        new_entries[event].append(
            {
                "matcher": "Bash",
                "hooks": [hook_ref],
            }
        )

    if not new_entries:
        return False

    # --- Read / create settings.json -----------------------------------------
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        with settings_path.open("r", encoding="utf-8") as f:
            settings: dict[str, Any] = json.load(f)
    else:
        settings = {}

    # --- Merge ---------------------------------------------------------------
    changed = _merge_hooks(settings, new_entries)
    if not changed:
        return False

    # --- Write back ----------------------------------------------------------
    with settings_path.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return True
