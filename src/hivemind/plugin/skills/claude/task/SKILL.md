---
description: "Execute tasks through the orchestrator pipeline (delegate coding/review to workers in isolated worktrees, verify directly, judge on a 4-axis rubric). Use when the user says 'run task', 'execute task', or wants to start working on the next task. Pass --parallel to run ready tasks concurrently."
---

# /hv:task -- Task execution pipeline (Orchestrator model)

You are the **orchestrator**. Workers run in isolated git worktrees. You never trust a worker's completion claim. You pull results into your own context, verify directly, judge reviews on a 4-axis rubric, and record tokens/cost per run.

## When to use

- User says "run the next task", "execute task", "start working on tasks"
- `/hv:task` or `/hv:task --sequential` — one ready task at a time
- `/hv:task --parallel` — up to `parallel.max_concurrency` ready tasks concurrently (DAG-respecting)

## Execution model

```
You (Orchestrator)
  ├── fetch ready task(s) via `hv run --ready-only`
  ├── read harness docs yourself (MANDATORY)
  ├── verify-first gate: worker adds failing check; YOU confirm it fails
  ├── spawn Coding Worker (Agent tool, isolation: "worktree")
  ├── VERIFY: read diff, check criteria yourself
  ├── RUN verification commands from verify.md (YOU, Bash)
  ├── spawn Review Worker (Agent tool, isolation: "worktree")
  ├── JUDGE: 4-axis rubric, blocking thresholds
  ├── merge worker branch back, mark done, write report
  └── record tokens + cost in report frontmatter
```

**Core principle**: Workers execute. You verify. You decide. You merge.

## Steps

### 0. Preflight (informational only)

Scan previous reports for unreviewed incidents:

```bash
grep -rl "## Incident" {data_path}/tasks/{project}/_reports/ 2>/dev/null | head -5
```

If any are found, show: **"N reports have unreviewed incidents. Run `/hv:feedback` to promote lessons."** Informational only — do NOT block. Proceed immediately.

### 1. Fetch ready task(s)

- **Sequential mode**: `hv run --format json` — returns the next ready task or exit 1.
- **Parallel mode**: `hv run --ready-only --limit <N> --format json` — returns up to N ready tasks as a JSON array. N = `hv config parallel.max_concurrency` (default 2).

A "ready" task is `pending` AND all `depends_on` entries are `done`.

If no tasks are available (exit code 1 or empty array) — stop.

### 2. Mark task(s) as in_progress

For each selected task:

```bash
hv task update <TASK-ID> --status in_progress
```

### 3. Load model profile + pricing

```bash
hv config model_profile
hv config profiles.<profile_name>
hv config pricing
```

Profile returns `{planner, executor, reviewer}` with concrete model IDs
(e.g. `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5`).
Pricing is a map of `model_id -> {input, output}` dollars per Mtoken. Keep both in context — you use pricing to estimate cost in the report.

### 4. Read harness documents (YOU do this — MANDATORY)

Read docs in `{data_path}/projects/{project}/` referenced by the task's **Spec References**:

- `architecture.md` — module boundaries, data flow
- `tech-stack.md` — libraries, versions, patterns
- `features/*.md` — detailed feature specs
- `verify.md` — verification commands (lint/type/test/build, project-defined)
  — Fallback to `build-verify.md` (v2 name) if `verify.md` does not exist
- `rules.md` — NEVER/ALWAYS constraints

**You must understand the task fully before delegating.** Not optional.

If neither `verify.md` nor `build-verify.md` exists: stop and ask the user to create `verify.md` describing the project's verification commands.

### 5. Search the knowledge base

```bash
hv search "<task title keywords>"
```

If relevant L2 lessons are found, include them in worker prompts.

### 6. Verification-first gate (TDD-style, language-agnostic)

**Applies unless** the task frontmatter has `verification_required: false` OR the task `type` is `chore`/`docs`.

The worker must add a **failing verification artifact** BEFORE writing implementation. The artifact is any executable check that fails in the current state and will pass when the task is done:

- a unit/integration test that asserts the target behavior
- a type check that the current code cannot satisfy
- a runtime assertion or schema/contract check
- an executable spec (e.g. OpenAPI conformance test)

**Protocol**:

1. Spawn the Coding Worker with **only this instruction first** (see step 7 for full spawn params):
   > "Step A: add a failing verification artifact for this task. Do NOT write the implementation yet. Commit the artifact."
2. Worker returns; read the diff — confirm an artifact was added (not just a stub).
3. Run the verification commands from `verify.md`. Read the output yourself.
4. **Gate**: the artifact MUST fail. If it passes, the worker has written implementation too — instruct via SendMessage: "revert implementation; keep only the failing check". Max 1 revert attempt before blocking.
5. Once the failing check is confirmed, SendMessage to the worker: "Step B: implement the task. Make the verification artifact pass."

Continue to step 7 with the same worker.

### 7. Spawn Coding Worker (Agent tool)

Use the **Agent** tool with these parameters:

```
Agent(
  subagent_type: "general-purpose",
  model: <executor from profile>,
  isolation: "worktree",          # NEW: CC creates an isolated worktree
  description: "Implement <TASK-ID>",
  prompt: <see below>,
)
```

Prompt contents:
- Task description + completion criteria (from task body)
- Harness document paths (explicit list, not "read the docs")
- Verification commands from `verify.md` — worker runs these when done
- Project rules from `rules.md`
- Relevant L2 lessons from step 5
- "Do NOT mark the task as done. Orchestrator handles that."

Wait for the worker to return. CC returns the worktree path + branch name when changes are made.

**Record usage**: when the Agent call returns, note the response length and your prompt length — you'll estimate tokens in step 13.

### 8. Verify coding output (YOU do this — NEVER skip)

For each task:

1. **Pull the worker's changes into view**: the Agent result describes the worktree path. Read the diff via Bash: `git -C <worktree> diff <base>..HEAD`.
2. **Read changed files**: for each modified file, read it to confirm the code actually exists.
3. **Check completion criteria**: for each `- [ ]` in the task body, output a verification line:
   ```
   [PASS] API endpoint returns 200 on POST /api/todos
   [FAIL] Rate limiting at 100 req/min — no rate limit code found
   ```
4. **On any [FAIL]**: SendMessage to the same worker with the failed criteria. Max 2 coding retries.

### 9. Run verification commands (YOU do this — NEVER delegate)

Read the command list from `verify.md` (or `build-verify.md` fallback) and run each via Bash **in the worker's worktree**:

```bash
# Example (but read the exact commands from verify.md):
git -C <worktree> exec -- <command-from-verify.md>
```

Or `cd <worktree> && <command>`.

Read the output yourself. Do not trust exit codes alone. If the verification artifact from step 6 now passes and any pre-existing checks still pass → success.

If checks fail:
1. SendMessage to the coding worker with the failing output.
2. Worker fixes. Re-run. Max 2 verification retries.

### 10. Spawn Review Worker (Agent tool)

```
Agent(
  subagent_type: "general-purpose",
  model: <reviewer from profile>,
  isolation: "worktree",
  description: "Review <TASK-ID>",
  prompt: <see below>,
)
```

Prompt contents:
- The full `git diff` of the worker's branch
- Harness document paths (architecture, rules)
- Boundary-mismatch checklist (API/type/import consistency)
- **Instruction**: "Output a structured review with two sections:
  1. `Findings` — list each issue with severity (blocking|advisory).
  2. `Rubric` — score each axis 0–10 and explain each score in one sentence:
     - `correctness`
     - `spec_compliance`
     - `safety`
     - `clarity`
  Return the review as plain markdown."

Wait for the worker to return.

### 11. Judge review output (YOU do this — 4-axis rubric)

Read the review worker's output. Extract the four rubric scores. Apply blocking thresholds:

| Axis | Range | Block if |
|------|-------|----------|
| correctness | 0–10 | `< 7` |
| spec_compliance | 0–10 | `< 7` |
| safety | 0–10 | `< 8` |
| clarity | 0–10 | advisory only |

If any axis is below its blocking threshold, OR the `Findings` section lists a `blocking` item:
1. SendMessage to the coding worker with the review output.
2. Worker fixes. Re-verify (step 8) and re-run verification (step 9).
3. Max 1 review round.

Record `review_scores` and `blocking_issues` for step 13.

### 12. Merge worker branch + mark done

Merge the worker's branch into the main branch of the project repo (single worktree merge for sequential; one-at-a-time for parallel):

```bash
git -C <project_root> merge <worker-branch> --squash --no-commit
git -C <project_root> status
# Orchestrator reviews staged changes, then commits
git -C <project_root> commit -m "task: <TASK-ID> <title>"
```

Then:

```bash
hv task update <TASK-ID> --status done
```

Only proceed to step 12 after ALL of:
- Every completion criterion marked [PASS]
- All verification commands pass
- 4-axis rubric has no blocking scores and no blocking Findings

### 13. Record execution report

Write to `{data_path}/tasks/{project}/_reports/{TASK-ID}-report.md`:

```markdown
---
task_id: <TASK-ID>
completed_at: <ISO timestamp>
duration_minutes: <estimated>
coding_retries: <0-2>
verify_retries: <0-2>
review_rounds: <0-1>
verification_required: <true|false>
verification_passed: <true|false>
blocking_issues: <true|false>
review_scores:
  correctness: <0-10>
  spec_compliance: <0-10>
  safety: <0-10>
  clarity: <0-10>
tokens:
  estimated: true
  input: <N>
  output: <N>
cost_usd: <0.XX>
profile: <quality|balanced|budget>
models:
  executor: <model-id>
  reviewer: <model-id>
---

## Summary
<What was done>

## Changes
<List of files changed>

## Verification
<Commands run + results>

## Review
<Summary of review findings + rubric explanations>

## Notes
<Any issues encountered>
```

**Token estimation** (no exact CC usage API — approximate):
- `input_tokens ≈ ceil(len(prompt_chars) / 3.5)` for every Agent call
- `output_tokens ≈ ceil(len(response_chars) / 3.5)`
- Sum across all Agent calls for this task (coding worker round-trips + review worker)

**Cost**:
- For each model used, `cost = (input_tokens / 1_000_000) * pricing[model].input + (output_tokens / 1_000_000) * pricing[model].output`
- Sum across models → `cost_usd`, rounded to 2 decimal places

### 14. Incident section (conditional, automatic)

Append a `## Incident` section ONLY if any of:
- `coding_retries > 0`
- `verify_retries > 0`
- `review_rounds > 0` with blocking scores or findings

```markdown
## Incident

### What broke
- <Specific criterion, check, or review issue that failed>

### Why
- <Root cause from the failure context>

### What fixed it
- <The specific change that resolved it, on which retry>
```

**Do NOT invoke `/hv:feedback` or save to L2.** Let the user review and promote later.

### 15. Auto-draft lesson candidates (same trigger as incident)

When step 14 produced an Incident section, extract **0–3 reusable-lesson candidates** and pipe each to `hv feedback draft-add`. The CLI enforces a quality gate — rejected candidates are not saved.

For each candidate:
1. Title (one phrase, ≤120 chars) naming the technology and the fix.
2. Content between 50 and 500 chars. It MUST:
   - Name a concrete technology, library, file path, or identifier (not "the API" — use the real name).
   - Use an action verb (`use`, `avoid`, `set`, `add`, `wrap`, `configure`, `prefer`, `always`, `never`, ...).
   - Explain WHY (one sentence) so the lesson survives context loss.
3. Avoid restating task-specific details that will not reuse. If you cannot phrase the lesson without the original bug's variable names, it is not reusable — skip it.
4. **Choose a `--target`** (REQUIRED):

   | Target | When to use | Example |
   |---|---|---|
   | `rules` | NEVER/ALWAYS rule that applies specifically to THIS project | "NEVER import from `src/legacy/` — scheduled for removal in Q3" |
   | `tech-stack` | Library version / compat / upgrade decision tied to THIS project's stack | "Pin `python-frontmatter==1.1.0` until #42 fixes stdin handling" |
   | `architecture` | Module boundary / dependency-direction constraint for THIS project | "`hivemind.core` must not import from `hivemind.commands`" |
   | `L2` | Generic, reusable across projects | "FastAPI CORSMiddleware must precede custom middleware — preflight bypasses routes" |

   **Rule of thumb**: if the lesson names *this project's* files/modules/policies → harness target. If it names a *public library behavior* the same way any project would → `L2`.

Pipe it:

```bash
cat <<EOF | hv feedback draft-add -p <project> --task <TASK-ID> \
  --title "<title>" --target <L2|rules|tech-stack|architecture>
<content body>
EOF
```

- Exit 0 → draft saved under `_reports/{TASK-ID}-lessons-draft.json`.
- Exit 1 → gate rejected it (stderr has the reason). Try once to fix the reason; if still rejected, skip and do NOT work around the gate.

**Do NOT promote drafts yourself.** The user invokes `hv feedback promote-drafts -p <project>` later to confirm, override the target, or reject each one. L2 goes through BM25 dedup; harness targets append a dated bullet under `## Learned rules/patterns/constraints`.

### 16. Next task

Proceed immediately to the next task:
- Sequential: go back to step 1.
- Parallel: wait for the next worker notification; when one completes, do steps 8–14 for it; after merge, call `hv run --ready-only` again to pick up newly-ready tasks; exit when no more ready tasks and all in-flight workers have returned.

## Parallel-mode specifics

1. `hv run --ready-only --limit N --format json` returns up to N ready tasks.
2. For each task, spawn Agent with both `run_in_background: true` AND `isolation: "worktree"`.
3. You receive completion notifications from the runtime. Collect workers as they finish; **serialize steps 8–12** (verify + run checks + review + merge) to avoid conflicting merges.
4. After each merge, call `hv run --ready-only` again to pick up tasks that are now ready.
5. Stop when no more ready tasks and no in-flight workers.

If `parallel.max_concurrency = 1` or `--sequential` is passed: fall back to the sequential flow.

## Retry & Escalation

| Stage | Max | Method | On exhaustion |
|-------|-----|--------|---------------|
| Verify-first gate | 1 | SendMessage "revert impl, keep failing check" | Block task |
| Coding | 2 | SendMessage to same worker | Block |
| Verification | 2 | SendMessage with output | Block |
| Review | 1 | SendMessage with review | Block |

Blocked task:
```bash
hv task update <TASK-ID> --status blocked --reason "<what failed and why>"
```
Record incident in report, proceed to next task (do NOT stop the pipeline).

## Important Rules

- **NEVER trust a worker's completion claim.** Verify yourself.
- **NEVER read task body before reading harness docs.** Step 4 is mandatory.
- **NEVER hardcode language-specific build/test commands.** Always load from `verify.md`.
- **NEVER skip verify-first gate** for normal task types. Override requires explicit `verification_required: false` in task frontmatter, or type in `chore`/`docs`.
- **NEVER spawn workers without `isolation: "worktree"`.**
- **NEVER auto-accept a review.** Apply the 4-axis rubric and blocking thresholds.
- **NEVER let a worker mark a task as done.** Only you do this, and only after merge.
- **ALWAYS** use `hv run --format json` (sequential) or `hv run --ready-only --limit N` (parallel) for structured task data.
- **ALWAYS** mark task `in_progress` before starting work.
- **ALWAYS** use the model IDs from `hv config profiles.<profile>`. Do NOT hardcode.
- **ALWAYS** use **SendMessage** to continue a worker (preserves worktree + context).
- **ALWAYS** estimate tokens and compute cost for the report. Use `hv config pricing`.
- **ALWAYS** run `hv` CLI commands via the Bash tool.
- **NEVER** write reports or feedback in Korean. English only for BM25 consistency.
