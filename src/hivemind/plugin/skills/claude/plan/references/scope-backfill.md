# Scope back-fill (opt-in, never auto)

Procedure for populating `scope` on existing scope-less pending tasks. Invoked only when the user explicitly asks to "add scope to existing tasks". Never run by default — new projects must not pay this context cost.

## Trigger

User message contains an explicit request to back-fill scope (e.g. "add scope to existing tasks", "back-fill scope on the pending pool"). Never infer the request from anything else.

## Steps

1. **List scope-less pending tasks**: `hv task list -p PROJECT -s pending --flat` and select entries whose frontmatter has missing or empty `scope`. Use `hv task get <id>` per candidate to confirm.
2. **For each candidate:**
   - Read the task's `## Spec References` block.
   - Open each referenced feature spec and find the `## Implementation` section.
   - Identify the minimum honest subset of paths the task will actually touch. NEVER speculate paths that are not anchored in the referenced spec.
   - If the minimum honest subset cannot be identified, propose `["*"]` (solo) — do NOT guess.
3. **Show the user a per-task diff before applying:**
   ```
   TASK-001  scope: [] → ["src/foo.py", "manifest:python"]
   TASK-002  scope: [] → ["*"]  (unenumerable — see Implementation: refactor)
   ```
4. **Single yes/no confirmation** for the whole batch. Never apply silently. Never apply partial changes from a "yes to some" — the user re-runs with a narrower selection if they disagree.
5. **Apply** with `hv task scope-set <id> <entry> [<entry>...]` per task.
6. **Report** the counts:
   - applied with concrete scope: N
   - applied with `["*"]` (under-specified feature spec — surface to user): M
   - skipped (user declined or task ineligible): K

## Guarantees

- Never auto-applied. Even after confirmation, apply via `hv task scope-set`, not by editing frontmatter directly.
- Never speculative. Anchor every path to a `## Implementation` entry in a referenced feature spec, or fall back to `["*"]`.
- The `["*"]` count is reported separately so the user can spot features whose specs under-document the implementation surface.
