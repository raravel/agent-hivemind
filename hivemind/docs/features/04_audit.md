# Feature: Audit (Spec-Code Drift Detection)

## Overview

`hv audit` detects inconsistencies between harness specs and the actual codebase, plus stale completed tasks.

## Command

### `hv audit -p PROJECT [--fix]`

## Detection Logic

### 1. Code Without Spec

- Runs `git ls-files` in the linked project directory
- Loads all harness spec files from `projects/{project}/**/*.md`
- Extracts module references from specs (backtick-wrapped paths like `` `src/foo.py` `` and bare path patterns)
- Reports code files not mentioned in any spec

### 2. Spec Without Code

- For each reference found in spec files, checks if the corresponding file exists in git
- Reports spec references pointing to non-existent code files
- Useful for catching deleted/renamed files still referenced in specs

### 3. Stale Tasks

- Scans `tasks/{project}/*.md` for `done` tasks
- Calculates days since `updated` date
- Reports tasks done more than 30 days ago (`STALE_DAYS = 30`)
- Suggests: archive or reopen if still relevant

## Module Reference Extraction

Two patterns are matched:

1. **Backtick paths**: `` `path/to/file.ext` `` — any backtick-wrapped text ending in `.{1-4 char extension}`
2. **Bare paths**: `word/word.ext` — path-like strings ending in common code extensions (`.py`, `.js`, `.ts`, `.rs`, `.go`, `.java`, `.rb`, `.cpp`, `.c`, `.h`)

Path matching is flexible: exact match, suffix match, or prefix match (handles relative vs absolute paths).

## Fix Mode (`--fix`)

When `--fix` is passed, appends a "Fix Suggestions" section:
- Code without spec -> "Create spec documentation for {file}"
- Spec without code -> "Update {spec}: remove or update reference to {ref}"
- Stale tasks -> "Review {task_id} — archive or reopen if still relevant"

Note: `--fix` only prints suggestions, it does not auto-fix.

## Output Format

```
=== Drift Report: my-app ===

Code without spec:
  - src/utils/helpers.py
  - src/api/v2/routes.py

Spec without code:
  - architecture.md → referenced module not found: src/old_module.py

Stale tasks:
  - MYA-003 (done 45 days ago, no recent activity)

Total: 4 issues found
```
