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


# --- Structured shortlist (contract between executor phases and critic) ---


def _shortlist_path(run_dir: Path) -> Path:
    return run_dir / "shortlist.json"


def load_shortlist(run_dir: Path) -> list[dict[str, Any]]:
    path = _shortlist_path(run_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
    except Exception:
        pass
    return []


def save_shortlist(run_dir: Path, items: list[dict[str, Any]]) -> None:
    path = _shortlist_path(run_dir)
    path.write_text(
        json.dumps(items, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _norm_name(name: str) -> str:
    """
    Aggressive name key for merge: lowercase, strip generic tokens
    (hotel, resort, spa, …), keep alphanumerics only.
    """
    import re as _re

    s = (name or "").lower()
    for token in (
        "hotel",
        "resort",
        "spa",
        "apartments",
        "apartment",
        "boutique",
        "the",
        "adults only",
        "adults-only",
        "holiday",
        "club",
        "suites",
        "suite",
    ):
        s = s.replace(token, " ")
    s = _re.sub(r"[^a-z0-9]+", "", s)
    return s


def _parse_price_hint(price: Any) -> float | None:
    """Best-effort numeric extract for compare; None if unparseable."""
    if price is None:
        return None
    if isinstance(price, (int, float)):
        return float(price)
    s = str(price)
    import re as _re

    m = _re.search(r"(\d+[.,]?\d*)", s.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _validate_constraints_check(cc: Any) -> tuple[bool, str, dict[str, Any] | None]:
    """
    Generic constraint honesty field — no domain keywords.
    Accepts dict with matched / unmatched / unknown lists (strings from the task),
    or match_status in {full, partial, unknown} plus optional notes.
    """
    if cc is None:
        return False, (
            "constraints_check is required: "
            '{"matched": [...], "unmatched": [...], "unknown": [...]} '
            "using hard requirements from the task (free-text labels), "
            'or include match_status: "full"|"partial"|"unknown".'
        ), None
    if not isinstance(cc, dict):
        return False, "constraints_check must be an object", None

    match_status = str(cc.get("match_status") or "").strip().lower()
    matched = cc.get("matched")
    unmatched = cc.get("unmatched")
    unknown = cc.get("unknown")
    notes = str(cc.get("notes") or "").strip()

    def _as_list(v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    matched_l = _as_list(matched)
    unmatched_l = _as_list(unmatched)
    unknown_l = _as_list(unknown)

    if match_status and match_status not in ("full", "partial", "unknown"):
        return False, 'match_status must be "full", "partial", or "unknown"', None

    if not match_status and not matched_l and not unmatched_l and not unknown_l:
        return False, (
            "constraints_check empty: list at least one item under "
            "matched, unmatched, or unknown (labels from the task), "
            "or set match_status."
        ), None

    if not match_status:
        if unmatched_l and matched_l:
            match_status = "partial"
        elif unmatched_l and not matched_l:
            match_status = "partial"
        elif matched_l and not unmatched_l and not unknown_l:
            match_status = "full"
        else:
            match_status = "unknown"

    cleaned = {
        "match_status": match_status,
        "matched": matched_l,
        "unmatched": unmatched_l,
        "unknown": unknown_l,
    }
    if notes:
        cleaned["notes"] = notes[:500]
    return True, "", cleaned


def add_to_shortlist(
    run_dir: Path,
    *,
    name: str,
    source_url: str = "",
    price: str | float | None = None,
    details: str = "",
    session: str = "",
    constraints_check: dict[str, Any] | None = None,
    match_status: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Idempotent shortlist upsert keyed by normalized candidate name.
    Same name → one entry: merge source_urls, prefer lower price, keep richer details.
    Requires constraints_check (generic honesty about task hard requirements).
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}

    # Allow match_status top-level as shorthand merged into constraints_check
    cc_in: Any = constraints_check
    if isinstance(cc_in, dict) and match_status and "match_status" not in cc_in:
        cc_in = dict(cc_in)
        cc_in["match_status"] = match_status
    elif cc_in is None and match_status:
        cc_in = {"match_status": match_status, "matched": [], "unmatched": [], "unknown": []}

    ok_cc, err_cc, cleaned_cc = _validate_constraints_check(cc_in)
    if not ok_cc:
        return {"ok": False, "error": err_cc}

    if not (source_url or "").strip() and (price is None or not str(price).strip()):
        return {
            "ok": False,
            "error": "Provide at least source_url or price for a shortlist candidate",
        }

    items = load_shortlist(run_dir)
    key_name = _norm_name(name)
    key_url = (source_url or "").strip()
    new_price_num = _parse_price_hint(price)

    matched_idx: int | None = None
    for i, it in enumerate(items):
        if _norm_name(str(it.get("name") or "")) == key_name:
            matched_idx = i
            break

    action = "added"
    if matched_idx is not None:
        old = items[matched_idx]
        urls: list[str] = []
        for u in list(old.get("source_urls") or []):
            if isinstance(u, str) and u and u not in urls:
                urls.append(u)
        old_primary = (old.get("source_url") or "").strip()
        if old_primary and old_primary not in urls:
            urls.insert(0, old_primary)
        if key_url and key_url not in urls:
            urls.append(key_url)

        old_price_num = _parse_price_hint(old.get("price"))
        # Prefer lower parseable price; otherwise keep non-empty new price
        if (
            new_price_num is not None
            and old_price_num is not None
            and old_price_num <= new_price_num
        ):
            chosen_price = old.get("price")
        elif price is not None and str(price).strip():
            chosen_price = price
        else:
            chosen_price = old.get("price") or ""

        old_details = str(old.get("details") or "")
        new_details = (details or "").strip()
        # Keep the longer / richer details string
        chosen_details = (
            new_details
            if len(new_details) >= len(old_details)
            else old_details
        )[:1200]

        # Prefer display name without heavy parenthetical noise if new is cleaner
        chosen_name = name if len(name) >= len(str(old.get("name") or "")) else old.get("name")

        # Prefer a more specific detail/booking URL as primary source_url
        def _url_specificity(u: str) -> tuple[int, int]:
            low = (u or "").lower()
            # Lower score for search/list pages; higher for longer paths
            listish = any(
                x in low
                for x in (
                    "/zoeken",
                    "/search",
                    "/results",
                    "/vakanties?",
                    "sort=",
                    "offset=",
                    "limit=",
                )
            )
            path_len = len(low.split("?")[0])
            return (0 if listish else 1, path_len)

        ranked_urls = sorted(urls, key=_url_specificity, reverse=True)
        primary_url = ranked_urls[0] if ranked_urls else key_url

        entry: dict[str, Any] = {
            "name": chosen_name,
            "source_url": primary_url,
            "source_urls": ranked_urls if ranked_urls else urls,
            "price": chosen_price,
            "details": chosen_details,
            "constraints_check": cleaned_cc,
            "match_status": (cleaned_cc or {}).get("match_status") or "unknown",
            "session": session or old.get("session") or "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            for k, v in extra.items():
                if k not in entry and isinstance(v, (str, int, float, bool, list, dict)):
                    entry[k] = v
        items[matched_idx] = entry
        action = "updated"
    else:
        urls = [key_url] if key_url else []
        entry = {
            "name": name,
            "source_url": key_url,
            "source_urls": urls,
            "price": price if price is not None else "",
            "details": (details or "")[:1200],
            "constraints_check": cleaned_cc,
            "match_status": (cleaned_cc or {}).get("match_status") or "unknown",
            "session": session,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            for k, v in extra.items():
                if k not in entry and isinstance(v, (str, int, float, bool, list, dict)):
                    entry[k] = v
        items.append(entry)

    save_shortlist(run_dir, items)
    return {
        "ok": True,
        "action": action,
        "count": len(items),
        "entry": entry,
    }


def shortlist_as_prompt_text(run_dir: Path, max_chars: int = 6000) -> str:
    items = load_shortlist(run_dir)
    if not items:
        return "(shortlist empty)"
    lines = [f"Shortlist ({len(items)} unique candidates):"]
    total = 0
    for i, it in enumerate(items, 1):
        urls = it.get("source_urls") or ([it.get("source_url")] if it.get("source_url") else [])
        urls_s = "; ".join(str(u) for u in urls[:4] if u)
        ms = it.get("match_status") or (it.get("constraints_check") or {}).get("match_status") or "?"
        line = (
            f"{i}. {it.get('name')}"
            f" | match={ms}"
            f" | price={it.get('price') or '—'}"
            f" | urls={urls_s or '—'}"
            f" | {str(it.get('details') or '')[:200]}"
        )
        if total + len(line) > max_chars:
            lines.append("...[shortlist truncated]")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)
