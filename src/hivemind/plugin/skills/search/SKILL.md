---
description: "Search the knowledge base for relevant lessons. Use when the user asks to search feedback, find lessons, or needs context from past experiences."
---

# /hv:search -- Knowledge base search

Searches the hivemind knowledge base (L2 documents) using multi-query BM25 ranking.

## When to use

- User asks "what do we know about...", "search for...", "find lessons about..."
- User runs `/hv:search` explicitly
- Before starting implementation, to check for relevant prior knowledge

## Available commands

ONLY these commands exist. Do NOT invent others.

```
hv search "<query>"                    # Search (read-only, no hits increment)
hv search-read "<path>"                # Read document + increment hits
hv index rebuild                       # Rebuild search index
```

The `<path>` for `hv search-read` is the exact Path value from `hv search` output.

## Steps

### 1. Generate English keywords FIRST — NEVER search raw user input

L2 documents are English-only. Your FIRST action must be generating 2-4 English keyword combinations. Do NOT run `hv search` with the user's raw input at all — not even as a first attempt.

Do this silently. Do not explain or mention the translation.

**Examples:**

| User says | Your FIRST searches (no raw input search before these) |
|-----------|-------------------------------------------------------|
| "실시간 검색" | `hv search "real-time search"`, `hv search "websearch live data"` |
| "인증 관련" | `hv search "authentication"`, `hv search "auth login token"` |
| "에러 처리" | `hv search "error handling"`, `hv search "exception retry"` |
| "web search" | `hv search "web search"`, `hv search "websearch fetch URL"` |

### 2. Run multiple searches

```bash
hv search "english keywords 1"
hv search "english keywords 2"
hv search "english keywords 3"
```

### 3. Merge results

Deduplicate by path, keep highest relevance %, sort descending.

### 4. Apply thresholds — MANDATORY, NO EXCEPTIONS

| Relevance | Action |
|-----------|--------|
| **>= 70%** | Run `hv search-read "<path>"` IMMEDIATELY. No table. No asking. Just read and present content. |
| **30-69%** | Ask the user: "Found '{title}' ({relevance}%). Read it?" Run `hv search-read` only if confirmed. |
| **< 30%** | Skip. No read, no hit increment. |

### 5. Handle promotion suggestions

If `hv search-read` suggests promotion (hits >= 3), show it and offer `hv important promote <path>`.

### 6. Rebuild if empty

If ALL searches return nothing: `hv index rebuild`, then retry.

## Rules

- **NEVER run `hv search` with the user's raw input.** Generate English keywords first. Always.
- **NEVER use commands that don't exist** (no `hv root`, `hv config show`, etc.). Only the 3 commands listed above.
- **NEVER Read L2 files directly.** Always use `hv search-read`.
- **>= 70% = auto-read.** Do not ask, do not show a table first.
- **< 30% = skip.** Do not read, do not increment hits.
