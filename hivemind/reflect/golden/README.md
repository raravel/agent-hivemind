# Golden Task Set — Phase 3 placeholder

This directory will hold *frozen* representative task specs used for
controlled before/after ablation when promoting lessons. Phase 1 of the
meta-harness rollout ships only `lesson-log.jsonl` + `rollback-log.jsonl`
+ the time-delayed rollback gate driven by trailing `review_scores` in
`_reports/*.md`. Phase 3 will add ablation here.

## What will go here

Per representative task, freeze 3 artifacts:

1. The task spec (`<TASK-ID>.md` with frontmatter + body) at the time it
   first passed verification.
2. A snapshot of `verify.md` commands that should still pass against the
   resulting code.
3. The recorded `review_scores` from the original
   `_reports/<TASK-ID>-report.md` for baseline comparison.

## Why this is empty now

The trailing-review-scores signal used in `hv-task` step 15.5 is noisy
and only detects post-hoc regressions. Golden ablation will let us
measure a lesson's effect on the *same* task before/after, isolating the
lesson from per-task difficulty variance.

Do not commit golden artefacts here until the Phase 3 tooling (`hv
goldens record` / `hv goldens replay`) lands; raw spec files here without
the surrounding tooling would mislead the gate.
