---
description: "Search the knowledge base for relevant lessons. Use when the user asks to search feedback, find lessons, or needs context from past experiences."
---

# /hv:search -- Knowledge base search

## Available commands

```
hv search "<query>"                    # Search (no hits increment)
hv search-read "<path>"                # Read + increment hits
hv index rebuild                       # Rebuild index
```

## Execution flow

When this skill is invoked, execute these steps IN ORDER without stopping between them:

**Step 1.** Convert user input to 2-3 English keyword combinations. NEVER use the raw user input.

**Step 2.** Run `hv search` for each combination:
```bash
hv search "english keywords 1"
hv search "english keywords 2"
```

**Step 3.** For EVERY result with relevance >= 70%, IMMEDIATELY run:
```bash
hv search-read "<path from results>"
```
Do this right away. Do not present a table. Do not ask. Do not summarize first. Just run the command.

**Step 4.** For results 30-69%, ask the user if they want to read it.

**Step 5.** Present a summary of what was read.

## Example (correct)

User: "웹 검색"

```bash
hv search "web search"           # Step 2
hv search "websearch real-time"  # Step 2
# Results show 100% relevance for a document
hv search-read "level2\general\use-websearch-proactively.md"  # Step 3 — IMMEDIATE
```

Then present the content to the user.

## Example (WRONG — do not do this)

```bash
hv search "웹 검색"              # WRONG: raw Korean input
hv search "web search"
# Shows table, asks "read it?" # WRONG: 100% should auto-read
```

## Rules

- NEVER search with raw user input. English keywords only.
- NEVER stop after search to show a table if any result is >= 70%. Read it first, present after.
- NEVER use nonexistent commands. Only the 3 listed above.
- NEVER read L2 files with the Read tool. Use `hv search-read` only.
