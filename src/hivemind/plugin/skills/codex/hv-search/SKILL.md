---
description: "Search the knowledge base for relevant lessons. Use when the user asks to search feedback, find lessons, or needs context from past experiences."
---

# hv-search -- Knowledge base search

> **Worker-mode guard.** If you were spawned as a sub-worker by another orchestrator (for example via `codex:codex-rescue` from inside `hv-task`), do NOT engage this skill. Read the orchestrator's prompt literally and execute exactly what it asks. The hv-* skills are for direct user invocation, not nested execution. Signals you are a sub-worker: the prompt starts with `--fresh` or `--resume`, or contains explicit instructions like "Step A:", "Step B:", "Review only", "Implement <TASK-ID>", or "Edit only inside the current working directory".

## Execution

**Step 1.** Convert user input to 2-3 English keyword combinations. NEVER use raw user input. Do this silently.

**Step 2.** Run search with `--auto-read` for each combination:

```bash
hv search --auto-read "english keywords 1"
hv search --auto-read "english keywords 2"
```

The `--auto-read` flag makes the CLI automatically:
- **>= 70% relevance**: Print full document content + increment hits
- **30-69%**: List title and path (you ask user if they want to read)
- **< 30%**: Hidden

**Step 3.** If any 30-69% docs were listed, ask the user. If confirmed:
```bash
hv search-read "<path>"
```

**Step 4.** If ALL searches return nothing: `hv index rebuild`, then retry.

## Example

User: "웹 검색"

```bash
hv search --auto-read "web search"
hv search --auto-read "websearch real-time"
```

Output automatically includes full content of high-relevance docs.

## Available commands

```
hv search --auto-read "<query>"   # Search + auto-read >= 70% docs
hv search-read "<path>"           # Read a specific doc + increment hits (use for 30-69% docs user confirmed)
hv index rebuild                  # Rebuild search index
```

## Rules

- NEVER search with raw user input. English keywords only. Silently.
- ALWAYS use `--auto-read` flag when searching.
- Use `hv search-read "<path>"` to read 30-69% docs that the user confirms.
- NEVER use nonexistent commands. Only the 3 above.
