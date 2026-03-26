# L2 Document Format

L2 (Level 2) documents are the primary knowledge storage units in the hivemind knowledge base. They store lessons learned, patterns, and insights discovered during agent sessions.

## File Location

L2 documents are stored in `{data_path}/level2/{category}/` where category is one of:
- `frontend` -- UI, CSS, JavaScript/TypeScript, components, browser APIs
- `backend` -- APIs, databases, server-side logic, authentication, ORMs
- `infra` -- Docker, CI/CD, deployment, cloud services, monitoring
- `general` -- Everything else that doesn't fit the above categories

## Frontmatter Schema

```yaml
---
title: "API authentication requires token refresh before 401 retry"
category: backend
hits: 3
sources:
  - "my-project:2025-01-15"
  - "my-project:2025-01-20"
  - "other-project:2025-01-22"
promoted: false
created: "2025-01-15"
---
```

## Fields

| Field      | Type       | Description                                               |
|-----------|------------|-----------------------------------------------------------|
| `title`   | string     | Short, searchable description of the lesson               |
| `category`| string     | Auto-detected category (frontend/backend/infra/general)   |
| `hits`    | integer    | Number of times this lesson was accessed or reinforced     |
| `sources` | list[str]  | List of `{project}:{date}` entries tracking where/when    |
| `promoted`| boolean    | Whether this lesson has been promoted to L1 (important.md) |
| `created` | string     | ISO date of initial creation                              |

## Body

The markdown body below the frontmatter contains the full lesson content. Recommended structure:

```markdown
## Problem
What went wrong or what situation was encountered.

## Solution
How it was resolved or what the correct approach is.

## Why
Why this happens and why the solution works.

## Example
Code snippet or concrete example if applicable.
```

## Filename

Filenames are slugified from the title:
- Lowercased
- Special characters removed
- Spaces replaced with hyphens
- Truncated to 60 characters
- Example: `api-authentication-requires-token-refresh-before-401-retry.md`

## Hit Counter and Promotion

- The `hits` field is incremented each time the document is accessed via `hv search`.
- When `hits` reaches the promotion threshold (default: 3), `hv search` suggests promoting the document to L1.
- Promotion is done via `hv important promote <path>`.
- Promoted documents have `promoted: true` and their content is aggregated into `level1/important.md`.

## Similarity Detection

When saving new feedback via `hv feedback save`:
1. BM25 similarity is checked against all existing L2 documents.
2. If a match scores above 0.7, the existing document is updated (hits incremented, source added).
3. If no match is found, a new document is created.

This prevents duplicate lessons and reinforces frequently encountered patterns.
