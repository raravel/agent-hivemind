"""Unit tests for hivemind hooks (hv-pre-commit.js)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

# Resolve the JS hook file relative to the package source tree.
_HOOK_FILE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "hivemind"
    / "hooks"
    / "hv-pre-commit.js"
)


def _node_available() -> bool:
    """Return True if Node.js is available on the system."""
    return shutil.which("node") is not None


class TestHookFileExists:
    """Verify the hook JS file is present and syntactically valid."""

    def test_file_exists(self) -> None:
        assert _HOOK_FILE.exists(), f"Expected hook file at {_HOOK_FILE}"

    def test_file_is_not_empty(self) -> None:
        content = _HOOK_FILE.read_text(encoding="utf-8")
        assert len(content) > 100, "Hook file seems too short"

    def test_file_contains_expected_markers(self) -> None:
        content = _HOOK_FILE.read_text(encoding="utf-8")
        assert "tool_name" in content
        assert "git commit" in content
        assert ".hivemind-link.json" in content
        assert "additionalContext" in content

    @pytest.mark.skipif(not _node_available(), reason="node not installed")
    def test_syntax_valid(self) -> None:
        """Ask Node to parse the file (--check) without executing."""
        result = subprocess.run(
            ["node", "--check", str(_HOOK_FILE)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


def _run_hook(input_data: dict[str, Any], cwd: str | None = None) -> dict[str, Any]:
    """Run the hook JS via node and return the parsed JSON output."""
    result = subprocess.run(
        ["node", str(_HOOK_FILE)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd,
    )
    assert result.returncode == 0, f"Hook exited with {result.returncode}: {result.stderr}"
    return json.loads(result.stdout)  # type: ignore[no-any-return]


@pytest.mark.skipif(not _node_available(), reason="node not installed")
class TestHookLogic:
    """Integration tests that run the hook JS with node."""

    def test_non_bash_tool_approves(self) -> None:
        out = _run_hook({"tool_name": "Write", "tool_input": {"file_path": "x"}})
        assert out["status"] == "approve"
        assert "additionalContext" not in out

    def test_bash_without_git_commit_approves(self) -> None:
        out = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
        )
        assert out["status"] == "approve"
        assert "additionalContext" not in out

    def test_git_commit_without_link_file_approves(self, tmp_path: Path) -> None:
        # tmp_path will not contain .hivemind-link.json
        out = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'test'"}},
            cwd=str(tmp_path),
        )
        assert out["status"] == "approve"
        assert "additionalContext" not in out

    def test_git_commit_with_link_file_adds_context(self, tmp_path: Path) -> None:
        # Set up a minimal git repo so git diff --cached works
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )

        # Create a file and stage it
        (tmp_path / "hello.py").write_text("print('hi')", encoding="utf-8")
        subprocess.run(
            ["git", "add", "hello.py"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )

        # Create .hivemind-link.json
        link = {"project": "my-project"}
        (tmp_path / ".hivemind-link.json").write_text(
            json.dumps(link), encoding="utf-8"
        )

        out = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'feat'"}},
            cwd=str(tmp_path),
        )

        assert out["status"] == "approve"
        assert "additionalContext" in out
        ctx = out["additionalContext"]
        assert "my-project" in ctx
        assert "hello.py" in ctx
        assert "harness specs" in ctx

    def test_git_commit_with_no_staged_files(self, tmp_path: Path) -> None:
        # git repo with no staged files
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
        )

        link = {"project": "empty-proj"}
        (tmp_path / ".hivemind-link.json").write_text(
            json.dumps(link), encoding="utf-8"
        )

        out = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'empty'"}},
            cwd=str(tmp_path),
        )

        # No staged files, so should just approve without context
        assert out["status"] == "approve"
        assert "additionalContext" not in out

    def test_empty_stdin_approves(self) -> None:
        """If stdin is empty/malformed, hook should still approve."""
        result = subprocess.run(
            ["node", str(_HOOK_FILE)],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert out["status"] == "approve"
