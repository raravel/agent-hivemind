# Feature: Scope-aware Parallel Scheduling

## Overview

`/hv:task --parallel` currently picks the top-N ready tasks by priority and spawns workers concurrently. The only conflict avoidance is the `depends_on` DAG plus serialized merge — two parallel workers can still write to the same files, surfacing as merge conflicts or silent overwrites at squash-merge time.

This feature adds a **declared scope** to every leaf task. `hv run --ready-only --limit N` becomes scope-aware: it greedily packs a batch of tasks whose declared scopes are mutually disjoint, deferring conflicting candidates to the next round. Scope is treated as a *reservation contract* about the future — paths that do not yet exist are valid and expected.

## Motivation

- Prevent merge / add-add conflicts before workers start, not after.
- Promote each task plan into an architectural commitment ("this code will live at these paths") instead of an aspirational sketch.
- Mirror the harness's existing pattern: `verify.md`, `features/*.md ## Implementation`, `depends_on` — all forward-looking declarations whose value comes from being declared *before* code exists. Scope is the spatial counterpart of `depends_on`'s temporal ordering.

## Scope field format

`scope` is an optional top-level frontmatter field on leaf tasks (`task` / `bug` / `chore`). Type: `list[str]`. Each entry is one of:

| Form | Meaning | Example |
|------|---------|---------|
| Path glob | Files the task writes to. May reference paths that do not yet exist. | `src/hivemind/core/scope.py` |
| `manifest:<eco>` | Touches dependency manifest of the named ecosystem. | `manifest:python` |
| `harness:<area>` | Edits a harness document under `hivemind/docs/`. | `harness:rules`, `harness:features/05` |
| `config:<name>` | Edits a system-state config file. | `config:hivemind.json` |
| `"*"` | Wide-scope task (refactor, format, rename). Forces solo execution. | — |

Globs support `*` (single path segment) and `**` (recursive). Matching is case-sensitive. Namespaced tags (`manifest:`, `harness:`, `config:`) only match within their own namespace.

## Conflict semantics

Two scope lists *A* and *B* conflict if any entry in *A* matches any entry in *B* (or vice versa). Matching rules:

- Two path globs: `fnmatch`-style bidirectional match. `src/foo.py` conflicts with `src/foo.py` and with `src/**`.
- Two namespaced tags: same namespace, bidirectional glob match on the value. `manifest:python` conflicts with `manifest:python` but not with `manifest:node`.
- `"*"`: conflicts with every entry.
- Missing or empty scope (`[]`): treated as conflict-with-everything — runs solo.
- Path glob and namespaced tag: never conflict (different namespaces).

## Packing algorithm

Greedy by priority. `_find_ready_tasks` already returns candidates sorted `(priority desc, created asc)`.

```python
def pack_non_conflicting(candidates, limit):
    selected, deferred = [], []
    for cand in candidates:
        if len(selected) >= limit:
            break
        first_conflict = next(
            (s for s in selected if conflicts(cand.scope, s.scope)),
            None,
        )
        if first_conflict is None:
            selected.append(cand)
        else:
            deferred.append((cand, first_conflict, overlap_items(cand, first_conflict)))
    return selected, deferred
```

Invariants:

- The top-priority ready task is always selected (no opponents yet when it is considered).
- A loser of a conflict stays in the pending pool; next call to `hv run --ready-only` reconsiders it with the new highest priority.
- No starvation: priority order across rounds eventually anchors every task.
- `"*"` and empty scope force solo batches.
- Sequential-mode equivalence: with `limit=1`, the algorithm reduces to "pick the top candidate".

## Index integration

`hivemind/tasks/_index.json` bumps from v2 to v3. `_INDEX_FIELDS` gains `"scope"`. Old v2 indices are auto-rebuilt on read by the existing `_load_task_index` version-mismatch path — no migration code. Storing scope in the index keeps `pack_non_conflicting` to a single JSON read instead of parsing N frontmatter files per `hv run` call.

## CLI surface

- `hv task create ... --scope <entry>` (multiple allowed)
- `hv task scope-add <id> <entry> [<entry>...]`
- `hv task scope-rm <id> <entry> [<entry>...]`
- `hv task scope-set <id> <entry> [<entry>...]` (replace)
- `hv task get <id>` already prints frontmatter — scope appears automatically.

`hv run --ready-only --limit N --format json` switches output shape from a bare array to an object:

```json
{
  "tasks": [ {"...task entries...": true} ],
  "deferred": [
    {
      "id": "AGE-020",
      "reason": "scope conflict",
      "conflict_with": "AGE-018",
      "overlap": ["src/hivemind/commands/search.py"]
    }
  ]
}
```

The only consumers are the `/hv:plan` and `/hv:task` SKILLs (verified via repo grep); they migrate to the new shape in the same PR.

## Plan-time obligations

`/hv:plan` Phase 2 sets scope on every new leaf task. When the scope cannot be honestly enumerated, the planner sets `scope: ["*"]` — speculative paths are forbidden because they create false-positive conflicts.

A separate, opt-in **scope back-fill** mode populates scope on existing scope-less pending tasks. Triggered by the user asking to "add scope to existing tasks". The procedure lives in `references/scope-backfill.md` (not the main SKILL body) so new projects do not carry the cost in context. The planner reads each task's `## Spec References`, picks the relevant subset of paths from the referenced feature's `## Implementation`, proposes a per-task diff, and applies via `hv task scope-set` only after a single yes/no confirmation.

## Drift gate (execution time)

`/hv:task` adds **step 8.5** between coding verification and review. After the coding worker returns:

1. Compute `touched = git -C <worktree> diff <base>..HEAD --name-only`.
2. For each path in `touched`, confirm it matches at least one entry in the task's declared scope.
3. On any unmatched path: SendMessage to the worker — "out-of-scope writes: `<list>`. Either revert these or call `hv task scope-add <id> <path>` first so the orchestrator can recheck against in-flight peers."
4. If `scope-add` is requested, the orchestrator must verify the new path is disjoint from every in-flight worker's scope; on conflict, instruct revert (the peer has priority).
5. Maximum 1 retry round. On exhaustion, block the task with `contract-drift: out-of-scope writes`.

## Implementation

- `src/hivemind/core/scope.py` — pure logic module (normalize, is_solo, conflicts, pack_non_conflicting, glob matcher)
- `tests/unit/test_scope.py` — matching matrix, namespace isolation, packing invariants
- `src/hivemind/commands/task.py` — `scope-add` / `scope-rm` / `scope-set` subcommands; `create --scope`; `_INDEX_FIELDS`/`_INDEX_VERSION = 3`
- `src/hivemind/core/parser.py` — optional scope validation in `validate_task_frontmatter`
- `src/hivemind/commands/run.py` — integrate `pack_non_conflicting`; switch JSON output to `{tasks, deferred}` object
- `tests/unit/test_task_scope_cli.py` — CLI mutations propagate to frontmatter + index entry
- `tests/unit/test_run_parallel.py` — synthetic fixtures, disjoint batch selection, deferred reporting accuracy
- `src/hivemind/plugin/skills/claude/plan/SKILL.md` — inline 5-line scope obligation in Phase 2 + 4-line pointer to references/scope-backfill.md
- `src/hivemind/plugin/skills/claude/plan/references/scope-backfill.md` — full back-fill procedure (new)
- `src/hivemind/plugin/skills/codex/hv-plan/SKILL.md` — mirror of claude/plan changes
- `src/hivemind/plugin/skills/codex/hv-plan/references/scope-backfill.md` — mirror (new)
- `src/hivemind/plugin/skills/claude/plan/references/task-format.md` — document `scope` field in schema table
- `src/hivemind/plugin/skills/codex/hv-plan/references/task-format.md` — mirror
- `src/hivemind/plugin/skills/claude/task/SKILL.md` — step 8.5 scope-drift gate; consume new JSON object output
- `src/hivemind/plugin/skills/codex/hv-task/SKILL.md` — mirror
- `hivemind/docs/rules.md` — add ALWAYS rule for scope on new leaf tasks
