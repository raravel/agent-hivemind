---
task_id: AGE-006-d923
completed_at: 2026-05-22T00:30:00Z
duration_minutes: 8
coding_retries: 0
verify_retries: 0
review_rounds: 0
verification_required: false
verification_passed: true
blocking_issues: false
review_scores:
  correctness: 9
  spec_compliance: 10
  safety: 10
  clarity: 9
tokens:
  estimated: true
  input: 4860
  output: 3680
cost_usd: 0.35
profile: quality
models:
  executor: claude-opus-4-7
  reviewer: claude-opus-4-7
---

## Summary

Updated `/hv:plan` SKILLs (claude and codex variants) so the planner sets `--scope`
on every new leaf task and reaches an opt-in scope back-fill mode whose full
procedure lives in `references/scope-backfill.md`. Documented the `scope` frontmatter
field in `references/task-format.md`. Pure docs/SKILL edit — no source code changed.

## Changes

- `src/hivemind/plugin/skills/claude/plan/SKILL.md` — added Mode (c) Scope back-fill
  pointer in the decision tree, expanded the Phase 2 example to include `--scope`,
  added a "Scope (every new leaf task)" paragraph after Hierarchy rules, added two
  ALWAYS/NEVER bullets in Important Rules.
- `src/hivemind/plugin/skills/claude/plan/references/scope-backfill.md` (NEW) — full
  back-fill procedure (Trigger / Steps / Guarantees), opt-in only, never auto-applied,
  reports `["*"]` count separately so under-specified features surface.
- `src/hivemind/plugin/skills/claude/plan/references/task-format.md` — added `scope`
  row to the frontmatter schema table + new `## Scope as future reservation` paragraph.
- `src/hivemind/plugin/skills/codex/hv-plan/SKILL.md` — byte-equivalent mirror of the
  claude SKILL changes.
- `src/hivemind/plugin/skills/codex/hv-plan/references/scope-backfill.md` (NEW) —
  byte-identical mirror.
- `src/hivemind/plugin/skills/codex/hv-plan/references/task-format.md` — mirror of
  task-format changes.

## Verification

After rebasing the worker's branch onto the post-AGE-005 main:

- `python -m ruff check src/ tests/` → `All checks passed!`
- `python -m mypy src/` → `Success: no issues found in 43 source files`
- `python -m pytest -q` → `698 passed, 4 skipped in 9.12s`
- `python -m build --wheel` → `Successfully built agent_hivemind-6.0.0-py3-none-any.whl`

Completion-criteria audit (orchestrator-side):

- [PASS] `claude/plan/SKILL.md:313-325` and `codex/hv-plan/SKILL.md:319-331` mention
  `--scope` in the Phase 2 example block.
- [PASS] `claude/plan/SKILL.md:32` and `codex/hv-plan/SKILL.md:32` carry
  `**Mode (c) Scope back-fill**` with a pointer to `references/scope-backfill.md`.
- [PASS] Phase 2 obligation is a single bold paragraph (~1 source line, ~5 wrapped
  lines) — within the spec's ~5-line budget.
- [PASS] Both `references/scope-backfill.md` files exist (2149 bytes each,
  byte-identical) with the full procedure body.
- [PASS] Both `references/task-format.md` files document the `scope` field as a
  schema row + a `## Scope as future reservation` prose section.
- [PASS-N/A] `hv run --ready-only --format json` is not referenced in either plan
  SKILL — no update required for that criterion (criterion was conditional).

## Review

4-axis rubric clean — correctness 9, spec_compliance 10, safety 10, clarity 9. No
blocking findings. Advisory items:

- "Mode (c)" sits as item 3 in the decision tree alongside state-driven items 1/2,
  while (c) is request-triggered and orthogonal. A future polish pass could add
  "Independent of 1/2:" to disambiguate. Non-blocking.
- The Phase 2 scope paragraph is one long source line that wraps to ~6–8 lines at
  ~100 cols — borderline against the ~5-line budget. Content accuracy keeps it
  proportional to importance.

## Harness Sync

Step 11.5 skipped — all six touched files are already enumerated in
`hivemind/docs/features/10_scope-aware-parallel.md ## Implementation` (lines 123–128),
and no manifest file changed.

## Notes

- The worker's worktree was forked from a pre-AGE-003 commit (`cd15280`) and
  initially reported 6 pre-existing test failures. After the orchestrator rebased
  the worktree onto post-AGE-005 main, the suite returned to 698 passed. Lesson:
  validate the worker's base commit before trusting "pre-existing failure" claims.
- Worktree `agent-a01889d15b780fa93` is left in place — `git worktree remove`
  reports `cannot remove a locked working tree` because the Claude agent runtime
  still holds the lock; the harness cleans up when the agent exits.
