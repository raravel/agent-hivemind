# Feature: Knowledge Base (Search & Feedback)

## Overview

Three-tier knowledge system: L3 (raw session logs) -> L2 (structured lessons) -> L1 (critical lessons). BM25-based search and similarity deduplication.

## Feedback Tiers

### L3 — Session Logs

- **Source**: Auto-saved by `hv-session-log.js` hook on `UserPromptSubmit` and `Stop` events
- **Location**: `level3/{project}/{YYYYMMDD}_{session_id}.md`
- **Format**: Raw conversation messages with timestamps
- **Retention**: Append-only, never deleted

### L2 — Structured Lessons

- **Source**: Extracted by `/hv:feedback` skill -> `hv feedback save` command
- **Location**: `level2/{category}/{slugified-title}.md`
- **Categories**: `frontend`, `backend`, `infra`, `general` (auto-detected by keyword matching)
- **Dedup**: BM25 similarity check (threshold 0.7) — updates existing doc if similar
- **Format**:

```yaml
---
title: "Use parameterized queries for SQL"
category: backend
hits: 3
sources: ["my-app:2025-01-15", "my-app:2025-01-20"]
promoted: false
created: 2025-01-15
---

Always use parameterized queries instead of string concatenation
to prevent SQL injection attacks. This applies to all database
access patterns regardless of the ORM being used.
```

### L1 — Critical Lessons

- **Source**: Promoted from L2 when `hits >= 10`
- **Location**: `level1/important.md`
- **Format**: Merged document sorted by hit count (highest first)
- **Management**: `hv important promote PATH`, `hv important demote QUERY`, `hv important generate`

## Commands

### `hv feedback save -p PROJECT [-t TITLE] [-c CONTENT_FILE]`

1. Read lesson text from file or stdin
2. Auto-detect title from first line if not provided
3. Run BM25 similarity check against existing L2 docs
4. If similar (>= 0.7): increment `hits` counter on existing doc, add source
5. If new: create new L2 doc with auto-detected category
6. Rebuild `index.json`
7. Auto-commit if enabled

### `hv search QUERY [-p PROJECT] [--auto-read]`

1. Tokenize query (lowercasing, camelCase split, hyphen/underscore split)
2. Run BM25 search against `index.json`
3. Return top-k results with scores
4. With `--auto-read`: display full content of high-relevance docs

### `hv search-read PATH`

- Read and display a specific L2 document
- Increments the `hits` counter

### `hv index rebuild`

- Scan all `level2/**/*.md` files
- Tokenize title + body of each
- Save to `index.json`

### `hv important promote PATH`

- Add an L2 doc to `level1/important.md`
- Set `promoted: true` in the L2 doc's frontmatter

### `hv important demote QUERY [--yes]`

- Remove a lesson from `level1/important.md`
- Reset `promoted: false` in the L2 doc

### `hv important generate`

- Regenerate `level1/important.md` from all promoted L2 docs
- Sorted by hit count descending

## BM25 Implementation Details

### Tokenization (`core/indexer.py:_tokenize`)

```
"WebSearch"    -> ["websearch", "web", "search"]
"real-time"    -> ["real-time", "real", "time"]
"test_case"    -> ["test_case", "test", "case"]
"don't"        -> ["don't"]
```

- Lowercase all tokens
- Split camelCase words (only if word contains uppercase)
- Split hyphenated and underscored words
- Strip punctuation from boundaries

### Search Behavior

- **>= 3 docs**: Full BM25Okapi scoring
- **< 3 docs**: Falls back to token overlap scoring (BM25 IDF goes negative with tiny corpora)
- Results filtered to `score > 0`, sorted descending, top-k returned

### Category Detection (`commands/feedback.py:detect_category`)

Keyword matching with regex word boundaries:
- `frontend`: react, vue, css, html, ui, component, browser, dom, etc.
- `backend`: api, server, database, sql, rest, auth, middleware, orm, etc.
- `infra`: docker, kubernetes, ci, cd, deploy, terraform, aws, etc.
- `general`: fallback when no category scores > 0

### Similarity Check (`core/similarity.py:find_similar`)

- Builds fresh index from `level2/` on every call
- Searches with `top_k=10`
- Returns only results with `score >= threshold` (default 0.7)
