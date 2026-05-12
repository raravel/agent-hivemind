"""Implementation of `hv feedback` command group."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import click
import frontmatter

from hivemind.core.config import HivemindConfig
from hivemind.core.git import auto_commit
from hivemind.core.indexer import build_index, save_index
from hivemind.core.similarity import find_similar

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "frontend": [
        "react",
        "vue",
        "angular",
        "css",
        "html",
        "ui",
        "ux",
        "component",
        "browser",
        "dom",
        "layout",
        "style",
        "responsive",
        "javascript",
        "typescript",
        "jsx",
        "tsx",
    ],
    "backend": [
        "api",
        "server",
        "database",
        "sql",
        "rest",
        "graphql",
        "endpoint",
        "auth",
        "middleware",
        "orm",
        "migration",
        "python",
        "node",
        "django",
        "flask",
        "fastapi",
    ],
    "infra": [
        "docker",
        "kubernetes",
        "k8s",
        "ci",
        "cd",
        "deploy",
        "pipeline",
        "terraform",
        "aws",
        "gcp",
        "azure",
        "nginx",
        "monitoring",
        "logging",
        "helm",
        "container",
    ],
}


def detect_category(text: str) -> str:
    """Detect category from text using keyword matching.

    Returns one of: frontend, backend, infra, general.
    """
    text_lower = text.lower()
    scores: dict[str, int] = {"frontend": 0, "backend": 0, "infra": 0}

    for category, keywords in _CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword) + r"\b"
            matches = re.findall(pattern, text_lower)
            scores[category] += len(matches)

    best_category = max(scores, key=lambda k: scores[k])
    if scores[best_category] == 0:
        return "general"
    return best_category


def _slugify(text: str) -> str:
    """Create a filename-safe slug from text."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:60].strip("-")


def _resolve_data_path(project: str) -> Path:
    """Resolve the data path from the config (canonical or legacy candidate)."""
    del project  # accepted for call-site clarity; resolution is project-agnostic
    try:
        return HivemindConfig.find_for_command().data_path
    except FileNotFoundError:
        return Path("~/agent-hivemind-data").expanduser()


def _resolve_linked_path(project: str) -> Path | None:
    """Resolve project's ``linked_path`` (v5 spec/task root). None if not registered."""
    try:
        cfg = HivemindConfig.find_for_command()
    except FileNotFoundError:
        return None
    from hivemind.core.paths import linked_path_for
    try:
        return linked_path_for(cfg, project)
    except FileNotFoundError:
        return None


def _update_existing_doc(
    data_path: Path, doc_rel_path: str, source_info: str
) -> Path:
    """Increment hits and add source link to an existing L2 doc."""
    doc_path = data_path / doc_rel_path
    post = frontmatter.load(str(doc_path))

    hits = post.metadata.get("hits", 1)
    if isinstance(hits, int):
        post.metadata["hits"] = hits + 1
    else:
        post.metadata["hits"] = 2

    sources = post.metadata.get("sources", [])
    if not isinstance(sources, list):
        sources = []
    sources.append(source_info)
    post.metadata["sources"] = sources

    doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return doc_path


def _create_new_doc(
    data_path: Path,
    title: str,
    body: str,
    category: str,
    today: str,
) -> Path:
    """Create a new L2 document with frontmatter."""
    slug = _slugify(title) if title else _slugify(body[:50])
    if not slug:
        slug = "lesson"

    cat_dir = data_path / "level2" / category
    cat_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{slug}.md"
    doc_path = cat_dir / filename

    # Avoid overwriting: add numeric suffix if needed
    counter = 1
    while doc_path.exists():
        counter += 1
        filename = f"{slug}-{counter}.md"
        doc_path = cat_dir / filename

    fm: dict[str, Any] = {
        "title": title,
        "category": category,
        "hits": 1,
        "sources": [],
        "promoted": False,
        "created": today,
    }

    post = frontmatter.Post(body, **fm)
    doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return doc_path


# ---------------------------------------------------------------------------
# Target routing — where should a draft lesson land?
# ---------------------------------------------------------------------------

# Valid routing targets. L2 is the generic cross-project tier; the other
# four write into the project's harness docs (project-scoped, git-tracked).
# `features` is a per-feature target — caller must also provide a feature slug.
VALID_TARGETS: tuple[str, ...] = ("L2", "rules", "tech-stack", "architecture", "features")

# The section header each harness-doc target appends under. Chosen so a reader
# can distinguish hand-curated content from auto-added entries.
# Default section for `tech-stack` is "Learned patterns" (lessons); the
# binding-sync caller overrides this with `--section "Active Dependencies"`.
_HARNESS_TARGET_FILES: dict[str, tuple[str, str]] = {
    # target -> (filename, default section heading)
    "rules": ("rules.md", "## Learned rules"),
    "tech-stack": ("tech-stack.md", "## Learned patterns"),
    "architecture": ("architecture.md", "## Learned constraints"),
    # `features` is special — filename depends on the feature slug.
    # The append helper resolves the actual path via _resolve_feature_path.
    "features": ("features/<slug>.md", "## Implementation"),
}

# Binding-target combinations that are allowed to auto-promote without
# human review. Binding records are mechanical (file paths, pinned versions)
# and not subject to the lesson quality gate.
_BINDING_COMBOS: frozenset[tuple[str, str]] = frozenset({
    ("features", "## Implementation"),
    ("tech-stack", "## Active Dependencies"),
})


def _is_binding(target: str, section: str | None) -> bool:
    """Return True when (target, section) is a binding-sync combination."""
    if target == "features":
        # Section is always Implementation for features.
        return True
    if target == "tech-stack" and section and section.strip().lstrip("#").strip() == "Active Dependencies":
        return True
    return False


def _normalize_target(raw: str | None) -> str:
    """Return a canonical target string. Default / unknown -> 'L2'."""
    if raw is None:
        return "L2"
    v = str(raw).strip().lower()
    # Accept common variants
    if v in {"l2", ""}:
        return "L2"
    if v in {"rules", "rule", "rules.md"}:
        return "rules"
    if v in {"tech-stack", "tech_stack", "techstack", "tech-stack.md"}:
        return "tech-stack"
    if v in {"architecture", "arch", "architecture.md"}:
        return "architecture"
    if v in {"features", "feature", "features.md"}:
        return "features"
    return "L2"


def _resolve_feature_path(linked_path: Path, slug: str) -> Path | None:
    """Find features/*.md whose stem contains the slug (v5: under linked_path/hivemind/docs/features).

    Accepts either `features/NN_<slug>.md` (the planner convention) or
    `features/<slug>.md`. Returns None when nothing matches or multiple match.
    """
    from hivemind.core.paths import harness_spec_dir
    features_dir = harness_spec_dir(linked_path) / "features"
    if not features_dir.exists():
        return None
    slug_norm = slug.strip().lower().replace(" ", "-")
    candidates = [
        p for p in features_dir.glob("*.md")
        if slug_norm in p.stem.lower()
    ]
    if len(candidates) != 1:
        return None
    return candidates[0]


def _normalize_section_heading(raw: str | None) -> str | None:
    """Allow callers to pass either 'Active Dependencies' or '## Active Dependencies'."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if not s.startswith("#"):
        s = f"## {s}"
    return s


def _append_to_harness_doc(
    linked_path: Path,
    target: str,
    content: str,
    source_task: str,
    today: str,
    *,
    section: str | None = None,
    feature_slug: str | None = None,
    kind: str = "LEARNED",
) -> tuple[Path, bool]:
    """Append a bullet to a harness-doc section (v5: under linked_path/hivemind/docs/).

    Returns (file_path, appended). If an exact-string duplicate already
    exists in the section, the file is untouched and *appended* is False.

    Keyword args:
      - section: override the default section heading for the target. Pass
        with or without leading '## '. For `tech-stack` the binding-sync
        caller uses `"Active Dependencies"`.
      - feature_slug: required when target == "features". The slug is
        resolved to features/*.md via _resolve_feature_path.
      - kind: tag inserted at the start of the bullet. Default "LEARNED"
        for lessons; binding sync uses "BOUND" so readers can distinguish
        mechanical entries from curated lessons.
    """
    from hivemind.core.paths import harness_spec_dir
    default_filename, default_heading = _HARNESS_TARGET_FILES[target]
    override = _normalize_section_heading(section)
    heading = override or default_heading

    if target == "features":
        if not feature_slug:
            raise ValueError("feature_slug is required when target='features'")
        resolved = _resolve_feature_path(linked_path, feature_slug)
        if resolved is None:
            raise ValueError(
                f"feature slug '{feature_slug}' did not match exactly one features/*.md"
            )
        path = resolved
    else:
        path = harness_spec_dir(linked_path) / default_filename
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    bullet_content = content.strip().replace("\n", " ")
    bullet = f"- [{kind.upper()} {today} from {source_task}] {bullet_content}"

    # Dedup: exact-content match inside the Learned section
    if bullet_content in existing:
        return path, False

    if heading in existing:
        # Append to the existing section — insert before the next heading (or EOF)
        lines = existing.splitlines()
        out: list[str] = []
        inserted = False
        heading_seen = False
        for i, line in enumerate(lines):
            out.append(line)
            if not heading_seen and line.strip() == heading:
                heading_seen = True
                continue
            if heading_seen and not inserted and line.startswith("## ") and line.strip() != heading:
                # Insert bullet just before this next heading
                out.insert(len(out) - 1, bullet)
                inserted = True
        if not inserted:
            out.append(bullet)
        new_text = "\n".join(out)
        if not new_text.endswith("\n"):
            new_text += "\n"
    else:
        prefix = existing
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        new_text = f"{prefix}{heading}\n\n{bullet}\n"

    path.write_text(new_text, encoding="utf-8")
    return path, True


# ---------------------------------------------------------------------------
# Quality gate + draft storage (auto-extraction of L2 candidates)
# ---------------------------------------------------------------------------

# Minimum signal that distinguishes a reusable lesson from a one-off note.
_MIN_CONTENT_CHARS = 50
_MAX_CONTENT_CHARS = 500
_SIMILARITY_REJECT = 0.8

_ACTION_VERBS = (
    "use",
    "avoid",
    "set",
    "add",
    "check",
    "ensure",
    "verify",
    "run",
    "configure",
    "wrap",
    "handle",
    "prefer",
    "disable",
    "enable",
    "replace",
    "apply",
    "pin",
    "always",
    "never",
    # rule/architecture style
    "enforce",
    "forbid",
    "require",
    "isolate",
    "decouple",
)

# Tokens that look like a concrete technology reference: CamelCase, dotted
# path, identifier with separator, or backtick-quoted code. Plain long English
# words (e.g. "always", "ensure") are intentionally NOT accepted here — they
# are caught by the action-verb check instead. Category keywords (fastapi,
# docker, ...) are a fallback when the regex misses.
_TECH_TOKEN_RE = re.compile(
    r"(?:[A-Z][a-z]+[A-Z]\w*"         # CamelCase: FastAPI, JSONSchema
    r"|[a-zA-Z][\w-]*\.\w+"            # dotted: foo.bar, package.json
    r"|\w+[_-]\w+"                     # snake_case, kebab-case
    r"|`[^`]+`)"                       # backtick-quoted code
)


def _has_action_verb(text: str) -> bool:
    lowered = text.lower()
    return any(
        re.search(r"\b" + re.escape(v) + r"\b", lowered) for v in _ACTION_VERBS
    )


def _has_tech_token(text: str) -> bool:
    if _TECH_TOKEN_RE.search(text):
        return True
    lowered = text.lower()
    for bucket in _CATEGORY_KEYWORDS.values():
        for kw in bucket:
            if re.search(r"\b" + re.escape(kw) + r"\b", lowered):
                return True
    return False


def quality_gate(
    title: str, content: str, data_path: Path
) -> tuple[bool, str]:
    """Return (accept, reason). Enforces the auto-draft quality rules.

    Rules:
      1. title is non-empty and <= 120 chars
      2. content length is within [_MIN_CONTENT_CHARS, _MAX_CONTENT_CHARS]
      3. content contains an action verb (actionable)
      4. content contains a concrete tech token (specific)
      5. BM25 similarity to any existing L2 doc is < _SIMILARITY_REJECT
    """
    title = (title or "").strip()
    content = (content or "").strip()

    if not title or len(title) > 120:
        return False, "title must be 1..120 chars"
    if len(content) < _MIN_CONTENT_CHARS:
        return False, f"content < {_MIN_CONTENT_CHARS} chars (too vague)"
    if len(content) > _MAX_CONTENT_CHARS:
        return False, f"content > {_MAX_CONTENT_CHARS} chars (split or shorten)"
    if not _has_action_verb(content):
        return False, "no action verb — lesson is not actionable"
    if not _has_tech_token(content):
        return False, "no concrete tech token — lesson is too generic"

    similar = find_similar(
        title + "\n" + content, data_path, threshold=_SIMILARITY_REJECT
    )
    if similar:
        path, score = similar[0]
        return False, f"near-duplicate of existing L2 {path} (score={score:.2f})"

    return True, "ok"


def _draft_path(linked_path: Path, task_id: str) -> Path:
    from hivemind.core.paths import task_dir
    return task_dir(linked_path) / "_reports" / f"{task_id}-lessons-draft.json"


def _load_draft_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"task_id": path.stem.replace("-lessons-draft", ""), "drafts": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("drafts"), list):
            return {"task_id": path.stem.replace("-lessons-draft", ""), "drafts": []}
        return data
    except (OSError, json.JSONDecodeError):
        return {"task_id": path.stem.replace("-lessons-draft", ""), "drafts": []}


def _save_draft_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _pending_drafts(
    linked_path: Path, task_id: str | None
) -> list[tuple[Path, dict[str, Any], int]]:
    """Return [(draft_file, file_data, index)] for each pending draft."""
    from hivemind.core.paths import task_dir
    reports_dir = task_dir(linked_path) / "_reports"
    if not reports_dir.exists():
        return []
    files = (
        [_draft_path(linked_path, task_id)]
        if task_id
        else sorted(reports_dir.glob("*-lessons-draft.json"))
    )
    pending: list[tuple[Path, dict[str, Any], int]] = []
    for f in files:
        if not f.exists():
            continue
        data = _load_draft_file(f)
        for i, draft in enumerate(data["drafts"]):
            if draft.get("status") == "pending":
                pending.append((f, data, i))
    return pending


@click.group()
def feedback() -> None:
    """Manage feedback and lessons learned."""


@feedback.command()
@click.option("--project", "-p", required=True, help="Project name.")
@click.option(
    "--content",
    "-c",
    "content_file",
    type=click.Path(exists=True),
    default=None,
    help="File with lesson text (reads from stdin if omitted).",
)
@click.option("--title", "-t", default=None, help="Title for the lesson.")
def save(project: str, content_file: str | None, title: str | None) -> None:
    """Save a learning/lesson to L2 documents with BM25 similarity check."""
    # 1. Read lesson text
    if content_file is not None:
        text = Path(content_file).read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            click.echo("Enter lesson text (Ctrl+D to finish):")
        text = sys.stdin.read()

    text = text.strip()
    if not text:
        click.echo("Error: Empty lesson text.", err=True)
        raise SystemExit(1)

    # Use first line as title if not provided
    if title is None:
        first_line = text.split("\n")[0].strip()
        # Strip markdown heading prefix
        title = re.sub(r"^#+\s*", "", first_line)[:100]

    # 2. Resolve data path
    data_path = _resolve_data_path(project)

    # 3. Run BM25 similarity check
    similar = find_similar(text, data_path, threshold=0.7)

    today = date.today().isoformat()

    if similar:
        # 4a. Update existing doc
        best_path, best_score = similar[0]
        click.echo(
            f"Similar lesson found: {best_path} (score: {best_score:.2f})"
        )
        source_info = f"{project}:{today}"
        doc_path = _update_existing_doc(data_path, best_path, source_info)
        click.echo(f"Updated existing lesson: {doc_path}")
    else:
        # 4b. Create new doc
        category = detect_category(text)
        doc_path = _create_new_doc(data_path, title, text, category, today)
        click.echo(f"Created new lesson: {doc_path}")
        click.echo(f"Category: {category}")

    # 5. Update index
    index_data = build_index(data_path)
    index_path = data_path / "index.json"
    save_index(index_data, index_path)
    click.echo("Index updated.")

    # 6. Auto-commit
    auto_commit(data_path, f"feedback: {title}")


# ---------------------------------------------------------------------------
# Draft subcommands
# ---------------------------------------------------------------------------


@feedback.command(name="draft-add")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option("--task", "task_id", required=True, help="Source task ID.")
@click.option("--title", "-t", required=True, help="Candidate lesson title.")
@click.option(
    "--content",
    "-c",
    "content_file",
    type=click.Path(exists=True),
    default=None,
    help="File with lesson text (reads from stdin if omitted).",
)
@click.option(
    "--category",
    default=None,
    help="Override auto-detected category (for L2 target only).",
)
@click.option(
    "--target",
    default=None,
    type=click.Choice(list(VALID_TARGETS), case_sensitive=False),
    help=(
        "Where to route the lesson on promote. "
        "L2=generic cross-project (default); "
        "rules/tech-stack/architecture/features=project harness docs."
    ),
)
@click.option(
    "--feature",
    default=None,
    help="Feature slug (required when --target=features). Matches features/*<slug>*.md.",
)
@click.option(
    "--section",
    default=None,
    help=(
        "Override the harness-doc section heading. Pass with or without '## ' prefix. "
        "Used by binding sync — e.g. --target tech-stack --section 'Active Dependencies'."
    ),
)
@click.option(
    "--auto-promote",
    is_flag=True,
    default=False,
    help=(
        "Promote the draft immediately after saving. Only allowed for binding "
        "combinations (--target features, or --target tech-stack --section 'Active Dependencies'). "
        "Binding entries are mechanical and skip the lesson quality gate."
    ),
)
def draft_add(
    project: str,
    task_id: str,
    title: str,
    content_file: str | None,
    category: str | None,
    target: str | None,
    feature: str | None,
    section: str | None,
    auto_promote: bool,
) -> None:
    """Append a candidate lesson to the task's draft file (quality-gated).

    Exit code 0 on accept, 1 if the quality gate rejects the candidate.

    Binding mode: pass --target features (with --feature) or --target tech-stack
    --section 'Active Dependencies' to record a binding (file path / pinned
    version) instead of a lesson. With --auto-promote, the entry is written to
    the harness doc immediately and the quality gate is skipped.
    """
    if content_file is not None:
        content = Path(content_file).read_text(encoding="utf-8").strip()
    else:
        content = sys.stdin.read().strip()

    if not content:
        click.echo("Error: empty content", err=True)
        raise SystemExit(1)

    data_path = _resolve_data_path(project)
    resolved_target = _normalize_target(target)
    resolved_section = _normalize_section_heading(section)
    is_binding = _is_binding(resolved_target, resolved_section)

    # Cross-check argument combinations BEFORE invoking the quality gate
    # so we surface usage errors first.
    if resolved_target == "features" and not feature:
        click.echo("Error: --feature is required when --target=features", err=True)
        raise SystemExit(2)
    if feature and resolved_target != "features":
        click.echo("Error: --feature is only valid with --target=features", err=True)
        raise SystemExit(2)
    if auto_promote and not is_binding:
        click.echo(
            "Error: --auto-promote is only allowed for binding combinations "
            "(--target=features, or --target=tech-stack --section='Active Dependencies').",
            err=True,
        )
        raise SystemExit(2)

    # Binding entries skip the lesson quality gate — they're mechanical
    # records (file paths, pinned versions), not reusable lessons.
    if not is_binding:
        accepted, reason = quality_gate(title, content, data_path)
        if not accepted:
            click.echo(f"Rejected: {reason}", err=True)
            raise SystemExit(1)

    cat = category or detect_category(title + "\n" + content)
    draft_entry: dict[str, Any] = {
        "title": title,
        "category": cat,
        "content": content,
        "target": resolved_target,
        "status": "pending",
    }
    if feature:
        draft_entry["feature"] = feature
    if resolved_section:
        draft_entry["section"] = resolved_section
    if is_binding:
        draft_entry["kind"] = "BOUND"

    # Drafts live alongside tasks under the project repo (v5).
    draft_linked = _resolve_linked_path(project)
    if draft_linked is None:
        raise click.ClickException(
            f"Project '{project}' is not linked. Run `hv link` first."
        )
    draft_path = _draft_path(draft_linked, task_id)
    data = _load_draft_file(draft_path)
    data["task_id"] = task_id
    data.setdefault("created", date.today().isoformat())
    data["drafts"].append(draft_entry)
    _save_draft_file(draft_path, data)

    if not auto_promote:
        click.echo(
            f"Draft saved: {draft_path} (target={resolved_target}, category={cat})"
        )
        return

    # Auto-promote path: immediately write to the harness doc and mark
    # the draft as promoted. Used by `/hv:task` step 11.5 (Harness sync).
    today = date.today().isoformat()
    linked_path = _resolve_linked_path(project)
    try:
        action, doc_path = _promote_to_target(
            data_path, linked_path, project, draft_entry, resolved_target, task_id, today
        )
    except ValueError as exc:
        click.echo(f"Auto-promote failed: {exc}", err=True)
        raise SystemExit(1)
    draft_entry["status"] = "promoted"
    draft_entry["promoted_target"] = resolved_target
    _save_draft_file(draft_path, data)
    click.echo(f"Bound + promoted: {action} -> {doc_path}")


@feedback.command(name="drafts")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option("--task", "task_id", default=None, help="Filter by task ID.")
def drafts_list(project: str, task_id: str | None) -> None:
    """List pending draft lessons for a project."""
    linked_path = _resolve_linked_path(project)
    if linked_path is None:
        raise click.ClickException(
            f"Project '{project}' is not linked. Run `hv link` first."
        )
    pending = _pending_drafts(linked_path, task_id)
    if not pending:
        click.echo("No pending drafts.")
        return
    for path, data, idx in pending:
        d = data["drafts"][idx]
        click.echo(f"--- {path.name} #{idx} ({d['category']}) ---")
        click.echo(f"Title: {d['title']}")
        click.echo(d["content"])
        click.echo("")


_TARGET_PROMPT_MAP: dict[str, str] = {
    "1": "L2",
    "2": "rules",
    "3": "tech-stack",
    "4": "architecture",
    "5": "features",
}


def _promote_to_target(
    data_path: Path,
    linked_path: Path | None,
    project: str,
    draft: dict[str, Any],
    target: str,
    task_id: str,
    today: str,
) -> tuple[str, Path]:
    """Execute the promote action for the chosen target.

    L2 promotes use ``data_path`` (cross-project knowledge base).
    Harness promotes use ``linked_path`` (project-local v5 location). Pass
    ``linked_path=None`` to defer harness promotes (will raise).

    Returns (action_label, file_path). action_label is one of
    'L2-new', 'L2-update', 'harness-append', 'harness-duplicate'.
    """
    del project  # kept for call-site clarity; no longer used for path computation
    if target == "L2":
        similar = find_similar(draft["content"], data_path, threshold=0.7)
        source_info = f"{task_id}:{today}"
        if similar:
            best_path, _score = similar[0]
            doc = _update_existing_doc(data_path, best_path, source_info)
            return "L2-update", doc
        doc = _create_new_doc(
            data_path, draft["title"], draft["content"], draft["category"], today
        )
        return "L2-new", doc

    # Harness-doc targets (including features). Pass through binding-specific
    # fields stored on the draft.
    if linked_path is None:
        raise click.ClickException(
            "Cannot promote to harness target: project is not linked."
        )
    doc, appended = _append_to_harness_doc(
        linked_path,
        target,
        draft["content"],
        task_id,
        today,
        section=draft.get("section"),
        feature_slug=draft.get("feature"),
        kind=str(draft.get("kind") or "LEARNED"),
    )
    return ("harness-append" if appended else "harness-duplicate"), doc


@feedback.command(name="promote-drafts")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option("--task", "task_id", default=None, help="Scope to one task ID.")
@click.option(
    "--auto",
    is_flag=True,
    default=False,
    help="Promote all pending drafts without prompting (use suggested target).",
)
def promote_drafts(project: str, task_id: str | None, auto: bool) -> None:
    """Interactively review and promote draft lessons.

    For each pending draft the user sees the suggested target and chooses:
      1=L2 (generic), 2=rules.md, 3=tech-stack.md, 4=architecture.md,
      n=reject, s=skip.
    L2 promotes flow through the standard `hv feedback save` path
    (BM25 dedup + index rebuild + auto-commit). Harness-doc promotes
    append a dated bullet under the target file's Learned section.
    """
    data_path = _resolve_data_path(project)
    linked_path = _resolve_linked_path(project)
    if linked_path is None:
        raise click.ClickException(
            f"Project '{project}' is not linked. Run `hv link` first."
        )
    pending = _pending_drafts(linked_path, task_id)
    if not pending:
        click.echo("No pending drafts.")
        return

    today = date.today().isoformat()
    promoted_l2 = 0
    promoted_harness = 0
    rejected = 0
    skipped = 0

    for path, data, idx in pending:
        d = data["drafts"][idx]
        suggested = _normalize_target(d.get("target"))
        # Map to the numeric prompt choice so pressing Enter accepts the suggestion
        default_choice = next(
            (k for k, v in _TARGET_PROMPT_MAP.items() if v == suggested), "1"
        )

        click.echo("")
        click.echo(f"=== {path.name} #{idx} ({d['category']}) ===")
        click.echo(f"Title:    {d['title']}")
        click.echo(f"Content:  {d['content']}")
        click.echo(f"Suggested target: {suggested}")

        if auto:
            choice_target = suggested
        else:
            ans = click.prompt(
                "Promote [1=L2, 2=rules, 3=tech-stack, 4=architecture, 5=features, n=reject, s=skip]",
                default=default_choice,
                show_default=True,
            ).strip().lower()
            if ans == "s":
                skipped += 1
                click.echo("  ... skipped")
                continue
            if ans == "n":
                d["status"] = "rejected"
                _save_draft_file(path, data)
                rejected += 1
                click.echo("  rejected")
                continue
            if ans not in _TARGET_PROMPT_MAP:
                click.echo("  invalid choice; skipping")
                skipped += 1
                continue
            choice_target = _TARGET_PROMPT_MAP[ans]

        action, doc_path = _promote_to_target(
            data_path,
            linked_path,
            project,
            d,
            choice_target,
            str(data.get("task_id") or "?"),
            today,
        )

        if action == "L2-update":
            click.echo(f"  L2: updated {doc_path}")
            promoted_l2 += 1
        elif action == "L2-new":
            click.echo(f"  L2: created {doc_path}")
            promoted_l2 += 1
        elif action == "harness-append":
            click.echo(f"  harness: appended to {doc_path}")
            promoted_harness += 1
        elif action == "harness-duplicate":
            click.echo(f"  harness: duplicate of existing content in {doc_path} — no change")
            # Still mark promoted so we don't revisit the same draft
            promoted_harness += 1

        d["status"] = "promoted"
        d["promoted_target"] = choice_target
        _save_draft_file(path, data)

    # Rebuild index + commit once at the end
    if promoted_l2:
        index_data = build_index(data_path)
        save_index(index_data, data_path / "index.json")
    if promoted_l2 or promoted_harness:
        auto_commit(
            data_path,
            f"feedback: promoted {promoted_l2 + promoted_harness} draft(s)",
        )

    click.echo("")
    click.echo(
        f"Done. L2={promoted_l2} harness={promoted_harness} rejected={rejected} skipped={skipped}"
    )
