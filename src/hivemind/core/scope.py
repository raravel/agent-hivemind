"""Pure scope-logic for scope-aware parallel scheduling.

See ``hivemind/docs/features/10_scope-aware-parallel.md`` for the design
contract. This module is pure — no I/O, no Click, no commands-layer
imports — and provides:

- :func:`normalize` — clean a raw scope list (strip / dedupe / order).
- :func:`is_solo` — detect "runs alone" scopes (``None``/``[]``/``"*"``).
- :func:`conflicts` — bidirectional conflict check, returning the first
  offending entry from the left side (or ``None``).
- :func:`overlap` — every entry from the left side that has a partner
  in the right side, in original order.
- :func:`pack_non_conflicting` — greedy packing of ``(id, scope)``
  candidates into a single batch up to ``limit`` slots, returning the
  selected ids and a list of :class:`ConflictReport` for losers.

The module is intentionally permissive about inputs: callers (parser,
task index loader) are expected to have already validated YAML types,
but we still tolerate ``None`` for the scope field.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "ConflictReport",
    "conflicts",
    "is_solo",
    "normalize",
    "overlap",
    "pack_non_conflicting",
]


# ---------------------------------------------------------------------------
# Public data shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConflictReport:
    """A deferred candidate that lost to a previously-selected peer.

    ``id`` is the deferred candidate's task id; ``conflict_with`` is the
    selected peer's task id; ``overlap`` is the list of offending entries
    from the deferred candidate's own scope (a-side of the match).
    """

    id: str
    conflict_with: str
    overlap: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Glob matcher (segment-aware)
# ---------------------------------------------------------------------------


_NAMESPACES: tuple[str, ...] = ("manifest:", "harness:", "config:")


def _split_namespace(entry: str) -> tuple[str | None, str]:
    """Split ``entry`` into ``(namespace, value)``.

    Returns ``(None, entry)`` if ``entry`` is a path glob, the literal
    ``"*"`` token, or any other non-namespaced string. Returns
    ``(prefix, value)`` (where ``prefix`` keeps the trailing colon) when
    the entry starts with a known namespace prefix.
    """
    for ns in _NAMESPACES:
        if entry.startswith(ns):
            return ns, entry[len(ns) :]
    return None, entry


def _glob_segments_match(pat_segments: list[str], path_segments: list[str]) -> bool:
    """Match ``path_segments`` against ``pat_segments`` with glob rules.

    Rules:

    - ``*`` matches exactly one segment.
    - ``**`` matches zero or more segments.
    - Any other segment matches literally with optional in-segment ``*``
      and ``?`` wildcards (``*`` here does NOT cross ``/`` because we
      operate per-segment).
    - Case-sensitive.

    This is a small recursive matcher; the recursion depth is bounded by
    the number of pattern segments, which is tiny in practice.
    """
    # Empty pattern matches only empty path.
    if not pat_segments:
        return not path_segments

    head, *rest = pat_segments

    if head == "**":
        # Zero-segment match: consume the '**' and try the remainder.
        if _glob_segments_match(rest, path_segments):
            return True
        # One-or-more: consume a path segment and retry the '**'.
        if path_segments and _glob_segments_match(
            pat_segments, path_segments[1:]
        ):
            return True
        return False

    if not path_segments:
        return False

    if not _single_segment_match(head, path_segments[0]):
        return False

    return _glob_segments_match(rest, path_segments[1:])


def _single_segment_match(pattern: str, segment: str) -> bool:
    """Match a single segment with optional in-segment ``*``/``?``.

    Notably, a literal ``*`` here is treated as "any characters within
    this segment", but because we are already in per-segment matching
    territory the segment by definition contains no ``/``. Case-sensitive.
    """
    return _wildcard_match(pattern, segment)


def _wildcard_match(pattern: str, text: str) -> bool:
    """Case-sensitive wildcard matcher with ``*`` (any) and ``?`` (one)."""
    # Iterative DP-ish two-pointer scan.
    p_i = 0
    t_i = 0
    star_p = -1
    star_t = 0
    while t_i < len(text):
        if p_i < len(pattern) and pattern[p_i] == "*":
            star_p = p_i
            star_t = t_i
            p_i += 1
            continue
        if p_i < len(pattern) and (
            pattern[p_i] == "?" or pattern[p_i] == text[t_i]
        ):
            p_i += 1
            t_i += 1
            continue
        if star_p != -1:
            p_i = star_p + 1
            star_t += 1
            t_i = star_t
            continue
        return False
    # Trailing stars in the pattern are fine.
    while p_i < len(pattern) and pattern[p_i] == "*":
        p_i += 1
    return p_i == len(pattern)


def _glob_match(pattern: str, target: str) -> bool:
    """Top-level glob match honoring ``/`` as a segment separator.

    ``*`` in a pattern segment never crosses a ``/``. ``**`` crosses
    arbitrarily many segments.
    """
    return _glob_segments_match(pattern.split("/"), target.split("/"))


def _entries_match(a_entry: str, b_entry: str) -> bool:
    """Bidirectional match between two scope entries.

    Returns ``True`` if either ``a_entry`` matches ``b_entry`` (treating
    ``a_entry`` as the pattern) OR vice versa, subject to the namespace
    rules:

    - ``"*"`` matches anything (including namespaced tags).
    - Namespaced tags only match within the same namespace, applying
      glob rules to the value part.
    - Path globs never match namespaced tags (different namespace).
    """
    # The literal "*" token short-circuits to a wildcard match.
    if a_entry == "*" or b_entry == "*":
        return True

    a_ns, a_val = _split_namespace(a_entry)
    b_ns, b_val = _split_namespace(b_entry)

    if a_ns is None and b_ns is None:
        # Two path globs: bidirectional match.
        return _glob_match(a_entry, b_entry) or _glob_match(b_entry, a_entry)

    if a_ns is None or b_ns is None:
        # One side is namespaced and the other is a path glob — never conflict.
        return False

    if a_ns != b_ns:
        # Different namespaces never conflict.
        return False

    # Same namespace: bidirectional glob match on the value parts.
    return _glob_match(a_val, b_val) or _glob_match(b_val, a_val)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize(raw: list[str] | None) -> list[str]:
    """Clean a raw scope list: strip whitespace, drop empty, dedupe.

    - ``None`` / ``[]`` → ``[]``.
    - Each entry is ``.strip()``'d; entries that become empty are dropped.
    - First-seen order is preserved when removing duplicates.
    """
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        stripped = item.strip()
        if not stripped:
            continue
        if stripped in seen:
            continue
        seen.add(stripped)
        out.append(stripped)
    return out


def is_solo(scope: list[str] | None) -> bool:
    """Return True when ``scope`` forces solo execution.

    Solo means: missing scope (``None``), empty scope (``[]``), or any
    entry equal to the literal ``"*"`` token.
    """
    if not scope:
        return True
    return "*" in scope


def conflicts(a: list[str], b: list[str]) -> str | None:
    """Return the first entry from ``a`` that conflicts with anything in ``b``.

    Solo semantics: if either side is empty (``[]`` / ``None`` already
    coerced by callers) we still need to surface a non-``None`` sentinel
    so callers can detect the conflict. Per the spec, missing/empty
    scope is treated as "*" — conflict-with-everything.

    - Both sides empty → returns ``"*"`` (the implicit solo entry).
    - Empty ``a``, non-empty ``b`` → returns the first entry of ``b``
      (the offending peer's entry; ``a`` had no entry of its own).
    - Non-empty ``a``, empty ``b`` → returns the first entry of ``a``
      (every ``a`` entry conflicts with the implicit ``"*"`` of ``b``).
    - Otherwise: scan ``a`` left-to-right, return the first entry that
      matches at least one entry in ``b``. ``None`` if disjoint.
    """
    a_empty = not a
    b_empty = not b
    if a_empty and b_empty:
        return "*"
    if a_empty:
        # ``a`` is implicitly "*"; its first (only) entry is "*", so
        # return ``b``'s first entry as the visible offender.
        return b[0]
    if b_empty:
        # ``b`` is implicitly "*"; every ``a`` entry conflicts with it.
        return a[0]

    for a_entry in a:
        for b_entry in b:
            if _entries_match(a_entry, b_entry):
                return a_entry
    return None


def overlap(a: list[str], b: list[str]) -> list[str]:
    """Return every entry from ``a`` that has at least one match in ``b``.

    Preserves the original order of ``a``. Returns ``[]`` when either
    side is empty (callers needing solo semantics should rely on
    :func:`is_solo` / :func:`conflicts` instead).
    """
    if not a or not b:
        return []
    out: list[str] = []
    for a_entry in a:
        for b_entry in b:
            if _entries_match(a_entry, b_entry):
                out.append(a_entry)
                break
    return out


def pack_non_conflicting(
    candidates: list[tuple[str, list[str]]],
    limit: int,
) -> tuple[list[str], list[ConflictReport]]:
    """Greedily pack ``candidates`` into a batch up to ``limit`` slots.

    ``candidates`` is an ordered list of ``(task_id, scope)`` tuples,
    assumed already priority-sorted by the caller. The returned tuple is
    ``(selected_ids, deferred_reports)``:

    - ``selected_ids`` keeps the original candidate order.
    - ``deferred_reports`` contains one :class:`ConflictReport` per
      candidate that was *considered* but conflicted with a previously
      selected peer. Candidates skipped because the batch was already
      full are NOT recorded — they were never weighed for conflict.

    Empty input or ``limit <= 0`` returns ``([], [])`` without inspecting
    any candidate.
    """
    if limit <= 0 or not candidates:
        return [], []

    selected: list[tuple[str, list[str]]] = []
    deferred: list[ConflictReport] = []

    for cand_id, cand_scope in candidates:
        if len(selected) >= limit:
            # Batch full — remaining candidates are simply not considered
            # this round (no conflict reported).
            break

        # First conflict partner wins; greedy stops at the first match.
        first_partner: tuple[str, list[str]] | None = None
        for sel_id, sel_scope in selected:
            if conflicts(cand_scope, sel_scope) is not None:
                first_partner = (sel_id, sel_scope)
                break

        if first_partner is None:
            selected.append((cand_id, cand_scope))
            continue

        partner_id, partner_scope = first_partner
        deferred.append(
            ConflictReport(
                id=cand_id,
                conflict_with=partner_id,
                overlap=overlap(cand_scope, partner_scope),
            )
        )

    return [sid for sid, _ in selected], deferred
