# Task File Format

Task files are markdown documents stored in `{data_path}/tasks/{project}/{TASK-ID}.md`.

## Frontmatter Schema

```yaml
---
id: PRJ-001
title: "Implement user authentication"
status: pending          # pending | in_progress | done | blocked | cancelled
priority: high           # high | medium | low
type: feature            # task | bug | feature | chore
depends_on:              # list of task IDs this depends on
  - PRJ-000
created: 2025-01-15
updated: 2025-01-15
---
```

## Fields

| Field        | Type       | Required | Description                              |
|-------------|------------|----------|------------------------------------------|
| `id`        | string     | yes      | Unique task ID, format: `{PREFIX}-{NNN}` |
| `title`     | string     | yes      | Short descriptive title                  |
| `status`    | string     | yes      | Current status                           |
| `priority`  | string     | yes      | Execution priority                       |
| `type`      | string     | yes      | Task category                            |
| `depends_on`| list[str]  | no       | IDs of tasks that must be done first     |
| `created`   | date       | yes      | ISO date of creation                     |
| `updated`   | date       | yes      | ISO date of last update                  |

## Body

The markdown body below the frontmatter contains the task description, acceptance criteria, implementation notes, or any other relevant details. The body is free-form markdown.

## Task ID Format

Task IDs follow the pattern `{PREFIX}-{NNN}` where:
- `PREFIX` is the 2-3 character project prefix (auto-generated from project name)
- `NNN` is a zero-padded sequential counter (e.g., 001, 002, ...)

The counter is tracked in `.hivemind.json` under `projects.{name}.counter`.

## Status Transitions

```
pending -> in_progress -> done
pending -> blocked -> pending (when unblocked)
pending -> cancelled
in_progress -> blocked
in_progress -> cancelled
```

## Priority Ordering

When selecting the next task (`hv task next`), priority is ranked:
1. `high` (selected first)
2. `medium`
3. `low` (selected last)

Within the same priority, older tasks (by `created` date) are selected first.
