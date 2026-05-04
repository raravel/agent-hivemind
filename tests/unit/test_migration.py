"""Unit tests for hivemind.core.migration (v3 → v4)."""

from __future__ import annotations

import json
from pathlib import Path

from hivemind.core.migration import SCHEMA_V4, migrate_v3_to_v4


def _v3_config(
    data_path: Path,
    projects: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "version": "3.0.0",
        "data_path": str(data_path),
        "projects": projects or {},
    }


def _write_link(linked_path: Path, payload: dict[str, object]) -> Path:
    linked_path.mkdir(parents=True, exist_ok=True)
    link_file = linked_path / ".hivemind-link.json"
    link_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return link_file


def test_returns_false_when_config_missing(tmp_path: Path) -> None:
    assert migrate_v3_to_v4(tmp_path / "missing.json") is False


def test_returns_false_when_already_v4(tmp_path: Path) -> None:
    config = tmp_path / ".hivemind.json"
    config.write_text(
        json.dumps({"version": SCHEMA_V4, "projects": {}}),
        encoding="utf-8",
    )
    pre = config.read_text(encoding="utf-8")
    assert migrate_v3_to_v4(config) is False
    assert config.read_text(encoding="utf-8") == pre


def test_drops_top_level_data_path_and_bumps_version(tmp_path: Path) -> None:
    data_path = tmp_path / "hivemind-data"
    data_path.mkdir()
    config = data_path / ".hivemind.json"
    config.write_text(
        json.dumps(_v3_config(data_path)),
        encoding="utf-8",
    )

    assert migrate_v3_to_v4(config) is True
    parsed = json.loads(config.read_text(encoding="utf-8"))
    assert parsed["version"] == SCHEMA_V4
    assert "data_path" not in parsed


def test_drains_prefix_and_counter_from_projects(tmp_path: Path) -> None:
    data_path = tmp_path / "hivemind-data"
    data_path.mkdir()
    project_dir = tmp_path / "myproj"
    _write_link(
        project_dir,
        {
            "project": "myproj",
            "data_path": str(data_path),
            "targets": ["claude"],
        },
    )

    config = data_path / ".hivemind.json"
    config.write_text(
        json.dumps(
            _v3_config(
                data_path,
                {
                    "myproj": {
                        "prefix": "MYP",
                        "linked_path": str(project_dir),
                        "counter": 5,
                    }
                },
            )
        ),
        encoding="utf-8",
    )

    assert migrate_v3_to_v4(config) is True

    parsed = json.loads(config.read_text(encoding="utf-8"))
    assert "prefix" not in parsed["projects"]["myproj"]
    assert "counter" not in parsed["projects"]["myproj"]
    assert parsed["projects"]["myproj"] == {"linked_path": str(project_dir)}

    link = json.loads(
        (project_dir / ".hivemind-link.json").read_text(encoding="utf-8")
    )
    assert link == {"project": "myproj", "prefix": "MYP"}

    counter_payload = json.loads(
        (data_path / "tasks" / "myproj" / "_counter.json").read_text(
            encoding="utf-8"
        )
    )
    assert counter_payload == {"value": 5}


def test_existing_link_prefix_wins_over_global(tmp_path: Path) -> None:
    data_path = tmp_path / "hivemind-data"
    data_path.mkdir()
    project_dir = tmp_path / "proj"
    _write_link(project_dir, {"project": "proj", "prefix": "OLD"})

    config = data_path / ".hivemind.json"
    config.write_text(
        json.dumps(
            _v3_config(
                data_path,
                {"proj": {"prefix": "NEW", "linked_path": str(project_dir)}},
            )
        ),
        encoding="utf-8",
    )

    migrate_v3_to_v4(config)
    link = json.loads(
        (project_dir / ".hivemind-link.json").read_text(encoding="utf-8")
    )
    assert link["prefix"] == "OLD"


def test_counter_seed_does_not_downgrade_existing_file(tmp_path: Path) -> None:
    data_path = tmp_path / "hivemind-data"
    data_path.mkdir()
    project_dir = tmp_path / "proj"
    _write_link(project_dir, {"project": "proj"})

    counter_file = data_path / "tasks" / "proj" / "_counter.json"
    counter_file.parent.mkdir(parents=True)
    counter_file.write_text(json.dumps({"value": 99}), encoding="utf-8")

    config = data_path / ".hivemind.json"
    config.write_text(
        json.dumps(
            _v3_config(
                data_path,
                {"proj": {"linked_path": str(project_dir), "counter": 10}},
            )
        ),
        encoding="utf-8",
    )

    migrate_v3_to_v4(config)
    payload = json.loads(counter_file.read_text(encoding="utf-8"))
    assert payload == {"value": 99}


def test_zero_counter_is_skipped_but_still_dropped_from_global(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "hivemind-data"
    data_path.mkdir()
    project_dir = tmp_path / "proj"
    _write_link(project_dir, {"project": "proj"})

    config = data_path / ".hivemind.json"
    config.write_text(
        json.dumps(
            _v3_config(
                data_path,
                {"proj": {"linked_path": str(project_dir), "counter": 0}},
            )
        ),
        encoding="utf-8",
    )

    migrate_v3_to_v4(config)
    parsed = json.loads(config.read_text(encoding="utf-8"))
    assert "counter" not in parsed["projects"]["proj"]
    assert not (data_path / "tasks" / "proj" / "_counter.json").exists()


def test_orphan_project_keeps_prefix_when_link_missing(
    tmp_path: Path,
) -> None:
    """Without a reachable link file there is no committed home for the
    prefix, so migration leaves it in the global config rather than
    silently dropping it. counter still drains."""
    data_path = tmp_path / "hivemind-data"
    data_path.mkdir()
    config = data_path / ".hivemind.json"
    config.write_text(
        json.dumps(
            _v3_config(
                data_path,
                {
                    "orphan": {
                        "prefix": "ORP",
                        "linked_path": str(tmp_path / "nonexistent"),
                        "counter": 2,
                    }
                },
            )
        ),
        encoding="utf-8",
    )

    migrate_v3_to_v4(config)
    parsed = json.loads(config.read_text(encoding="utf-8"))
    assert parsed["projects"]["orphan"]["prefix"] == "ORP"
    assert "counter" not in parsed["projects"]["orphan"]


def test_idempotent_second_run_returns_false(tmp_path: Path) -> None:
    data_path = tmp_path / "hivemind-data"
    data_path.mkdir()
    project_dir = tmp_path / "proj"
    _write_link(project_dir, {"project": "proj"})

    config = data_path / ".hivemind.json"
    config.write_text(
        json.dumps(
            _v3_config(
                data_path,
                {
                    "proj": {
                        "prefix": "PRO",
                        "linked_path": str(project_dir),
                        "counter": 3,
                    }
                },
            )
        ),
        encoding="utf-8",
    )

    assert migrate_v3_to_v4(config) is True
    assert migrate_v3_to_v4(config) is False
