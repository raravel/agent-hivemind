# Feature: Search & Feedback Improvements

## 1. Category Filter for Search (`hv search --category`)

### Problem
Users may want to search within a specific L2 category (backend, frontend, infra, general) but the current `hv search` always searches the entire corpus.

### Solution
Add a `--category` option to `hv search` that filters docs before BM25 scoring.

### Implementation
In `commands/search.py`, filter the index docs by path prefix before passing to `search()`:

```python
@click.option("--category", "-c", default=None,
              type=click.Choice(["frontend", "backend", "infra", "general"]),
              help="Filter search to a specific category.")
def search(query, project, category, ...):
    index_data = load_index(...)
    if category:
        index_data["docs"] = [
            d for d in index_data["docs"]
            if d["path"].startswith(f"level2/{category}/")
        ]
    results = search(query, index_data, top_k=top_k)
```

### Files to Modify
- `src/hivemind/commands/search.py` — add `--category` option, filter before search

## 2. Title Token Weighting in BM25

### Problem
BM25 treats title and body tokens equally. A query matching a document's title is more relevant than one matching a passing mention in the body, but both score the same.

### Solution
When building the token list for each document, repeat title tokens 3x so they have higher BM25 weight.

### Implementation
In `core/indexer.py:build_index()`:

```python
# Current:
text = f"{title} {body}"
tokens = _tokenize(text)

# Proposed:
title_tokens = _tokenize(title)
body_tokens = _tokenize(body)
tokens = title_tokens * 3 + body_tokens  # title weighted 3x
```

This is a 2-line change. BM25's TF component naturally gives higher scores to tokens that appear more frequently, so repeating title tokens 3x makes title matches ~3x more influential.

### Files to Modify
- `src/hivemind/core/indexer.py` — `build_index()` function, token construction

## 3. Blocked Task Reason (`--reason` flag)

### Problem
When a task is marked `blocked`, there's no structured way to record WHY. The next session must read the execution report to understand the blocking reason. The orchestrator pipeline marks tasks blocked when retries exhaust, but the reason is lost.

### Solution
Add a `--reason` option to `hv task update` that stores the blocking reason in the task frontmatter.

### Implementation
In `commands/task.py:update()`:

```python
@click.option("--reason", default=None, help="Reason for blocking (used with --status blocked).")
def update(task_id, status, priority, title, reason):
    ...
    if reason is not None:
        updates["blocked_reason"] = reason
```

The orchestrator pipeline uses this when marking blocked:
```bash
hv task update <TASK-ID> --status blocked --reason "Tests failed after 2 retries: assertion error in test_auth.py line 42"
```

The `hv task get` command shows the reason. The next session's `/hv:task` reads it before deciding how to proceed.

### Files to Modify
- `src/hivemind/commands/task.py` — add `--reason` option to `update` command
- `src/hivemind/core/parser.py` — no change needed (frontmatter is freeform dict)
- `plugin/skills/task/SKILL.md` — update blocked escalation to include `--reason`

## 4. Automatic Incident Recording in Pipeline

### Problem
The `/hv:task` pipeline currently calls `/hv:feedback` as Step 13, which requires user confirmation and blocks unattended execution. Knowledge from failed attempts is lost if the user doesn't manually run feedback.

### Solution
Replace Step 13 with automatic incident recording that writes to the execution report WITHOUT user confirmation and WITHOUT saving to L2 directly.

### Trigger Condition
Only when non-trivial events occurred:
- `coding_retries > 0`
- `test_retries > 0`
- Review had blocking issues

Smooth tasks (no retries, no blocking issues) skip this step entirely.

### Incident Format
Added to the execution report `_reports/{TASK-ID}-report.md`:

```markdown
## Incident

### What broke
- Completion criterion "Rate limiting at 100 req/min" was not met after coding

### Why
- The coding worker implemented the endpoint but did not add rate limiting middleware
- The harness doc features/00_api.md specifies rate limiting in section 3 but the worker did not read that section

### What fixed it
- SendMessage with specific criterion failure → worker added express-rate-limit middleware
- Fixed on retry 1 of 2
```

### Extraction Prompt
The orchestrator uses forensic framing, NOT reflective:
- NOT: "What did you learn?" (produces platitudes)
- YES: "What broke, why, and what fixed it?" (produces specific, searchable facts)

### Pipeline Flow
```
Task completes → check retries/review status
  if non-trivial: write ## Incident to report (automatic)
  always: proceed to next task immediately (NO /hv:feedback, NO user prompt)
```

### Files to Modify
- `plugin/skills/task/SKILL.md` — replace Step 13 with conditional incident recording
- `plugin/skills/task/references/pipeline-stages.md` — update COMPLETE stage

## 5. Unreviewed Incident Reminder

### Problem
Incidents recorded in reports need eventual human review to be promoted to L2 lessons. Without a reminder, they remain buried in report files.

### Solution
At session start, check for reports with `## Incident` sections that haven't been processed, and remind the user.

### Implementation Options

**Option A (SKILL.md)**: Add to `/hv:task` Step 1, before fetching the next task:
```bash
# Check for reports with incidents
grep -rl "## Incident" {data_path}/tasks/{project}/_reports/ | head -5
```
If any found, show: "N reports have unreviewed incidents. Run `/hv:feedback` to promote lessons."

**Option B (CLI)**: New command `hv feedback pending -p project` that lists reports with incidents.

**Option C (Hook)**: Add to `hv-session-log.js` UserPromptSubmit hook — scan reports dir on first prompt.

### Recommended: Option A
Simplest — just a grep in the SKILL.md before starting work. No new commands, no hook changes.

### Files to Modify
- `plugin/skills/task/SKILL.md` — add incident check before Step 1
