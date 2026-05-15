---
description: "Save a learning directly to L2 or a harness doc via 'hv feedback save'. Single entry point; no draft queue; no confirmation. Called by hv-task auto pipeline or by the user."
---

# hv-feedback -- Direct lesson save

Extracts a lesson from the current session or task incident and saves it
immediately via `hv feedback save`. No drafts, no human gate. The CLI
enforces the quality gate; binding combinations (features / tech-stack
Active Dependencies) bypass it automatically. Every successful save is
an isolated git commit so it can be auto-reverted if subsequent review
scores regress (see hv-task step 15.5).

## When to use

- At the end of `hv-task` (called by step 15 auto-save)
- When the user says "save feedback", "remember this", "record this lesson"
- After a notable bug fix or convention discovery

## Steps

### 1. Identify the lesson

Compose a concise lesson following the criteria in
[references/lesson-quality-guide.md](references/lesson-quality-guide.md):

- **Specific**: name the technology, file path, or identifier
- **Actionable**: use a verb -- `use`, `avoid`, `set`, `add`, `prefer`, etc.
- **Contextual**: explain when this applies (one phrase)
- **Concise**: 50-500 characters

### 2. Pick a target

| Target | When to use | Example |
|---|---|---|
| `L2` | Generic, reusable across projects | "FastAPI CORSMiddleware must precede custom middleware" |
| `rules` | NEVER/ALWAYS rule specific to THIS project | "NEVER import from `src/legacy/` -- scheduled for Q3 removal" |
| `tech-stack` | Library version / compat decision for THIS project's stack | "Pin python-frontmatter==1.1.0 until #42 fixes stdin handling" |
| `architecture` | Module boundary / dependency direction for THIS project | "`hivemind.core` must not import from `hivemind.commands`" |
| `features` | File-path binding to a feature (mechanical, not a lesson) | "`src/auth/jwt.py` -- token validation" |

**Rule of thumb**: if the lesson names *this project's* files / modules /
policies → harness target. If it names a *public library behavior* the
same way any project would → `L2`.

### 3. Save

```bash
hv feedback save \
  -p <project> \
  --task <TASK-ID> \
  --title "<title>" \
  --target <L2|rules|tech-stack|architecture|features> \
  [--feature <slug>] \
  [--section "<heading>"] \
  -c /tmp/lesson.txt
```

Or pipe via stdin:

```bash
echo "<lesson body>" | hv feedback save \
  -p <project> --task <TASK-ID> -t "<title>" --target <target>
```

### 4. Handle the result

- Exit 0 → docs updated + isolated git commit (subject contains
  `[lesson:<TASK-ID>]`) + entry appended to
  `hivemind/reflect/lesson-log.jsonl`. Echo the CLI output as-is.
- Exit 1 → quality gate rejected the lesson. Read the reason from
  stderr. Make ONE attempt to fix the lesson (add a verb, name a
  concrete tech, shorten / extend). If the second attempt is also
  rejected, stop -- do NOT pass `--skip-gate`.
- Exit 2 → usage error (missing `--feature`, etc.). Fix and retry.

## Rules

- **English only** for titles, content, rationale. The BM25 index expects English.
- **NEVER write feedback files directly.** Use `hv feedback save` -- it
  handles category detection, BM25 dedup, doc append, and the isolated
  lesson commit atomically.
- **Quality gate is enforced by the CLI.** Do NOT pass `--skip-gate`.
  Binding combinations are bypassed automatically; explicit skip is
  reserved for very narrow caller overrides and is not used here.
- **One lesson per call.** If a session yields multiple lessons, call
  `save` once per lesson with the appropriate `--target` for each.
- **Binding writes are mechanical.** When you use `--target features
  --feature <slug>` or `--target tech-stack --section 'Active
  Dependencies'`, the entry is a binding record (not a reusable lesson)
  and bypasses the quality gate. Use these only for file-path / pinned-
  version records, never for prose lessons.

## Related commands

- `hv feedback applied -p <project> --limit N [--format json]` -- list
  recent lesson-log entries.
- `hv feedback rollback -p <project> --commit <hash> [--reason TEXT]`
  -- revert a lesson commit. Called automatically by `hv-task` step 15.5
  when trailing review scores regress.

## Removed in v5

The earlier draft queue (`hv feedback draft-add` →
`hv feedback promote-drafts`) is gone. Those commands remain as
deprecated stubs that redirect to `save` for backwards compatibility but
will be removed in the next major version. The "ALWAYS get user
confirmation" rule and the `fully automated mode` distinction are also
gone: there is one path, and it never blocks for human input.

See [references/l2-format.md](references/l2-format.md) for the L2
document format and
[references/lesson-quality-guide.md](references/lesson-quality-guide.md)
for the quality gate criteria the CLI enforces.
