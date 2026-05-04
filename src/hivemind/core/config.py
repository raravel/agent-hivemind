"""Config management for .hivemind.json (v4 schema).

v4 invariant: the global config lives at ``<data_path>/.hivemind.json``.
``data_path`` is derived from the config file's parent directory and is
no longer persisted as a top-level field. Legacy v3 files (with a
``data_path`` field at the top level) continue to load — the field is
simply ignored by the runtime — but ``hv migrate --to v4`` is the
intended path to refresh them.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

CONFIG_FILENAME = ".hivemind.json"
DEFAULT_DATA_PATH = "~/agent-hivemind-data"
SCHEMA_VERSION = "4.0.0"
SUPPORTED_TARGETS = ("claude", "codex")

# Per-Mtoken USD pricing, seeded from public Anthropic pricing. Users may
# override in .hivemind.json; values are cents-level estimates.
CLAUDE_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.8, "output": 4.0},
}
CODEX_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.2-codex": {"input": 1.75, "output": 14.0},
    "gpt-5.1-codex": {"input": 1.25, "output": 10.0},
    "codex-mini-latest": {"input": 1.5, "output": 6.0},
}
# Backward-compatible alias for older imports.
DEFAULT_PRICING = copy.deepcopy(CLAUDE_DEFAULT_PRICING)

CLAUDE_DEFAULT_PROFILES: dict[str, dict[str, str]] = {
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
}
CODEX_DEFAULT_PROFILES: dict[str, dict[str, str]] = {
    "quality": {
        "planner": "gpt-5.2-codex",
        "executor": "gpt-5.2-codex",
        "reviewer": "gpt-5.2-codex",
    },
    "balanced": {
        "planner": "gpt-5.2-codex",
        "executor": "gpt-5.1-codex",
        "reviewer": "gpt-5.1-codex",
    },
    "budget": {
        "planner": "gpt-5.1-codex",
        "executor": "codex-mini-latest",
        "reviewer": "codex-mini-latest",
    },
}


def default_runtime_models() -> dict[str, dict[str, Any]]:
    """Return runtime-scoped profile/pricing defaults."""
    return {
        "claude": {
            "model_profile": "balanced",
            "profiles": copy.deepcopy(CLAUDE_DEFAULT_PROFILES),
            "pricing": copy.deepcopy(CLAUDE_DEFAULT_PRICING),
        },
        "codex": {
            "model_profile": "balanced",
            "profiles": copy.deepcopy(CODEX_DEFAULT_PROFILES),
            "pricing": copy.deepcopy(CODEX_DEFAULT_PRICING),
        },
    }


def expand_target_selection(target: str) -> list[str]:
    """Expand a target selector into concrete runtime targets."""
    if target == "both":
        return list(SUPPORTED_TARGETS)
    if target in SUPPORTED_TARGETS:
        return [target]
    raise ValueError(f"Unsupported target: {target}")


def default_config() -> dict[str, Any]:
    """Return default v4 config dict (no top-level data_path)."""
    return {
        "version": SCHEMA_VERSION,
        "git_enabled": False,
        "auto_commit": False,
        "model_profile": "balanced",
        "profiles": copy.deepcopy(CLAUDE_DEFAULT_PROFILES),
        "pricing": copy.deepcopy(CLAUDE_DEFAULT_PRICING),
        "parallel": {"max_concurrency": 2},
        "projects": {},
        "filter_patterns": [],
        "runtime": {
            "default_target": "claude",
            "enabled_targets": ["claude"],
        },
        "runtime_models": default_runtime_models(),
    }


def default_config_path() -> Path:
    """Return the canonical global config path.

    Always ``<DEFAULT_DATA_PATH>/.hivemind.json``. v4 dropped the legacy
    finder candidates (``cwd/.hivemind.json``, ``~/.hivemind.json``) so
    every caller resolves to the same on-disk location.
    """
    return Path(DEFAULT_DATA_PATH).expanduser() / CONFIG_FILENAME


def data_path_for_storage(p: Path | str) -> str:
    """Normalize a path for cross-platform storage in JSON.

    Used by migration tooling and link/instruction writers that still
    need to record an absolute path in committed files. The runtime
    config no longer stores ``data_path``.
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
    """Resolve a stored ``data_path`` value (legacy/migration helper).

    Reads from legacy v3 ``.hivemind.json`` snapshots or from
    ``.hivemind-link.json`` files written before the v4 schema migration
    landed. Falls back to ``~/agent-hivemind-data`` when *raw* is empty
    or carries a foreign-platform path. New runtime code should use
    :pyattr:`HivemindConfig.data_path` instead.
    """
    default = Path(DEFAULT_DATA_PATH).expanduser().resolve()
    if not raw:
        return default
    s = str(raw)
    if _looks_like_foreign_windows(s):
        return default
    return Path(s).expanduser().resolve()


class HivemindConfig:
    """Reads and writes ``.hivemind.json``.

    Under the v4 schema the data directory is the parent of the config
    file. Callers should resolve the global config via
    :pymeth:`load_global` and read paths from
    :pyattr:`data_path`/:pyattr:`path`.
    """

    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self._path = Path(path).expanduser().resolve()
        self._data = data

    @staticmethod
    def load(path: Path | str) -> HivemindConfig:
        """Load config from a ``.hivemind.json`` file path."""
        resolved = Path(path).expanduser().resolve()
        with resolved.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        return HivemindConfig(resolved, data)

    @staticmethod
    def load_global() -> HivemindConfig:
        """Load the global config from the canonical location.

        Triggers an idempotent v3 → v4 migration on first read after
        upgrade so existing installations stay functional without
        requiring an explicit ``hv migrate --to v4`` step. Raises
        :class:`FileNotFoundError` when the config does not exist; CLI
        commands should translate this into a user-facing error pointing
        at ``hv init``.
        """
        path = default_config_path()
        if not path.exists():
            raise FileNotFoundError(
                f"No hivemind config at {path}. Run `hv init` first."
            )
        # Local import: core.migration depends on core.config helpers.
        from hivemind.core.migration import migrate_v3_to_v4

        migrate_v3_to_v4(path)
        return HivemindConfig.load(path)

    @staticmethod
    def find_for_command() -> HivemindConfig:
        """Locate the config for a CLI command and return it loaded.

        Searches ``cwd/.hivemind.json``, ``~/.hivemind.json``, and the
        canonical ``~/agent-hivemind-data/.hivemind.json`` in that
        order. The auto v3 → v4 migration only runs when the chosen
        path is the canonical one — non-canonical layouts (cwd or HOME
        root) require an explicit ``hv migrate --to v4`` to opt in,
        which keeps v3-shaped test fixtures and one-off ad-hoc configs
        from being rewritten on every CLI invocation. Raises
        :class:`FileNotFoundError` when no candidate exists.

        The non-canonical candidates are deprecated transitional
        fallbacks; they will be retired once tests move to the
        canonical layout.
        """
        canonical = default_config_path()
        candidates = [
            Path.cwd() / CONFIG_FILENAME,
            Path("~/" + CONFIG_FILENAME).expanduser(),
            canonical,
        ]
        for candidate in candidates:
            if candidate.exists():
                if candidate.resolve() == canonical.resolve():
                    from hivemind.core.migration import migrate_v3_to_v4

                    migrate_v3_to_v4(candidate)
                return HivemindConfig.load(candidate)
        raise FileNotFoundError(
            f"No {CONFIG_FILENAME} found. Run `hv init` first."
        )

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
        """Add or update a project entry.

        Note: ``prefix`` is still accepted for backward compatibility
        during the v3→v4 migration window. Step 3 of the schema cleanup
        will move ``prefix`` into ``.hivemind-link.json`` and drop it
        from this signature.
        """
        if "projects" not in self._data or not isinstance(
            self._data["projects"], dict
        ):
            self._data["projects"] = {}
        self._data["projects"][name] = {
            "prefix": prefix,
            "linked_path": linked_path,
        }

    def set_runtime_targets(
        self,
        *,
        default_target: str,
        enabled_targets: list[str],
    ) -> None:
        """Persist runtime target defaults in config."""
        runtime = self._data.setdefault("runtime", {})
        if not isinstance(runtime, dict):
            runtime = {}
            self._data["runtime"] = runtime
        runtime["default_target"] = default_target
        runtime["enabled_targets"] = enabled_targets

    def ensure_runtime_models(self) -> bool:
        """Ensure runtime-scoped profiles/pricing catalogs exist."""
        changed = False
        defaults = default_runtime_models()
        runtime_models = self._data.get("runtime_models")
        if not isinstance(runtime_models, dict):
            runtime_models = {}
            self._data["runtime_models"] = runtime_models
            changed = True

        for target, target_defaults in defaults.items():
            existing = runtime_models.get(target)
            if not isinstance(existing, dict):
                runtime_models[target] = target_defaults
                changed = True
                continue
            for key, value in target_defaults.items():
                if key not in existing or not isinstance(existing[key], type(value)):
                    existing[key] = value
                    changed = True
        return changed

    @property
    def path(self) -> Path:
        """Return the resolved config file path."""
        return self._path

    @property
    def data_path(self) -> Path:
        """Return the data directory.

        Under v4 this is the config file's parent directory. During the
        v3 → v4 transition, a legacy top-level ``data_path`` field still
        wins when present so existing installations and v3-shaped test
        fixtures keep working. ``hv migrate --to v4`` drops the field
        once the on-disk layout matches ``<data_path>/.hivemind.json``.
        """
        raw = self._data.get("data_path")
        if isinstance(raw, str) and raw:
            return normalize_data_path(raw)
        return self._path.parent

    @property
    def default_target(self) -> str:
        """Return the configured default runtime target."""
        runtime = self._data.get("runtime")
        if isinstance(runtime, dict):
            value = runtime.get("default_target")
            if isinstance(value, str) and value in SUPPORTED_TARGETS:
                return value
        return "claude"

    @property
    def enabled_targets(self) -> list[str]:
        """Return configured runtime targets, defaulting to Claude only."""
        runtime = self._data.get("runtime")
        if isinstance(runtime, dict):
            raw = runtime.get("enabled_targets")
            if isinstance(raw, list):
                values = [
                    item
                    for item in raw
                    if isinstance(item, str) and item in SUPPORTED_TARGETS
                ]
                if values:
                    return values
        return [self.default_target]

    def runtime_model_profile(self, target: str | None = None) -> str:
        """Return the selected profile for a target runtime."""
        selected = target or self.default_target
        runtime_models = self._data.get("runtime_models")
        if isinstance(runtime_models, dict):
            raw = runtime_models.get(selected)
            if isinstance(raw, dict):
                value = raw.get("model_profile")
                if isinstance(value, str):
                    return value
        value = self._data.get("model_profile")
        return value if isinstance(value, str) else "balanced"

    def runtime_profiles(self, target: str | None = None) -> dict[str, Any]:
        """Return role profiles for a target runtime."""
        selected = target or self.default_target
        runtime_models = self._data.get("runtime_models")
        if isinstance(runtime_models, dict):
            raw = runtime_models.get(selected)
            if isinstance(raw, dict):
                profiles = raw.get("profiles")
                if isinstance(profiles, dict) and profiles:
                    return profiles
        profiles = self._data.get("profiles")
        return profiles if isinstance(profiles, dict) else {}

    def runtime_pricing(self, target: str | None = None) -> dict[str, Any]:
        """Return pricing map for a target runtime."""
        selected = target or self.default_target
        runtime_models = self._data.get("runtime_models")
        if isinstance(runtime_models, dict):
            raw = runtime_models.get(selected)
            if isinstance(raw, dict):
                pricing = raw.get("pricing")
                if isinstance(pricing, dict) and pricing:
                    return pricing
        pricing = self._data.get("pricing")
        return pricing if isinstance(pricing, dict) else {}

    def set_runtime_model_profile(
        self, profile_name: str, target: str | None = None
    ) -> None:
        """Set the selected profile for a target runtime."""
        selected = target or self.default_target
        self.ensure_runtime_models()
        self.set(f"runtime_models.{selected}.model_profile", profile_name)
        if selected == "claude":
            self.set("model_profile", profile_name)

    def set_runtime_profiles(
        self, profiles: dict[str, Any], target: str | None = None
    ) -> None:
        """Set the profile map for a target runtime."""
        selected = target or self.default_target
        self.ensure_runtime_models()
        self.set(f"runtime_models.{selected}.profiles", profiles)
        if selected == "claude":
            self.set("profiles", profiles)

    def set_runtime_pricing(
        self, pricing: dict[str, Any], target: str | None = None
    ) -> None:
        """Set the pricing map for a target runtime."""
        selected = target or self.default_target
        self.ensure_runtime_models()
        self.set(f"runtime_models.{selected}.pricing", pricing)
        if selected == "claude":
            self.set("pricing", pricing)

    def runtime_profile(
        self,
        profile_name: str | None = None,
        *,
        target: str | None = None,
    ) -> dict[str, Any]:
        """Return one named profile for the selected runtime."""
        resolved_profile = profile_name or self.runtime_model_profile(target)
        profile = self.runtime_profiles(target).get(resolved_profile)
        return profile if isinstance(profile, dict) else {}

    @property
    def raw(self) -> dict[str, Any]:
        """Return the raw config dict."""
        return self._data
