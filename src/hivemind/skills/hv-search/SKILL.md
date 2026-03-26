# /hv:search -- Knowledge base search

Searches the hivemind knowledge base (L2 documents) using BM25 ranking and loads matching content into context. Reports hit counts and suggests promotions for frequently accessed lessons.

## When to use

- User asks "what do we know about...", "search for...", "find lessons about..."
- User runs `/hv:search` explicitly
- Before starting implementation, to check for relevant prior knowledge
- Called internally by `/hv:run-task` to load context for the coding agent

## Steps

### 1. Run the search

```
hv search "<query>"
```

Optionally filter by project:
```
hv search "<query>" -p <project>
```

The command:
- Loads or builds the BM25 index from L2 documents
- Returns the top 5 matching documents ranked by relevance score
- Increments the `hits` counter on each matched document
- Checks for promotion candidates (hits >= 3 and not yet promoted)

### 2. Present results

The output is a table with columns:
- **Score**: BM25 relevance score
- **Path**: Relative path to the L2 document
- **Title**: Document title from frontmatter
- **Hits**: Total access count

Show the user the results table. If specific documents are highly relevant, read their full content and present key insights.

### 3. Handle promotion suggestions

If the output includes promotion suggestions (documents with hits >= 3 that are not yet promoted):
- Show the suggestion to the user
- Offer to promote via `/hv:important` or:
  ```
  hv important promote <path>
  ```

### 4. Rebuild index if needed

If search returns no results but you suspect documents exist, rebuild the index:
```
hv index rebuild
```
Then retry the search.

## Important Rules

- ALWAYS use `hv search` via Bash tool. Do NOT directly read L2 files for search purposes.
- ALWAYS report the number of hits and any promotion suggestions to the user.
- NEVER modify L2 documents directly. The `hv search` command handles hit counting automatically.
- If the user asks about a topic and search returns relevant results, present the key lessons before starting implementation.
- Use specific, keyword-rich queries for better BM25 matching (e.g., "react state management" not "how to manage state").
