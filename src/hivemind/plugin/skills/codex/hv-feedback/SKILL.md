---
description: "Extract and save session feedback as L2 lessons. Use at the end of a session or when the user wants to record lessons learned."
---

# hv-feedback -- Session feedback extraction

Extracts lessons learned from the current conversation or work session and saves them as L2 (Level 2) documents in the hivemind knowledge base. Always confirms with the user before saving.

## When to use

- End of a coding session where something notable was learned
- After a bug fix where the root cause is worth documenting
- After discovering a project convention or gotcha
- User says "save feedback", "record this lesson", "remember this"
- User asks the `hv` plugin to save feedback explicitly
- Called at the end of the `hv-task` pipeline

## Steps

### 1. Identify lessons learned

Review the current conversation for:
- Bug root causes and their fixes
- Project-specific conventions discovered
- Tool configurations or environment quirks
- Patterns that worked well (or didn't)
- Common pitfalls to avoid

Compose a concise lesson following the quality criteria in [references/lesson-quality-guide.md](references/lesson-quality-guide.md):
- **Specific**: Name the exact technology, pattern, or API
- **Actionable**: State what to do, not just what went wrong
- **Contextual**: Explain when this applies
- **Concise**: One paragraph, not an essay

### 2. Present the lesson to the user for confirmation

Show the user:
- **Title**: The proposed lesson title
- **Category**: Auto-detected category (frontend/backend/infra/general)
- **Content**: The full lesson text

Ask: "Save this feedback to the knowledge base?"

**ALWAYS wait for user confirmation before proceeding.**

### 3. Save the feedback

Write the lesson content to a temporary file and pass it to the CLI:
```
hv feedback save -p <project> -t "<title>" -c /tmp/hv-feedback-content.txt
```

Or pipe via stdin:
```
echo "<lesson content>" | hv feedback save -p <project> -t "<title>"
```

The `hv feedback save` command will:
- Run BM25 similarity check against existing L2 documents
- If a similar lesson exists: increment its hit count and add a source link
- If no similar lesson exists: create a new L2 document
- Auto-detect the category (frontend/backend/infra/general)
- Update the search index

### 4. Report results

Show the user:
- Whether a new document was created or an existing one was updated
- The file path of the affected document
- The detected category
- If the document has high hits, suggest promotion to L1

See [references/l2-format.md](references/l2-format.md) for the L2 document format.

## Important Rules

- ALWAYS get user confirmation before saving feedback. This is a mandatory rule with NO exceptions.
- NEVER write L2 documents in Korean. All titles and content must be in English.
- NEVER manually create or edit L2 markdown files. Always use `hv feedback save` via Bash.
- NEVER save trivial or obvious information. Focus on non-obvious lessons that future agents would benefit from.
- When a saved lesson leads to adding a new rule in `rules.md`, tag the rule with origin: `<!-- origin: level2/category/slug.md -->`
- ALWAYS include a clear, descriptive title that future searches can match against.
- If the user declines to save, respect their decision and do NOT save.
- When called from `hv-task`, still present the lesson and ask for confirmation unless running in fully automated mode.
