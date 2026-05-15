# Feature: Task Management

## Overview

Hierarchical task tracking system with YAML frontmatter files. Supports epic -> story/feature -> task/bug/chore hierarchy with auto-completion propagation.

## Commands

### `hv task create -p PROJECT -t TITLE [--type TYPE] [--priority PRIORITY] [--parent PARENT] [--depends DEP1 --depends DEP2]`
- Generates sequential task ID: `{PREFIX}-{NNN}` (e.g., `AGE-001`)
- Validates parent hierarchy rules
- Creates Markdown file at `tasks/{project}/{TASK_ID}.md`
- Updates counter in `.hivemind.json`
- Auto-commits if enabled

### `hv task list [-p PROJECT] [-s STATUS] [--priority PRIORITY] [--flat]`
- Default: tree view with box-drawing characters (unicode `├─`, `└─`, `│`)
- `--flat`: flat table output
- Sorted by priority (high > medium > low) then by ID

### `hv task get TASK_ID [--format json|text]`
- Shows full task details including parent chain
- JSON format includes `parent_chain` array

### `hv task update TASK_ID [--status STATUS] [--priority PRIORITY] [--title TITLE]`
- Updates specific frontmatter fields
- When status changes to `done`: triggers auto-completion of parent tasks
- Auto-commits if enabled

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
- `projects/agent-hivemind/architecture.md`

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
