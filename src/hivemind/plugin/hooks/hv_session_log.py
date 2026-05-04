#!/usr/bin/env python3
"""Session summary hook (UserPromptSubmit, PreCompact, Stop events).

Writes a compact L3 session record once per session/compaction boundary
instead of on every UserPromptSubmit — this reduces disk I/O by ~10-30x
while still giving the feedback skills enough material to mine lessons from.

UserPromptSubmit: persist the raw user prompt for Codex sessions.
PreCompact:       persist a transcript snapshot when Claude compacts context.
Stop:             final assistant flush when the session ends.

Input:  JSON on stdin from Claude Code, including transcript_path when
        available.
Output: JSON {status: "approve"} (hook is advisory only).

L3 file format:
    ~/agent-hivemind-data/level3/{project}/{YYYYMMDD}_{session_short}.md

The file is created on first write, then appended on subsequent events.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def _approve() -> None:
    sys.stdout.write(json.dumps({"status": "approve"}))


def _read_input() -> dict[str, object] | None:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else None
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_data_path() -> Path:
    """Resolve the hivemind data directory.

    Under v4 the data dir is the parent of the canonical global config
    file (``~/agent-hivemind-data``). A legacy v3 ``data_path`` field is
    honoured if still present so a freshly-upgraded install keeps
    logging until ``hv migrate --to v4`` rewrites the file.
    """
    canonical = Path("~/agent-hivemind-data/.hivemind.json").expanduser()
    default = canonical.parent
    if not canonical.exists():
        return default
    try:
        cfg = json.loads(canonical.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if isinstance(cfg, dict):
        legacy = cfg.get("data_path")
        if isinstance(legacy, str) and legacy:
            if (
                sys.platform != "win32"
                and len(legacy) >= 2
                and legacy[1] == ":"
                and legacy[0].isalpha()
            ):
                return default
            return Path(legacy).expanduser()
    return default


def _read_tail(path: Path, max_bytes: int = 65536) -> str:
    """Read up to *max_bytes* from the end of a text file (utf-8, lossy)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.read(1)  # skip partial line
            return f.read().decode("utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""


def _summarize_transcript(transcript_path: Path | None) -> str:
    """Extract a light summary from the CC transcript JSONL if available.

    The transcript is a JSONL stream of conversation turns. We grab the
    last few user/assistant exchanges to anchor the L3 record.
    """
    if transcript_path is None or not transcript_path.exists():
        return ""
    raw = _read_tail(transcript_path)
    if not raw:
        return ""

    lines = raw.splitlines()[-60:]
    out_lines: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = entry.get("role") or entry.get("type") or ""
        content = entry.get("content") or entry.get("text") or ""
        if isinstance(content, list):
            parts: list[str] = []
            for c in content:
                if isinstance(c, dict):
                    t = c.get("text")
                    if isinstance(t, str):
                        parts.append(t)
            content = "\n".join(parts)
        if not isinstance(content, str) or not content.strip():
            continue
        role_tag = str(role).strip() or "turn"
        snippet = content.strip()
        if len(snippet) > 600:
            snippet = snippet[:600] + " [...]"
        out_lines.append(f"**[{role_tag}]**\n{snippet}\n")

    return "\n".join(out_lines[-20:])


def _append_entry(log_file: Path, title: str, body: str, timestamp: str) -> None:
    """Append one markdown section to the session log."""
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"## {title} [{timestamp}]\n\n{body}\n\n")


def main() -> None:
    data = _read_input()
    if data is None:
        _approve()
        return

    session_id = str(data.get("session_id") or "unknown")
    event = str(data.get("hook_event_name") or "")
    cwd = Path(str(data.get("cwd") or Path.cwd()))

    link_file = cwd / ".hivemind-link.json"
    if not link_file.exists():
        _approve()
        return

    try:
        link = json.loads(link_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _approve()
        return

    project = link.get("project")
    if not project:
        _approve()
        return
    data_path = _resolve_data_path()

    today = datetime.now().strftime("%Y%m%d")
    short_id = session_id[:8]
    log_dir = data_path / "level3" / str(project)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{today}_{short_id}.md"

    if not log_file.exists():
        header = (
            f"---\n"
            f"session_id: \"{session_id}\"\n"
            f"project: \"{project}\"\n"
            f"date: \"{datetime.now().isoformat()}\"\n"
            f"---\n\n"
            f"# Session Log\n\n"
        )
        log_file.write_text(header, encoding="utf-8")

    timestamp = datetime.now().strftime("%H:%M:%S")

    if event == "UserPromptSubmit":
        prompt = data.get("user_prompt") or data.get("prompt") or data.get("input")
        if isinstance(prompt, str) and prompt.strip():
            snippet = prompt.strip()
            if len(snippet) > 2000:
                snippet = snippet[:2000] + " [...]"
            _append_entry(log_file, "User prompt", snippet, timestamp)
    elif event == "PreCompact":
        transcript_raw = data.get("transcript_path")
        transcript_path = (
            Path(str(transcript_raw)) if transcript_raw else None
        )
        summary = _summarize_transcript(transcript_path)
        _append_entry(
            log_file,
            "Compact snapshot",
            summary if summary else "_(no transcript available)_",
            timestamp,
        )
    elif event == "Stop":
        last = data.get("last_assistant_message") or ""
        if isinstance(last, str) and last.strip():
            snippet = last.strip()
            if len(snippet) > 2000:
                snippet = snippet[:2000] + " [...]"
            _append_entry(log_file, "Session end", snippet, timestamp)

    _approve()


if __name__ == "__main__":
    main()
