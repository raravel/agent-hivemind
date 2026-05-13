"""Unit tests for hivemind.commands.unlink."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from hivemind.commands.unlink import unlink_cmd, unlink_project


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    """Build a fully-linked project workspace.

    Returns (config_path, linked_path). The config's dirname doubles as
    ``data_path`` (v4+ convention), so level3 lives at ``tmp_path/level3/``.
    """
    linked = tmp_path / "proj"
    linked.mkdir()

    cfg = {
        "version": "5.0.0",
        "auto_commit": False,
        "projects": {
            "demo": {"prefix": "DM", "linked_path": str(linked)},
        },
    }
    config_path = tmp_path / ".hivemind.json"
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Populate in-repo hivemind/ artifacts.
    docs = linked / "hivemind" / "docs"
    docs.mkdir(parents=True)
    (docs / "architecture.md").write_text("# arch\n", encoding="utf-8")
    (docs / "rules.md").write_text("# rules\n", encoding="utf-8")
    tasks = linked / "hivemind" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "DM-001.md").write_text(
        "---\nid: DM-001\nstatus: done\n---\nbody\n", encoding="utf-8"
    )
    (tasks / "_counter.json").write_text('{"value": 1}\n', encoding="utf-8")
    (linked / "hivemind" / "link.json").write_text(
        json.dumps({"project": "demo", "prefix": "DM"}), encoding="utf-8"
    )

    # Managed CLAUDE.md / AGENTS.md.
    (linked / "CLAUDE.md").write_text(
        "# Top\n\n<!-- hivemind:start -->\n# Hivemind Project\n- project: demo\n<!-- hivemind:end -->\n\n# After\n",
        encoding="utf-8",
    )
    (linked / "AGENTS.md").write_text(
        "<!-- hivemind:start -->\n# Hivemind Project\n- project: demo\n<!-- hivemind:end -->\n",
        encoding="utf-8",
    )

    # .codex/hooks.json
    codex_dir = linked / ".codex"
    codex_dir.mkdir()
    (codex_dir / "hooks.json").write_text("{}\n", encoding="utf-8")

    # cross-project level3 (data_path = config file's parent = tmp_path)
    (tmp_path / "level3" / "demo").mkdir(parents=True)
    (tmp_path / "level3" / "demo" / "graph.json").write_text("{}\n", encoding="utf-8")

    return config_path, linked


def _invoke(tmp_path: Path, args: list[str], input: str | None = None) -> Any:
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(unlink_cmd, args, input=input)
    finally:
        os.chdir(old_cwd)


class TestUnlink:
    def test_full_unlink_with_force(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)

        result = _invoke(tmp_path, ["--project", "demo", "--force"])
        assert result.exit_code == 0, result.output

        # In-repo hivemind/ is gone.
        assert not (linked / "hivemind").exists()
        # CLAUDE.md kept user content, stripped block.
        claude = (linked / "CLAUDE.md").read_text(encoding="utf-8")
        assert "hivemind:start" not in claude
        assert "# Top" in claude
        assert "# After" in claude
        # AGENTS.md was block-only -> deleted.
        assert not (linked / "AGENTS.md").exists()
        # .codex/hooks.json + empty .codex/ dir removed.
        assert not (linked / ".codex" / "hooks.json").exists()
        assert not (linked / ".codex").exists()
        # Global config entry gone.
        cfg = json.loads((tmp_path / ".hivemind.json").read_text(encoding="utf-8"))
        assert "demo" not in cfg["projects"]
        # level3 gone.
        assert not (tmp_path / "level3" / "demo").exists()

    def test_confirmation_required_without_force(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        # Wrong confirmation answer aborts.
        result = _invoke(tmp_path, ["--project", "demo"], input="wrong\n")
        assert result.exit_code != 0
        assert "Confirmation failed" in result.output
        # Nothing was touched.
        assert (linked / "hivemind").exists()
        cfg = json.loads((tmp_path / ".hivemind.json").read_text(encoding="utf-8"))
        assert "demo" in cfg["projects"]

    def test_confirmation_accepts_matching_name(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        result = _invoke(tmp_path, ["--project", "demo"], input="demo\n")
        assert result.exit_code == 0, result.output
        assert not (linked / "hivemind").exists()

    def test_auto_detect_from_cwd(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        # Copy config into linked so find_for_command resolves there from cwd.
        (linked / ".hivemind.json").write_text(
            (tmp_path / ".hivemind.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(linked)
            result = runner.invoke(unlink_cmd, ["--force"])
        finally:
            os.chdir(old_cwd)
        assert result.exit_code == 0, result.output
        assert not (linked / "hivemind").exists()

    def test_errors_when_cwd_not_linked(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        elsewhere = tmp_path / "stranger"
        elsewhere.mkdir()
        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(elsewhere)
            # No config in this dir, no project arg → resolve to find the cwd
            # config from tmp_path? It won't — find_for_command searches cwd,
            # $HOME, canonical. With cwd at elsewhere, it falls back to canonical
            # (which doesn't exist in test). So we expect an error.
            result = runner.invoke(unlink_cmd, ["--force"])
        finally:
            os.chdir(old_cwd)
        assert result.exit_code != 0

    def test_errors_when_project_missing(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        result = _invoke(tmp_path, ["--project", "ghost", "--force"])
        assert result.exit_code != 0
        assert "not linked" in result.output or "no linked_path" in result.output

    def test_idempotent_second_run(self, tmp_path: Path) -> None:
        _config, _linked = _setup(tmp_path)
        # First run: cwd needs to be in tmp_path so find_for_command picks the
        # fixture's config (not the real one in the repo root).
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            first = unlink_project("demo", force=True)
            assert first["removed_hivemind_dir"] is True
            # Second run: the project entry is gone, so it errors cleanly.
            import click
            import pytest as _pytest

            with _pytest.raises(click.ClickException):
                unlink_project("demo", force=True)
        finally:
            os.chdir(old_cwd)

    def test_legacy_link_file_removed(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        # Remove the v5 link.json by wiping hivemind/, then plant a legacy
        # link file so the cleanup path exercises the resolve_link_file branch.
        import shutil

        shutil.rmtree(linked / "hivemind")
        (linked / ".hivemind-link.json").write_text(
            json.dumps({"project": "demo"}), encoding="utf-8"
        )
        result = _invoke(tmp_path, ["--project", "demo", "--force"])
        assert result.exit_code == 0, result.output
        assert not (linked / ".hivemind-link.json").exists()
