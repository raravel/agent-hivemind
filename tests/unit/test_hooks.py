"""Unit tests for the hivemind Python hooks (hv_pre_commit.py, hv_session_log.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


_HOOKS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "hivemind"
    / "plugin"
    / "hooks"
)

_PRE_COMMIT = _HOOKS_DIR / "hv_pre_commit.py"
_SESSION_LOG = _HOOKS_DIR / "hv_session_log.py"


class TestHookFileExists:
    """Verify the Python hook files are present and runnable."""

    def test_file_exists(self) -> None:
        assert _PRE_COMMIT.exists(), f"Expected hook file at {_PRE_COMMIT}"

    def test_file_is_not_empty(self) -> None:
        content = _PRE_COMMIT.read_text(encoding="utf-8")
        assert len(content) > 100, "Hook file seems too short"

    def test_file_contains_expected_markers(self) -> None:
        content = _PRE_COMMIT.read_text(encoding="utf-8")
        assert "tool_name" in content
        assert "git commit" in content
        assert ".hivemind-link.json" in content
        assert "additionalContext" in content

    def test_syntax_valid(self) -> None:
        """Byte-compile the hook to catch syntax errors."""
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(_PRE_COMMIT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


def _run_hook(
    script: Path,
    input_data: dict[str, Any],
    cwd: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Run a Python hook with JSON on stdin; return parsed stdout.

    *home* redirects ``~`` resolution inside the subprocess so the hook
    sees a controlled canonical-config location instead of the
    developer's real home.
    """
    import os

    env = os.environ.copy()
    if home is not None:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd,
        env=env,
    )
    assert (
        result.returncode == 0
    ), f"Hook exited with {result.returncode}: {result.stderr}"
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def _setup_canonical_data_path(home: Path) -> Path:
    """Materialize a canonical ~/agent-hivemind-data layout under *home*."""
    data_path = home / "agent-hivemind-data"
    data_path.mkdir(parents=True, exist_ok=True)
    (data_path / ".hivemind.json").write_text(
        json.dumps({"version": "4.0.0", "projects": {}}),
        encoding="utf-8",
    )
    return data_path


class TestHookLogic:
    """Integration tests that run the hook with the system Python."""

    def test_non_bash_tool_approves(self) -> None:
        out = _run_hook(
            _PRE_COMMIT, {"tool_name": "Write", "tool_input": {"file_path": "x"}}
        )
        assert out["status"] == "approve"
        assert "additionalContext" not in out

    def test_bash_without_git_commit_approves(self) -> None:
        out = _run_hook(
            _PRE_COMMIT,
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        )
        assert out["status"] == "approve"
        assert "additionalContext" not in out

    def test_git_commit_without_link_file_approves(self, tmp_path: Path) -> None:
        out = _run_hook(
            _PRE_COMMIT,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'test'"},
                "cwd": str(tmp_path),
            },
            cwd=str(tmp_path),
        )
        assert out["status"] == "approve"
        assert "additionalContext" not in out

    def test_git_commit_with_link_file_adds_context(self, tmp_path: Path) -> None:
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

        (tmp_path / "hello.py").write_text("print('hi')", encoding="utf-8")
        subprocess.run(
            ["git", "add", "hello.py"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )

        link = {"project": "my-project", "data_path": str(tmp_path)}
        (tmp_path / ".hivemind-link.json").write_text(
            json.dumps(link), encoding="utf-8"
        )

        out = _run_hook(
            _PRE_COMMIT,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'feat'"},
                "cwd": str(tmp_path),
            },
            cwd=str(tmp_path),
        )

        assert out["status"] == "approve"
        assert "additionalContext" in out
        ctx = out["additionalContext"]
        assert "my-project" in ctx
        assert "hello.py" in ctx
        assert "harness specs" in ctx

    def test_git_commit_with_no_staged_files(self, tmp_path: Path) -> None:
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
        )

        link = {"project": "empty-proj", "data_path": str(tmp_path)}
        (tmp_path / ".hivemind-link.json").write_text(
            json.dumps(link), encoding="utf-8"
        )

        out = _run_hook(
            _PRE_COMMIT,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'empty'"},
                "cwd": str(tmp_path),
            },
            cwd=str(tmp_path),
        )

        assert out["status"] == "approve"
        assert "additionalContext" not in out

    def test_empty_stdin_approves(self) -> None:
        """If stdin is empty/malformed, hook should still approve."""
        result = subprocess.run(
            [sys.executable, str(_PRE_COMMIT)],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert out["status"] == "approve"


class TestSessionLogHook:
    """Tests for the PreCompact / Stop session log hook."""

    def test_syntax_valid(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(_SESSION_LOG)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr

    def test_no_link_file_approves(self, tmp_path: Path) -> None:
        out = _run_hook(
            _SESSION_LOG,
            {
                "hook_event_name": "Stop",
                "session_id": "sess-00000001",
                "cwd": str(tmp_path),
                "last_assistant_message": "done",
            },
            cwd=str(tmp_path),
        )
        assert out["status"] == "approve"

    def test_stop_event_writes_l3(self, tmp_path: Path) -> None:
        data_path = _setup_canonical_data_path(tmp_path)
        project_dir = tmp_path / "myproj"
        project_dir.mkdir()
        (project_dir / ".hivemind-link.json").write_text(
            json.dumps({"project": "demo", "prefix": "DEM"}),
            encoding="utf-8",
        )

        out = _run_hook(
            _SESSION_LOG,
            {
                "hook_event_name": "Stop",
                "session_id": "abcdef1234567890",
                "cwd": str(project_dir),
                "last_assistant_message": "Here is my final answer.",
            },
            cwd=str(project_dir),
            home=tmp_path,
        )
        assert out["status"] == "approve"

        log_dir = data_path / "level3" / "demo"
        assert log_dir.exists()
        files = list(log_dir.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "Session end" in content
        assert "Here is my final answer." in content

    def test_user_prompt_submit_writes_l3(self, tmp_path: Path) -> None:
        data_path = _setup_canonical_data_path(tmp_path)
        project_dir = tmp_path / "myproj"
        project_dir.mkdir()
        (project_dir / ".hivemind-link.json").write_text(
            json.dumps({"project": "demo", "prefix": "DEM"}),
            encoding="utf-8",
        )

        out = _run_hook(
            _SESSION_LOG,
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "abcdef1234567890",
                "cwd": str(project_dir),
                "user_prompt": "please implement the next task",
            },
            cwd=str(project_dir),
            home=tmp_path,
        )
        assert out["status"] == "approve"

        files = list((data_path / "level3" / "demo").glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "User prompt" in content
        assert "please implement the next task" in content

    def test_windows_path_fallback(self, tmp_path: Path) -> None:
        """Windows-style data_path in legacy global config falls back on POSIX."""
        if sys.platform == "win32":
            pytest.skip("not applicable on Windows")

        data_path = _setup_canonical_data_path(tmp_path)
        # Replace the canonical config with a v3-shaped one that points
        # at a foreign Windows path; hook should ignore it and write
        # under the canonical default instead.
        (data_path / ".hivemind.json").write_text(
            json.dumps(
                {
                    "version": "3.0.0",
                    "data_path": "C:\\Users\\foreign\\agent-hivemind-data",
                    "projects": {},
                }
            ),
            encoding="utf-8",
        )
        project_dir = tmp_path / "myproj"
        project_dir.mkdir()
        (project_dir / ".hivemind-link.json").write_text(
            json.dumps({"project": "demo", "prefix": "DEM"}),
            encoding="utf-8",
        )

        out = _run_hook(
            _SESSION_LOG,
            {
                "hook_event_name": "Stop",
                "session_id": "win-test-001",
                "cwd": str(project_dir),
                "last_assistant_message": "ok",
            },
            cwd=str(project_dir),
            home=tmp_path,
        )
        assert out["status"] == "approve"
        # Hook fell back to canonical ~/agent-hivemind-data (= tmp_path/agent-hivemind-data)
        log_dir = data_path / "level3" / "demo"
        assert log_dir.exists()
