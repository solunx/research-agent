"""
Run storage: conversation log, sources, report, candidates, research state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def create_run_dir(runs_dir: str, task_slug: str = "research") -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_slug[:40])
    run_id = f"{ts}_{slug}"
    path = Path(runs_dir) / run_id
    path.mkdir(parents=True, exist_ok=True)
    # notes/sources/report live as files; no unused raw/candidates dirs
    return path


def save_task(run_dir: Path, task_text: str) -> None:
    (run_dir / "task.md").write_text(task_text, encoding="utf-8")


def append_conversation(run_dir: Path, event: dict[str, Any]) -> None:
    event = dict(event)
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    with open(run_dir / "conversation.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def save_sources(run_dir: Path, sources: list[dict[str, Any]]) -> None:
    with open(run_dir / "sources.json", "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=2, ensure_ascii=False)


def save_report(run_dir: Path, report_md: str) -> None:
    (run_dir / "report.md").write_text(report_md, encoding="utf-8")


def save_metadata(run_dir: Path, metadata: dict[str, Any]) -> None:
    with open(run_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


def save_state(run_dir: Path, state: dict[str, Any]) -> None:
    """Compact research_state for resets and forced reports."""
    state = dict(state)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = run_dir / "research_state.json"
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Human-readable twin
    md_lines = [
        "# Research state",
        "",
        f"- Updated: {state.get('updated_at')}",
        f"- Status: {state.get('status', 'running')}",
        f"- LLM calls: {state.get('llm_calls', 0)}",
        f"- Tool calls: {state.get('tool_calls', 0)}",
        f"- Sources: {state.get('sources_count', 0)}",
        f"- Notes: {state.get('notes_count', 0)}",
        "",
        "## Progress",
        state.get("progress") or "(none)",
        "",
        "## Key findings (compact)",
        state.get("key_findings") or "(none yet)",
        "",
    ]
    (run_dir / "research_state.md").write_text("\n".join(md_lines), encoding="utf-8")


def load_state(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "research_state.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def append_note(run_dir: Path, note: dict[str, Any]) -> None:
    """Append a compact observation to notes.jsonl (evidence outside LLM context)."""
    note = dict(note)
    note.setdefault("ts", datetime.now(timezone.utc).isoformat())
    with open(run_dir / "notes.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")


def load_notes(run_dir: Path, limit: int = 80) -> list[dict[str, Any]]:
    path = run_dir / "notes.jsonl"
    if not path.exists():
        return []
    notes: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                notes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return notes[-limit:]


def _note_priority(n: dict[str, Any]) -> int:
    """Higher = more useful for synthesis (generic signals, not domain)."""
    st = (n.get("source_type") or "").lower()
    summary = (n.get("summary") or "").lower()
    score = 0
    if st in ("browser_open", "browser_click", "browser_type", "browser_extract_text", "browser"):
        score += 30
    if st == "web_fetch":
        score += 15
    if st == "search":
        score += 5
    if "price" in summary or "€" in summary or "eur" in summary or "prijs" in summary:
        score += 25
    if n.get("ok") is False or "error" in summary or "blocked" in summary:
        score -= 5
    if summary.startswith("search error") or summary == "search error":
        score -= 20
    return score


def notes_as_prompt_text(
    notes: list[dict[str, Any]],
    max_chars: int = 6000,
    prioritize: bool = False,
) -> str:
    if not notes:
        return "(no notes yet)"
    ordered = list(notes)
    if prioritize:
        # Keep chronological tie-break; prefer high-signal notes first for critic budget
        ordered = sorted(
            enumerate(ordered),
            key=lambda ix: (-_note_priority(ix[1]), ix[0]),
        )
        ordered = [n for _, n in ordered]
    parts: list[str] = []
    total = 0
    for n in ordered:
        line = (
            f"- [{n.get('source_type', 'note')}] {n.get('title') or n.get('url') or ''}: "
            f"{(n.get('summary') or n.get('snippet') or '')[:400]}"
        )
        if n.get("url"):
            line += f" ({n['url']})"
        if n.get("session"):
            line += f" {{session:{n['session']}}}"
        if total + len(line) > max_chars:
            parts.append("...[more notes truncated]")
            break
        parts.append(line)
        total += len(line)
    return "\n".join(parts)


def compact_session_handoff(
    notes: list[dict[str, Any]],
    session_label: str,
    max_chars: int = 2500,
) -> str:
    """Short read-only digest of one session for the next sub-task (generic)."""
    session_notes = [n for n in notes if n.get("session") == session_label]
    if not session_notes:
        session_notes = notes[-15:]
    return notes_as_prompt_text(session_notes, max_chars=max_chars, prioritize=True)
