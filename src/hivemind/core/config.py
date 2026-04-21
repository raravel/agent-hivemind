"""Config management for .hivemind.json (v3 schema)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_DATA_PATH = "~/agent-hivemind-data"

# Per-Mtoken USD pricing, seeded from public Anthropic pricing. Users may
# override in .hivemind.json; values are cents-level estimates.
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.8, "output": 4.0},
}


def default_config() -> dict[str, Any]:
    """Return default v3 config dict."""
    return {
        "version": "3.0.0",
        "data_path": DEFAULT_DATA_PATH,
        "git_enabled": False,
        "auto_commit": False,
        "model_profile": "balanced",
        "profiles": {
            "quality": {
                "planner": "claude-opus-4-7",
                "executor": "claude-opus-4-7",
                "reviewer": "claude-opus-4-7",
            },
            "balanced": {
                "planner": "claude-opus-4-7",
                "executor": "claude-sonnet-4-6",
                "reviewer": "claude-sonnet-4-6",
            },
            "budget": {
                "planner": "claude-sonnet-4-6",
                "executor": "claude-haiku-4-5",
                "reviewer": "claude-haiku-4-5",
            },
        },
        "pricing": DEFAULT_PRICING,
        "parallel": {"max_concurrency": 2},
        "projects": {},
        "filter_patterns": [],
    }


def data_path_for_storage(p: Path | str) -> str:
    """Normalize a path for cross-platform storage in JSON configs.

    Uses ``~`` prefix when the path lives under HOME so the file stays
    portable across machines. Always writes POSIX-style separators.
    """
    path = Path(str(p)).expanduser().resolve()
    try:
        rel = path.relative_to(Path.home().resolve())
        return f"~/{rel.as_posix()}" if rel.parts else "~"
    except ValueError:
        return path.as_posix()


def _looks_like_foreign_windows(raw: str) -> bool:
    """Return True if *raw* is a Windows-style absolute path on non-Windows."""
    if sys.platform == "win32":
        return False
    return len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha()


def normalize_data_path(raw: str | Path | None) -> Path:
    """Resolve a stored ``data_path`` value to a usable Path.

    Falls back to ``~/agent-hivemind-data`` when *raw* is empty or carries a
    path from a foreign platform (e.g. ``C:\\...`` on macOS).
    """
    default = Path(DEFAULT_DATA_PATH).expanduser().resolve()
    if not raw:
        return default
    s = str(raw)
    if _looks_like_foreign_windows(s):
        return default
    return Path(s).expanduser().resolve()


class HivemindConfig:
    """Reads and writes .hivemind.json."""

    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self._path = path
        self._data = data

    @staticmethod
    def load(path: Path | str) -> HivemindConfig:
        """Load config from a .hivemind.json file path."""
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        return HivemindConfig(path, data)

    def save(self) -> None:
        """Write config to path."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def get(self, key: str) -> Any:
        """Get config value using dot notation (e.g. 'profiles.balanced')."""
        parts = key.split(".")
        current: Any = self._data
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def set(self, key: str, value: Any) -> None:
        """Set config value using dot notation."""
        parts = key.split(".")
        current: dict[str, Any] = self._data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def get_project(self, name: str) -> dict[str, Any] | None:
        """Get project config dict by name."""
        projects = self._data.get("projects", {})
        if not isinstance(projects, dict):
            return None
        proj: dict[str, Any] | None = projects.get(name)
        return proj

    def set_project(
        self, name: str, prefix: str, linked_path: str
    ) -> None:
        """Add or update a project entry."""
        if "projects" not in self._data or not isinstance(
            self._data["projects"], dict
        ):
            self._data["projects"] = {}
        self._data["projects"][name] = {
            "prefix": prefix,
            "linked_path": linked_path,
        }

    @property
    def data_path(self) -> Path:
        """Return resolved data path, cross-platform safe."""
        raw = self._data.get("data_path")
        return normalize_data_path(raw if isinstance(raw, str) else None)

    @property
    def raw(self) -> dict[str, Any]:
        """Return the raw config dict."""
        return self._data
