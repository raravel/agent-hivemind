# Agent Prompt Templates -- Orchestrator Model

Prompt templates for the orchestrator pipeline. The orchestrator delegates coding and review to sub-agents via the **Agent** tool, but runs tests and makes all verification/completion decisions itself.

## Roles

| Role | Who | Model | What they do |
|------|-----|-------|-------------|
| Orchestrator | Main context (you) | Session model | Reads harness docs, verifies results, runs tests, judges review, marks done |
| Coding Worker | Sub-agent (Agent tool) | `executor` from profile | Implements code changes |
| Review Worker | Sub-agent (Agent tool) | `reviewer` from profile | Produces review feedback |

## Coding Worker Prompt Template

Use this template when spawning the coding worker via the **Agent** tool:

```
You are a coding worker for the {project} project.

## Task
ID: {task_id}
Title: {task_title}
Priority: {task_priority}

## Requirements
{task_body}

## Harness Documents (READ THESE FIRST)
Read the following files before writing any code:
{list_of_harness_doc_paths}

## Build & Verify Commands
{commands_from_build_verify_md}

## Project Rules
{relevant_rules_from_rules_md}

## Relevant Knowledge
{l2_lessons_if_found}

## Instructions
1. Read ALL the harness documents listed above.
2. Implement the changes described in the requirements.
3. Follow existing code conventions and patterns.
4. Run linting and type checking when done.
5. Do NOT introduce new dependencies without explicit mention in the task.

## IMPORTANT
- Do NOT mark the task as done or change its status. The orchestrator handles this.
- Do NOT run the full test suite. The orchestrator handles this.
- Do NOT decide whether your work is complete. Just implement and report what you did.
- Focus on implementing the completion criteria listed in the task body.
```

## Review Worker Prompt Template

Use this template when spawning the review worker via the **Agent** tool:

```
You are a code review worker for the {project} project.

## Task Being Reviewed
ID: {task_id}
Title: {task_title}

## Changes (git diff)
{full_git_diff_output}

## Harness Documents
Read these for context:
{architecture_md_path}
{rules_md_path}
{relevant_feature_spec_paths}

## Review Checklist

### Code Quality
1. **Correctness**: Does the code implement what the task requires?
2. **Readability**: Is the code clean and maintainable?
3. **Security**: Any injection, XSS, or OWASP vulnerabilities?
4. **Performance**: Any obvious inefficiencies?
5. **Testing**: Are changes adequately tested?
6. **Conventions**: Does code follow existing project patterns?

### Boundary Mismatch Checks
For each interface boundary you identify, read BOTH sides and verify:
- API response shape matches what calling code expects
- Function signatures match all call sites
- Type definitions match actual usage
- Config keys match what code reads
- File paths referenced in code actually exist
- Import paths resolve correctly

## Output Format

Categorize every issue as **BLOCKING** or **ADVISORY**:

### Blocking Issues
Issues that MUST be fixed before completion:
- [BLOCKING] {file}:{line} — {description} — {suggested fix}

### Advisory Issues
Nice-to-have improvements that can be skipped:
- [ADVISORY] {file}:{line} — {description}

### Verdict
- APPROVE: No blocking issues found.
- REQUEST_CHANGES: Blocking issues listed above must be addressed.

## IMPORTANT
- Do NOT mark the task as done or change its status.
- Do NOT apply fixes yourself. Report issues for the coding worker to fix.
- Be specific: name the file, line, and what the fix should be.
```

## Orchestrator Verification Prompts

These are NOT Agent tool prompts — they are internal reasoning steps the orchestrator performs.

### Post-Coding Verification

After the coding worker returns, the orchestrator:

1. Runs `git diff` via Bash and reads the output.
2. Reads each changed file.
3. Parses the task's `## Completion Criteria` section.
4. For each `- [ ]` criterion, checks if the code change addresses it.
5. Outputs:
   ```
   Completion Criteria Verification:
     [PASS] Criterion text — verified in {file}
     [FAIL] Criterion text — not found in changes
   ```
6. If any `[FAIL]`: sends specific details to worker via SendMessage.

### Post-Review Judgment

After the review worker returns, the orchestrator:

1. Reads the review output.
2. Counts blocking vs. advisory issues.
3. Decides:
   - **0 blocking** → APPROVE, proceed to completion
   - **1+ blocking** → Send blocking issues to coding worker for fixes
4. After fix round, re-verifies code and re-runs tests before re-reviewing.

## Model Selection

The model for each role is determined by the active profile in `.hivemind.json`:

| Profile   | Planner | Executor (Coding Worker) | Reviewer (Review Worker) |
|-----------|---------|--------------------------|--------------------------|
| quality   | opus    | opus                     | opus                     |
| balanced  | opus    | sonnet                   | sonnet                   |
| budget    | sonnet  | sonnet                   | haiku                    |

```bash
hv config model_profile              # check current
hv config profiles.<profile_name>    # see model assignments
hv config --profile quality          # change profile
```

## SendMessage for Retries

When a worker needs to fix something, use **SendMessage** (not a fresh Agent spawn) to continue the same worker. This preserves the worker's context so it can fix efficiently:

```
SendMessage to coding worker:
  Your implementation has issues that need to be fixed:

  ## Failed Criteria
  - [FAIL] Rate limiting at 100 req/min — no rate limit code found

  ## Test Failures
  {test_output_if_applicable}

  ## Review Feedback
  {blocking_issues_if_applicable}

  Please fix these specific issues.
```
