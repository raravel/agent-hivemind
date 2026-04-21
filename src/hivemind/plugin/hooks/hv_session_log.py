#!/usr/bin/env python3
"""Session summary hook (PreCompact + Stop events).

Writes a compact L3 session record once per session/compaction boundary
instead of on every UserPromptSubmit — this reduces disk I/O by ~10-30x
while still giving /hv:feedback enough material to mine lessons from.

PreCompact: fires before the runtime compacts the conversation. Good
            moment to persist the current session state so feedback
            extraction can see it later.
Stop:       fires when the session ends. Final flush.

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


def _resolve_data_path(raw: str) -> Path | None:
    """Resolve a stored data_path, skipping Windows-style paths on POSIX."""
    if not raw:
        return None
    if sys.platform != "win32" and len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        return Path("~/agent-hivemind-data").expanduser()
    return Path(raw).expanduser()


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
    data_path = _resolve_data_path(str(link.get("data_path", "")))
    if not project or data_path is None:
        _approve()
        return

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

    if event == "PreCompact":
        transcript_raw = data.get("transcript_path")
        transcript_path = (
            Path(str(transcript_raw)) if transcript_raw else None
        )
        summary = _summarize_transcript(transcript_path)
        entry = (
            f"## Compact snapshot [{timestamp}]\n\n"
            + (summary if summary else "_(no transcript available)_\n")
            + "\n"
        )
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    elif event == "Stop":
        last = data.get("last_assistant_message") or ""
        if isinstance(last, str) and last.strip():
            snippet = last.strip()
            if len(snippet) > 2000:
                snippet = snippet[:2000] + " [...]"
            entry = f"## Session end [{timestamp}]\n\n{snippet}\n\n"
            with log_file.open("a", encoding="utf-8") as f:
                f.write(entry)

    _approve()


if __name__ == "__main__":
    main()
