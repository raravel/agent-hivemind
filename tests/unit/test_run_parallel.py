"""Unit tests for `hv run --ready-only` packing + JSON object output.

These tests target the new contract introduced by AGE-005-07ca:

1. ``hv run --ready-only --format json`` returns a JSON OBJECT with
   ``"tasks"`` (the selected, non-conflicting batch) and ``"deferred"``
   (per-candidate :class:`ConflictReport` dicts) — no longer a bare
   array.
2. The selection step runs every ready candidate through
   :func:`hivemind.core.scope.pack_non_conflicting`, so wide-scope and
   empty-scope tasks force their lower-priority peers to be deferred,
   and disjoint scopes ride together.
3. ``--limit N`` caps how many candidates are *weighed* for the batch —
   any beyond ``N`` are simply not considered (not deferred), matching
   the ``pack_non_conflicting`` contract.

Step A of the two-step protocol: these tests intentionally fail today
because ``commands/run.py`` still emits a bare list and does not import
the packer. The implementation lands in step B.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from hivemind.commands.run import run
from hivemind.commands.task import task


def _make_workspace(
    tmp_path: Path,
    projects: dict[str, dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    """Create a minimal workspace with .hivemind.json and tasks dir."""
    data_path = tmp_path / "data"
    data_path.mkdir(exist_ok=True)
    (data_path / "tasks").mkdir(exist_ok=True)

    if projects is None:
        projects = {
            "myproj": {
                "prefix": "MP",
                "linked_path": str(tmp_path),
                "counter": 0,
            }
        }

    config_data = {
        "version": "3.0.0",
        "data_path": str(data_path),
        "projects": projects,
    }

    config_path = tmp_path / ".hivemind.json"
    config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    return config_path, data_path


def _invoke_task(tmp_path: Path, args: list[str]) -> Any:
    """Invoke the task CLI in tmp_path context."""
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(task, args)
    finally:
        os.chdir(old_cwd)


def _invoke_run(tmp_path: Path, args: list[str]) -> Any:
    """Invoke the run CLI in tmp_path context."""
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        return runner.invoke(run, args)
    finally:
        os.chdir(old_cwd)


def _create(tmp_path: Path, args: list[str]) -> Any:
    """Shorthand: invoke `hv task create -p myproj ...`."""
    result = _invoke_task(tmp_path, ["create", "-p", "myproj", *args])
    assert result.exit_code == 0, result.output
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestJsonObjectShape:
    """The new contract: JSON object with `tasks` + `deferred` keys."""

    def test_json_shape_has_tasks_and_deferred_keys(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _create(tmp_path, ["-t", "Alpha", "--priority", "high", "--scope", "src/a.py"])
        _create(tmp_path, ["-t", "Beta", "--priority", "high", "--scope", "src/b.py"])

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        assert isinstance(data, dict), "Expected JSON object, got: " + type(data).__name__
        assert "tasks" in data
        assert "deferred" in data
        assert isinstance(data["tasks"], list)
        assert isinstance(data["deferred"], list)
        assert len(data["tasks"]) == 2
        assert data["deferred"] == []


class TestWideScopeDefersOthers:
    """A wide-scope (`*`) top-priority task forces every peer to defer."""

    def test_wide_scope_top_priority_defers_others(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        # Highest-priority wide-scope task — created last so we control the ID.
        _create(tmp_path, ["-t", "Wide", "--priority", "high", "--scope", "*"])
        # Lower-priority disjoint peers
        _create(tmp_path, ["-t", "T-a", "--priority", "medium", "--scope", "src/a.py"])
        _create(tmp_path, ["-t", "T-b", "--priority", "medium", "--scope", "src/b.py"])
        _create(tmp_path, ["-t", "T-c", "--priority", "medium", "--scope", "src/c.py"])
        _create(tmp_path, ["-t", "T-d", "--priority", "medium", "--scope", "src/d.py"])

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        assert len(data["tasks"]) == 1
        wide_id = data["tasks"][0]["id"]
        assert data["tasks"][0]["frontmatter"]["title"] == "Wide"

        assert len(data["deferred"]) == 4
        for entry in data["deferred"]:
            assert "id" in entry
            assert entry["reason"] == "scope conflict"
            assert entry["conflict_with"] == wide_id
            assert isinstance(entry["overlap"], list)
            assert len(entry["overlap"]) >= 1


class TestDisjointScopesAllSelected:
    """Pairwise-disjoint scopes ride together."""

    def test_three_disjoint_all_selected(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _create(tmp_path, ["-t", "A", "--priority", "high", "--scope", "src/a.py"])
        _create(tmp_path, ["-t", "B", "--priority", "high", "--scope", "src/b.py"])
        _create(tmp_path, ["-t", "C", "--priority", "high", "--scope", "src/c.py"])

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        assert len(data["tasks"]) == 3
        assert data["deferred"] == []


class TestPriorityPreserved:
    """Selection order in `tasks` follows priority order from the scanner."""

    def test_priority_preserved_in_selection(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        # Create out of priority order to prove the sort happens.
        _create(tmp_path, ["-t", "Mid", "--priority", "medium", "--scope", "src/m.py"])
        _create(tmp_path, ["-t", "Low", "--priority", "low", "--scope", "src/l.py"])
        _create(tmp_path, ["-t", "High", "--priority", "high", "--scope", "src/h.py"])

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        titles = [t["frontmatter"]["title"] for t in data["tasks"]]
        assert titles == ["High", "Mid", "Low"]


class TestLimitSlotFill:
    """`--limit N` caps consideration to N candidates — extras aren't deferred."""

    def test_slot_filling_with_limit(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        # Distinct priorities to nail down ordering. Disjoint scopes so nothing
        # would conflict anyway — limit alone is what cuts the list.
        _create(tmp_path, ["-t", "T1", "--priority", "high", "--scope", "src/1.py"])
        _create(tmp_path, ["-t", "T2", "--priority", "high", "--scope", "src/2.py"])
        _create(tmp_path, ["-t", "T3", "--priority", "medium", "--scope", "src/3.py"])
        _create(tmp_path, ["-t", "T4", "--priority", "medium", "--scope", "src/4.py"])
        _create(tmp_path, ["-t", "T5", "--priority", "low", "--scope", "src/5.py"])

        result = _invoke_run(
            tmp_path, ["--ready-only", "--limit", "2", "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        assert len(data["tasks"]) == 2
        # Candidates beyond the limit are not weighed → no deferred entries.
        assert data["deferred"] == []
        # Top-two priority tasks selected.
        titles = sorted(t["frontmatter"]["title"] for t in data["tasks"])
        assert titles == ["T1", "T2"]


class TestDeferredFields:
    """Deferred entries carry `conflict_with` and `overlap`."""

    def test_deferred_records_conflict_with_and_overlap(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        # Same scope, both ready. Higher priority wins.
        _create(
            tmp_path,
            ["-t", "First", "--priority", "high", "--scope", "src/shared.py"],
        )
        _create(
            tmp_path,
            ["-t", "Second", "--priority", "medium", "--scope", "src/shared.py"],
        )

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        assert len(data["tasks"]) == 1
        first_id = data["tasks"][0]["id"]
        assert data["tasks"][0]["frontmatter"]["title"] == "First"

        assert len(data["deferred"]) == 1
        deferred = data["deferred"][0]
        assert deferred["reason"] == "scope conflict"
        assert deferred["conflict_with"] == first_id
        assert deferred["overlap"] == ["src/shared.py"]


class TestEmptyScopeSolo:
    """Empty scope behaves like `["*"]` — conflicts with everything."""

    def test_empty_scope_forces_solo(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        # No --scope arg ⇒ frontmatter has no scope key ⇒ treated as solo.
        _create(tmp_path, ["-t", "Solo-A", "--priority", "high"])
        _create(tmp_path, ["-t", "Solo-B", "--priority", "medium"])

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["frontmatter"]["title"] == "Solo-A"
        first_id = data["tasks"][0]["id"]

        assert len(data["deferred"]) == 1
        deferred = data["deferred"][0]
        assert deferred["reason"] == "scope conflict"
        assert deferred["conflict_with"] == first_id

    def test_empty_scope_picked_as_first_only(self, tmp_path: Path) -> None:
        """Empty-scope task in the middle of the queue gets deferred but
        does not poison later disjoint candidates (packing checks selected
        peers only)."""
        _make_workspace(tmp_path)
        # Priority order: First > Middle > Last (creation order is monotonic
        # for the secondary `created` tiebreak).
        _create(tmp_path, ["-t", "First", "--priority", "high", "--scope", "src/x.py"])
        _create(tmp_path, ["-t", "Middle", "--priority", "medium"])  # empty scope
        _create(tmp_path, ["-t", "Last", "--priority", "low", "--scope", "src/y.py"])

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        # First (src/x.py) + Last (src/y.py) ride together; Middle (empty)
        # conflicts with First and is deferred.
        assert len(data["tasks"]) == 2
        titles = [t["frontmatter"]["title"] for t in data["tasks"]]
        assert titles == ["First", "Last"]

        assert len(data["deferred"]) == 1
        deferred = data["deferred"][0]
        assert deferred["reason"] == "scope conflict"
        # Middle's conflict_with is First (the first selected peer it hits).
        first_id = data["tasks"][0]["id"]
        assert deferred["conflict_with"] == first_id


class TestTextFormatDeferred:
    """Default text output lists deferred ids on stderr so humans see them."""

    def test_text_format_lists_deferred_on_stderr(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _create(
            tmp_path,
            ["-t", "Winner", "--priority", "high", "--scope", "src/shared.py"],
        )
        _create(
            tmp_path,
            ["-t", "Loser", "--priority", "medium", "--scope", "src/shared.py"],
        )

        runner = CliRunner()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(run, ["--ready-only"])
        finally:
            os.chdir(old_cwd)
        assert result.exit_code == 0, result.output

        # The deferred loser's id should appear on stderr; stdout should
        # carry the selected `Winner` line.
        stderr = result.stderr
        assert "MP-002" in stderr or "Loser" in stderr, (
            f"Expected deferred task on stderr; got stderr={stderr!r} "
            f"stdout={result.stdout!r}"
        )


class TestDefaultNoLimitStillPacks:
    """No `--limit` still applies packing — packing isn't gated on the flag."""

    def test_default_no_limit_still_packs(self, tmp_path: Path) -> None:
        _make_workspace(tmp_path)
        _create(
            tmp_path,
            ["-t", "T1", "--priority", "high", "--scope", "src/shared.py"],
        )
        _create(
            tmp_path,
            ["-t", "T2", "--priority", "medium", "--scope", "src/shared.py"],
        )
        _create(
            tmp_path,
            ["-t", "T3", "--priority", "low", "--scope", "src/shared.py"],
        )

        result = _invoke_run(tmp_path, ["--ready-only", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["frontmatter"]["title"] == "T1"
        assert len(data["deferred"]) == 2
        deferred_titles = sorted(
            entry["id"] for entry in data["deferred"]
        )
        # Both losers carry their own id and the same conflict_with.
        winner_id = data["tasks"][0]["id"]
        for entry in data["deferred"]:
            assert entry["conflict_with"] == winner_id
            assert entry["reason"] == "scope conflict"
            assert entry["overlap"] == ["src/shared.py"]
        # Sanity: deferred ids are distinct and not the winner.
        assert winner_id not in deferred_titles
        assert len(set(deferred_titles)) == 2
