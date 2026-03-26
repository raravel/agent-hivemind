# /hv:important -- L1 promote/demote orchestration

Manages the L1 (Level 1) knowledge layer by promoting high-value L2 lessons to `important.md` or demoting them. L1 content is the curated, high-signal knowledge that is always loaded into agent context.

## When to use

- User wants to promote a frequently-hit lesson to L1
- User wants to demote an L1 lesson that is no longer relevant
- `hv search` suggests a promotion candidate
- User says "promote this", "make this important", "remove from important"
- User runs `/hv:important` explicitly
- After significant knowledge base changes, to regenerate important.md

## Steps

### Promoting an L2 document to L1

1. **Identify the document to promote.** Use the relative path from `hv search` output:
   ```
   hv important promote level2/backend/api-auth-token-refresh.md
   ```

2. **Review the output.** The command:
   - Sets `promoted: true` in the L2 document's frontmatter
   - Regenerates `level1/important.md` from all promoted documents
   - Reports the path to the generated file

3. **Show the updated important.md.** Read and display the current L1 content so the user can verify:
   ```
   hv search "<topic>"
   ```
   Or read the important.md file directly to confirm the promoted content is included.

### Demoting an L1 document

1. **Search for the document to demote:**
   ```
   hv important demote "<search query>"
   ```
   This searches only among currently promoted documents and shows the top match.

2. **Confirm the demotion.** The command asks for confirmation (unless `--yes` is passed):
   ```
   hv important demote "<query>" --yes
   ```

3. **Review the output.** The command:
   - Sets `promoted: false` in the L2 document's frontmatter
   - Regenerates `level1/important.md` without the demoted document

### Regenerating important.md

To rebuild `important.md` from all currently promoted L2 documents:
```
hv important generate
```

This is useful after manual changes or to ensure consistency.

## Important Rules

- NEVER manually edit `level1/important.md`. Always use `hv important generate` to regenerate it.
- NEVER manually edit L2 document frontmatter to set `promoted: true/false`. Use `hv important promote` and `hv important demote`.
- ALWAYS show the user what will be promoted/demoted before executing (unless they've already specified the exact path).
- ALWAYS use Bash tool to run `hv` CLI commands. Do NOT import Python modules directly.
- The `promote` command takes a path relative to the data directory (e.g., `level2/backend/api-auth.md`).
- The `demote` command takes a search query string, not a path.
- L1 content in `important.md` is sorted by hits (highest first).
- NEVER write important.md content in Korean. All content must be in English.
