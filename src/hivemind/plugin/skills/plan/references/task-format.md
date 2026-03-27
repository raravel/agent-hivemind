# Task File Format

Task files are markdown documents stored in `{data_path}/tasks/{project}/{TASK-ID}.md`.

## Frontmatter Schema

```yaml
---
id: PRJ-001
title: "Implement user authentication"
status: pending          # pending | in_progress | done | blocked | cancelled
priority: high           # high | medium | low
type: task               # epic | story | task | bug | chore
parent: PRJ-000          # parent task ID (optional)
depends_on:              # list of task IDs this depends on
  - PRJ-000
created: 2025-01-15
updated: 2025-01-15
---
```

## Hierarchy

| Type | Role | Parent | Children |
|------|------|--------|----------|
| `epic` | Top-level grouping | None | story |
| `story` | Groups related work | epic | task/bug/chore |
| `task` | Actual work item | story | None |
| `bug` | Bug fix | story | None |
| `chore` | Maintenance | story | None |

When all tasks in a story are done, the story auto-completes.
When all stories in an epic are done, the epic auto-completes.

## Required Body

Every task MUST have a markdown body with these sections:

```markdown
## Description
Brief explanation of what this task implements and why.

## Spec References
- `projects/{project}/architecture.md` — module boundaries
- `projects/{project}/features/01_auth.md` — authentication spec

## Completion Criteria
- [ ] POST /api/auth/login returns 200 with valid credentials
- [ ] POST /api/auth/login returns 401 with invalid credentials
- [ ] JWT token is stored in httpOnly cookie
- [ ] `npm run lint` passes
- [ ] `npm test` passes
```

### Completion Criteria Rules

Each criterion must be:
- **Concrete**: "Returns 200 on POST /api/todos" not "works correctly"
- **Verifiable**: Can be checked by running a command or inspecting output
- **Independent**: Each criterion can be verified on its own

Always include:
- At least one **functional** criterion (what the code does)
- At least one **build/lint** criterion (code quality gate)
- **Integration** criteria if the task touches multiple modules

### Spec References

Link to harness documents that the task implementer should read:
- `projects/{project}/architecture.md` — for module boundaries and data flow
- `projects/{project}/tech-stack.md` — for library versions and usage patterns
- `projects/{project}/features/*.md` — for detailed feature specs
- `projects/{project}/build-verify.md` — for build and test commands

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

## Task ID Format

Task IDs follow the pattern `{PREFIX}-{NNN}` where:
- `PREFIX` is the 2-3 character project prefix (auto-generated from project name)
- `NNN` is a zero-padded sequential counter (e.g., 001, 002, ...)

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
