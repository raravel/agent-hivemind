# Feature: Task directory layout (v6)

## Why

`hivemind/tasks/` was a single flat directory until v5. With multiple
agents creating tasks daily, that flat layout caused two pains the
project couldn't ignore:

1. **Visibility collapse.** A few hundred `AGE-NNN-<hash>.md` files
   side-by-side made it impossible for humans or agents to glance at
   "what's open right now" — every read was a full directory walk.
2. **git-log pollution.** Combined with `auto_commit=true` (forced ON
   by `hv init --git` before v6), every `hv task update` produced its
   own commit. The user's `git log` filled with `task: update …` /
   `task: criteria-check …` clerical noise that drowned real work.

External platforms (Linear / Plane / GitHub Issues) were evaluated and
rejected — the wiki-readable file layout is load-bearing for hivemind's
"human + AI both read the same files" principle. The fix had to keep
the files local and Markdown.

## What

The flat `hivemind/tasks/` is split into three lifecycle directories:

```
hivemind/tasks/
├── _index.json              # schema v2: per-task `path` field
├── active/                  # pending · in_progress · in_review · rejected
│   └── AGE-001-<hash>.md
├── done/                    # recently completed; short stay
│   └── AGE-NNN-<hash>.md
├── archive/                 # long-finished, monthly buckets
│   └── 2026-05/
│       └── AGE-NNN-<hash>.md
└── _reports/                # post-merge execution reports (unchanged)
```

**Status → directory mapping** is enforced by `hv task create` and
`hv task update`:

| Status                                                | Directory |
|-------------------------------------------------------|-----------|
| `pending`, `in_progress`, `in_review`, `rejected`     | `active/` |
| `done`, `cancelled`                                   | `done/`   |
| (only via `hv task archive`)                          | `archive/{YYYY-MM}/` |

`hv task archive --older-than 30d` (default 30 days, i.e. roughly one
month) moves stale
`done/` entries into the monthly bucket derived from `completed_at` (or
`updated`). The archive command is the *only* path into `archive/` —
status mutations on an archived task restore it to `active/` or `done/`
because mutating implies the user wants it back in circulation.

## How resolution stays cheap

`_index.json` was bumped to schema v2. Each task entry now carries a
`path` field relative to `tasks_dir` (POSIX, e.g.
`"active/AGE-001-abc1.md"`). `_resolve_in_tasks_dir` (`task.py`) checks
the index first and returns the recorded path immediately when the
file still exists. Only on miss/stale entries does it walk every
directory yielded by `core.paths.iter_task_dirs`.

`_load_task_index` returns `None` on a version mismatch (v1 layout →
None), which forces `_rebuild_task_index` to refresh the index with v2
fields — so users that haven't run the migration yet still get correct
behavior, just with a one-time scan cost on the first command.

## Migration

`hv migrate --to v6` (in `commands/migrate.py:migrate_v5_to_v6`):

1. For each registered project, read every flat `hivemind/tasks/*.md`
   and move it into `active/` or `done/` based on its frontmatter
   `status`. Uses `_move_path` (with `git mv` when the repo is a git
   tree) so history is preserved.
2. Rebuild `_index.json` at schema v2 with each task's `path` recorded.
3. Bump `.hivemind.json` `version` to `6.0.0`.
4. Echo a warning when `auto_commit` is currently true, suggesting
   `hv config set auto_commit false` to align with the new skill flow
   (see below).

Idempotent: re-running after split is complete is a no-op.

## Skill responsibility — single commits

Since v6, `auto_commit` defaults to OFF. `hv task update`, `hv task
archive`, and `hv feedback save` mutate files without auto-committing.
The orchestrator skills (`/hv:task`, `/hv:plan`, the codex equivalents)
take responsibility for bundling `hivemind/` mutations into the same
git commit as the related code change:

```bash
# In /hv:task step 12:
git -C <project_root> merge <worker-branch> --squash --no-commit
hv task update <TASK-ID> --status done           # moves active/ → done/
git -C <project_root> add hivemind/              # stage move + report
git -C <project_root> commit -m "task: <TASK-ID> <title>"
```

Result: one commit per unit of work in `git log`, with the
status-move and the report living inside that commit's diff. The
auditable history stays inside `_reports/` and `git log` simultaneously
without any clerical noise commits.

**Exception**: lesson saves from `hv feedback save` (step 15) keep their
own `[lesson:<TASK-ID>]` commit so the time-delayed rollback gate
(step 15.5) can revert them independently.

## Operational guidance

- `hv task archive` is **not** invoked automatically. Run it manually
  (or schedule it via `/loop` / cron) when `done/` grows large.
- The BM25 index in the cross-project data dir is not affected — tasks
  were never indexed there. If archive search becomes a need later, a
  separate per-project BM25 index is the natural follow-up.
- Backwards compatibility: pre-v6 flat layouts still resolve via the
  `iter_task_dirs` fallback. Migration is recommended but not
  blocking — first command after upgrade will rebuild the index.
