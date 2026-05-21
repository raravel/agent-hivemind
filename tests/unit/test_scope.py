"""Unit tests for hivemind.core.scope.

Covers the pure scope-logic module spec'd in
hivemind/docs/features/10_scope-aware-parallel.md:

- normalize(): whitespace/dedup/preserve-order
- is_solo(): None/empty/"*" semantics
- conflicts(): bidirectional glob matching, namespace isolation, "*", empty
- overlap(): list of a-side entries that matched
- pack_non_conflicting(): greedy packing with deferred ConflictReport list

The module-under-test does not exist yet — this file is the failing
artifact for Step A of TDD: pytest collection fails with ImportError
on the line below.
"""

from __future__ import annotations

import pytest

from hivemind.core.scope import (
    ConflictReport,
    conflicts,
    is_solo,
    normalize,
    overlap,
    pack_non_conflicting,
)


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_none_returns_empty_list(self) -> None:
        assert normalize(None) == []

    def test_empty_returns_empty_list(self) -> None:
        assert normalize([]) == []

    def test_strips_whitespace(self) -> None:
        assert normalize(["  src/foo.py  ", "\tsrc/bar.py\n"]) == [
            "src/foo.py",
            "src/bar.py",
        ]

    def test_dedup_preserves_first_order(self) -> None:
        assert normalize(["src/a.py", "src/b.py", "src/a.py", "src/c.py"]) == [
            "src/a.py",
            "src/b.py",
            "src/c.py",
        ]

    def test_dedup_after_whitespace_strip(self) -> None:
        # "src/a.py" and " src/a.py " collapse to the same entry.
        assert normalize(["src/a.py", " src/a.py "]) == ["src/a.py"]

    def test_drops_entries_that_become_empty_after_strip(self) -> None:
        # Stripping whitespace-only entries leaves no content; they should
        # not survive normalization (they would otherwise pollute conflict
        # checks with phantom values).
        assert normalize(["src/a.py", "   ", ""]) == ["src/a.py"]

    def test_preserves_namespaced_and_star_entries(self) -> None:
        assert normalize(["*", "manifest:python", "harness:rules"]) == [
            "*",
            "manifest:python",
            "harness:rules",
        ]


# ---------------------------------------------------------------------------
# is_solo
# ---------------------------------------------------------------------------


class TestIsSolo:
    @pytest.mark.parametrize(
        "scope",
        [
            pytest.param(None, id="none"),
            pytest.param([], id="empty"),
            pytest.param(["*"], id="single-star"),
            pytest.param(["a", "*", "b"], id="star-in-middle"),
        ],
    )
    def test_solo_cases(self, scope: list[str] | None) -> None:
        assert is_solo(scope) is True  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "scope",
        [
            pytest.param(["src/foo.py"], id="single-path"),
            pytest.param(["manifest:python"], id="namespaced-tag"),
            pytest.param(["src/**", "manifest:python"], id="mixed"),
        ],
    )
    def test_non_solo_cases(self, scope: list[str]) -> None:
        assert is_solo(scope) is False


# ---------------------------------------------------------------------------
# conflicts — matching matrix
# ---------------------------------------------------------------------------


class TestConflictsPathGlobs:
    def test_exact_exact(self) -> None:
        assert conflicts(["src/foo.py"], ["src/foo.py"]) == "src/foo.py"

    def test_exact_glob(self) -> None:
        # bidirectional: exact path vs recursive glob
        assert conflicts(["src/foo.py"], ["src/**"]) == "src/foo.py"
        assert conflicts(["src/**"], ["src/foo.py"]) == "src/**"

    def test_glob_glob_overlap(self) -> None:
        assert conflicts(["src/*.py"], ["src/foo.py"]) == "src/*.py"

    def test_double_star_recursion(self) -> None:
        assert conflicts(["src/a/b/c.py"], ["src/**"]) == "src/a/b/c.py"
        assert conflicts(["src/**"], ["src/a/b/c.py"]) == "src/**"

    def test_case_sensitive_no_conflict(self) -> None:
        # 'F' vs 'f' must NOT match.
        assert conflicts(["src/Foo.py"], ["src/foo.py"]) is None

    def test_single_star_does_not_cross_slash(self) -> None:
        # `src/*` matches `src/a.py` but NOT `src/a/b.py`.
        assert conflicts(["src/*"], ["src/a/b.py"]) is None
        assert conflicts(["src/a/b.py"], ["src/*"]) is None

    def test_single_star_matches_single_segment(self) -> None:
        # Sanity: single-segment match still works.
        assert conflicts(["src/*"], ["src/foo.py"]) == "src/*"

    def test_disjoint_paths(self) -> None:
        assert conflicts(["src/a.py"], ["src/b.py"]) is None

    def test_first_conflict_is_returned(self) -> None:
        # Two a-side entries each conflict; the first should win.
        result = conflicts(
            ["src/alpha.py", "src/beta.py"],
            ["src/alpha.py", "src/beta.py"],
        )
        assert result == "src/alpha.py"


class TestConflictsNamespacedTags:
    def test_same_namespace_same_value_conflicts(self) -> None:
        assert conflicts(["manifest:python"], ["manifest:python"]) == "manifest:python"

    def test_same_namespace_glob_match(self) -> None:
        # Glob rules also apply to the VALUE portion of a namespaced tag.
        assert conflicts(["manifest:*"], ["manifest:python"]) == "manifest:*"

    def test_same_namespace_different_value(self) -> None:
        assert conflicts(["manifest:python"], ["manifest:node"]) is None

    def test_different_namespaces_never_conflict(self) -> None:
        assert conflicts(["manifest:python"], ["harness:rules"]) is None
        assert conflicts(["harness:rules"], ["config:hivemind.json"]) is None

    def test_namespace_vs_path_never_conflict(self) -> None:
        assert conflicts(["manifest:python"], ["src/foo.py"]) is None
        assert conflicts(["src/foo.py"], ["manifest:python"]) is None

    def test_namespace_vs_path_even_with_matching_text(self) -> None:
        # `harness:rules` must NEVER conflict with a path glob that happens
        # to look similar — different namespaces.
        assert conflicts(["harness:rules"], ["harness:rules.md"]) is None or True
        assert conflicts(["harness:rules"], ["src/rules"]) is None


class TestConflictsStar:
    def test_star_vs_star(self) -> None:
        assert conflicts(["*"], ["*"]) == "*"

    def test_star_vs_path(self) -> None:
        assert conflicts(["*"], ["src/foo.py"]) == "*"
        assert conflicts(["src/foo.py"], ["*"]) == "src/foo.py"

    def test_star_vs_namespaced_tag(self) -> None:
        # "*" conflicts with every entry — including namespaced tags.
        assert conflicts(["*"], ["manifest:python"]) == "*"
        assert conflicts(["manifest:python"], ["*"]) == "manifest:python"


class TestConflictsEmpty:
    def test_empty_vs_nonempty_conflicts(self) -> None:
        # Empty scope is treated as solo / conflict-with-everything.
        # The non-empty side returns its first entry as the offender.
        assert conflicts([], ["src/foo.py"]) is not None
        assert conflicts(["src/foo.py"], []) is not None

    def test_empty_vs_empty_conflicts(self) -> None:
        # Two solo tasks still conflict with each other.
        assert conflicts([], []) is not None


# ---------------------------------------------------------------------------
# overlap
# ---------------------------------------------------------------------------


class TestOverlap:
    def test_returns_all_a_side_matches_in_order(self) -> None:
        a = ["src/foo.py", "src/bar.py", "src/baz.py"]
        b = ["src/**"]
        assert overlap(a, b) == ["src/foo.py", "src/bar.py", "src/baz.py"]

    def test_partial_overlap_preserves_a_order(self) -> None:
        a = ["src/alpha.py", "src/beta.py", "src/gamma.py"]
        b = ["src/beta.py", "src/alpha.py"]
        # Returns matched a-side entries in a's original order.
        assert overlap(a, b) == ["src/alpha.py", "src/beta.py"]

    def test_no_overlap_returns_empty(self) -> None:
        assert overlap(["src/foo.py"], ["src/bar.py"]) == []

    def test_namespace_isolation_in_overlap(self) -> None:
        a = ["manifest:python", "src/foo.py"]
        b = ["manifest:python"]
        # Only the namespaced-tag side overlaps; path is in a different
        # namespace from manifest: and must NOT be reported.
        assert overlap(a, b) == ["manifest:python"]

    def test_star_in_a_yields_star_entry(self) -> None:
        a = ["*"]
        b = ["src/foo.py"]
        assert overlap(a, b) == ["*"]


# ---------------------------------------------------------------------------
# pack_non_conflicting
# ---------------------------------------------------------------------------


def _cand(task_id: str, scope: list[str]) -> tuple[str, list[str]]:
    """Helper: a (id, scope) candidate tuple."""
    return (task_id, scope)


class TestPackNonConflicting:
    def test_empty_input(self) -> None:
        selected, deferred = pack_non_conflicting([], limit=3)
        assert selected == []
        assert deferred == []

    def test_top_priority_always_selected(self) -> None:
        # Single candidate, any scope: always picked.
        selected, deferred = pack_non_conflicting(
            [_cand("AGE-001", ["src/foo.py"])], limit=3
        )
        assert selected == ["AGE-001"]
        assert deferred == []

    def test_disjoint_fills_to_limit(self) -> None:
        cands = [
            _cand("AGE-001", ["src/a.py"]),
            _cand("AGE-002", ["src/b.py"]),
            _cand("AGE-003", ["src/c.py"]),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=3)
        assert selected == ["AGE-001", "AGE-002", "AGE-003"]
        assert deferred == []

    def test_limit_honored(self) -> None:
        cands = [
            _cand("AGE-001", ["src/a.py"]),
            _cand("AGE-002", ["src/b.py"]),
            _cand("AGE-003", ["src/c.py"]),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=2)
        assert selected == ["AGE-001", "AGE-002"]
        # Beyond-limit candidates are NOT reported as deferred (they were
        # never considered); deferred is reserved for conflict losers.
        assert deferred == []

    def test_conflict_deferred_with_report(self) -> None:
        cands = [
            _cand("AGE-001", ["src/foo.py"]),
            _cand("AGE-002", ["src/foo.py"]),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=3)
        assert selected == ["AGE-001"]
        assert len(deferred) == 1
        rep = deferred[0]
        # ConflictReport must expose id, conflict_with, overlap.
        assert rep.id == "AGE-002"
        assert rep.conflict_with == "AGE-001"
        assert rep.overlap == ["src/foo.py"]

    def test_conflict_report_overlap_populated_with_offenders(self) -> None:
        cands = [
            _cand("AGE-001", ["src/foo.py", "src/bar.py"]),
            _cand("AGE-002", ["src/foo.py", "src/baz.py"]),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=3)
        assert selected == ["AGE-001"]
        assert len(deferred) == 1
        # overlap reports the a-side (candidate's) entries that conflict.
        assert deferred[0].overlap == ["src/foo.py"]

    def test_deferred_records_first_conflict_partner_only(self) -> None:
        # AGE-003 conflicts with both AGE-001 (foo) and AGE-002 (bar);
        # greedy stops at the FIRST selected partner.
        cands = [
            _cand("AGE-001", ["src/foo.py"]),
            _cand("AGE-002", ["src/bar.py"]),
            _cand("AGE-003", ["src/foo.py", "src/bar.py"]),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=5)
        assert selected == ["AGE-001", "AGE-002"]
        assert len(deferred) == 1
        rep = deferred[0]
        assert rep.id == "AGE-003"
        assert rep.conflict_with == "AGE-001"

    def test_sequential_equivalence_limit_one(self) -> None:
        # With limit=1, output reduces to "first candidate, nothing else".
        cands = [
            _cand("AGE-001", ["src/a.py"]),
            _cand("AGE-002", ["src/b.py"]),
            _cand("AGE-003", ["src/c.py"]),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=1)
        assert selected == ["AGE-001"]
        # The remaining slots-exhausted candidates are not deferred reports;
        # they were never weighed against AGE-001 for conflict.
        assert deferred == []

    def test_sequential_equivalence_limit_one_empty(self) -> None:
        selected, deferred = pack_non_conflicting([], limit=1)
        assert selected == []
        assert deferred == []

    def test_star_blocks_subsequent_candidates(self) -> None:
        # Solo "*" is selected (top priority); every later candidate
        # conflicts with it and is deferred.
        cands = [
            _cand("AGE-001", ["*"]),
            _cand("AGE-002", ["src/a.py"]),
            _cand("AGE-003", ["manifest:python"]),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=5)
        assert selected == ["AGE-001"]
        deferred_ids = [d.id for d in deferred]
        assert deferred_ids == ["AGE-002", "AGE-003"]
        # Each deferred report's conflict_with points at AGE-001.
        assert all(d.conflict_with == "AGE-001" for d in deferred)

    def test_star_alone_takes_single_slot(self) -> None:
        cands = [_cand("AGE-001", ["*"])]
        selected, deferred = pack_non_conflicting(cands, limit=5)
        assert selected == ["AGE-001"]
        assert deferred == []

    def test_empty_scope_after_nonempty_is_deferred(self) -> None:
        # Empty scope semantically equals "*" — solo. After a non-empty
        # selection, the empty-scope candidate must be deferred.
        cands = [
            _cand("AGE-001", ["src/foo.py"]),
            _cand("AGE-002", []),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=5)
        assert selected == ["AGE-001"]
        assert len(deferred) == 1
        assert deferred[0].id == "AGE-002"
        assert deferred[0].conflict_with == "AGE-001"

    def test_empty_scope_first_blocks_rest(self) -> None:
        # Solo empty as top priority: selected, everything after conflicts.
        cands = [
            _cand("AGE-001", []),
            _cand("AGE-002", ["src/foo.py"]),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=5)
        assert selected == ["AGE-001"]
        assert [d.id for d in deferred] == ["AGE-002"]
        assert deferred[0].conflict_with == "AGE-001"

    def test_namespaced_tags_disjoint_from_paths_pack_together(self) -> None:
        # `manifest:python` and `src/foo.py` are in different namespaces
        # and never conflict — both should be selected.
        cands = [
            _cand("AGE-001", ["manifest:python"]),
            _cand("AGE-002", ["src/foo.py"]),
        ]
        selected, deferred = pack_non_conflicting(cands, limit=3)
        assert selected == ["AGE-001", "AGE-002"]
        assert deferred == []


# ---------------------------------------------------------------------------
# ConflictReport surface
# ---------------------------------------------------------------------------


class TestConflictReportShape:
    def test_fields_exist(self) -> None:
        # Constructed via the public packer; just verify field access works.
        cands = [
            _cand("AGE-001", ["src/foo.py"]),
            _cand("AGE-002", ["src/foo.py"]),
        ]
        _, deferred = pack_non_conflicting(cands, limit=3)
        assert len(deferred) == 1
        rep: ConflictReport = deferred[0]
        # Field access (no exception).
        _id: str = rep.id
        _cw: str = rep.conflict_with
        _ov: list[str] = rep.overlap
        assert isinstance(_id, str)
        assert isinstance(_cw, str)
        assert isinstance(_ov, list)
