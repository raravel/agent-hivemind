---
description: "Execute tasks through the orchestrator pipeline (delegate coding/review to workers in isolated worktrees, verify directly, judge on a 4-axis rubric). Use when the user says 'run task', 'execute task', or wants to start working on the next task. Pass --parallel to run ready tasks concurrently."
---

# hv-task -- Task execution pipeline (Orchestrator model)

> **Worker-mode guard (CRITICAL — prevents recursion).** If you were spawned as a sub-worker by another orchestrator (for example via `codex:codex-rescue` from inside another `hv-task` run), do NOT engage this skill. The orchestrator that spawned you needs you to execute its prompt literally — implement code, write a failing check, or produce a review — not start your own pipeline. Signals you are a sub-worker: the prompt starts with `--fresh` or `--resume`, or contains explicit instructions like "Step A:", "Step B:", "Review only", "Implement <TASK-ID>", or "Edit only inside the current working directory".

You are the **orchestrator**. Workers run in isolated git worktrees. You never trust a worker's completion claim. You pull results into your own context, verify directly, judge reviews on a 4-axis rubric, and record tokens/cost per run.

## When to use

- User says "run the next task", "execute task", "start working on tasks"
- The `hv` plugin is asked to execute tracked work
- Sequential mode — one ready task at a time
- Parallel mode — up to `parallel.max_concurrency` ready tasks concurrently (DAG-respecting)

## Execution model

```
You (Orchestrator)
  ├── fetch ready task(s) via `hv run --ready-only`
  ├── read harness docs yourself (MANDATORY)
  ├── verify-first gate: worker adds failing check; YOU confirm it fails
  ├── spawn Coding Worker (subagent / worker, isolation: "worktree")
  ├── VERIFY: read diff, check criteria yourself
  ├── RUN verification commands from verify.md (YOU, Bash)
  ├── spawn Review Worker (subagent / worker, isolation: "worktree")
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

If any are found, show: **"N reports have unreviewed incidents. Run `hv-feedback` to promote lessons."** Informational only — do NOT block. Proceed immediately.

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

**Provider routing (optional)**: the profile may include `coder_provider` and/or `reviewer_provider`, each one of `claude` (default) or `codex`. Read them:

```bash
hv config profiles.<profile_name>.coder_provider
hv config profiles.<profile_name>.reviewer_provider
```

`null` / empty / missing → treat as `claude`. When EITHER provider is `codex`:
- **Force sequential mode** for this run, regardless of `parallel.max_concurrency`. Codex companion's session-resume scope is per-repo, so concurrent worktrees can collide. Print one line: `"codex provider routing detected — running sequentially"`.
- The codex-plugin-cc plugin (`codex:codex-rescue` subagent) must be installed. If the spawn later fails with "no such subagent", stop and tell the user to run `/codex:setup`.

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

**Protocol** (Claude provider — uses one persistent worker):

1. Spawn the Coding Worker with **only this instruction first** (see step 7 for full spawn params):
   > "Step A: add a failing verification artifact for this task. Do NOT write the implementation yet. Commit the artifact."
2. Worker returns; read the diff — confirm an artifact was added (not just a stub).
3. Run the verification commands from `verify.md`. Read the output yourself.
4. **Gate**: the artifact MUST fail. If it passes, the worker has written implementation too — instruct via `send_input`: "revert implementation; keep only the failing check". Max 1 revert attempt before blocking.
5. Once the failing check is confirmed, use `send_input` to tell the worker: "Step B: implement the task. Make the verification artifact pass."

Continue to step 7 with the same worker.

**Protocol (codex provider — uses two spawn calls with codex session resume)**:

When `coder_provider == codex`, you cannot continue the codex thread via `send_input` (the rescue forwarder is one-shot). Use codex's own resume mechanism instead.

**Codex prompt header (MANDATORY for every `codex:codex-rescue` call in this run)**: prepend the following line to every codex prompt below — coding, review, and retry alike. This prevents codex from auto-engaging any installed `hv-*` skill recursively.

```
Do not invoke any hv-* skills (hv-task, hv-clarify, hv-feedback, hv-plan, etc.). Execute the prompt literally.
```

1. **Do NOT call `codex-companion.mjs` directly.** That script lives inside the codex-plugin-cc plugin, not the hv plugin; any `${CLAUDE_PLUGIN_ROOT}/scripts/...` path resolves wrong from here. Go through `subagent_type:"codex:codex-rescue"` and let the rescue forwarder handle codex internals. No resume precheck is needed — Step A uses `--fresh` (clean slate); Step B's `--resume` resumes the most recent codex session in the repo, which is Step A's.
2. **Step A** — spawn `subagent_type:"codex:codex-rescue"` worker in the worktree. Prompt MUST contain `--fresh` on its own line at the top:
   ```
   --fresh
   Step A: add a failing verification artifact for <TASK-ID>. Do NOT write the implementation yet. Commit the artifact only. Edit only inside the current working directory.

   Task: <task body>
   Verification commands: <from verify.md>
   ```
3. Worker returns. Read the diff in the worktree. Run the verification commands yourself.
4. **Gate**: same as Claude — artifact must fail. If it passes, spawn one more `codex:codex-rescue` call with prompt starting with `--resume` and "revert implementation; keep only the failing check". Max 1 revert.
5. **Step B** — spawn another `codex:codex-rescue` call. Prompt MUST start with `--resume`:
   ```
   --resume
   Step B: implement the task. Make the verification artifact you added in Step A pass. Edit only inside the current working directory.
   ```

Continue to step 7. From here on, every codex coding call uses `--resume`.

### 7. Spawn Coding Worker (subagent / worker)

**Claude provider** (default, `coder_provider != codex`):

```
spawn_agent(
  subagent_type: "general-purpose",
  model: <executor from profile>,
  isolation: "worktree",
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

Wait for the worker to return. Record the worktree path + branch name when changes are made.

**Codex provider** (`coder_provider == codex`):

If you came through the codex Step A→B verify-first gate (step 6), Step B already covers the initial implementation; skip the spawn here and go to step 8 directly. If verify-first was skipped (`verification_required: false` or type `chore`/`docs`):

```
spawn_agent(
  subagent_type: "codex:codex-rescue",
  isolation: "worktree",
  description: "Implement <TASK-ID>",
  prompt: <see below>,
)
```

Prompt format (the rescue forwarder strips routing tokens before passing the rest to `codex task`):
```
--fresh
Implement <TASK-ID>. Edit only inside the current working directory. Do NOT mark the task as done; the orchestrator handles that.

Task: <task body + completion criteria>
Harness docs (read these first): <explicit paths>
Verification commands: <from verify.md>
Project rules: <from rules.md>
Relevant lessons: <from step 5>
```

The codex executor model is whatever codex CLI defaults to (or `~/.codex/config.toml`'s `model`). Do NOT pass `--model` unless the user explicitly set one. The profile's `executor` field is recorded in the report but does not select the codex model.

**Record usage**: when the worker call returns, note the response length and your prompt length — you'll estimate tokens in step 13. **Codex token usage is opaque** — record only what you can see (your prompt + response chars) and mark `codex_usage.tracked: false` in the report.

### 8. Verify coding output (YOU do this — NEVER skip)

For each task:

1. **Pull the worker's changes into view**: the worker result describes the worktree path. Read the diff via Bash: `git -C <worktree> diff <base>..HEAD`.
2. **Read changed files**: for each modified file, read it to confirm the code actually exists.
3. **Check completion criteria**: for each `- [ ]` in the task body, output a verification line:
   ```
   [PASS] API endpoint returns 200 on POST /api/todos
   [FAIL] Rate limiting at 100 req/min — no rate limit code found
   ```
4. **On any [FAIL]**:
   - Claude provider: use `send_input` to the same worker with the failed criteria.
   - Codex provider: spawn a fresh `codex:codex-rescue` worker whose prompt starts with `--resume` so the rescue forwarder issues `codex task --resume-last`. Include the failed criteria verbatim. Each retry is a separate spawn but lands in the same codex thread.

   Max 2 coding retries.

### 9. Run verification commands (YOU do this — NEVER delegate)

Read the command list from `verify.md` (or `build-verify.md` fallback) and run each via Bash **in the worker's worktree**:

```bash
# Example (but read the exact commands from verify.md):
git -C <worktree> exec -- <command-from-verify.md>
```

Or `cd <worktree> && <command>`.

Read the output yourself. Do not trust exit codes alone. If the verification artifact from step 6 now passes and any pre-existing checks still pass → success.

If checks fail:
1. Send the failing output to the coding worker:
   - Claude provider: `send_input` to the same worker.
   - Codex provider: spawn a fresh `codex:codex-rescue` worker with prompt starting `--resume` and the failing output appended.
2. Worker fixes. Re-run. Max 2 verification retries.

### 10. Spawn Review Worker (subagent / worker)

**Claude provider** (default, `reviewer_provider != codex`):

```
spawn_agent(
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

**Codex provider** (`reviewer_provider == codex`, adversarial review tone):

`/codex:adversarial-review` is `disable-model-invocation: true` — you cannot trigger it. Route the review through `codex:codex-rescue` with a strict review-only prompt instead. The rescue forwarder skips `--write` when the request clearly asks for review-only behavior, so the prompt MUST make that explicit.

```
spawn_agent(
  subagent_type: "codex:codex-rescue",
  isolation: "worktree",
  description: "Review <TASK-ID>",
  prompt: <see below>,
)
```

Prompt format:
```
--fresh
Review only. Do NOT edit any files. Do NOT write. Do NOT apply patches. Read-only adversarial review.

Challenge the implementation: question the chosen approach, design tradeoffs, and assumptions. Then output a structured review with two sections:

1. `Findings` — list each issue with severity (blocking|advisory).
2. `Rubric` — score each axis 0–10 and explain each score in one sentence:
   - correctness
   - spec_compliance
   - safety
   - clarity

Return the review as plain markdown.

Diff to review:
<full git diff of the worker branch>

Harness docs (read these first): <explicit paths to architecture.md, rules.md>
Boundary-mismatch checklist: API/type/import consistency, harness rule violations.
```

Wait for the worker to return. Rubric scores from a codex reviewer may show more variance than Claude — that is expected for the verification trial.

### 11. Judge review output (YOU do this — 4-axis rubric)

Read the review worker's output. Extract the four rubric scores. Apply blocking thresholds:

| Axis | Range | Block if |
|------|-------|----------|
| correctness | 0–10 | `< 7` |
| spec_compliance | 0–10 | `< 7` |
| safety | 0–10 | `< 8` |
| clarity | 0–10 | advisory only |

If any axis is below its blocking threshold, OR the `Findings` section lists a `blocking` item:
1. Send the review output to the coding worker:
   - Claude provider: `send_input` to the same worker.
   - Codex provider: spawn a fresh `codex:codex-rescue` worker with prompt starting `--resume` and the review output appended.
2. Worker fixes. Re-verify (step 8) and re-run verification (step 9).
3. Max 1 review round.

Record `review_scores` and `blocking_issues` for step 13.

### 12. Merge worker branch + mark done

**Worktree edit-scope sanity check (codex provider only)**: codex CLI inherits CWD but is not formally sandboxed to the worktree. Before merging, verify nothing leaked outside:

```bash
git -C <project_root> status --short
git -C <worktree> status --short
```

If `<project_root> status` shows modifications that aren't from the worker's branch (and aren't in the staged merge), stop and ask the user — do NOT auto-revert; codex may have touched a sibling file the orchestrator needs to see.

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
providers:
  coder: <claude|codex>
  reviewer: <claude|codex>
codex_usage:
  tracked: false
  note: "Codex token usage is not visible to the orchestrator; check ChatGPT/OpenAI dashboard separately"
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
- `input_tokens ≈ ceil(len(prompt_chars) / 3.5)` for every worker call
- `output_tokens ≈ ceil(len(response_chars) / 3.5)`
- Sum across all worker calls for this task (coding worker round-trips + review worker)
- For codex-rescue calls: count only the prompt the orchestrator sent and the stdout returned. The codex CLI's internal model tokens are NOT visible — those are the savings the trial is measuring.

**Cost**:
- For each model used, `cost = (input_tokens / 1_000_000) * pricing[model].input + (output_tokens / 1_000_000) * pricing[model].output`
- Sum across models → `cost_usd`, rounded to 2 decimal places
- `cost_usd` covers Claude-side cost only. Codex usage shows up on the OpenAI/ChatGPT account, not here.

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

**Do NOT invoke `hv-feedback` or save to L2.** Let the user review and promote later.

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
2. For each task, spawn a worker with both `run_in_background: true` AND `isolation: "worktree"`.
3. You receive completion notifications from the runtime. Collect workers as they finish; **serialize steps 8–12** (verify + run checks + review + merge) to avoid conflicting merges.
4. After each merge, call `hv run --ready-only` again to pick up tasks that are now ready.
5. Stop when no more ready tasks and no in-flight workers.

If `parallel.max_concurrency = 1` or `--sequential` is passed: fall back to the sequential flow.

**Codex routing forces sequential.** If `coder_provider == codex` OR `reviewer_provider == codex` for the active profile, ignore parallel mode for this run and use the sequential flow. Codex companion's `task-resume-candidate` is per-repo, so two concurrent worktrees would collide on the resume thread. (See step 3.)

## Retry & Escalation

| Stage | Max | Method | On exhaustion |
|-------|-----|--------|---------------|
| Verify-first gate | 1 | `send_input` "revert impl, keep failing check" | Block task |
| Coding | 2 | `send_input` to same worker | Block |
| Verification | 2 | `send_input` with output | Block |
| Review | 1 | `send_input` with review | Block |

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
- **ALWAYS** use `send_input` to continue a Claude worker (preserves worktree + context). For codex workers, spawn a fresh `codex:codex-rescue` call with prompt starting `--resume` — the codex companion handles `--resume-last` routing.
- **ALWAYS** force sequential mode when any provider is `codex` (codex resume scope is per-repo).
- **ALWAYS** estimate tokens and compute cost for the report. Use `hv config pricing`.
- **ALWAYS** run `hv` CLI commands via the Bash tool.
- **NEVER** write reports or feedback in Korean. English only for BM25 consistency.
