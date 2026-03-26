# /clarify -- Requirement ambiguity resolution

Evaluates implementation requests across 7 ambiguity axes using Socratic questioning. Iterates until all axes score <= 0.2 before allowing work to begin.

## When to use

Invoke `/clarify` BEFORE starting any implementation work when the user requests:
- make, build, create, add, implement, refactor (in any language)

## Exemptions (do NOT invoke)

- Information queries (explain, search, find, tell me)
- Reading or searching existing code
- Tasks with existing spec documents
- Bug fixes with explicit cause and scope

## The 7 Ambiguity Axes

| # | Axis | Tag | Core Question |
|---|------|-----|---------------|
| 1 | Purpose | Why | Why build this? What problem does it solve? |
| 2 | Scope | Scope | Where does it start and end? |
| 3 | Technical Context | How | What tech stack, environment, project? |
| 4 | Integration | Fit | How does it fit with existing systems? Any conflicts? |
| 5 | User/IO | Who/What | Who uses it? What are inputs and outputs? |
| 6 | Done Criteria | Done | What are the must_haves to confirm completion? |
| 7 | Constraints | Constraints | What must be followed or avoided? |

## Steps

### 1. Receive the implementation request

Parse the user's request and identify what is being asked for.

### 2. Score each axis (0.0 -- 1.0)

Evaluate how much ambiguity exists on each axis based on the information provided. Use the scoring guide at [references/scoring-guide.md](references/scoring-guide.md) for detailed criteria.

- **0.0**: Fully clear, no questions needed
- **0.2**: Mostly clear, minor gaps that can be inferred
- **> 0.2**: Ambiguous, requires clarification

### 3. Present the scoreboard

Display the current scores in a compact table:

```
Axis         Score  Status
───────────  ─────  ──────
Purpose      0.1    PASS
Scope        0.5    ASK
How          0.2    PASS
Fit          0.3    ASK
Who/What     0.4    ASK
Done         0.6    ASK
Constraints  0.1    PASS
```

### 4. Ask Socratic questions for axes scoring > 0.2

For each axis that needs clarification:
- Ask 1-2 focused questions per axis
- Questions should be specific and actionable, not generic
- Group related questions together to minimize round-trips
- Frame questions to help the user think through their own requirements

### 5. Re-score after each answer

After the user responds:
1. Update scores based on new information
2. Display the updated scoreboard
3. If any axes still score > 0.2, ask follow-up questions
4. Repeat until ALL axes score <= 0.2

### 6. Output the confirmed spec

When all axes pass (<= 0.2), output a structured spec block:

```
--- Confirmed Spec ---

Purpose:      <why this is being built>
Scope:        <boundaries of the work>
How:          <tech stack, environment, approach>
Fit:          <integration points, compatibility>
Who/What:     <users, inputs, outputs>
Done:
  truths:     <statements that must be true after completion>
  artifacts:  <files/outputs that must exist>
  key_links:  <connections between artifacts>
Constraints:  <rules, limitations, things to avoid>
```

### 7. Proceed with implementation

After outputting the confirmed spec, proceed with the implementation work.

## Done Criteria: must_haves Pattern

The Done axis uses a structured **must_haves** pattern with three components:

| Component | Description | Example |
|-----------|-------------|---------|
| **truths** | Statements that must be true after completion | "All tests pass", "API responds under 200ms" |
| **artifacts** | Files or outputs that must exist | "src/auth/login.ts", "migration file", "test file" |
| **key_links** | Connections between artifacts that must hold | "Router imports login handler", "Migration references users table" |

When scoring the Done axis:
- If all 3 must_haves are explicitly stated or clearly inferable: score <= 0.2
- If only general expectations exist ("it should work"): score >= 0.5
- Always push toward concrete truths, artifacts, and key_links

## Important Rules

- NEVER skip clarification for implementation requests. This is mandatory.
- NEVER start coding before all axes score <= 0.2.
- ALWAYS show the scoreboard so the user can see progress.
- ALWAYS ask Socratic questions -- guide the user to think through requirements, don't just demand answers.
- When context makes an axis self-evident (e.g., the codebase is a Python project so "How" is obvious), score it low and move on. Do not ask unnecessary questions.
- Minimize round-trips: batch questions for multiple axes in a single message.
- If the user explicitly says "just do it" or "skip clarification", respect their choice but warn them once about potential ambiguity.
