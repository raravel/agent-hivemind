---
description: "Score the project's harness documents (architecture.md, tech-stack.md, rules.md, verify.md, features/*.md) on 5 design-quality axes using LLM judgment. Use when the user asks 'how good is our harness', or automatically after hv-plan generates or refreshes harness docs. Cached; re-runs only when harness content changes."
---

# hv-score-harness — Harness design-quality scoring

You apply the rubric in [references/rubric.md](references/rubric.md) to the current project's harness documents and produce a 5-axis score. The CLI stores results in `_harness_scores.jsonl` so `hv stats --harness` can show a trend.

## When to use

- User asks how mature / well-designed the harness is
- Right after `hv-plan` finishes writing harness docs (establish baseline)
- Periodic maintenance (weekly/monthly)
- User invokes `hv-score-harness` explicitly

## Rules

- **Temperature 0** when you (the orchestrator) generate scores. Determinism matters for trend tracking.
- You do not hash or compute overall totals; the CLI does both. You only supply per-axis scores, rationales, and recommendations.
- English only in rationales and recommendations (BM25/stats consistency).

## Steps

### 1. Identify the project

Read `.hivemind-link.json` in the cwd for the project name. If missing, ask the user which linked project to score.

### 2. Cache check

```bash
hv harness-score show -p <project> --if-fresh 7d
```

- Exit 0 → A fresh score already exists for the current harness content. Display the stdout as-is and STOP. Do NOT call the LLM again.
- Exit 2 → Stale or not recorded. Proceed to step 3.

### 3. Read harness documents

Read all of the following (skip missing files, do not fail):

- `{data_path}/projects/{project}/architecture.md`
- `{data_path}/projects/{project}/tech-stack.md`
- `{data_path}/projects/{project}/rules.md`
- `{data_path}/projects/{project}/verify.md` (fallback: `build-verify.md`)
- `{data_path}/projects/{project}/features/*.md`

If no harness docs exist at all, STOP and tell the user to run `hv-plan` first.

### 4. Score each axis per the rubric

For each of these 5 axes, consult [references/rubric.md](references/rubric.md) and produce:

- `score`: integer 0–10
- `rationale`: ONE sentence citing concrete evidence from the docs (file names, missing sections, counts — not vague adjectives)
- `recommendations`: up to 2 concrete, actionable items (each < 120 chars)

Axes:
1. `architecture` — structural clarity, Mermaid diagrams, module boundaries, dependency direction
2. `specs_detail` — `features/*.md` completeness: inputs, outputs, error/edge cases
3. `rules_clarity` — NEVER/ALWAYS rules are concrete, non-overlapping, actionable
4. `tech_stack` — libraries have versions, usage examples, rationale
5. `verification` — `verify.md` covers lint/type/test/build for the declared stack, language-agnostic phrasing

### 5. Record the score

Pipe the JSON into the CLI. Use a heredoc so quoting is stable:

```bash
cat <<'JSON' | hv harness-score record -p <project> --from-stdin
{
  "axes": {
    "architecture":    {"score": 8, "rationale": "...", "recommendations": ["...", "..."]},
    "specs_detail":    {"score": 6, "rationale": "...", "recommendations": ["..."]},
    "rules_clarity":   {"score": 9, "rationale": "...", "recommendations": []},
    "tech_stack":      {"score": 5, "rationale": "...", "recommendations": ["..."]},
    "verification":    {"score": 7, "rationale": "...", "recommendations": ["..."]}
  }
}
JSON
```

- Exit 0 → recorded. CLI prints the full formatted score. Show that output to the user.
- Exit non-zero → payload validation failed. Read the stderr message, fix the JSON, try once. Do not work around the validation.

### 6. Explain next steps to the user (one line each)

- If `overall < 50%` of max: recommend `hv-plan` to fill gaps
- If any axis scored ≤ 3: name the axis and its top recommendation
- Otherwise: mention `hv harness-score history -p <project>` to see the trend

## Important rules

- **NEVER** invent evidence. Every rationale must cite something verifiable from the docs (a file, a missing section, a keyword count).
- **NEVER** run the LLM pass if step 2 returned fresh. Re-running wastes tokens and adds noise to the trend.
- **NEVER** edit the harness docs yourself. That's `hv-plan`'s job. Your output is only scores + recommendations.
- **ALWAYS** use the `reviewer` model from the active profile (same model used by `hv-task`'s 4-axis code review judge). Consistency across judgment tasks keeps the harness score comparable with code review score trends.
