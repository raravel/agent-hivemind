---
description: "Search the knowledge base for relevant lessons. Use when the user asks to search feedback, find lessons, or needs context from past experiences."
---

# /hv:search -- Knowledge base search

Searches the hivemind knowledge base (L2 documents) using multi-query BM25 ranking. Automatically translates any query into English keywords, runs multiple searches, and applies relevance thresholds to decide what to read.

## When to use

- User asks "what do we know about...", "search for...", "find lessons about..."
- User runs `/hv:search` explicitly
- Before starting implementation, to check for relevant prior knowledge
- Called internally by `/hv:task` to load context for the coding agent

## Steps

### 1. Generate English keyword combinations (NEVER search raw user input)

L2 documents are English-only. **NEVER pass the user's raw input directly to `hv search`.** Always generate 2-4 English keyword combinations first, then search ONLY with those.

Do NOT mention this translation to the user. Just do it silently.

**Examples:**

| User says | You search with |
|-----------|----------------|
| "실시간 검색" | `"real-time search"`, `"websearch live data"`, `"web search current"` |
| "인증 관련 교훈" | `"authentication"`, `"auth login token"`, `"authorization session"` |
| "how to handle errors" | `"error handling"`, `"exception retry fallback"`, `"failure recovery"` |
| "DB 성능" | `"database performance"`, `"query optimization slow"`, `"SQL index"` |

### 2. Run multiple searches

Run `hv search` for EACH keyword combination:

```bash
hv search "keyword combination 1"
hv search "keyword combination 2"
hv search "keyword combination 3"
```

`hv search` does NOT increment hits — it only returns results with relevance %.

### 3. Merge results

Combine results from all queries:
- Deduplicate by document path
- Keep the highest relevance % for each document
- Sort by relevance descending

### 4. Apply relevance thresholds — MANDATORY, NO EXCEPTIONS

You MUST follow these rules AUTOMATICALLY. Do NOT ask the user for confirmation on >= 70% documents. Do NOT present a table and wait — just read them immediately.

| Relevance | Action | User confirmation |
|-----------|--------|-------------------|
| **>= 70%** | Run `hv search-read <path>` IMMEDIATELY. No questions. No table. Just read it and present the content. | **NO — forbidden to ask** |
| **30-69%** | Ask the user: "Found a possibly relevant lesson: '{title}' ({relevance}%). Read it?" Only run `hv search-read <path>` if confirmed. | **YES — required** |
| **< 30%** | Skip entirely. Do not read, do not increment hits. | N/A |

### 5. Read selected documents

For documents selected by auto-read or user confirmation:

```bash
hv search-read "<doc_path>"
```

This command:
- Prints the full document content
- Increments the hit counter
- Suggests promotion if hits >= 3

### 6. Handle promotion suggestions

If `hv search-read` outputs a promotion suggestion:
- Show it to the user
- Offer to promote: `hv important promote <path>`

### 7. Rebuild index if needed

If ALL searches return no results but you suspect documents exist:
```bash
hv index rebuild
```
Then retry.

## Important Rules

- **ALWAYS translate queries to English keywords** before searching. L2 docs are English-only.
- **ALWAYS run 2-4 search variations** with different keyword combinations.
- **NEVER run `hv search-read` on documents below 30% relevance.**
- **NEVER run `hv search-read` on 30-69% documents without user confirmation.**
- **ONLY `hv search-read` increments hits** — `hv search` is read-only.
- ALWAYS use Bash tool for `hv` commands. Do NOT read L2 files directly.
