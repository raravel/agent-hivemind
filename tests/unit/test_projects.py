"""Unit tests for `hv projects`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from hivemind.commands.projects import (
    _collect_rows,
    _format_table,
    projects_cmd,
)
from hivemind.core.config import HivemindConfig


def _write_config(data_path: Path, projects: dict[str, Any]) -> Path:
    data_path.mkdir(parents=True, exist_ok=True)
    cfg_path = data_path / ".hivemind.json"
    cfg_path.write_text(
        json.dumps(
            {
                "version": "5.0.0",
                "auto_commit": False,
                "projects": projects,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return cfg_path


def _linked_with_link_json(parent: Path, project: str) -> Path:
    linked = parent / project
    (linked / "hivemind" / "tasks").mkdir(parents=True)
    (linked / "hivemind" / "link.json").write_text(
        json.dumps({"project": project}), encoding="utf-8"
    )
    return linked


def _invoke(tmp_path: Path, args: list[str]) -> Any:
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(projects_cmd, args)
    finally:
        os.chdir(old_cwd)


class TestCollectRows:
    def test_linked_project_counts_tasks(self, tmp_path: Path) -> None:
        linked = _linked_with_link_json(tmp_path, "demo")
        tasks = linked / "hivemind" / "tasks"
        (tasks / "DM-001.md").write_text("body", encoding="utf-8")
        (tasks / "DM-002.md").write_text("body", encoding="utf-8")
        # Excluded: counter / index / internal files starting with "_".
        (tasks / "_counter.json").write_text("{}", encoding="utf-8")
        (tasks / "_index.json").write_text("{}", encoding="utf-8")

        _write_config(
            tmp_path,
            {"demo": {"prefix": "DM", "linked_path": str(linked)}},
        )
        cfg = HivemindConfig.load(tmp_path / ".hivemind.json")
        rows = _collect_rows(cfg)

        assert len(rows) == 1
        row = rows[0]
        assert row["name"] == "demo"
        assert row["prefix"] == "DM"
        assert row["status"] == "linked"
        assert row["tasks"] == 2

    def test_missing_linked_path_dir(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            {"ghost": {"prefix": "GH", "linked_path": str(tmp_path / "nowhere")}},
        )
        cfg = HivemindConfig.load(tmp_path / ".hivemind.json")
        rows = _collect_rows(cfg)

        assert rows[0]["status"] == "missing"
        assert rows[0]["tasks"] is None

    def test_unlinked_dir_without_link_file(self, tmp_path: Path) -> None:
        linked = tmp_path / "demo"
        linked.mkdir()
        _write_config(
            tmp_path,
            {"demo": {"prefix": "DM", "linked_path": str(linked)}},
        )
        cfg = HivemindConfig.load(tmp_path / ".hivemind.json")
        rows = _collect_rows(cfg)

        assert rows[0]["status"] == "unlinked"
        assert rows[0]["tasks"] is None

    def test_no_linked_path_field(self, tmp_path: Path) -> None:
        _write_config(tmp_path, {"weird": {"prefix": "WD"}})
        cfg = HivemindConfig.load(tmp_path / ".hivemind.json")
        rows = _collect_rows(cfg)

        assert rows[0]["status"] == "no-linked-path"
        assert rows[0]["linked_path"] is None

    def test_alphabetical_sort(self, tmp_path: Path) -> None:
        for name in ("zebra", "apple", "mango"):
            _linked_with_link_json(tmp_path, name)
        _write_config(
            tmp_path,
            {
                name: {"prefix": name[:2].upper(), "linked_path": str(tmp_path / name)}
                for name in ("zebra", "apple", "mango")
            },
        )
        cfg = HivemindConfig.load(tmp_path / ".hivemind.json")
        rows = _collect_rows(cfg)

        assert [r["name"] for r in rows] == ["apple", "mango", "zebra"]


class TestFormatTable:
    def test_empty_message(self) -> None:
        out = _format_table([])
        assert "No projects configured" in out
        assert "hv link" in out

    def test_table_has_header_and_rows(self, tmp_path: Path) -> None:
        rows = [
            {
                "name": "demo",
                "prefix": "DM",
                "linked_path": "/repos/demo",
                "status": "linked",
                "tasks": 3,
            },
            {
                "name": "ghost",
                "prefix": "GH",
                "linked_path": "/tmp/missing",
                "status": "missing",
                "tasks": None,
            },
        ]
        out = _format_table(rows)
        assert "NAME" in out
        assert "PREFIX" in out
        assert "LINKED" in out
        assert "STATUS" in out
        assert "TASKS" in out
        assert "demo" in out
        assert "ghost" in out
        # missing task counts render as "-".
        assert "-" in out


class TestCLI:
    def test_table_output(self, tmp_path: Path) -> None:
        linked = _linked_with_link_json(tmp_path, "demo")
        _write_config(
            tmp_path,
            {"demo": {"prefix": "DM", "linked_path": str(linked)}},
        )
        result = _invoke(tmp_path, [])
        assert result.exit_code == 0, result.output
        assert "NAME" in result.output
        assert "demo" in result.output
        assert "linked" in result.output

    def test_json_output(self, tmp_path: Path) -> None:
        linked = _linked_with_link_json(tmp_path, "demo")
        _write_config(
            tmp_path,
            {"demo": {"prefix": "DM", "linked_path": str(linked)}},
        )
        result = _invoke(tmp_path, ["--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["name"] == "demo"
        assert data[0]["status"] == "linked"

    def test_empty_when_no_projects(self, tmp_path: Path) -> None:
        _write_config(tmp_path, {})
        result = _invoke(tmp_path, [])
        assert result.exit_code == 0, result.output
        assert "No projects configured" in result.output

    def test_errors_without_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Push HOME so find_for_command can't fall back to a real config.
        # On Windows Path.home() reads USERPROFILE, not HOME, so we patch both.
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("USERPROFILE", str(fake_home))
        empty = tmp_path / "empty"
        empty.mkdir()
        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(empty)
            result = runner.invoke(projects_cmd, [])
        finally:
            os.chdir(old_cwd)
        assert result.exit_code != 0
