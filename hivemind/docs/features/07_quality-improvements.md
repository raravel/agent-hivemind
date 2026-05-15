# Feature: Quality Improvements

## 1. False Completion Detection

### Problem

The coding agent may claim "done" without addressing all completion criteria. Currently, the only checks are running tests and code review — neither mechanically verifies criteria.

### Solution

Add a verification step in the orchestrator pipeline (between coding and testing) that:

1. Reads the task's `## Completion Criteria` section
2. Parses each `- [ ]` checklist item
3. Reads `git diff` to see actual changes
4. For each criterion, the orchestrator checks if the code changes plausibly address it
5. Outputs a verification table:

```
Completion Criteria Verification:
  [PASS] API endpoint returns 200 on POST /api/todos
  [PASS] Input validation rejects empty title
  [FAIL] Rate limiting at 100 req/min — no rate limit code found
```

6. If any criterion is `[FAIL]`, sends specifics back to coding worker

### Integration Point

This happens in the orchestrator's post-coding verification (see `features/05_orchestrator-pipeline.md`). It is NOT a separate tool or command — it is orchestrator behavior defined in SKILL.md.

## 2. Reviewer Prompt Enhancement

### Problem

The code review agent uses a generic review prompt. It does not specifically check for boundary mismatches (the most common defect pattern per revfactory QA research).

### Solution

Add these rules to the review worker's prompt in `agent-prompts.md`:

```markdown
## Boundary Mismatch Checks

When reviewing code, specifically verify these cross-boundary contracts:
- API response shape matches what the calling code expects
- Function signatures match all call sites
- Type definitions match actual usage
- Config keys match what the code reads
- File paths referenced in code actually exist
- Import paths resolve correctly

For each boundary you identify, read BOTH sides and confirm they agree.
```

## 3. Skill Trigger Description Improvement

### Problem

Some skill descriptions are terse (e.g., `init: "Initialize Agent Hivemind workspace"`), which may cause Claude to be conservative about triggering them.

### Approach

1. Review L3 session logs for cases where a skill should have triggered but didn't
2. For confirmed cases, expand the skill description to be more explicit about trigger conditions
3. Use the "pushy description" pattern: enumerate concrete actions, not abstract categories

### Example

Before:
```yaml
description: Initialize Agent Hivemind workspace
```

After:
```yaml
description: Initialize Agent Hivemind workspace. Use when setting up hivemind for the first time, linking a new project, running /hv:init, or when the user says "init", "setup", "initialize", "link project".
```

Note: This requires data first. Only modify descriptions where missed triggers are observed.

## 4. L2 Lesson Quality & BM25 Search Accuracy

### Problem

The feedback system's value depends on L2 lesson quality and search relevance. Current issues:
- Lessons may be too vague ("always test your code")
- BM25 may surface irrelevant results for short queries
- No guidelines for what makes a good L2 lesson

### Solutions

**A. Lesson writing guidelines** — Add to `feedback/SKILL.md` references:
```markdown
## Good L2 Lesson Criteria
- Specific: names the exact technology, pattern, or API
- Actionable: states what to DO, not just what went wrong
- Contextual: explains WHEN this applies (project type, language, etc.)
- Concise: one paragraph, not an essay

Bad: "Be careful with async code"
Good: "In Python asyncio, always use `async with` for aiohttp sessions
       to prevent connection pool exhaustion under concurrent requests"
```

**B. Query expansion** — The `/hv:search` skill already translates queries to English keyword variations. Improve by:
- Adding synonym expansion (e.g., "auth" → also search "authentication", "login", "session")
- Using compound token splitting already in `_tokenize()` more aggressively

## 5. L2 Feedback ID Origin Tagging

### Problem

Rules in `rules.md` have no traceability to the failures that motivated them.

### Solution

When `/hv:feedback` saves a lesson that leads to a rule being added or updated, tag the rule with the L2 document path:

```markdown
- NEVER store session tokens in localStorage <!-- origin: level2/backend/session-token-storage.md -->
```

This is mechanical (the feedback skill adds the comment when it updates rules) and does not rely on AI-generated provenance.

### Files to Modify

- `plugin/skills/task/SKILL.md` — orchestrator verification steps
- `plugin/skills/task/references/agent-prompts.md` — reviewer boundary mismatch rules
- `plugin/skills/feedback/SKILL.md` — lesson quality guidelines
- `plugin/skills/feedback/references/l2-format.md` — updated format with quality criteria
- Skill description YAML fields across all SKILL.md files (data-driven)
