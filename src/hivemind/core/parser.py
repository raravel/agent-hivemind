"""Shared parser for task/report documents with YAML frontmatter."""

from __future__ import annotations

from pathlib import Path

import frontmatter

VALID_STATUSES: list[str] = [
    "pending",
    "in_progress",
    "in_review",
    "rejected",
    "done",
]

VALID_TYPES: list[str] = [
    "epic",
    "story",
    "task",
    "bug",
    "chore",
]

REQUIRED_TASK_FIELDS: list[str] = [
    "id",
    "title",
    "status",
    "priority",
    "type",
]


def validate_status(status: str) -> None:
    """Raise ValueError if status is not in the valid list."""
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}"
        )


def validate_task_frontmatter(fm: dict[str, object]) -> None:
    """Raise ValueError if required fields are missing or status is invalid."""
    for field in REQUIRED_TASK_FIELDS:
        if field not in fm:
            raise ValueError(f"Missing required field: '{field}'")
    status = fm["status"]
    if not isinstance(status, str):
        raise ValueError(
            f"Invalid status type: expected str, got {type(status).__name__}"
        )
    validate_status(status)


def parse_task(path: Path) -> tuple[dict[str, object], str]:
    """Parse a markdown file with YAML frontmatter.

    Returns (frontmatter_dict, body_string).
    Raises FileNotFoundError if the path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    post = frontmatter.load(str(path))
    fm: dict[str, object] = dict(post.metadata)
    body: str = post.content
    return fm, body


def update_frontmatter(path: Path, updates: dict[str, object]) -> None:
    """Update specific frontmatter keys without changing the body.

    Validates status value if 'status' is in updates.
    Raises FileNotFoundError if the path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if "status" in updates:
        status = updates["status"]
        if not isinstance(status, str):
            raise ValueError(
                f"Invalid status type: expected str, got {type(status).__name__}"
            )
        validate_status(status)
    post = frontmatter.load(str(path))
    for key, value in updates.items():
        post[key] = value
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def create_task_file(
    path: Path, fm: dict[str, object], body: str
) -> None:
    """Create a new task file with frontmatter and body.

    Validates required fields and status value.
    Creates parent directories if needed.
    """
    validate_task_frontmatter(fm)
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, **fm)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
