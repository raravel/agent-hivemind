# Harness Quality Rubric (v2)

Each axis scores 0–10. Use the anchor levels below. Interpolate when between anchors; round to the nearest integer.

**Bump `RUBRIC_VERSION` in `core/harness_quality.py` when any anchor below changes** — older scores must not be compared to new ones.

---

## 1. `architecture` — structural clarity

| Score | Anchor |
|-------|--------|
| 0 | `architecture.md` missing or empty. |
| 3 | File exists; plain prose only; no diagrams; fewer than 3 named components. |
| 5 | Names 3+ components; describes their roles; no diagram OR diagram does not match the prose. |
| 7 | Has at least one Mermaid diagram consistent with the prose; dependency direction implied but not stated. |
| 10 | Mermaid diagram(s) + explicit dependency direction rules + layer/module boundaries + at least one rationale for a key design choice. |

Penalize when the diagram references components not defined in prose, or vice versa.

---

## 2. `specs_detail` — feature completeness

Judge `features/*.md` collectively. If none exist, score 0.

Per file, check four sub-anchors:
- has **Inputs / parameters** section (named explicitly or via a structured list)
- has **Outputs / return / response** section
- has **Error cases / edge cases** section
- has **`## Implementation`** section listing at least one in-tree file path (code↔spec map maintained by `/hv:task` step 11.5)

Score is driven by the *proportion* of feature files satisfying each sub-anchor, normalized to 10.

| Score | Anchor |
|-------|--------|
| 0 | No feature files, or files exist but are placeholders (< 20 lines, no structure). |
| 3 | Files exist with a description only — no explicit inputs/outputs/error sections; no `## Implementation`. |
| 5 | ≥ 50% of feature files cover inputs + outputs; few or none cover error cases or `## Implementation`. |
| 7 | ≥ 80% cover inputs + outputs; ≥ 50% cover error cases; ≥ 50% have `## Implementation` with at least one path. |
| 10 | ≥ 90% of feature files cover all four sub-anchors (inputs + outputs + errors + `## Implementation`); at least one file uses a data-model or sequence diagram. |

Penalize files that are effectively empty (TBD placeholders, one-liners). A `## Implementation` section that lists only `TBD` or `<path>` placeholders does not count.

---

## 3. `rules_clarity` — NEVER/ALWAYS actionability

| Score | Anchor |
|-------|--------|
| 0 | `rules.md` missing or empty. |
| 3 | Has prose but no clearly tagged NEVER/ALWAYS (or similar imperative) rules. |
| 5 | 3+ imperative rules, but some are vague (e.g. "write clean code"). |
| 7 | 5+ imperative rules; most are concrete (name specific files, APIs, or patterns). |
| 10 | 5+ imperative rules, **all** concrete; no duplicates; no internal contradictions; each rule points to a concrete file path, API, or pattern. |

Call out contradictions or duplicates explicitly in `rationale`.

---

## 4. `tech_stack` — library declaration quality

Inspect `tech-stack.md`. Count libraries (any `- name` or `| name |` entry that names a package).

`/hv:plan` Phase 0 grounds this file in detected manifests + build artifacts. The rubric rewards that grounding: a doc that contradicts the manifest is worse than a sparse-but-truthful doc.

| Score | Anchor |
|-------|--------|
| 0 | File missing or lists no libraries. |
| 3 | Lists libraries; no versions; no usage examples. |
| 5 | ≥ 50% of libraries have a version; few or no usage examples. |
| 7 | ≥ 80% have versions; ≥ 50% have an import/usage example or brief rationale. |
| 10 | ≥ 90% have versions; ≥ 80% have usage examples or rationale; includes at least one "why this, not X" rationale; AND has a `## Active Dependencies` section grounded in a manifest (or a `## Legacy / Vendored` section that explicitly explains why a listed library is not in any manifest). |

A version is any pinned form: `1.2.3`, `^1.2`, `>=1.0,<2`, `~=1.2`. `latest`/`stable` does not count.

**Manifest-contradiction cap (v2 addition):** if you can identify a library listed under `## Active Dependencies` (or equivalent role section) whose name does NOT appear in any detected manifest file in the repo (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, etc.), **cap the final score at 5** and cite the contradiction in `rationale`. Libraries belonging in `## Legacy / Vendored` (vendored as static assets) are exempt from this cap, but they must be in that section, not `## Active Dependencies`.

---

## 5. `verification` — verify.md coverage

Inspect `verify.md` (or legacy `build-verify.md`). Count distinct commands (shell-like lines, excluding comments).

Stages to recognize (by keywords in command):
- **lint-like**: `lint`, `ruff check`, `eslint`, `flake8`, `golangci-lint`, `clippy`
- **type-like**: `mypy`, `tsc`, `pyright`, `go vet`
- **test-like**: `pytest`, `npm test`, `go test`, `cargo test`, `vitest`, `jest`
- **build-like**: `build`, `compile`, `cargo build`, `tsc -b`, `webpack`

| Score | Anchor |
|-------|--------|
| 0 | File missing or contains no runnable command. |
| 3 | 1 command total; covers only 1 stage. |
| 5 | 2+ commands; covers 2 stages. |
| 7 | Covers 3 stages; includes at least one project-specific command (not just stock `pytest` etc.). |
| 10 | Covers all 4 stages OR explicitly justifies each absent stage by name (e.g. "no `lint` stage — repository has no JS source"); each command has a one-line purpose. |

Favor language-agnostic phrasing: hard-coded `ruff/mypy/pytest` in a polyglot project is a minor deduction (-1), since the project's actual stack may differ.

**Justification specificity (v2 addition):** a vague justification such as "we don't need that" or "N/A" does NOT count toward anchor 10. The justification must name the absent stage explicitly and give a reason tied to the project's actual scope (e.g. "no `type` stage — repository is plain Python without type hints in source").

---

## Global cautions

- Do not penalize a doc for being short if it is *complete* for the project's scope. Small projects can legitimately score 10.
- When evidence is ambiguous, prefer the lower score and cite the ambiguity in `rationale`.
- Do not copy whole sentences from the docs into `rationale` — summarize the evidence in ≤ 20 words.
