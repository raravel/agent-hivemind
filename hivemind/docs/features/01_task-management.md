# Feature: Task Management

## Overview

Hierarchical task tracking system with YAML frontmatter files. Supports epic -> story/feature -> task/bug/chore hierarchy with auto-completion propagation.

## Commands

### `hv task create -p PROJECT -t TITLE [--type TYPE] [--priority PRIORITY] [--parent PARENT] [--depends DEP1 --depends DEP2]`
- Generates sequential task ID: `{PREFIX}-{NNN}-{hash}` (e.g., `AGE-001-abc1`)
- Validates parent hierarchy rules
- Creates Markdown file at `<linked>/hivemind/tasks/active/{TASK_ID}.md`
- Updates `_index.json` (v2) with the file's relative path
- Auto-commits only if `auto_commit=true` (default `false`)

### `hv task list [-p PROJECT] [-s STATUS] [--priority PRIORITY] [--flat]`
- Default: tree view with box-drawing characters (unicode `├─`, `└─`, `│`)
- `--flat`: flat table output
- Sorted by priority (high > medium > low) then by ID

### `hv task get TASK_ID [--format json|text]`
- Shows full task details including parent chain
- JSON format includes `parent_chain` array

### `hv task update TASK_ID [--status STATUS] [--priority PRIORITY] [--title TITLE]`
- Updates specific frontmatter fields
- **Moves the file across the lifecycle boundary** when status crosses `done`/`cancelled` ↔ open: e.g., `pending → done` relocates `active/<id>.md → done/<id>.md` and refreshes `_index.json.path`. Tasks under `archive/{YYYY-MM}/` are pulled back to `active/` or `done/` on any status change (archive is meant as a snapshot — mutating implies the user wants the task back in circulation).
- When status changes to a terminal value: triggers auto-completion of parent tasks (and moves the parent file too)
- Auto-commits only if `auto_commit=true` (default `false`) — the orchestrator is expected to bundle the move into a single user-facing commit

### `hv task archive [-p PROJECT] [--older-than 14d] [--all] [--dry-run]`
- Moves `done/<id>.md` entries whose `completed_at` (or `updated`) is older than the threshold into `archive/{YYYY-MM}/<id>.md`
- `--all` overrides the age threshold; `--dry-run` previews the move set without touching the filesystem
- Updates `_index.json.path` so lookups stay O(1)
- Idempotent — re-running on an already-archived layout is a no-op

### `hv task next [-p PROJECT]`
- Returns the highest-priority pending leaf task (task/bug/chore only)
- Filters out tasks with unresolved dependencies
- Filters out tasks under completed parents

### `hv run [-p PROJECT] [-t TASK_ID] [--format json|text]`
- Pipeline task fetcher: first looks for `in_progress`, then next `pending`
- Used by `/hv:task` skill to get the next task to execute
- JSON format includes `id`, `frontmatter`, `body`, `path`

## Task File Format

```yaml
---
id: AGE-001
title: "Implement BM25 search"
status: pending
priority: high
type: task
parent: AGE-000
depends_on: [AGE-002]
created: 2025-01-15
updated: 2025-01-15
---

## Description
What this task implements and why.

## Spec References
- [[architecture]] `../architecture.md`

## Completion Criteria
- [ ] BM25 search returns ranked results
- [ ] Tests pass
```

## Hierarchy Rules

| Type | Valid Parent | Can be Parent of |
|------|------------|-----------------|
| `epic` | None (must be root) | story, feature |
| `story` | epic | task, bug, chore |
| `feature` | epic | task, bug, chore |
| `task` | story, feature | — |
| `bug` | story, feature | — |
| `chore` | story, feature | — |

## Status Flow

```
pending -> in_progress -> in_review -> done
                    \          \-> rejected -> pending
                     \-> blocked -> pending
```

Valid statuses: `pending`, `in_progress`, `in_review`, `rejected`, `done`

## Auto-Completion

When a task is marked `done`:
1. Find its parent task
2. Check if all siblings (children of same parent) are `done`
3. If yes, mark parent `done`
4. Recurse upward (parent's parent, etc.)

## Priority & Scheduling

- Priority order: `high` (3) > `medium` (2) > `low` (1)
- `hv task next` sorts by priority desc, then `created` date asc (oldest first)
- Dependencies (`depends_on`) must all be `done` before a task is eligible
