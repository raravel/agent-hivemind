---
description: "Execute tasks through the orchestrator pipeline (delegate coding/review to workers, verify directly). Use when the user says 'run task', 'execute task', or wants to start working on the next task."
---

# /hv:task -- Task execution pipeline (Orchestrator model)

You are the **orchestrator**. You delegate work to sub-agents but **never trust their completion claims**. You pull results into your own context and verify directly before proceeding.

## When to use

- User says "run the next task", "execute task", "start working on tasks"
- User runs `/hv:task` explicitly
- Automated pipeline execution is needed

## Execution Model

```
You (Orchestrator) ──┬── read harness docs yourself
                     ├── spawn Coding Worker (Agent tool)
                     ├── VERIFY: read git diff, check criteria yourself
                     ├── RUN TESTS yourself (Bash)
                     ├── spawn Review Worker (Agent tool)
                     ├── JUDGE: read review output, decide yourself
                     └── only YOU mark done
```

**Core principle**: Workers execute. You verify. You decide.

## Steps

### 0. Check for unreviewed incidents (informational only)

Before starting, check if previous task reports have unreviewed incidents:

```bash
grep -rl "## Incident" {data_path}/tasks/{project}/_reports/ 2>/dev/null | head -5
```

If any are found, show: **"N reports have unreviewed incidents. Run `/hv:feedback` to promote lessons."**

This is informational only — do NOT block pipeline execution. Proceed immediately.

### 1. Fetch the next task

```bash
hv run --format json
# Or: hv run -p <project> --format json
# Or: hv run -t <TASK-ID> --format json
```

Returns JSON with `id`, `frontmatter`, `body`, and `path`. Exit code 1 = no tasks available — stop.

### 2. Mark task as in_progress

```bash
hv task update <TASK-ID> --status in_progress
```

### 3. Load model profile

```bash
hv config model_profile
hv config profiles.<profile_name>
```

Returns:
```json
{
  "planner": "opus",
  "executor": "sonnet",
  "reviewer": "sonnet"
}
```

- **executor** model → Coding Worker
- **reviewer** model → Review Worker

### 4. Read harness documents (YOU do this — MANDATORY)

Before delegating ANYTHING, read the harness documents referenced in the task's **Spec References** section. These are in `{data_path}/projects/{project}/`:

- `architecture.md` — module boundaries, data flow
- `tech-stack.md` — libraries, versions, patterns
- `features/*.md` — detailed feature specs
- `build-verify.md` — build/test commands
- `rules.md` — NEVER/ALWAYS constraints

**You must understand the task fully before delegating.** This is not optional.

### 5. Search knowledge base

```bash
hv search "<task title keywords>"
```

If relevant L2 lessons are found, include them in the worker prompt.

### 6. Spawn Coding Worker (Agent tool)

Use the **Agent** tool to spawn a coding worker with the **executor** model.

Construct the worker prompt with:
- Task description and completion criteria (from the task body)
- Harness document paths to read (list them explicitly)
- Build/verify commands from `build-verify.md`
- Project rules from `rules.md`
- Any relevant L2 lessons from step 5

Example Agent tool usage:
```
Agent tool:
  model: <executor model from profile>
  prompt: |
    You are a coding worker. Implement the following task.

    ## Task
    <task description and completion criteria>

    ## Harness Documents (READ THESE FIRST)
    <list of file paths to read>

    ## Build & Verify
    <commands from build-verify.md>

    ## Rules
    <relevant rules from rules.md>

    Implement the task. Run lint and type checks when done.
    Do NOT mark the task as done — the orchestrator will do that.
```

Wait for the worker to return.

### 7. Verify coding output (YOU do this — NEVER skip)

After the worker returns, **do not trust its claim of completion**. Verify directly:

1. **Read the diff**: Run `git diff` and read the actual changes
2. **Read changed files**: Open and read each modified file
3. **Check completion criteria**: For each `- [ ]` item in the task body:
   - Determine if the code changes address this criterion
   - Output a verification line:
     ```
     [PASS] API endpoint returns 200 on POST /api/todos
     [FAIL] Rate limiting at 100 req/min — no rate limit code found
     ```
4. **If any criterion fails**: Use **SendMessage** to continue the same worker with specific failure details. The worker retains its context, so it can fix efficiently. Max 2 retries.

### 8. Run tests (YOU do this — NEVER delegate)

Run tests directly via Bash:

```bash
ruff check src/ tests/        # lint
mypy src/                      # type check (if applicable)
pytest                         # test suite
```

**Read the output yourself.** Do not rely on exit codes alone — read the actual test output to confirm what passed and what failed.

If tests fail:
1. Use **SendMessage** to send the test output to the coding worker
2. Worker fixes, you re-run tests
3. Max 2 test retries

### 9. Spawn Review Worker (Agent tool)

Use the **Agent** tool to spawn a review worker with the **reviewer** model.

Construct the review prompt with:
- The full `git diff` output
- Harness document paths (architecture, rules)
- Boundary mismatch checklist:
  - API response shape matches calling code expectations
  - Function signatures match all call sites
  - Type definitions match actual usage
  - Config keys match what code reads
  - Import paths resolve correctly
- Instruction: produce a structured review with blocking vs. advisory issues

Wait for the worker to return.

### 10. Judge review output (YOU do this — NEVER auto-accept)

Read the review feedback yourself and categorize:

- **Blocking issues**: Must be fixed before done
- **Advisory issues**: Nice-to-have, can skip

If blocking issues exist:
1. Use **SendMessage** to send review feedback to the coding worker
2. Worker fixes, you re-verify (step 7) and re-test (step 8)
3. Max 1 review round

If only advisory or no issues → proceed.

### 11. Mark task as done

Only after ALL of the following are true:
- All completion criteria verified as [PASS]
- All tests pass (you saw the output)
- Review passed (no blocking issues)

```bash
hv task update <TASK-ID> --status done
```

### 12. Record execution report

Write to `{data_path}/tasks/{project}/_reports/{TASK-ID}-report.md`:

```markdown
---
task_id: <TASK-ID>
duration_minutes: <estimated>
coding_retries: <0-2>
test_retries: <0-2>
review_rounds: <0-1>
review_passed: true|false
lint_failed: true|false
---

## Summary
<What was done>

## Changes
<List of files changed>

## Verification
<Lint, type check, test results>

## Notes
<Any issues encountered>
```

### 13. Record incident observations (automatic — NO user confirmation)

**Only if non-trivial events occurred** during this task:
- `coding_retries > 0`
- `test_retries > 0`
- Review had blocking issues

If ALL of the above are 0 (smooth execution), **skip this step entirely** and proceed to the next task.

Otherwise, append a `## Incident` section to the execution report with **forensic framing**:

```markdown
## Incident

### What broke
- <Specific criterion, test, or review issue that failed>

### Why
- <Root cause from the failure context — what the worker missed or got wrong>

### What fixed it
- <The specific change that resolved it, on which retry>
```

**Do NOT invoke `/hv:feedback`.** Do NOT ask the user for confirmation. Do NOT save to L2 directly. The incident stays in the report file until the user reviews it.

Proceed immediately to the next task.

## Retry & Escalation

| Stage | Max Retries | Method | On Exhaustion |
|-------|-------------|--------|---------------|
| Coding | 2 | SendMessage to same worker | Mark `blocked` with `--reason` |
| Tests | 2 | SendMessage with test output | Mark `blocked` with `--reason` |
| Review | 1 | SendMessage with review feedback | Mark `blocked` with `--reason` |

If all retries are exhausted at any stage:
```bash
hv task update <TASK-ID> --status blocked --reason "<what failed and why>"
```
Record incident in report, then proceed to the next task (do NOT stop the pipeline).

## Important Rules

- **NEVER trust a worker's claim of completion.** Always verify yourself.
- **NEVER start delegating without reading harness documents first.** Step 4 is mandatory.
- **NEVER delegate test execution.** You run tests via Bash and read the output.
- **NEVER auto-accept review.** You read review feedback and judge blocking vs. advisory.
- **NEVER let a worker mark a task as done.** Only you do this.
- ALWAYS use `hv run --format json` to get structured task data.
- ALWAYS mark the task as `in_progress` before starting work.
- ALWAYS use the model profile from `hv config` for agent model selection. Do NOT hardcode models.
- ALWAYS use **SendMessage** to continue a worker (preserves context) rather than spawning a new one for retries.
- If a task is blocked after all retries: `hv task update <TASK-ID> --status blocked`
- ALWAYS use Bash tool to run `hv` CLI commands.
- NEVER write reports or feedback in Korean. All content must be in English.
