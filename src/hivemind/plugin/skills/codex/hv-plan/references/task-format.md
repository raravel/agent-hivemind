# Task File Format

Task files are markdown documents stored in `{data_path}/tasks/{project}/{TASK-ID}.md`.

## Frontmatter Schema

```yaml
---
id: PRJ-001
title: "Implement user authentication"
status: pending            # pending | in_progress | in_review | rejected | blocked | cancelled | done
priority: high             # high | medium | low
type: task                 # epic | story | task | bug | chore
parent: PRJ-000            # parent task ID (optional)
depends_on:                # list of task IDs this depends on
  - PRJ-000
verification_required: true  # optional; default true. Set false to skip verify-first gate.
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
- [[architecture]] `../docs/architecture.md` — module boundaries
- [[features/01_auth|01_auth]] `../docs/features/01_auth.md` — authentication spec

## Completion Criteria
- [ ] POST /api/auth/login returns 200 with valid credentials
- [ ] POST /api/auth/login returns 401 with invalid credentials
- [ ] JWT token is stored in httpOnly cookie
- [ ] All commands listed in `../docs/verify.md` pass
```

### Completion Criteria Rules

Each criterion must be:
- **Concrete**: "Returns 200 on POST /api/todos" not "works correctly"
- **Verifiable**: Can be checked by running a command or inspecting output
- **Independent**: Each criterion can be verified on its own

Always include:
- At least one **functional** criterion (what the code does)
- One criterion pointing to `verify.md` (covers lint/type/test/build — project-defined)
- **Integration** criteria if the task touches multiple modules

### Spec References

Link to harness documents that the task implementer should read. Tasks live at `hivemind/tasks/{TASK-ID}.md`, so paths MUST be file-relative (one `..` up to the `hivemind/` namespace, then `docs/...`). Each bullet pairs an Obsidian wikilink with the backtick path so the line is clickable in Obsidian *and* resolves in code editors / GitHub.

- `[[architecture]] \`../docs/architecture.md\`` — for module boundaries and data flow
- `[[tech-stack]] \`../docs/tech-stack.md\`` — for library versions and usage patterns
- `[[features/01_auth|01_auth]] \`../docs/features/01_auth.md\`` — for detailed feature specs
- `[[verify]] \`../docs/verify.md\`` — language-agnostic verification commands (fallback: `build-verify.md` for v2 projects)

Tasks generated before v5.1 may still carry legacy `projects/{project}/...` or root-relative `hivemind/docs/...` paths — run `hv migrate --to v5.1` once to rewrite them in place.

## Fields

| Field        | Type       | Required | Description                              |
|-------------|------------|----------|------------------------------------------|
| `id`        | string     | yes      | Unique task ID, format: `{PREFIX}-{NNN}` |
| `title`     | string     | yes      | Short descriptive title                  |
| `status`    | string     | yes      | Current status                           |
| `priority`  | string     | yes      | Execution priority                       |
| `type`      | string     | yes      | Task category                            |
| `depends_on`| list[str]  | no       | IDs of tasks that must be done first     |
| `verification_required` | bool | no | When false, `hv-task` skips the verify-first gate. Defaults to true. |
| `scope`     | list[str]  | no (recommended on leaf tasks) | Declared write set. Path globs, `manifest:<eco>`, `harness:<area>`, `config:<name>`, or `"*"`. Drives scope-aware parallel scheduling — empty/missing forces solo. See `hivemind/docs/features/10_scope-aware-parallel.md` for matching rules and conflict semantics. |
| `created`   | date       | yes      | ISO date of creation                     |
| `updated`   | date       | yes      | ISO date of last update                  |

## Scope as future reservation

The `scope` field is a *reservation contract*: paths that don't exist yet are valid. Two tasks with disjoint scopes can run in parallel without merge conflicts. Empty scope is treated as `["*"]` (solo). Wide-scope (`["*"]`) is correct and preferred over speculation when the write set cannot be honestly enumerated at plan time.

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
