"""Harness quality scoring storage.

LLM judgment lives in the /hv:score-harness skill; this module is the
deterministic bookkeeping layer: hash the harness doc set, persist scores
to a jsonl history, and answer freshness queries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Bump when the rubric in score-harness/references/rubric.md changes in a
# way that invalidates previous scores. Scores with an older rubric_version
# are shown as "stale (rubric v%d)" and not counted as fresh.
RUBRIC_VERSION = 1

# Files considered part of the harness for hashing. Missing files are skipped
# silently; the hash of an empty harness is still deterministic.
_HARNESS_FILES = (
    "architecture.md",
    "tech-stack.md",
    "rules.md",
    "verify.md",
    "build-verify.md",  # v2 fallback
)


@dataclass
class AxisScore:
    score: int
    max_score: int = 10
    rationale: str = ""
    recommendations: list[str] = field(default_factory=list)


@dataclass
class HarnessScore:
    timestamp: str
    hash: str
    rubric_version: int
    model: str
    axes: dict[str, AxisScore]
    overall: int
    overall_max: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HarnessScore":
        axes_raw = raw.get("axes", {})
        axes: dict[str, AxisScore] = {}
        if isinstance(axes_raw, dict):
            for name, ax in axes_raw.items():
                if not isinstance(ax, dict):
                    continue
                axes[str(name)] = AxisScore(
                    score=int(ax.get("score", 0)),
                    max_score=int(ax.get("max_score", 10)),
                    rationale=str(ax.get("rationale", "")),
                    recommendations=list(ax.get("recommendations", []) or []),
                )
        return cls(
            timestamp=str(raw.get("timestamp", "")),
            hash=str(raw.get("hash", "")),
            rubric_version=int(raw.get("rubric_version", 0)),
            model=str(raw.get("model", "")),
            axes=axes,
            overall=int(raw.get("overall", 0)),
            overall_max=int(raw.get("overall_max", len(axes) * 10 if axes else 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "hash": self.hash,
            "rubric_version": self.rubric_version,
            "model": self.model,
            "axes": {name: asdict(ax) for name, ax in self.axes.items()},
            "overall": self.overall,
            "overall_max": self.overall_max,
        }


def harness_spec_dir(data_path: Path, project: str) -> Path:
    return data_path / "projects" / project


def scores_path(data_path: Path, project: str) -> Path:
    return harness_spec_dir(data_path, project) / "_harness_scores.jsonl"


def hash_harness(spec_dir: Path) -> str:
    """Deterministic SHA256 over the concatenated harness doc set.

    Missing files contribute a sentinel ``<name>::<missing>``. features/*.md
    are sorted alphabetically so ordering is stable.
    """
    h = hashlib.sha256()
    for name in _HARNESS_FILES:
        path = spec_dir / name
        h.update(f"{name}::".encode())
        if path.exists():
            h.update(path.read_bytes())
        else:
            h.update(b"<missing>")
        h.update(b"\n")

    features_dir = spec_dir / "features"
    if features_dir.is_dir():
        for feat in sorted(features_dir.glob("*.md")):
            h.update(f"features/{feat.name}::".encode())
            h.update(feat.read_bytes())
            h.update(b"\n")
    return "sha256:" + h.hexdigest()


def append_score(data_path: Path, project: str, score: HarnessScore) -> Path:
    """Append a HarnessScore as one JSONL line. Returns the file path."""
    path = scores_path(data_path, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(score.to_dict(), ensure_ascii=False))
        f.write("\n")
    return path


def load_scores(data_path: Path, project: str) -> list[HarnessScore]:
    """Read all historical scores. Malformed lines are skipped silently."""
    path = scores_path(data_path, project)
    if not path.exists():
        return []
    out: list[HarnessScore] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(HarnessScore.from_dict(json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return out


def latest_score(data_path: Path, project: str) -> HarnessScore | None:
    scores = load_scores(data_path, project)
    return scores[-1] if scores else None


def is_fresh(
    score: HarnessScore | None,
    current_hash: str,
    max_age: timedelta,
    *,
    now: datetime | None = None,
) -> bool:
    """A cached score is fresh iff:
      - same rubric_version as current
      - same content hash
      - timestamp is within max_age of *now*
    """
    if score is None:
        return False
    if score.rubric_version != RUBRIC_VERSION:
        return False
    if score.hash != current_hash:
        return False
    try:
        ts = datetime.fromisoformat(score.timestamp)
    except ValueError:
        return False
    effective_now = now if now is not None else datetime.now(ts.tzinfo)
    if effective_now.tzinfo is None and ts.tzinfo is not None:
        effective_now = effective_now.replace(tzinfo=ts.tzinfo)
    if effective_now.tzinfo is not None and ts.tzinfo is None:
        ts = ts.replace(tzinfo=effective_now.tzinfo)
    return (effective_now - ts) <= max_age


def build_score_from_payload(
    payload: dict[str, Any], *, hash_str: str, model: str
) -> HarnessScore:
    """Construct a HarnessScore from a /hv:score-harness JSON payload.

    Payload shape:
      {"axes": {"architecture": {"score": 8, "rationale": "...", "recommendations": [...]}, ...}}

    Raises ValueError if the payload is missing ``axes`` or any axis score.
    """
    axes_raw = payload.get("axes")
    if not isinstance(axes_raw, dict) or not axes_raw:
        raise ValueError("payload must include non-empty 'axes' dict")

    axes: dict[str, AxisScore] = {}
    overall = 0
    overall_max = 0
    for name, ax in axes_raw.items():
        if not isinstance(ax, dict) or "score" not in ax:
            raise ValueError(f"axis '{name}' missing 'score' field")
        score_val = int(ax["score"])
        max_val = int(ax.get("max_score", 10))
        axes[str(name)] = AxisScore(
            score=score_val,
            max_score=max_val,
            rationale=str(ax.get("rationale", "")),
            recommendations=list(ax.get("recommendations", []) or []),
        )
        overall += score_val
        overall_max += max_val

    return HarnessScore(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        hash=hash_str,
        rubric_version=RUBRIC_VERSION,
        model=model,
        axes=axes,
        overall=overall,
        overall_max=overall_max,
    )
