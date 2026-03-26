"""Config management for .hivemind.json (v2 schema)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def default_config() -> dict[str, Any]:
    """Return default v2 config dict."""
    return {
        "version": "2.0.0",
        "data_path": "~/agent-hivemind-data",
        "git_enabled": False,
        "auto_commit": False,
        "model_profile": "balanced",
        "profiles": {
            "quality": {
                "planner": "opus",
                "executor": "opus",
                "reviewer": "opus",
            },
            "balanced": {
                "planner": "opus",
                "executor": "sonnet",
                "reviewer": "sonnet",
            },
            "budget": {
                "planner": "sonnet",
                "executor": "sonnet",
                "reviewer": "haiku",
            },
        },
        "projects": {},
        "filter_patterns": [],
    }


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
        """Return resolved data path (expand ~)."""
        raw = self._data.get("data_path", "~/agent-hivemind-data")
        if not isinstance(raw, str):
            raw = "~/agent-hivemind-data"
        return Path(raw).expanduser()

    @property
    def raw(self) -> dict[str, Any]:
        """Return the raw config dict."""
        return self._data
