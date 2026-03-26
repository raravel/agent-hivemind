"""Profile installer — ensures default model profiles exist in .hivemind.json."""

from __future__ import annotations

from pathlib import Path

from hivemind.core.config import HivemindConfig, default_config


def install_profiles(config_path: Path) -> bool:
    """Ensure default model profiles exist in the given ``.hivemind.json``.

    Reads the config at *config_path*.  If a ``profiles`` key is already
    present and non-empty the function returns ``False`` (no change).
    Otherwise the three default profiles (quality / balanced / budget) are
    written and the file is saved.

    Parameters
    ----------
    config_path:
        Path to an existing ``.hivemind.json`` file.

    Returns
    -------
    bool
        ``True`` if default profiles were added, ``False`` if they already
        existed.
    """
    cfg = HivemindConfig.load(config_path)

    existing_profiles = cfg.get("profiles")
    if isinstance(existing_profiles, dict) and existing_profiles:
        return False

    defaults = default_config()
    cfg.set("profiles", defaults["profiles"])
    cfg.save()
    return True
