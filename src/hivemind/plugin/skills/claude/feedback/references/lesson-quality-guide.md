# L2 Lesson Quality Guide

When extracting lessons for the L2 knowledge base, every lesson must meet these four quality criteria. Low-quality lessons dilute the knowledge base and reduce search relevance.

## Quality Criteria

### 1. Specific
Names the exact technology, pattern, API, or file involved. Vague lessons are useless.

- **Bad:** "Be careful with async code"
- **Good:** "In Python asyncio, always use `async with` for aiohttp sessions to prevent connection pool exhaustion under concurrent requests"

### 2. Actionable
States what to DO (or NOT do), not just what went wrong. A reader should be able to apply this immediately.

- **Bad:** "The database was slow"
- **Good:** "Add `select_related('author')` to Django QuerySets that access ForeignKey fields in loops — prevents N+1 queries that cause 10x latency on list views"

### 3. Contextual
Explains WHEN this lesson applies — which project type, language, framework, or situation. A lesson without context may be applied where it doesn't belong.

- **Bad:** "Always use indexes on database columns"
- **Good:** "For PostgreSQL tables with >100K rows queried by `status` field, add a partial index `WHERE status != 'archived'` — full index wastes space on the 90% of rows that are archived"

### 4. Concise
One paragraph, not an essay. If it takes more than 4-5 sentences, split into multiple lessons.

- **Bad:** A 3-page writeup about authentication that covers OAuth, JWT, session cookies, CORS, and CSRF all in one document
- **Good:** Separate lessons: one for "JWT refresh token rotation pattern", one for "CORS preflight caching with max-age header"

## Anti-Patterns (Do NOT save these)

- **Obvious truths:** "Write tests for your code" — every developer knows this
- **Transient state:** "The CI server is slow today" — not useful next month
- **Tool version notes:** "Upgraded React from 18 to 19" — git log has this
- **Personal preferences:** "I prefer tabs over spaces" — not a lesson
- **Single-use debug info:** "Port 3000 was in use, killed the process" — not reusable

## Template

When writing a lesson, follow this structure:

```
[WHAT to do/avoid] when [CONTEXT/WHEN it applies].
[WHY — the consequence of not following this].
[HOW — specific implementation detail or command].
```

Example:
```
Use `cursor.executemany()` instead of looping `cursor.execute()` when inserting
100+ rows into SQLite. Individual inserts are 50x slower due to per-statement
transaction overhead. Wrap in a single transaction: `with conn: conn.executemany(sql, rows)`.
```
