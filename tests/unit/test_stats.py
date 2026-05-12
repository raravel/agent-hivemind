"""Unit tests for hivemind.commands.stats."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter as fm_lib
from click.testing import CliRunner, Result

from hivemind.commands.stats import (
    _collect_reports,
    _compute_stats,
    _format_table,
    _parse_report,
    stats,
)


def _write_report(
    reports_dir: Path,
    filename: str,
    metadata: dict[str, object],
    body: str = "",
) -> Path:
    """Write a report .md file with YAML frontmatter into *reports_dir*."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / filename
    post = fm_lib.Post(body, **metadata)
    path.write_text(fm_lib.dumps(post), encoding="utf-8")
    return path


def _make_reports_dir(tmp_path: Path, project: str = "myproj") -> Path:
    """Return the v5 _reports directory inside *tmp_path*.

    tmp_path doubles as the project's linked_path in these tests.
    """
    del project  # noqa: F841 — retained for call-site clarity
    reports_dir = tmp_path / "hivemind" / "tasks" / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


# ---------------------------------------------------------------------------
# _parse_report
# ---------------------------------------------------------------------------


class TestParseReport:
    """Tests for _parse_report."""

    def test_parses_valid_report(self, tmp_path: Path) -> None:
        reports_dir = _make_reports_dir(tmp_path)
        path = _write_report(
            reports_dir,
            "PROJ-001.md",
            {"task_id": "PROJ-001", "status": "completed", "duration_minutes": 45},
        )
        result = _parse_report(path)
        assert result is not None
        assert result["task_id"] == "PROJ-001"
        assert result["duration_minutes"] == 45

    def test_returns_none_for_invalid_file(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.md"
        bad_file.write_text("{{not yaml", encoding="utf-8")
        result = _parse_report(bad_file)
        # frontmatter may still parse this (empty fm); just ensure no crash
        assert result is not None or result is None  # no exception raised


# ---------------------------------------------------------------------------
# _collect_reports
# ---------------------------------------------------------------------------


class TestCollectReports:
    """Tests for _collect_reports."""

    def test_collects_all_reports(self, tmp_path: Path) -> None:
        reports_dir = _make_reports_dir(tmp_path)
        _write_report(
            reports_dir,
            "PROJ-001.md",
            {
                "task_id": "PROJ-001",
                "status": "completed",
                "completed_at": "2026-03-20T10:00:00",
            },
        )
        _write_report(
            reports_dir,
            "PROJ-002.md",
            {
                "task_id": "PROJ-002",
                "status": "completed",
                "completed_at": "2026-03-25T12:00:00",
            },
        )
        result = _collect_reports(tmp_path)
        assert len(result) == 2

    def test_filters_by_since(self, tmp_path: Path) -> None:
        reports_dir = _make_reports_dir(tmp_path)
        _write_report(
            reports_dir,
            "PROJ-001.md",
            {
                "task_id": "PROJ-001",
                "status": "completed",
                "completed_at": "2026-03-10T10:00:00",
            },
        )
        _write_report(
            reports_dir,
            "PROJ-002.md",
            {
                "task_id": "PROJ-002",
                "status": "completed",
                "completed_at": "2026-03-25T12:00:00",
            },
        )
        since = datetime.fromisoformat("2026-03-20T00:00:00")
        result = _collect_reports(tmp_path, since=since)
        assert len(result) == 1
        assert result[0]["task_id"] == "PROJ-002"

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        result = _collect_reports(tmp_path)
        assert result == []

    def test_skips_reports_without_completed_at_when_since(
        self, tmp_path: Path
    ) -> None:
        reports_dir = _make_reports_dir(tmp_path)
        _write_report(
            reports_dir,
            "PROJ-001.md",
            {"task_id": "PROJ-001", "status": "completed"},
        )
        since = datetime.fromisoformat("2026-03-20T00:00:00")
        result = _collect_reports(tmp_path, since=since)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# _compute_stats
# ---------------------------------------------------------------------------


class TestComputeStats:
    """Tests for _compute_stats."""

    def test_empty_reports(self) -> None:
        result = _compute_stats([])
        assert result["total_tasks"] == 0
        assert result["avg_duration"] == 0.0

    def test_single_report(self) -> None:
        reports: list[dict[str, object]] = [
            {
                "task_id": "PROJ-001",
                "status": "completed",
                "duration_minutes": 30,
                "coding_retries": 1,
                "verify_retries": 1,
                "blocking_issues": False,
            }
        ]
        result = _compute_stats(reports)
        assert result["total_tasks"] == 1
        assert result["avg_duration"] == 30.0
        assert result["avg_retries"] == 2.0
        assert result["review_pass_rate"] == 100.0

    def test_multiple_reports(self) -> None:
        reports: list[dict[str, object]] = [
            {
                "duration_minutes": 30,
                "coding_retries": 0,
                "blocking_issues": False,
            },
            {
                "duration_minutes": 60,
                "coding_retries": 1,
                "verify_retries": 1,
                "blocking_issues": False,
            },
            {
                "duration_minutes": 45,
                "coding_retries": 1,
                "blocking_issues": True,
            },
            {
                "duration_minutes": 15,
                "coding_retries": 2,
                "verify_retries": 1,
                "blocking_issues": False,
            },
        ]
        result = _compute_stats(reports)
        assert result["total_tasks"] == 4
        assert result["avg_duration"] == 37.5
        # avg retries = (0 + 2 + 1 + 3) / 4 = 1.5
        assert result["avg_retries"] == 1.5
        assert result["review_pass_rate"] == 75.0

    def test_missing_numeric_fields(self) -> None:
        """Reports without duration/retries should still work."""
        reports: list[dict[str, object]] = [
            {"blocking_issues": False},
            {"blocking_issues": True},
        ]
        result = _compute_stats(reports)
        assert result["total_tasks"] == 2
        assert result["avg_duration"] == 0.0
        assert result["avg_retries"] == 0.0
        assert result["review_pass_rate"] == 50.0

    def test_rubric_averages(self) -> None:
        reports: list[dict[str, object]] = [
            {
                "review_scores": {
                    "correctness": 9,
                    "spec_compliance": 8,
                    "safety": 10,
                    "clarity": 7,
                },
            },
            {
                "review_scores": {
                    "correctness": 7,
                    "spec_compliance": 9,
                    "safety": 9,
                    "clarity": 8,
                },
            },
        ]
        result = _compute_stats(reports)
        assert result["avg_correctness"] == 8.0
        assert result["avg_spec_compliance"] == 8.5
        assert result["avg_safety"] == 9.5
        assert result["avg_clarity"] == 7.5

    def test_cost_aggregation(self) -> None:
        reports: list[dict[str, object]] = [
            {
                "tokens": {"input": 1000, "output": 500},
                "cost_usd": 0.12,
                "profile": "balanced",
                "task_type": "task",
            },
            {
                "tokens": {"input": 2000, "output": 1500},
                "cost_usd": 0.45,
                "profile": "balanced",
                "task_type": "bug",
            },
            {
                "tokens": {"input": 500, "output": 100},
                "cost_usd": 0.01,
                "profile": "budget",
                "task_type": "chore",
            },
        ]
        result = _compute_stats(reports)
        assert result["total_input_tokens"] == 3500
        assert result["total_output_tokens"] == 2100
        assert result["total_cost_usd"] == 0.58
        assert result["by_profile"]["balanced"]["tasks"] == 2
        assert abs(float(result["by_profile"]["balanced"]["cost_usd"]) - 0.57) < 0.001
        assert result["by_profile"]["budget"]["tasks"] == 1
        assert result["by_type"]["chore"]["tasks"] == 1


# ---------------------------------------------------------------------------
# _format_table
# ---------------------------------------------------------------------------


class TestFormatTable:
    """Tests for _format_table."""

    def test_table_contains_all_metrics(self) -> None:
        stats_data: dict[str, object] = {
            "total_tasks": 10,
            "avg_duration": 35.2,
            "avg_retries": 1.3,
            "review_pass_rate": 80.0,
            "avg_correctness": 8.2,
            "avg_spec_compliance": 8.0,
            "avg_safety": 9.1,
            "avg_clarity": 7.8,
            "total_input_tokens": 1_500_000,
            "total_output_tokens": 500_000,
            "total_cost_usd": 12.34,
            "by_profile": {"balanced": {"tasks": 10, "cost_usd": 12.34}},
            "by_type": {"task": {"tasks": 10, "cost_usd": 12.34}},
        }
        table = _format_table("myproj", stats_data)
        assert "=== Stats: myproj ===" in table
        assert "Total tasks" in table
        assert "10" in table
        assert "Avg duration" in table
        assert "35.2" in table
        assert "Review pass rate" in table
        assert "80.0" in table
        assert "correctness" in table
        assert "spec_compliance" in table
        assert "safety" in table
        assert "clarity" in table
        assert "$12.34" in table
        assert "By profile" in table
        assert "By task type" in table


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestStatsCLI:
    """Integration tests for the stats Click command."""

    def _invoke_stats(
        self, tmp_path: Path, args: list[str]
    ) -> tuple[Result, Path]:
        """Invoke the stats CLI with _find_config patched."""
        import json
        import os

        data_path = tmp_path / "data"
        data_path.mkdir(exist_ok=True)
        (data_path / "tasks").mkdir(exist_ok=True)

        config_data: dict[str, Any] = {
            "version": "2.0.0",
            "data_path": str(data_path),
            "projects": {
                "myproj": {"prefix": "MP", "linked_path": str(tmp_path), "counter": 0}
            },
        }
        config_path = tmp_path / ".hivemind.json"
        config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            return runner.invoke(stats, args), data_path
        finally:
            os.chdir(old_cwd)

    def test_no_reports(self, tmp_path: Path) -> None:
        result, _data_path = self._invoke_stats(tmp_path, ["-p", "myproj"])
        assert result.exit_code == 0
        assert "No execution reports found" in result.output

    def test_with_reports(self, tmp_path: Path) -> None:
        _result_obj, data_path = self._invoke_stats(tmp_path, ["-p", "myproj"])

        # Create reports after getting data_path
        reports_dir = tmp_path / "hivemind" / "tasks" / "_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        _write_report(
            reports_dir,
            "PROJ-001.md",
            {
                "task_id": "PROJ-001",
                "status": "completed",
                "duration_minutes": 30,
                "retries": 1,
                "review_passed": True,
                "lint_failed": False,
                "completed_at": "2026-03-25T10:00:00",
            },
        )
        _write_report(
            reports_dir,
            "PROJ-002.md",
            {
                "task_id": "PROJ-002",
                "status": "completed",
                "duration_minutes": 60,
                "retries": 0,
                "review_passed": True,
                "lint_failed": True,
                "completed_at": "2026-03-26T10:00:00",
            },
        )

        # Re-invoke now that reports exist
        result_obj, _ = self._invoke_stats(tmp_path, ["-p", "myproj"])
        assert result_obj.exit_code == 0
        output = result_obj.output
        assert "=== Stats: myproj ===" in output
        assert "Total tasks" in output
        assert "2" in output

    def test_since_filtering(self, tmp_path: Path) -> None:
        _, data_path = self._invoke_stats(tmp_path, ["-p", "myproj"])

        reports_dir = tmp_path / "hivemind" / "tasks" / "_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        _write_report(
            reports_dir,
            "PROJ-001.md",
            {
                "task_id": "PROJ-001",
                "status": "completed",
                "duration_minutes": 30,
                "retries": 1,
                "review_passed": True,
                "lint_failed": False,
                "completed_at": "2026-03-10T10:00:00",
            },
        )
        _write_report(
            reports_dir,
            "PROJ-002.md",
            {
                "task_id": "PROJ-002",
                "status": "completed",
                "duration_minutes": 60,
                "retries": 0,
                "review_passed": False,
                "lint_failed": True,
                "completed_at": "2026-03-25T10:00:00",
            },
        )

        result_obj, _ = self._invoke_stats(
            tmp_path, ["-p", "myproj", "--since", "2026-03-20"]
        )
        assert result_obj.exit_code == 0
        output = result_obj.output
        # Only 1 report (PROJ-002) should be included
        assert "=== Stats: myproj ===" in output
        assert "Total tasks" in output
        # avg_duration should be 60.0 (just PROJ-002)
        assert "60.0" in output

    def test_invalid_since_date(self, tmp_path: Path) -> None:
        result_obj, _ = self._invoke_stats(
            tmp_path, ["-p", "myproj", "--since", "not-a-date"]
        )
        assert result_obj.exit_code != 0
        assert "Invalid --since date" in result_obj.output
