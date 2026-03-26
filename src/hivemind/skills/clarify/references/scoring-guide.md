# Scoring Guide -- 7 Ambiguity Axes

Detailed scoring criteria for each axis. Scores range from 0.0 (fully clear) to 1.0 (completely unknown). The clarification threshold is 0.2 -- any axis scoring above this requires Socratic questioning.

---

## Axis 1: Purpose (Why)

**Core Question:** Why build this? What problem does it solve?

| Score | Criteria |
|-------|----------|
| 0.0 | Problem statement is explicit. User has stated the "why" clearly, including who benefits and what changes. |
| 0.2 | Purpose is mostly clear from context. Minor gaps exist but can be inferred from the request and project domain. |
| 0.3 | New project or exploratory work. Purpose is directional but not tied to a specific problem yet. |
| 0.5 | User described *what* to build but not *why*. The motivation is ambiguous -- could serve multiple purposes. |
| 0.8 | Request is a vague directive ("make it better", "add some features") with no discernible motivation. |

**Example questions to ask:**
- "What problem are you running into that this would solve?"
- "Who benefits from this change, and how does their workflow improve?"
- "What happens if we don't build this?"

---

## Axis 2: Scope (Scope)

**Core Question:** Where does it start and end?

| Score | Criteria |
|-------|----------|
| 0.0 | Boundaries are explicitly stated. User has specified what is included, what is excluded, and rough size. |
| 0.2 | Scope is mostly clear. One or two edge cases are unspecified but inferable from context. |
| 0.3 | New project where scope equals the full initial deliverable. No ambiguity because there is no existing boundary to conflict with. |
| 0.5 | Core deliverable is clear but boundaries are fuzzy. Could reasonably include or exclude adjacent features. |
| 0.8 | Request is open-ended ("build an auth system") with no indication of how far to go. |

**Example questions to ask:**
- "Should this include [adjacent feature] or is that out of scope?"
- "How many [entities/endpoints/pages] are we talking about?"
- "Is this a minimal first version or a complete implementation?"

---

## Axis 3: Technical Context (How)

**Core Question:** What tech stack, environment, project?

| Score | Criteria |
|-------|----------|
| 0.0 | Stack, framework, runtime, and target environment are all stated or visible in project config. |
| 0.2 | Most technical context is evident from the codebase. One minor detail (e.g., target Node version) is unspecified but inferable. |
| 0.3 | New project where the tech stack itself is part of the decision. User has expressed a preference but details are open. |
| 0.5 | Project exists but the request involves unfamiliar territory (new library, different pattern) not established in the codebase. |
| 0.8 | No project context. User has not specified language, framework, or environment, and no codebase is available to infer from. |

**Example questions to ask:**
- "Which framework/library should this use?"
- "Is there an existing project this goes into, or is this greenfield?"
- "Any specific version requirements or environment constraints?"

---

## Axis 4: Integration (Fit)

**Core Question:** How does it fit with existing systems? Any conflicts?

| Score | Criteria |
|-------|----------|
| 0.0 | Impact scope and compatibility strategy are explicitly stated. User has identified which existing components are affected and how conflicts will be handled. |
| 0.2 | The change is independent or its impact is self-evident. For example, adding a new utility function that nothing else calls yet, or the integration points are obvious from the codebase structure. |
| 0.3 | New project with no integration target. There is nothing to integrate with yet, so this axis is not applicable. |
| 0.5 | An existing system exists but the impact of the change is unclear. The request touches shared code, APIs, or data models without specifying how existing consumers will be affected. |
| 0.8 | Deep involvement in an existing system (modifying core modules, changing database schemas, altering public APIs) but no discussion of impact, backward compatibility, or migration. |

**Example questions to ask:**
- "Which existing modules or services will this interact with?"
- "Are there other consumers of the API/data model you're changing?"
- "Do we need backward compatibility, or can we make breaking changes?"
- "How should existing callers handle the change -- migration, adapter, or feature flag?"

---

## Axis 5: User/IO (Who/What)

**Core Question:** Who uses it? What are inputs and outputs?

| Score | Criteria |
|-------|----------|
| 0.0 | Users, inputs, and outputs are all explicitly defined. Data shapes, formats, and error cases are specified. |
| 0.2 | Primary user and happy-path IO are clear. Edge cases and error handling are unspecified but follow standard conventions. |
| 0.3 | New project where the user is implicitly the requester. IO is directional but formats are open. |
| 0.5 | User or IO is partially specified. For example, the input format is clear but the output format is not, or vice versa. |
| 0.8 | No clarity on who uses the feature, what data goes in, or what comes out. |

**Example questions to ask:**
- "What does the input look like? Can you give an example?"
- "What should the output format be (JSON, HTML, file, CLI output)?"
- "How should errors be handled -- throw, return null, log and continue?"
- "Is this for end users, other developers, or automated systems?"

---

## Axis 6: Done Criteria (Done)

**Core Question:** What are the must_haves to confirm completion?

This axis uses the **must_haves** pattern with three components:

| Component | Description |
|-----------|-------------|
| **truths** | Statements that must be true after completion |
| **artifacts** | Files or outputs that must exist |
| **key_links** | Connections between artifacts that must hold |

| Score | Criteria |
|-------|----------|
| 0.0 | All 3 must_haves are explicitly specified. Truths are testable, artifacts are named, and key_links describe how artifacts connect. |
| 0.2 | Truths are clear and artifacts/key_links are inferable from context. For example, "add a login page" implies a component file, a route registration, and a test. |
| 0.3 | New project where done means "the initial setup works." Truths are simple ("it runs"), artifacts are the project skeleton. |
| 0.5 | Only general expectations exist ("it should work", "users can log in"). No concrete truths, artifacts, or key_links. |
| 0.8 | No success criteria at all. The user has not indicated what "done" looks like beyond the initial request verb. |

**Example questions to ask:**
- "What specific things should be true when this is done?"
- "Which files or outputs should exist after completion?"
- "How should I verify this works -- what would you test?"
- "Are there specific connections between components that must exist (e.g., route registered, migration applied)?"

### must_haves examples

**Good (score 0.0):**
```
truths:
  - Login form validates email format before submission
  - Invalid credentials show an inline error message
  - Successful login redirects to /dashboard
artifacts:
  - src/components/LoginForm.tsx
  - src/components/LoginForm.test.tsx
  - src/api/auth.ts
key_links:
  - LoginForm calls auth.login() on submit
  - App router registers /login route pointing to LoginForm
```

**Vague (score 0.5):**
```
"Users should be able to log in"
```

---

## Axis 7: Constraints (Constraints)

**Core Question:** What must be followed or avoided?

| Score | Criteria |
|-------|----------|
| 0.0 | Constraints are explicitly listed: performance targets, style guidelines, forbidden approaches, security requirements, licensing. |
| 0.2 | Constraints are mostly covered by project conventions (linter config, existing patterns). Minor unstated constraints are inferable. |
| 0.3 | New project with no inherited constraints. The user has stated their preferences or the domain has obvious defaults. |
| 0.5 | Some constraints are implied but not stated. For example, the project has a style guide but the user's request involves a pattern not covered by it. |
| 0.8 | The request involves sensitive areas (security, performance, data handling) but no constraints or requirements have been mentioned. |

**Example questions to ask:**
- "Are there performance requirements (response time, memory limits)?"
- "Any libraries or approaches we should avoid?"
- "Does this need to follow specific security practices (auth, encryption, sanitization)?"
- "Are there style or architectural patterns this must conform to?"

---

## Scoring Principles

1. **Context reduces scores.** If the codebase, project config, or conversation history already answers an axis, score it low. Do not ask questions the environment already answers.

2. **New projects score 0.3 on inapplicable axes.** When there is no existing system, axes like Integration (Fit) are scored 0.3 rather than 0.0, because the absence of a target is itself a minor ambiguity worth acknowledging -- but it does not block progress (0.3 > 0.2 triggers a brief confirmation, not deep questioning).

3. **Batch questions.** When multiple axes need clarification, ask about all of them in one message. Do not ask one axis at a time.

4. **Socratic over interrogative.** Frame questions to help the user discover their own requirements. "What happens when the token expires?" is better than "Specify the token expiry behavior."

5. **Diminishing returns.** If a re-scored axis drops from 0.5 to 0.3 but the remaining gap is a trivial detail, use judgment. A 0.25 that would take another round-trip to resolve can be accepted if the risk is low.
