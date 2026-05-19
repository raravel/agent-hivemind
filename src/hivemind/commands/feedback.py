"""Implementation of `hv feedback` command group."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import click
import frontmatter

from hivemind.core.config import HivemindConfig
from hivemind.core.git import commit_paths
from hivemind.core.indexer import build_index, save_index
from hivemind.core.paths import lesson_log_path, rollback_log_path
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
@click.option(
    "--task",
    "task_id",
    default=None,
    help="Source task ID. Recorded in lesson-log.jsonl for rollback tracking.",
)
@click.option(
    "--target",
    default=None,
    type=click.Choice(list(VALID_TARGETS), case_sensitive=False),
    help=(
        "Where the lesson lands. L2=generic cross-project (default); "
        "rules/tech-stack/architecture/features=project harness docs."
    ),
)
@click.option(
    "--feature",
    default=None,
    help="Feature slug (required when --target=features).",
)
@click.option(
    "--section",
    default=None,
    help=(
        "Override the harness-doc section heading. Pass with or without '## ' "
        "prefix. Binding sync uses --target tech-stack --section 'Active Dependencies'."
    ),
)
@click.option(
    "--skip-gate",
    is_flag=True,
    default=False,
    help=(
        "Bypass the lesson quality gate. Binding combinations bypass "
        "automatically; this flag is for explicit caller overrides."
    ),
)
@click.option(
    "--no-commit",
    is_flag=True,
    default=False,
    help="Append docs but skip git-commit. Caller commits separately.",
)
def save(
    project: str,
    content_file: str | None,
    title: str | None,
    task_id: str | None,
    target: str | None,
    feature: str | None,
    section: str | None,
    skip_gate: bool,
    no_commit: bool,
) -> None:
    """Save a learning directly to L2 or a harness doc.

    Single entry point for all feedback: no draft queue, no human prompt.
    Each successful write is committed as an isolated commit (subject
    contains a ``[lesson:<task>]`` tag) and tracked in ``lesson-log.jsonl``
    so it can be reverted via ``hv feedback rollback``.
    """
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

    # 2. Title fallback
    if title is None:
        first_line = text.split("\n")[0].strip()
        title = re.sub(r"^#+\s*", "", first_line)[:100]

    # 3. Resolve target + section + binding flag
    resolved_target = _normalize_target(target)
    resolved_section = _normalize_section_heading(section)
    is_binding = _is_binding(resolved_target, resolved_section)

    # 4. Cross-check option combinations
    if resolved_target == "features" and not feature:
        click.echo("Error: --feature is required when --target=features", err=True)
        raise SystemExit(2)
    if feature and resolved_target != "features":
        click.echo("Error: --feature is only valid with --target=features", err=True)
        raise SystemExit(2)

    # 5. Quality gate (binding combos and explicit overrides bypass)
    data_path = _resolve_data_path(project)
    if not is_binding and not skip_gate:
        accepted, reason = quality_gate(title, text, data_path)
        if not accepted:
            click.echo(f"Rejected: {reason}", err=True)
            raise SystemExit(1)

    # 6. Resolve linked path. Harness targets require it; L2-only is OK.
    linked_path = _resolve_linked_path(project)
    if resolved_target != "L2" and linked_path is None:
        click.echo(
            f"Error: project '{project}' is not linked; harness targets require linking.",
            err=True,
        )
        raise SystemExit(2)

    today = date.today().isoformat()
    source_task = task_id or "manual"

    # 7. Apply the write (reuses the same helper that promote-drafts used).
    cat = detect_category(title + "\n" + text)
    draft_entry: dict[str, Any] = {
        "title": title,
        "category": cat,
        "content": text,
        "target": resolved_target,
    }
    if feature:
        draft_entry["feature"] = feature
    if resolved_section:
        draft_entry["section"] = resolved_section
    if is_binding:
        draft_entry["kind"] = "BOUND"

    try:
        action, doc_path = _promote_to_target(
            data_path,
            linked_path,
            project,
            draft_entry,
            resolved_target,
            source_task,
            today,
        )
    except ValueError as exc:
        click.echo(f"Save failed: {exc}", err=True)
        raise SystemExit(1) from exc

    # 8. Commit. Use commit_paths so the lesson commit is isolated (no
    #    incidental working-tree changes get pulled in) — this is what
    #    makes time-delayed rollback work.
    commit_hash: str | None = None
    commit_repo: str | None = None
    if not no_commit:
        commit_msg = f"feedback: {title} [lesson:{source_task}]"
        if resolved_target == "L2":
            index_data = build_index(data_path)
            index_path = data_path / "index.json"
            save_index(index_data, index_path)
            click.echo("Index updated.")
            commit_hash = commit_paths(
                data_path, commit_msg, [doc_path, index_path], force=True
            )
            commit_repo = "data"
        else:
            assert linked_path is not None  # gated at step 6
            commit_hash = commit_paths(
                linked_path, commit_msg, [doc_path], force=True
            )
            commit_repo = "linked"

    # 9. lesson-log entry (in linked repo's reflect/). L2 without a linked
    #    project skips the log: there is no project to roll the lesson back
    #    against.
    if linked_path is not None:
        # Store doc path relative to its hosting root so the log stays portable
        # when the project repo is shared (no leaking of local home paths).
        rel_base = data_path if resolved_target == "L2" else linked_path
        try:
            rel_doc_path = doc_path.relative_to(rel_base).as_posix()
        except ValueError:
            rel_doc_path = str(doc_path)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_id": source_task,
            "title": title,
            "target": resolved_target,
            "file_path": rel_doc_path,
            "commit_hash": commit_hash,
            "commit_repo": commit_repo,
            "is_binding": is_binding,
            "kind": "BOUND" if is_binding else "LEARNED",
        }
        log_path = lesson_log_path(linked_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # 10. Report
    if action == "L2-new":
        click.echo(f"Created new lesson: {doc_path}")
        click.echo(f"Category: {cat}")
    elif action == "L2-update":
        click.echo(f"Updated existing lesson: {doc_path}")
    elif action == "harness-append":
        click.echo(f"Appended to harness doc: {doc_path}")
    elif action == "harness-duplicate":
        click.echo(f"No change (duplicate content): {doc_path}")
    if commit_hash:
        click.echo(f"Commit: {commit_hash} ({commit_repo} repo)")


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
    """[deprecated] Redirects to ``hv feedback save``.

    Drafts have been removed: every call writes its target immediately.
    The ``--auto-promote`` and ``--category`` flags are now no-ops (save
    auto-detects binding combinations and re-derives the category).
    """
    click.echo(
        "[deprecated] 'hv feedback draft-add' has been replaced by 'hv feedback save'.",
        err=True,
    )
    del auto_promote, category  # accepted for compat; save handles both natively
    ctx = click.get_current_context()
    ctx.invoke(
        save,
        project=project,
        content_file=content_file,
        title=title,
        task_id=task_id,
        target=target,
        feature=feature,
        section=section,
        skip_gate=False,
        no_commit=False,
    )


@feedback.command(name="drafts")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option("--task", "task_id", default=None, help="Filter by task ID.")
def drafts_list(project: str, task_id: str | None) -> None:
    """[deprecated] Drafts have been removed; nothing to list."""
    del project, task_id
    click.echo(
        "[deprecated] 'hv feedback drafts' is deprecated; drafts are no longer used.",
        err=True,
    )
    click.echo("No pending drafts.")


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
    """[deprecated] Draft queue removed; ``hv feedback save`` writes immediately."""
    del project, task_id, auto
    click.echo(
        "[deprecated] 'hv feedback promote-drafts' is deprecated; drafts are no longer used.",
        err=True,
    )
    click.echo("Done. L2=0 harness=0 rejected=0 skipped=0")


# ---------------------------------------------------------------------------
# Rollback + applied — feed the time-delayed gate in hv-task step 15.5
# ---------------------------------------------------------------------------


def _iter_lesson_log(linked_path: Path) -> list[dict[str, Any]]:
    """Read lesson-log.jsonl entries in chronological order."""
    path = lesson_log_path(linked_path)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def _resolve_repo_for_entry(
    data_path: Path, linked_path: Path | None, entry: dict[str, Any]
) -> Path | None:
    """Return the git repo that hosts the lesson commit named in ``entry``."""
    repo = entry.get("commit_repo")
    if repo == "data":
        return data_path
    if repo == "linked":
        return linked_path
    return None


@feedback.command(name="rollback")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option(
    "--task",
    "task_id",
    default=None,
    help="Roll back the most recent lesson tagged with this task ID.",
)
@click.option(
    "--commit",
    "commit_hash",
    default=None,
    help="Roll back a specific commit hash from lesson-log.jsonl.",
)
@click.option(
    "--reason",
    default=None,
    help="Why the rollback was triggered (recorded in rollback-log.jsonl).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report the matching entry without reverting.",
)
def rollback(
    project: str,
    task_id: str | None,
    commit_hash: str | None,
    reason: str | None,
    dry_run: bool,
) -> None:
    """Revert a previously auto-saved lesson commit.

    Called by hv-task step 15.5 (time-delayed gate) and by users investigating
    a bad lesson. Matches by --commit (preferred) or --task; for --task the
    most recent matching entry wins.
    """
    if not task_id and not commit_hash:
        click.echo("Error: pass --task or --commit", err=True)
        raise SystemExit(2)

    linked_path = _resolve_linked_path(project)
    if linked_path is None:
        raise click.ClickException(
            f"Project '{project}' is not linked. Run `hv link` first."
        )

    entries = _iter_lesson_log(linked_path)
    if not entries:
        click.echo("No lesson-log entries found.", err=True)
        raise SystemExit(1)

    if commit_hash:
        candidates = [e for e in entries if e.get("commit_hash") == commit_hash]
    else:
        candidates = [e for e in entries if e.get("task_id") == task_id]

    if not candidates:
        click.echo("No matching lesson-log entry.", err=True)
        raise SystemExit(1)

    target_entry = candidates[-1]
    target_commit = target_entry.get("commit_hash")
    if not target_commit:
        click.echo("Matching entry has no commit_hash (was --no-commit).", err=True)
        raise SystemExit(1)

    data_path = _resolve_data_path(project)
    repo_dir = _resolve_repo_for_entry(data_path, linked_path, target_entry)
    if repo_dir is None:
        click.echo(
            "Cannot resolve repo for entry (missing commit_repo).", err=True
        )
        raise SystemExit(1)

    click.echo(
        f"Match: {target_commit} (task={target_entry.get('task_id')}, "
        f"target={target_entry.get('target')}, repo={target_entry.get('commit_repo')})"
    )

    if dry_run:
        click.echo("(dry-run; no revert performed)")
        return

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "revert", "--no-edit", target_commit],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        click.echo(f"git revert failed: {exc}", err=True)
        raise SystemExit(1) from exc

    if result.returncode != 0:
        click.echo(f"git revert failed: {result.stderr.strip()}", err=True)
        raise SystemExit(1)

    rev_result = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    revert_commit = (
        rev_result.stdout.strip() if rev_result.returncode == 0 else "unknown"
    )

    rb_path = rollback_log_path(linked_path)
    rb_path.parent.mkdir(parents=True, exist_ok=True)
    rb_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "rolled_back_commit": target_commit,
        "revert_commit": revert_commit,
        "task_id": target_entry.get("task_id"),
        "target": target_entry.get("target"),
        "commit_repo": target_entry.get("commit_repo"),
        "reason": reason,
    }
    with rb_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rb_entry, ensure_ascii=False) + "\n")

    click.echo(f"Reverted {target_commit} -> {revert_commit}")


@feedback.command(name="applied")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option(
    "--since-task",
    default=None,
    help="Return entries newer than the most recent lesson tagged with this task ID.",
)
@click.option(
    "--limit",
    default=10,
    type=int,
    help="Maximum entries to return when --since-task is not given.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
)
def applied(
    project: str,
    since_task: str | None,
    limit: int,
    fmt: str,
) -> None:
    """List recent lesson-log entries (auto-applied feedback)."""
    linked_path = _resolve_linked_path(project)
    if linked_path is None:
        raise click.ClickException(
            f"Project '{project}' is not linked. Run `hv link` first."
        )

    entries = _iter_lesson_log(linked_path)
    if since_task:
        cutoff_idx = -1
        for i, e in enumerate(entries):
            if e.get("task_id") == since_task:
                cutoff_idx = i
        if cutoff_idx >= 0:
            entries = entries[cutoff_idx + 1 :]
        # Unknown since_task: fall through with all entries.
    else:
        entries = entries[-max(1, limit) :]

    if fmt.lower() == "json":
        click.echo(json.dumps(entries, ensure_ascii=False, indent=2))
        return

    if not entries:
        click.echo("No applied lessons.")
        return
    for e in entries:
        commit = (e.get("commit_hash") or "-")[:12]
        click.echo(
            f"{e.get('ts')}  task={e.get('task_id'):<16}  "
            f"target={e.get('target'):<14}  commit={commit}"
        )
