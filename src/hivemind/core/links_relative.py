"""Rewrite legacy spec-reference paths in task/doc bodies to v5 file-relative form.

V4 stored harness specs at ``{data_path}/projects/{project}/...`` and task
bodies referenced them with absolute-style strings like
``projects/agent-cli/features/01_auth.md``. V5 relocated specs into the
linked repo at ``<repo>/hivemind/docs/`` and tasks at ``<repo>/hivemind/tasks/``,
so those v4 strings no longer resolve from any editor.

This module exposes a single pure function, :func:`rewrite_body`, that:

  1. Rewrites backtick paths to **file-relative** paths from the file's own
     location (e.g. ``../docs/architecture.md`` from ``tasks/X.md`` or
     ``../../docs/...`` from ``tasks/_reports/X.md``).
  2. Prepends an Obsidian wikilink in front of each bullet inside the
     ``## Spec References`` section, so the same line is both clickable in
     Obsidian and a copy-paste-friendly relative path elsewhere.

Both transforms are idempotent. The function never edits files — callers
write the returned string back to disk.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePosixPath

__all__ = ["rewrite_body"]


# Stems considered "root" specs (live directly under hivemind/docs/).
_ROOT_SPECS = ("architecture", "tech-stack", "rules", "verify", "build-verify")
_ROOT_SPECS_PATTERN = "|".join(re.escape(s) for s in _ROOT_SPECS)

# Subdirectories under hivemind/docs/ where slug-style files live.
_DOC_SUBDIRS = ("features", "decisions")
_DOC_SUBDIRS_PATTERN = "|".join(re.escape(s) for s in _DOC_SUBDIRS)


def _relative_to_docs(
    rel_from_hivemind: PurePosixPath, target_in_docs: str
) -> str:
    """Compute the file-relative path from *rel_from_hivemind* to ``docs/<target>``.

    ``rel_from_hivemind`` is the file's path **relative to the project's
    ``hivemind/`` directory** (e.g. ``tasks/AGE-001.md`` or
    ``docs/features/01_auth.md``). ``target_in_docs`` is the path under
    ``docs/`` (e.g. ``architecture.md`` or ``features/01_auth.md``).
    """
    source_dir = PurePosixPath("hivemind") / rel_from_hivemind.parent
    target = PurePosixPath("hivemind/docs") / target_in_docs

    # Manual relpath for PurePosixPath (works cross-platform unlike os.path.relpath).
    src_parts = list(source_dir.parts)
    tgt_parts = list(target.parts)
    common = 0
    for a, b in zip(src_parts, tgt_parts):
        if a != b:
            break
        common += 1
    up = [".."] * (len(src_parts) - common)
    down = tgt_parts[common:]
    parts = up + down
    return "/".join(parts) if parts else "."


def _build_path_rewriter(
    rel_from_hivemind: PurePosixPath, project: str
) -> tuple[re.Pattern[str], Callable[[re.Match[str]], str]]:
    """Return (compiled regex, sub-function) that rewrites backtick paths.

    Matches three flavours of legacy reference, all inside single backticks:
      - ``projects/<project>/<root-spec>.md``
      - ``projects/<project>/(features|decisions)/<slug>.md``
      - ``hivemind/docs/<rest>``

    Other project names and non-spec paths are left untouched.
    """
    proj = re.escape(project)
    # Order matters: longer / more specific alternatives first inside a single
    # alternation so the regex engine picks the right branch.
    pattern = re.compile(
        r"`("
        rf"projects/{proj}/(?:{_DOC_SUBDIRS_PATTERN})/[^/`\s]+\.md"
        r"|"
        rf"projects/{proj}/(?:{_ROOT_SPECS_PATTERN})\.md"
        r"|"
        r"hivemind/docs/[^`\s]+"
        r")`"
    )

    proj_prefix = f"projects/{project}/"

    def _sub(match: re.Match[str]) -> str:
        raw = match.group(1)
        if raw.startswith(proj_prefix):
            target = raw[len(proj_prefix):]
        else:  # hivemind/docs/...
            target = raw[len("hivemind/docs/"):]
        rel = _relative_to_docs(rel_from_hivemind, target)
        return f"`{rel}`"

    return pattern, _sub


def _wikilink_for(target_in_docs: str) -> str:
    """Return the Obsidian wikilink representation for a docs path.

    ``architecture.md`` -> ``[[architecture]]``
    ``features/01_auth.md`` -> ``[[features/01_auth|01_auth]]``

    Alias form keeps the visible label short while preserving the unique
    vault path so duplicate stems across ``features/`` and ``decisions/``
    don't collide.
    """
    stem = target_in_docs[:-3] if target_in_docs.endswith(".md") else target_in_docs
    if "/" in stem:
        alias = stem.rsplit("/", 1)[1]
        return f"[[{stem}|{alias}]]"
    return f"[[{stem}]]"


def _docs_target_from_relative(rel_path: str, rel_from_hivemind: PurePosixPath) -> str | None:
    """Resolve a file-relative backtick path back to its ``docs/<target>`` form.

    Returns ``None`` if the path does not point into ``hivemind/docs/``.
    Used by the wikilink prepender to derive the link target after the path
    has already been rewritten by :func:`_build_path_rewriter`.
    """
    source_dir = PurePosixPath("hivemind") / rel_from_hivemind.parent
    try:
        resolved_parts: list[str] = list(source_dir.parts)
        for segment in rel_path.split("/"):
            if segment == "" or segment == ".":
                continue
            if segment == "..":
                if not resolved_parts:
                    return None
                resolved_parts.pop()
            else:
                resolved_parts.append(segment)
    except Exception:
        return None
    # Expect hivemind/docs/<rest>
    if len(resolved_parts) < 3 or resolved_parts[0] != "hivemind" or resolved_parts[1] != "docs":
        return None
    return "/".join(resolved_parts[2:])


_SPEC_HEADING = re.compile(r"^##\s+Spec References\s*$")
_NEXT_HEADING = re.compile(r"^##\s+")
# Bullet starting with `- ` then optional whitespace, optional existing wikilink,
# then a backtick path. We capture the backtick path's contents to test it.
_BULLET = re.compile(
    r"^(\s*-\s+)"                       # bullet prefix
    r"(\[\[[^\]]+\]\]\s+)?"            # optional existing wikilink
    r"`([^`]+)`"                        # backtick path
    r"(.*)$"                            # trailing text
)


def _prepend_wikilinks(
    body: str, rel_from_hivemind: PurePosixPath
) -> tuple[str, int]:
    """Inside ``## Spec References`` blocks, prepend ``[[wikilink]]`` to each bullet.

    Skips bullets that already carry a wikilink (idempotent). Bullets whose
    backtick path does not point into ``hivemind/docs/`` are left alone.
    """
    lines = body.splitlines(keepends=False)
    out: list[str] = []
    in_spec = False
    changes = 0
    for line in lines:
        if _SPEC_HEADING.match(line):
            in_spec = True
            out.append(line)
            continue
        if in_spec and _NEXT_HEADING.match(line):
            in_spec = False
            out.append(line)
            continue
        if in_spec:
            m = _BULLET.match(line)
            if m and m.group(2) is None:
                prefix, _existing, path, rest = m.group(1), m.group(2), m.group(3), m.group(4)
                target = _docs_target_from_relative(path, rel_from_hivemind)
                if target is not None:
                    wikilink = _wikilink_for(target)
                    out.append(f"{prefix}{wikilink} `{path}`{rest}")
                    changes += 1
                    continue
        out.append(line)
    # Preserve trailing newline if the original body had one.
    suffix = "\n" if body.endswith("\n") else ""
    return "\n".join(out) + suffix, changes


def rewrite_body(
    body: str,
    *,
    rel_from_hivemind: PurePosixPath | str,
    project: str,
) -> tuple[str, int]:
    """Rewrite spec-reference paths and prepend wikilinks. Returns ``(new_body, change_count)``.

    Parameters
    ----------
    body:
        Full text of the file (task body or spec doc).
    rel_from_hivemind:
        File path **relative to the project's ``hivemind/`` directory** —
        e.g. ``tasks/AGE-001.md`` for a task or ``docs/features/01_auth.md``
        for a doc that cross-references peers. The rewriter uses this to
        compute the correct number of ``../`` segments.
    project:
        Project name as used in v4 paths (``projects/<project>/...``).

    Both transforms are idempotent: re-running on already-rewritten text
    returns the same text and ``change_count == 0``.
    """
    rel = (
        rel_from_hivemind
        if isinstance(rel_from_hivemind, PurePosixPath)
        else PurePosixPath(str(rel_from_hivemind).replace("\\", "/"))
    )

    pattern, sub_fn = _build_path_rewriter(rel, project)
    new_body, path_changes = pattern.subn(sub_fn, body)
    new_body, link_changes = _prepend_wikilinks(new_body, rel)
    return new_body, path_changes + link_changes
