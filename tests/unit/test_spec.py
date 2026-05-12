"""Unit tests for hivemind.commands.spec."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from hivemind.commands.spec import spec


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    """Create a workspace with a registered project.

    Returns (config_path, linked_path).
    """
    data = tmp_path / "data"
    data.mkdir()
    linked = tmp_path / "proj"
    linked.mkdir()
    cfg = {
        "version": "5.0.0",
        "projects": {
            "demo": {"prefix": "DM", "linked_path": str(linked)},
        },
    }
    config_path = tmp_path / ".hivemind.json"
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return config_path, linked


def _invoke(tmp_path: Path, args: list[str], input_text: str | None = None) -> Any:
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(spec, args, input=input_text)
    finally:
        os.chdir(old_cwd)


class TestSpecWrite:
    def test_write_canonical_name(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        result = _invoke(
            tmp_path,
            ["write", "tech-stack", "-p", "demo"],
            input_text="## Active Dependencies\n- foo 1.0\n",
        )
        assert result.exit_code == 0, result.output
        target = linked / "hivemind" / "docs" / "tech-stack.md"
        assert target.exists()
        assert "Active Dependencies" in target.read_text(encoding="utf-8")
        assert str(target) in result.output

    def test_write_from_content_file(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        body = tmp_path / "body.txt"
        body.write_text("# arch\n", encoding="utf-8")
        result = _invoke(
            tmp_path,
            ["write", "architecture", "-p", "demo", "-c", str(body)],
        )
        assert result.exit_code == 0, result.output
        target = linked / "hivemind" / "docs" / "architecture.md"
        assert target.read_text(encoding="utf-8") == "# arch\n"

    def test_write_features_slug_auto_numbers(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        result = _invoke(
            tmp_path,
            ["write", "features/multi-assign", "-p", "demo"],
            input_text="# feature body\n",
        )
        assert result.exit_code == 0, result.output
        features = linked / "hivemind" / "docs" / "features"
        files = sorted(p.name for p in features.glob("*.md"))
        assert files == ["01_multi-assign.md"]

    def test_write_features_keeps_existing_number(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        features = linked / "hivemind" / "docs" / "features"
        features.mkdir(parents=True)
        (features / "00_multi-assign.md").write_text("old\n", encoding="utf-8")

        result = _invoke(
            tmp_path,
            ["write", "features/multi-assign", "-p", "demo"],
            input_text="new content\n",
        )
        assert result.exit_code == 0, result.output
        assert (features / "00_multi-assign.md").read_text(encoding="utf-8") == "new content\n"

    def test_write_rejects_empty_content(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        result = _invoke(
            tmp_path, ["write", "rules", "-p", "demo"], input_text="   \n"
        )
        assert result.exit_code != 0
        assert "Empty content" in result.output

    def test_write_atomic_no_partial_on_replace(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        target = linked / "hivemind" / "docs" / "rules.md"
        target.parent.mkdir(parents=True)
        target.write_text("OLD\n", encoding="utf-8")

        result = _invoke(
            tmp_path, ["write", "rules", "-p", "demo"], input_text="NEW\n"
        )
        assert result.exit_code == 0, result.output
        assert target.read_text(encoding="utf-8") == "NEW\n"

    def test_write_resolves_project_from_cwd(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(linked)  # cwd matches linked_path
            (linked / ".hivemind.json").write_text(
                (tmp_path / ".hivemind.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            result = runner.invoke(spec, ["write", "rules"], input="hello\n")
        finally:
            os.chdir(old_cwd)
        assert result.exit_code == 0, result.output
        assert (linked / "hivemind" / "docs" / "rules.md").exists()


class TestSpecList:
    def test_lists_files_recursively(self, tmp_path: Path) -> None:
        _config, linked = _setup(tmp_path)
        docs = linked / "hivemind" / "docs"
        docs.mkdir(parents=True)
        (docs / "rules.md").write_text("r", encoding="utf-8")
        (docs / "features").mkdir()
        (docs / "features" / "00_foo.md").write_text("f", encoding="utf-8")

        result = _invoke(tmp_path, ["list", "-p", "demo"])
        assert result.exit_code == 0, result.output
        assert "rules.md" in result.output
        assert "features/00_foo.md" in result.output.replace(os.sep, "/")

    def test_list_reports_no_specs(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        result = _invoke(tmp_path, ["list", "-p", "demo"])
        assert result.exit_code == 0
        assert "No specs found" in result.output
