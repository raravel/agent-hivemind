"""Hook installer — registers Python hooks in ~/.claude/settings.json.

Primary installation path is the plugin system (``install_plugin``), which
copies ``hooks.json`` verbatim. This module supports the legacy code path
that writes directly into ``settings.json`` for standalone installs.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

_HOOKS_DIR_DEFAULT = Path("~/.claude/hooks")
_SETTINGS_DEFAULT = Path("~/.claude/settings.json")

# Markers embedded in every hivemind hook path so we can detect duplicates.
# Accept both legacy ``hv-*`` (JS) and current ``hv_*`` (Python) names.
_HV_HOOK_PREFIX = "~/.claude/hooks/hv-"
_HV_HOOK_MARKERS: tuple[str, ...] = ("~/.claude/hooks/hv-", "~/.claude/hooks/hv_")


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


def _looks_like_hv_ref(s: str) -> bool:
    """Return True if *s* references a hivemind-managed hook file."""
    if any(s.startswith(m) for m in _HV_HOOK_MARKERS):
        return True
    return "/hv-" in s or "/hv_" in s


def _is_hivemind_hook_entry(entry: str | dict[str, Any]) -> bool:
    """Return True if *entry* contains a hivemind-managed hook path.

    Handles both dict entries (``{"matcher": ..., "hooks": [...]}``) and
    plain-string entries that some settings.json variants use.
    """
    if isinstance(entry, str):
        return _looks_like_hv_ref(entry)
    hooks_list: list[str | dict[str, Any]] = entry.get("hooks", [])
    return any(_looks_like_hv_ref(_hook_ref_str(h)) for h in hooks_list)


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


_PYTHON_HOOK_EVENT_MAP: dict[str, tuple[str, str]] = {
    # filename stem -> (event_name, matcher)
    "hv_pre_commit": ("PreToolUse", "Bash"),
    "hv_session_log": ("PreCompact", ""),
}


def install_hooks(
    source_dir: Path,
    settings_path: Path | None = None,
) -> bool:
    """Install hivemind Python hook files and register them in settings.json.

    Parameters
    ----------
    source_dir:
        Directory containing ``hv_*.py`` hook files.
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

    hooks_dir = settings_path.parent / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # --- Copy Python hook files ---------------------------------------------
    py_files: list[Path] = sorted(source_dir.glob("hv_*.py"))
    for py_file in py_files:
        dest = hooks_dir / py_file.name
        shutil.copy2(py_file, dest)
        try:
            dest.chmod(0o755)
        except OSError:
            pass

    # --- Build new hook entries from copied files ---------------------------
    new_entries: dict[str, list[dict[str, Any]]] = {}
    for py_file in py_files:
        hook_ref = f"~/.claude/hooks/{py_file.name}"
        event, matcher = _PYTHON_HOOK_EVENT_MAP.get(
            py_file.stem, ("PreToolUse", "Bash")
        )
        new_entries.setdefault(event, []).append(
            {
                "matcher": matcher,
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {hook_ref}",
                        "timeout": 10,
                    }
                ],
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
