"""Unit tests for hivemind.core.links_relative — task body link rewriter."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from hivemind.core.links_relative import rewrite_body


# ---------------------------------------------------------------------------
# v4 path rewrite (projects/{project}/...)
# ---------------------------------------------------------------------------


def test_rewrites_v4_architecture_in_task_body() -> None:
    body = "Read `projects/agent-cli/architecture.md` for context.\n"
    new, count = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    assert "`../docs/architecture.md`" in new
    assert "projects/agent-cli" not in new
    assert count >= 1


def test_rewrites_v4_feature_path() -> None:
    body = "See `projects/agent-cli/features/39_verify_runner_powershell.md` — spec.\n"
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-410.md"),
        project="agent-cli",
    )
    assert "`../docs/features/39_verify_runner_powershell.md`" in new
    assert "projects/agent-cli" not in new


def test_rewrites_v5_root_relative_to_file_relative() -> None:
    body = "Linked: `hivemind/docs/features/00_x.md`.\n"
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    assert "`../docs/features/00_x.md`" in new
    assert "hivemind/docs/" not in new


def test_handles_nested_reports_subdir() -> None:
    body = "Spec: `projects/agent-cli/architecture.md`.\n"
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/_reports/AGE-001-report.md"),
        project="agent-cli",
    )
    assert "`../../docs/architecture.md`" in new


def test_docs_self_reference_uses_dot_prefix() -> None:
    # When the file is itself inside docs/, references to peers should be local.
    body = "Related: `projects/agent-cli/rules.md`.\n"
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("docs/architecture.md"),
        project="agent-cli",
    )
    assert "`rules.md`" in new
    assert "projects/" not in new


def test_docs_feature_to_root_uses_parent() -> None:
    body = "See `projects/agent-cli/architecture.md`.\n"
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("docs/features/01_auth.md"),
        project="agent-cli",
    )
    assert "`../architecture.md`" in new


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_rewrite_is_idempotent() -> None:
    body = "Spec: `projects/agent-cli/architecture.md`.\n"
    once, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    twice, count = rewrite_body(
        once,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    assert twice == once
    assert count == 0


# ---------------------------------------------------------------------------
# Wikilink prepend inside ## Spec References
# ---------------------------------------------------------------------------


def test_prepends_wikilink_for_root_doc_inside_spec_section() -> None:
    body = (
        "## Spec References\n"
        "- `projects/agent-cli/architecture.md` — module boundaries\n"
        "\n## Completion Criteria\n"
    )
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    assert "- [[architecture]] `../docs/architecture.md` — module boundaries" in new


def test_prepends_wikilink_for_feature_with_alias() -> None:
    body = (
        "## Spec References\n"
        "- `projects/agent-cli/features/01_auth.md` — authentication spec\n"
    )
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    assert "- [[features/01_auth|01_auth]] `../docs/features/01_auth.md` — authentication spec" in new


def test_does_not_prepend_wikilink_outside_spec_section() -> None:
    body = (
        "## Description\n"
        "See `projects/agent-cli/architecture.md` for context.\n"
        "\n## Completion Criteria\n"
        "- [ ] All commands in `projects/agent-cli/verify.md` pass\n"
    )
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    # Path is rewritten but no wikilink is added
    assert "`../docs/architecture.md`" in new
    assert "[[architecture]]" not in new
    assert "`../docs/verify.md`" in new


def test_wikilink_prepend_is_idempotent() -> None:
    body = (
        "## Spec References\n"
        "- [[architecture]] `../docs/architecture.md` — module boundaries\n"
    )
    new, count = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    # No double wikilink
    assert new.count("[[architecture]]") == 1
    assert count == 0


def test_preserves_non_spec_backticks() -> None:
    body = "Use `Callable[[int], None]` in the signature.\n"
    new, count = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    assert new == body
    assert count == 0


def test_handles_build_verify_legacy_name() -> None:
    body = "Run `projects/agent-cli/build-verify.md` commands.\n"
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    # Path is rewritten but filename is preserved (no rename here — out of scope).
    assert "`../docs/build-verify.md`" in new


def test_only_rewrites_matching_project_name() -> None:
    # Mentions of an unrelated project should be left alone.
    body = "See `projects/other-project/architecture.md`.\n"
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    assert new == body


def test_spec_section_with_blank_lines_between_items() -> None:
    body = (
        "## Spec References\n"
        "\n"
        "- `projects/agent-cli/architecture.md` — one\n"
        "- `projects/agent-cli/features/00_x.md` — two\n"
    )
    new, _ = rewrite_body(
        body,
        rel_from_hivemind=PurePosixPath("tasks/AGE-001.md"),
        project="agent-cli",
    )
    assert "[[architecture]]" in new
    assert "[[features/00_x|00_x]]" in new
