"""Unit tests for harness quality storage + freshness logic."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hivemind.core.harness_quality import (
    RUBRIC_VERSION,
    AxisScore,
    HarnessScore,
    append_score,
    build_score_from_payload,
    hash_harness,
    is_fresh,
    latest_score,
    load_scores,
    scores_path,
)


def _write_harness(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "architecture.md").write_text("# Arch\n", encoding="utf-8")
    (spec_dir / "rules.md").write_text("NEVER foo\n", encoding="utf-8")
    (spec_dir / "verify.md").write_text("pytest\n", encoding="utf-8")
    (spec_dir / "tech-stack.md").write_text("fastapi 0.100\n", encoding="utf-8")
    features = spec_dir / "features"
    features.mkdir(exist_ok=True)
    (features / "00_login.md").write_text("## Inputs\n## Outputs\n", encoding="utf-8")


class TestHashHarness:
    def test_deterministic(self, tmp_path: Path) -> None:
        spec = tmp_path / "projects" / "demo"
        _write_harness(spec)
        h1 = hash_harness(spec)
        h2 = hash_harness(spec)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_changes_when_content_changes(self, tmp_path: Path) -> None:
        spec = tmp_path / "projects" / "demo"
        _write_harness(spec)
        before = hash_harness(spec)
        (spec / "rules.md").write_text("NEVER foo\nALWAYS bar\n", encoding="utf-8")
        after = hash_harness(spec)
        assert before != after

    def test_stable_across_feature_order(self, tmp_path: Path) -> None:
        spec = tmp_path / "projects" / "demo"
        _write_harness(spec)
        h1 = hash_harness(spec)
        # Add files in "wrong" order — hash should still be stable because we
        # sort features before hashing
        (spec / "features" / "01_logout.md").write_text("...", encoding="utf-8")
        (spec / "features" / "02_admin.md").write_text("...", encoding="utf-8")
        h2 = hash_harness(spec)
        h3 = hash_harness(spec)
        assert h2 == h3
        assert h2 != h1  # different content => different hash

    def test_missing_files_ok(self, tmp_path: Path) -> None:
        spec = tmp_path / "projects" / "empty"
        spec.mkdir(parents=True)
        h = hash_harness(spec)
        assert h.startswith("sha256:")


class TestBuildScoreFromPayload:
    def test_valid_payload(self) -> None:
        payload = {
            "axes": {
                "architecture": {"score": 8, "rationale": "ok", "recommendations": []},
                "specs_detail": {"score": 6, "rationale": "mid", "recommendations": ["x"]},
            }
        }
        s = build_score_from_payload(payload, hash_str="sha256:x", model="m")
        assert s.overall == 14
        assert s.overall_max == 20
        assert s.model == "m"
        assert s.hash == "sha256:x"
        assert s.rubric_version == RUBRIC_VERSION

    def test_missing_axes_raises(self) -> None:
        with pytest.raises(ValueError, match="axes"):
            build_score_from_payload({}, hash_str="x", model="m")

    def test_missing_score_in_axis_raises(self) -> None:
        with pytest.raises(ValueError, match="score"):
            build_score_from_payload(
                {"axes": {"architecture": {"rationale": "oops"}}},
                hash_str="x",
                model="m",
            )

    def test_custom_max_score_preserved(self) -> None:
        payload = {
            "axes": {
                "custom": {"score": 3, "max_score": 5, "rationale": "r"},
            }
        }
        s = build_score_from_payload(payload, hash_str="h", model="m")
        assert s.overall == 3
        assert s.overall_max == 5


class TestAppendLoad:
    def test_append_and_reload(self, tmp_path: Path) -> None:
        data_path = tmp_path
        spec = tmp_path / "projects" / "demo"
        _write_harness(spec)
        payload = {"axes": {"architecture": {"score": 8, "rationale": "ok"}}}
        s = build_score_from_payload(payload, hash_str="sha256:a", model="m")
        append_score(data_path, "demo", s)
        loaded = load_scores(data_path, "demo")
        assert len(loaded) == 1
        assert loaded[0].overall == 8

    def test_multiple_entries_preserve_order(self, tmp_path: Path) -> None:
        data_path = tmp_path
        spec = tmp_path / "projects" / "demo"
        _write_harness(spec)
        for i in range(3):
            s = build_score_from_payload(
                {"axes": {"architecture": {"score": i, "rationale": "r"}}},
                hash_str=f"sha256:{i}",
                model="m",
            )
            append_score(data_path, "demo", s)
        loaded = load_scores(data_path, "demo")
        assert [s.overall for s in loaded] == [0, 1, 2]

    def test_malformed_line_skipped(self, tmp_path: Path) -> None:
        data_path = tmp_path
        path = scores_path(data_path, "demo")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"timestamp":"t","hash":"h","rubric_version":1,"model":"m","axes":{"a":{"score":5}},"overall":5,"overall_max":10}\n'
            "{{not json\n"
            '{"timestamp":"t2","hash":"h2","rubric_version":1,"model":"m","axes":{"a":{"score":7}},"overall":7,"overall_max":10}\n',
            encoding="utf-8",
        )
        loaded = load_scores(data_path, "demo")
        assert [s.overall for s in loaded] == [5, 7]

    def test_latest_on_empty(self, tmp_path: Path) -> None:
        assert latest_score(tmp_path, "nope") is None


class TestIsFresh:
    def _make(self, *, hash_str: str = "h", rubric: int = RUBRIC_VERSION, ts: str | None = None) -> HarnessScore:
        return HarnessScore(
            timestamp=ts or datetime.now().isoformat(timespec="seconds"),
            hash=hash_str,
            rubric_version=rubric,
            model="m",
            axes={"a": AxisScore(score=5)},
            overall=5,
            overall_max=10,
        )

    def test_fresh_when_recent_same_hash(self) -> None:
        s = self._make()
        assert is_fresh(s, current_hash="h", max_age=timedelta(days=7))

    def test_stale_when_hash_differs(self) -> None:
        s = self._make(hash_str="old")
        assert not is_fresh(s, current_hash="new", max_age=timedelta(days=7))

    def test_stale_when_rubric_version_differs(self) -> None:
        s = self._make(rubric=RUBRIC_VERSION - 1)
        assert not is_fresh(s, current_hash="h", max_age=timedelta(days=7))

    def test_stale_when_too_old(self) -> None:
        # timestamp 10 days ago, max_age 7 days
        ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        s = self._make(ts=ts)
        assert not is_fresh(s, current_hash="h", max_age=timedelta(days=7))

    def test_none_is_not_fresh(self) -> None:
        assert not is_fresh(None, current_hash="h", max_age=timedelta(days=7))

    def test_malformed_timestamp_is_not_fresh(self) -> None:
        s = self._make(ts="not-a-date")
        assert not is_fresh(s, current_hash="h", max_age=timedelta(days=7))


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


from click.testing import CliRunner  # noqa: E402

from hivemind.commands.harness_score import harness_score_cmd  # noqa: E402


def _setup_workspace(tmp_path: Path, project: str = "demo") -> tuple[Path, Path]:
    data_path = tmp_path / "data"
    data_path.mkdir()
    for d in ("projects", "tasks", "level1", "level2", "level3"):
        (data_path / d).mkdir()
    spec = data_path / "projects" / project
    _write_harness(spec)
    cfg = {
        "version": "3.0.0",
        "data_path": str(data_path),
        "model_profile": "balanced",
        "profiles": {
            "balanced": {
                "planner": "claude-opus-4-7",
                "executor": "claude-sonnet-4-6",
                "reviewer": "claude-sonnet-4-6",
            }
        },
        "projects": {project: {"prefix": "DM", "linked_path": str(tmp_path)}},
    }
    (tmp_path / ".hivemind.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8"
    )
    return data_path, spec


class TestCLIRecord:
    def test_record_from_stdin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        data_path, _ = _setup_workspace(tmp_path)
        payload = {
            "axes": {
                "architecture": {"score": 8, "rationale": "ok", "recommendations": []},
                "specs_detail": {"score": 6, "rationale": "mid", "recommendations": []},
                "rules_clarity": {"score": 9, "rationale": "g", "recommendations": []},
                "tech_stack": {"score": 5, "rationale": "eh", "recommendations": []},
                "verification": {"score": 7, "rationale": "k", "recommendations": []},
            }
        }
        runner = CliRunner()
        result = runner.invoke(
            harness_score_cmd,
            ["record", "-p", "demo", "--from-stdin"],
            input=json.dumps(payload),
        )
        assert result.exit_code == 0, result.output
        assert "Recorded" in result.output
        # Verify persistence
        loaded = load_scores(data_path, "demo")
        assert len(loaded) == 1
        assert loaded[0].overall == 35
        # Model came from profile reviewer
        assert loaded[0].model == "claude-sonnet-4-6"

    def test_record_requires_from_stdin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_workspace(tmp_path)
        runner = CliRunner()
        result = runner.invoke(harness_score_cmd, ["record", "-p", "demo"])
        assert result.exit_code != 0
        assert "--from-stdin" in result.output

    def test_record_rejects_invalid_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_workspace(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            harness_score_cmd,
            ["record", "-p", "demo", "--from-stdin"],
            input="{{not json",
        )
        assert result.exit_code != 0
        assert "invalid JSON" in result.output

    def test_record_without_spec_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        data_path, spec = _setup_workspace(tmp_path, project="demo")
        # Delete the spec dir
        import shutil

        shutil.rmtree(spec)
        runner = CliRunner()
        result = runner.invoke(
            harness_score_cmd,
            ["record", "-p", "demo", "--from-stdin"],
            input=json.dumps({"axes": {"a": {"score": 5}}}),
        )
        assert result.exit_code != 0
        assert "no harness spec dir" in result.output


class TestCLIShow:
    def test_show_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_workspace(tmp_path)
        runner = CliRunner()
        result = runner.invoke(harness_score_cmd, ["show", "-p", "demo"])
        assert "No harness score recorded" in result.output

    def test_if_fresh_exits_2_when_no_score(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_workspace(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            harness_score_cmd, ["show", "-p", "demo", "--if-fresh", "7d"]
        )
        assert result.exit_code == 2

    def test_if_fresh_exits_0_when_matching(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        data_path, spec = _setup_workspace(tmp_path)
        # Record a score matching current hash
        s = build_score_from_payload(
            {"axes": {"architecture": {"score": 8, "rationale": "r"}}},
            hash_str=hash_harness(spec),
            model="m",
        )
        append_score(data_path, "demo", s)

        runner = CliRunner()
        result = runner.invoke(
            harness_score_cmd, ["show", "-p", "demo", "--if-fresh", "7d"]
        )
        assert result.exit_code == 0
        assert "Harness score" in result.output

    def test_if_fresh_exits_2_when_hash_drifted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        data_path, spec = _setup_workspace(tmp_path)
        s = build_score_from_payload(
            {"axes": {"architecture": {"score": 8, "rationale": "r"}}},
            hash_str="sha256:stale",
            model="m",
        )
        append_score(data_path, "demo", s)
        runner = CliRunner()
        result = runner.invoke(
            harness_score_cmd, ["show", "-p", "demo", "--if-fresh", "7d"]
        )
        assert result.exit_code == 2

    def test_bad_if_fresh_format(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_workspace(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            harness_score_cmd, ["show", "-p", "demo", "--if-fresh", "weekly"]
        )
        assert result.exit_code != 0
        assert "Invalid" in result.output


class TestCLIHistory:
    def test_history_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_workspace(tmp_path)
        runner = CliRunner()
        result = runner.invoke(harness_score_cmd, ["history", "-p", "demo"])
        assert "No harness scores" in result.output

    def test_history_shows_trend_arrows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        data_path, _ = _setup_workspace(tmp_path)
        for score_val in (5, 7, 6):
            s = build_score_from_payload(
                {"axes": {"architecture": {"score": score_val, "rationale": "r"}}},
                hash_str=f"sha256:{score_val}",
                model="m",
            )
            append_score(data_path, "demo", s)

        runner = CliRunner()
        result = runner.invoke(harness_score_cmd, ["history", "-p", "demo"])
        assert result.exit_code == 0
        # Up arrow for 5->7, down for 7->6
        assert "↑" in result.output
        assert "↓" in result.output

    def test_history_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        data_path, _ = _setup_workspace(tmp_path)
        s = build_score_from_payload(
            {"axes": {"architecture": {"score": 8, "rationale": "r"}}},
            hash_str="h",
            model="m",
        )
        append_score(data_path, "demo", s)
        runner = CliRunner()
        result = runner.invoke(
            harness_score_cmd, ["history", "-p", "demo", "--format", "json"]
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert parsed[0]["overall"] == 8


# ---------------------------------------------------------------------------
# hv stats --harness integration
# ---------------------------------------------------------------------------


from hivemind.commands.stats import stats  # noqa: E402


class TestStatsHarness:
    def test_stats_harness_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _setup_workspace(tmp_path)
        runner = CliRunner()
        result = runner.invoke(stats, ["-p", "demo", "--harness"])
        assert result.exit_code == 0
        assert "No harness scores" in result.output

    def test_stats_harness_renders_trend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        data_path, _ = _setup_workspace(tmp_path)
        for sc in (20, 25, 30):
            s = build_score_from_payload(
                {"axes": {
                    "architecture": {"score": sc // 4, "rationale": "r"},
                    "rules_clarity": {"score": sc // 4, "rationale": "r"},
                    "tech_stack": {"score": sc // 4, "rationale": "r"},
                    "verification": {"score": sc - 3 * (sc // 4), "rationale": "r"},
                }},
                hash_str=f"h{sc}",
                model="m",
            )
            append_score(data_path, "demo", s)
        runner = CliRunner()
        result = runner.invoke(stats, ["-p", "demo", "--harness"])
        assert result.exit_code == 0
        assert "Harness score trend" in result.output
        assert "Latest axis breakdown" in result.output

    def test_stats_harness_rubric_version_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        data_path, _ = _setup_workspace(tmp_path)
        # Manually inject a score with stale rubric_version
        old = HarnessScore(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            hash="h",
            rubric_version=RUBRIC_VERSION - 1 if RUBRIC_VERSION > 0 else 999,
            model="m",
            axes={"architecture": AxisScore(score=8)},
            overall=8,
            overall_max=10,
        )
        append_score(data_path, "demo", old)
        runner = CliRunner()
        result = runner.invoke(stats, ["-p", "demo", "--harness"])
        assert result.exit_code == 0
        assert "rubric v" in result.output
