"""
Run storage: conversation log, sources, report, candidates, research state.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def create_run_dir(runs_dir: str, task_slug: str = "research") -> Path:
    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H-%M-%S")  # TZ env (e.g. Europe/Brussels)
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
    (hotel, resort, spa, …), drop parenthetical / em-dash suffixes
    (e.g. "— Corendon pakket"), keep alphanumerics only.
    """
    import re as _re

    s = (name or "").lower()
    # Drop common provider/suffix noise so list+detail rows merge
    s = _re.sub(r"\s*[—–\-|:]\s*.*$", " ", s)
    s = _re.sub(r"\([^)]*\)", " ", s)
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
        "pakket",
        "package",
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
    or match_status in {full, partial, unknown, observed_only} plus optional notes.

    observed_only = runtime harvest invariant saw name+price; not yet verified
    against task hard criteria (LLM / phase-2 may promote later).
    """
    if cc is None:
        return False, (
            "constraints_check is required: "
            '{"matched": [...], "unmatched": [...], "unknown": [...]} '
            "using hard requirements from the task (free-text labels), "
            'or include match_status: "full"|"partial"|"unknown"|"observed_only".'
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

    allowed_status = ("full", "partial", "unknown", "observed_only")
    if match_status and match_status not in allowed_status:
        return False, f'match_status must be one of {allowed_status}', None

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

    # Honesty guard: cannot claim full if anything is unmatched
    if match_status == "full" and unmatched_l:
        match_status = "partial"
    # full + only unknowns about hard criteria → still partial (safer for ranking)
    if match_status == "full" and unknown_l and not unmatched_l:
        # Keep full only when unknowns look soft (optional notes); if any unknown
        # exists, demote to partial so the critic does not over-trust.
        match_status = "partial"

    cleaned = {
        "match_status": match_status,
        "matched": matched_l,
        "unmatched": unmatched_l,
        "unknown": unknown_l,
    }
    if notes:
        cleaned["notes"] = notes[:500]
    return True, "", cleaned


def _normalize_claims(claims: Any) -> list[dict[str, Any]]:
    """Optional light claim list: [{claim, evidence_urls?, status?}]. Max 12."""
    if not claims:
        return []
    if not isinstance(claims, list):
        return []
    out: list[dict[str, Any]] = []
    for c in claims[:12]:
        if isinstance(c, str) and c.strip():
            out.append({"claim": c.strip()[:300], "status": "unknown", "evidence_urls": []})
            continue
        if not isinstance(c, dict):
            continue
        claim = str(c.get("claim") or c.get("text") or "").strip()
        if not claim:
            continue
        ev = c.get("evidence_urls") or c.get("evidence") or []
        if isinstance(ev, str):
            ev = [ev] if ev.strip() else []
        if not isinstance(ev, list):
            ev = []
        status = str(c.get("status") or "unknown").strip().lower()
        if status not in (
            "geverifieerd",
            "verified",
            "deels geverifieerd",
            "partial",
            "niet bevestigd",
            "unverified",
            "onduidelijk",
            "unknown",
        ):
            status = "unknown"
        out.append(
            {
                "claim": claim[:300],
                "status": status,
                "evidence_urls": [str(u)[:500] for u in ev if u][:5],
            }
        )
    return out


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
    claims: list | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Idempotent shortlist upsert keyed by normalized candidate name.
    Same name → one entry: merge source_urls, prefer lower price, keep richer details.
    Requires constraints_check (generic honesty about task hard requirements).
    Optional claims: light evidence list for the critic/report.
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}

    # Configuration/SKU lines are not top-level offers (generic structural gate)
    line_item = _is_line_item_entity(name)
    if line_item and (extra or {}).get("origin") == "harvest_invariant":
        return {
            "ok": False,
            "error": "line_item_not_top_level",
            "detail": "Configuration/SKU strings cannot be auto-promoted as candidates",
        }

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

    cleaned_claims = _normalize_claims(claims)
    now_iso = datetime.now(timezone.utc).isoformat()

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

        # Merge claims by claim text
        old_claims = list(old.get("claims") or [])
        if cleaned_claims:
            by_text = {
                str(c.get("claim") or "").lower(): c
                for c in old_claims
                if isinstance(c, dict)
            }
            for c in cleaned_claims:
                by_text[str(c.get("claim") or "").lower()] = c
            merged_claims = list(by_text.values())[:12]
        else:
            merged_claims = old_claims[:12]

        entry: dict[str, Any] = {
            "name": chosen_name,
            "source_url": primary_url,
            "source_urls": ranked_urls if ranked_urls else urls,
            "price": chosen_price,
            "details": chosen_details,
            "constraints_check": cleaned_cc,
            "match_status": (cleaned_cc or {}).get("match_status") or "unknown",
            "claims": merged_claims,
            "session": session or old.get("session") or "",
            "observed_at": old.get("observed_at") or now_iso,
            "updated_at": now_iso,
        }
        # Preserve sticky fields from previous entry (rankable=False never upgrades silently)
        for sticky in (
            "origin",
            "evidence",
            "eav_confidence",
            "entity_score",
            "amount_role",
        ):
            if sticky in old and sticky not in entry:
                entry[sticky] = old[sticky]
        if extra:
            for k, v in extra.items():
                if isinstance(v, (str, int, float, bool, list, dict)):
                    entry[k] = v
        # Rankable: once False, stays False unless extra explicitly sets True after re-verify
        old_rankable = old.get("rankable")
        if extra and "rankable" in extra:
            new_r = bool(extra["rankable"])
            if old_rankable is False and new_r is True:
                # Allow upgrade only when constraints improved (matched non-empty, no mismatch)
                unmatched_n = cleaned_cc.get("unmatched") or []
                has_mm = any(str(u).startswith("query_state_mismatch") for u in unmatched_n)
                if has_mm or not (cleaned_cc.get("matched") or []):
                    entry["rankable"] = False
                else:
                    entry["rankable"] = True
            else:
                entry["rankable"] = new_r and (old_rankable is not False)
        elif old_rankable is False:
            entry["rankable"] = False
        else:
            entry["rankable"] = compute_rankable(entry)
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
            "claims": cleaned_claims,
            "session": session,
            "observed_at": now_iso,
            "updated_at": now_iso,
        }
        if extra:
            for k, v in extra.items():
                if isinstance(v, (str, int, float, bool, list, dict)):
                    entry[k] = v
        if line_item:
            entry["is_line_item"] = True
            entry["rankable"] = False
        elif "rankable" not in entry:
            entry["rankable"] = compute_rankable(entry)
        else:
            # Still run gate (e.g. NIET BRUIKBAAR in details)
            if entry.get("rankable") is not False:
                entry["rankable"] = compute_rankable(entry)
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
        observed = it.get("observed_at") or it.get("updated_at") or ""
        origin = it.get("origin") or ""
        rankable = compute_rankable(it)
        rank_tag = "" if rankable else " | NOT_RANKABLE"
        line = (
            f"{i}. {it.get('name')}"
            f" | match={ms}"
            f"{rank_tag}"
            f" | price={it.get('price') or '—'}"
            f" | observed={observed[:19] if observed else '—'}"
            f"{' | auto' if origin == 'harvest_invariant' else ''}"
            f" | urls={urls_s or '—'}"
            f" | {str(it.get('details') or '')[:200]}"
        )
        if total + len(line) > max_chars:
            lines.append("...[shortlist truncated]")
            break
        lines.append(line)
        total += len(line)
        claims = it.get("claims") or []
        for c in claims[:4]:
            if not isinstance(c, dict):
                continue
            cl = (
                f"    claim: {c.get('claim')} [{c.get('status') or '?'}]"
            )
            if total + len(cl) > max_chars:
                break
            lines.append(cl)
            total += len(cl)
        ev = it.get("evidence") or {}
        if isinstance(ev, dict) and ev.get("verified"):
            vline = f"    verified={ev.get('verified')}"
            if total + len(vline) <= max_chars:
                lines.append(vline)
                total += len(vline)
    return "\n".join(lines)




def compute_rankable(item: dict[str, Any]) -> bool:
    """
    Runtime gate: is this shortlist entry eligible for ranking?
    Critic must not act as garbage filter — only rank rankable items.
    Generic signals only (no product-vertical hardcoding).
    """
    if not isinstance(item, dict):
        return False
    if item.get("rankable") is False:
        return False
    cc = item.get("constraints_check") or {}
    if not isinstance(cc, dict):
        cc = {}
    unmatched = [str(u) for u in (cc.get("unmatched") or [])]
    if any(u.startswith("query_state_mismatch") for u in unmatched):
        return False
    # Explicit human/LLM unusable markers in notes/details
    blob = " ".join(
        [
            str(cc.get("notes") or ""),
            str(item.get("details") or ""),
            str(item.get("name") or ""),
        ]
    ).upper()
    for marker in (
        "NIET BRUIKBAAR",
        "NOT_RANKABLE",
        "NOT RANKABLE",
        "NOT USABLE",
        "NOT_USABLE",
        "UNUSABLE",
    ):
        if marker in blob:
            return False
    # Weak auto-harvest without verification and with many unmatched → exclude
    matched = cc.get("matched") or []
    if (
        item.get("origin") == "harvest_invariant"
        and len(unmatched) >= 2
        and len(matched) == 0
    ):
        return False
    # Low multi-signal confidence from harvest
    eav_c = item.get("eav_confidence")
    if eav_c is not None:
        try:
            if float(eav_c) < 0.55:
                return False
        except (TypeError, ValueError):
            pass
    es = item.get("entity_score")
    if es is not None:
        try:
            if float(es) < 0.45:
                return False
        except (TypeError, ValueError):
            pass
    # Empty name
    if not str(item.get("name") or "").strip():
        return False
    # Configuration / SKU lines are never rankable top-level candidates
    if _is_line_item_entity(str(item.get("name") or "")):
        return False
    if item.get("is_line_item"):
        return False
    return True


def filter_rankable_shortlist(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Candidates eligible for report ranking (runtime gate, not critic cleanup)."""
    out: list[dict[str, Any]] = []
    for it in items or []:
        if compute_rankable(it):
            out.append(it)
    return out

# --- Harvest: observation → EAV → candidate (domain-agnostic) ---
#
# Observation = raw signal (may be noise).
# Candidate   = entity + primary value with enough structural confidence.
# Shortlist   = candidates only (not every observation).
#
# No site- or domain-specific word lists for products (hotels, cars, …).
# Structural cues only: amount role, proximity, title-like lines, confidence.

_AMOUNT_RE = re.compile(
    r"(?<![A-Za-z])([+\-−–]?)\s*(?:€|eur|euro|\$|£)\s*([\d]{1,3}(?:[.\s]\d{3})*(?:[.,]\d{1,2})?|\d+)",
    re.I,
)
# UI chrome / navigation — language-light structural patterns
_UI_CHROME_RE = re.compile(
    r"^(home|menu|login|register|cookie|accept|search|filter|sort|budget|"
    r"next|prev|more|less|back|close|ok|cancel)\b",
    re.I,
)
# Structural non-entity lines (distance-only, filter class labels, pure category chrome)
_NON_ENTITY_STRUCT_RE = re.compile(
    r"(?:"
    r"^\d+[.,]?\d*\s*km\b|"  # distance-only line
    r"^[·•\-–—]\s*|"
    r"^[A-ZÁÉÍÓÚÄËÏÖÜ]{3,}(?:\s+[A-ZÁÉÍÓÚÄËÏÖÜ]{2,}){0,2}$|"  # short ALL-CAPS
    r"^\W*$"
    r")"
)

# Occupancy / meal-plan / duration chrome often adjacent to prices on list cards
_OFFER_META_RE = re.compile(
    r"(?:"
    r"\b\d+\s*(persoon|personen|persons?|adults?|volwassenen|kinderen|kids?)\b|"
    r"\b\d+\s*(dagen|nachten|nights?|days?)\b|"
    r"\b(all\s*-?\s*inclusive|volpension|halfpension|logies|breakfast only)\b|"
    r"\bvanaf\s+prijs\b|\bfrom\s+price\b|"
    r"\b(za|zo|ma|di|wo|do|vr|sat|sun|mon|tue|wed|thu|fri)\b.+\b\d{1,2}\b"
    r")",
    re.I,
)
# Language-light closed-class tokens (NL/EN/FR/DE mix) — structural, not product-vertical
_CLOSED_CLASS = frozenset(
    """
    de het een en van voor met op aan tot uit bij na over onder tussen
    the a an of to from with and or for on in at by as
    le la les un une des du au aux et ou de à
    der die das und oder mit von zu dem den
    vanaf vanuit richting inclusief exclusief gratis
    flight hotel package deal offer save bespaar boek book
    heen terug vlucht kamer personen
    jong oud kinderen kids family familie prachtig heerlijk ultiem
    dagelijks daily weekly direct naar naar
    """.split()
)

# Structural marketing / slogan openers (language-light, not product-vertical).
# Matches experience-copy that sits next to prices on list pages.
_MARKETING_OPENER_RE = re.compile(
    r"^(?:"
    r"ontdek|discover|enjoy|geniet|beleef|experience|"
    r"perfect|ideaal|ideal|ultiem|ultimate|heerlijk|"
    r"direct|dagelijks|daily|nu\s+tot|op\s+zoek|"
    r"activiteiten|activities|entertainment|ontspannen|relax|"
    r"een\s+\w+\s+(all\s*)?inclusive|all\s*inclusive\s+vakantie|"
    # Promo calendar openers ("From March 2026…") — structural, not product titles
    r"vanaf\s+\w+\s+\d{4}|from\s+\w+\s+\d{4}|"
    r"garantie|guaranteed|gegarandeerd"
    r")\b",
    re.I,
)

# Slogan / USP shape: ends with ! or is pure marketing claim without proper-name shape
_SLOGAN_SHAPE_RE = re.compile(
    r"(?:"
    r"!$"  # trailing bang → almost always USP copy on list cards
    r"|(?:gegarandeerd|guaranteed|must.?see|unmissable)\b"
    r"|(?:voor\s+jong\s+en\s+oud|activiteiten\s+voor)\b"
    r")",
    re.I,
)

_FILTER_RANGE_RE = re.compile(
    r"(between|tot\s*€|van\s*€\s*\d|min\s*€|max\s*€|€\s*\d+\s*[-–]\s*€|"
    r"price\s*per\s*\w+\s*between|slider)",
    re.I,
)

# Configuration / SKU / room-line under a product — not a top-level offer entity.
# Structural (quantity × unit, room/cabin/seat config), not product-vertical word lists.
_LINE_ITEM_RE = re.compile(
    r"(?:"
    r"^\s*\d+\s*[×xX]\s*"  # "1 × 2-persoonskamer", "2 x Double"
    r"|\b\d+\s*[×xX]\s*\d+\s*-?\s*(persoons?|personen|persons?|adults?)\b"
    r"|\b(standaard|standard|type\s*\d+)\s*(kamer|room|cabin|suite)?\b.*\b(max\s*\d+|geschikt)\b"
    r"|\b(kamer|room|cabin)\s*(type|config|keuze|selection)\b"
    r"|\b(prijsberekening|price\s*calculation|room\s*only)\b"
    r")",
    re.I,
)

# Generic amenity / transfer chrome often mistaken for product titles next to prices
_AMENITY_CHROME_RE = re.compile(
    r"^(?:"
    r"luchthaven\s*transfer|airport\s*transfer|heen-?\s*en\s*terug|"
    r"rechtstreekse\s*vlucht|direct\s*flight|inclusief\s*vlucht|"
    r"boek\s*nu|book\s*now|betaal\s*later|pay\s*later|"
    r"enkel\s*kamer|single\s*room|double\s*room"
    r")\b",
    re.I,
)


def _split_extract_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in (text or "").replace("\r", "\n").split("\n") if ln.strip()]
    expanded: list[str] = []
    for ln in lines:
        if " | " in ln and len(ln) > 40:
            expanded.extend(p.strip() for p in ln.split("|") if p.strip())
        else:
            expanded.append(ln)
    return expanded


def _is_line_item_entity(name: str) -> bool:
    """
    True when the string looks like a configuration/SKU under a product,
    not a top-level offer (e.g. '1 × 2-persoonskamer Standaard').
    Domain-agnostic structural patterns only.
    """
    s = (name or "").strip()
    if not s:
        return True
    if _LINE_ITEM_RE.search(s):
        return True
    # Leading quantity marker without a multi-token proper name
    if re.match(r"^\d+\s*[×xX]\s*", s):
        return True
    return False


def _cluster_lines(lines: list[str]) -> list[list[str]]:
    """
    Structure-aware blocks for candidate extraction.

    Heuristic (generic, not card-only):
    - Start a new cluster when a high-scoring title-like line appears after a price
      or after a short amenity/chrome run.
    - Keep price + nearby titles in the same cluster so pairing stays local.

    Cards/tables/lists all benefit from local pairing; this is one strategy inside
    structure-aware extraction, not a claim that every site uses cards.
    """
    if not lines:
        return []
    clusters: list[list[str]] = []
    current: list[str] = []
    last_had_price = False

    for ln in lines:
        es = _entity_score(ln)
        has_price = bool(_AMOUNT_RE.search(ln))
        is_chrome = bool(
            _UI_CHROME_RE.search(ln)
            or _AMENITY_CHROME_RE.search(ln)
            or _is_line_item_entity(ln)
        )

        # Boundary: strong title after we already saw a price in this cluster
        if (
            current
            and last_had_price
            and es >= 0.55
            and not has_price
            and not is_chrome
            and len(current) >= 2
        ):
            clusters.append(current)
            current = [ln]
            last_had_price = False
            continue

        current.append(ln)
        if has_price:
            last_had_price = True

        # Soft cap: very long clusters → split after price+tail
        if last_had_price and len(current) >= 12:
            clusters.append(current)
            current = []
            last_had_price = False

    if current:
        clusters.append(current)
    return clusters if clusters else [lines]


def _classify_amount_role(line: str, signed_prefix: str, value: float) -> str:
    """
    Generic amount role from structure — not product-domain vocabulary.
    primary | adjustment | filter_ui | noise
    """
    s = line or ""
    if _FILTER_RANGE_RE.search(s):
        return "filter_ui"
    # Explicit +/- before currency → relative adjustment (discount/surcharge delta)
    if signed_prefix in ("+", "-", "−", "–"):
        return "adjustment"
    if re.search(r"(^|\s)[+\-−–]\s*(?:€|\$|£)", s):
        return "adjustment"
    # Savings / discount wording next to amount (generic commerce, not vertical-specific)
    if re.search(r"\b(bespaar|save|savings|discount|korting|rabatt|promo)\b", s, re.I):
        return "adjustment"
    # Tiny amounts often UI noise or deltas when no entity context
    if value < 15:
        return "noise"
    if value > 50000:
        return "noise"
    return "primary"


def _marketing_penalty(line: str) -> float:
    """
    0–1 penalty: structural cues that a line is marketing/slogan copy, not a product name.
    Domain-agnostic (no vertical product vocabulary).
    """
    s = (line or "").strip()
    if not s:
        return 1.0
    pen = 0.0
    if _MARKETING_OPENER_RE.search(s):
        pen += 0.45
    if _SLOGAN_SHAPE_RE.search(s):
        pen += 0.5
    words = [w for w in re.split(r"\s+", s) if w]
    norm = [re.sub(r"[^\w]", "", w).lower() for w in words]
    norm = [w for w in norm if w]
    if norm:
        closed = sum(1 for w in norm if w in _CLOSED_CLASS)
        ratio = closed / len(norm)
        if ratio >= 0.45:
            pen += 0.35
        elif ratio >= 0.3:
            pen += 0.2
    # Preposition-heavy short phrases ("X voor Y en Z") without multi-cap names
    if re.search(r"\b(voor|van|met|aan|voor|for|with|from)\b", s, re.I):
        caps = sum(1 for w in words if w[:1].isupper() and len(w) > 2 and not w.isupper())
        if caps < 2:
            pen += 0.25
    # Sentence-like: comma or multiple clauses
    if s.count(",") >= 1 and len(words) >= 5:
        pen += 0.15
    # All-lowercase multi-word line is rarely a product title on commercial list pages
    if words and len(words) >= 3 and not any(w[:1].isupper() and len(w) > 2 for w in words):
        pen += 0.2
    return max(0.0, min(1.0, pen))


def _entity_score(line: str) -> float:
    """
    Structural likelihood that a line is a product/entity title (0–1).
    Multi-signal, domain-agnostic: length, caps, closed-class, marketing penalty.
    """
    s = (line or "").strip()
    if len(s) < 4 or len(s) > 100:
        return 0.0
    if _UI_CHROME_RE.search(s):
        return 0.0
    if _is_line_item_entity(s):
        return 0.08  # config/SKU under a product — never top-level
    if _AMENITY_CHROME_RE.search(s):
        return 0.1
    if _NON_ENTITY_STRUCT_RE.search(s):
        return 0.05
    if re.match(r"^[\d€$£.,+\-\s]+$", s):
        return 0.0
    if _AMOUNT_RE.search(s) and len(s) < 25:
        return 0.15  # mostly a price line
    # Meal/occupancy/duration chrome next to prices — not a product title
    if _OFFER_META_RE.search(s) and len(s) < 80:
        # Pure meta line (only meal/pax/duration words) → never a product entity
        content_words = [
            w for w in re.split(r"\s+", s)
            if re.sub(r"\W", "", w) and re.sub(r"\W", "", w).lower() not in _CLOSED_CLASS
        ]
        meta_only = all(
            _OFFER_META_RE.search(w) or w.lower() in ("ultra", "plus", "premium", "-", "–")
            or re.match(r"^\d+$", w)
            for w in content_words
        ) if content_words else True
        if meta_only or len(s) < 40:
            return 0.12
    # Distance / map chrome embedded in line (generic)
    if re.search(r"\d+[.,]?\d*\s*km\b", s, re.I) and len(s) < 60:
        if not re.search(r"[A-Za-zÁÉÍÓÚ]{4,}.+[A-Za-zÁÉÍÓÚ]{4,}", s):
            return 0.1
    letters = sum(1 for c in s if c.isalpha())
    if letters < 4:
        return 0.0
    words = [w for w in re.split(r"\s+", s) if w]
    if len(words) > 14:
        return 0.2
    short_tok = sum(1 for w in words if len(re.sub(r"\W", "", w)) <= 3)
    if words and short_tok / len(words) >= 0.6:
        return 0.15
    norm_words = [re.sub(r"[^\w]", "", w).lower() for w in words]
    norm_words = [w for w in norm_words if w]
    if norm_words:
        closed = sum(1 for w in norm_words if w in _CLOSED_CLASS)
        if closed / len(norm_words) >= 0.5:
            return 0.15
        if closed >= 1 and len(norm_words) <= 3:
            return 0.2
    score = 0.35
    if len(words) >= 2:
        score += 0.2
    if len(words) >= 3:
        score += 0.1
    caps = sum(1 for w in words if w[:1].isupper() and len(w) > 1)
    if caps >= 2:
        score += 0.2
    elif caps == 1 and len(words) >= 2:
        score += 0.1
    if len(words) == 1 and letters < 10:
        score -= 0.25
    alpha_words = [w for w in words if any(c.isalpha() for c in w)]
    if alpha_words and all(w.isupper() for w in alpha_words if len(w) > 2):
        score -= 0.35
    if letters / max(len(s), 1) < 0.4:
        score -= 0.2
    if "·" in s and re.search(r"km", s, re.I):
        score -= 0.35
    # Multi-signal: subtract marketing/slogan penalty
    score -= 0.7 * _marketing_penalty(s)
    return max(0.0, min(1.0, score))


def _url_detail_bonus(url: str) -> float:
    """Higher when URL looks like a detail/product page vs search/list."""
    low = (url or "").lower()
    if not low:
        return 0.0
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
            "pageType=search",
            "searchMode=",
        )
    )
    if listish:
        return 0.0
    path = low.split("?")[0]
    segments = [p for p in path.split("/") if p and p not in ("www", "http:", "https:")]
    # Host + several path segments often = detail
    if len(segments) >= 4:
        return 0.15
    if len(segments) >= 3:
        return 0.08
    return 0.0


def _pairing_confidence(
    *,
    entity_score: float,
    role: str,
    value: float,
    entity: str,
    source_url: str,
) -> float:
    """
    Multi-signal confidence that (entity, amount) is a real offer pair.
    Not a single regex rule.
    """
    conf = 0.15
    if entity_score >= 0.65:
        conf += 0.4
    elif entity_score >= 0.5:
        conf += 0.25
    elif entity_score >= 0.35:
        conf += 0.1
    else:
        conf -= 0.15
    if role == "primary":
        conf += 0.25
    elif role == "adjustment":
        conf -= 0.3
    elif role in ("filter_ui", "noise"):
        conf -= 0.4
    if role == "primary" and 30 <= value <= 20000:
        conf += 0.1
    conf += _url_detail_bonus(source_url)
    # Marketing leftover on entity → cut confidence hard
    conf -= 0.35 * _marketing_penalty(entity or "")
    return max(0.0, min(1.0, conf))


def _parse_amount(raw_num: str) -> float | None:
    """
    Parse currency amounts with EU/US thousand separators.
    '2.328' / '2 328' → 2328; '2.328,50' → 2328.50; '2,328.50' → 2328.50.
    """
    try:
        s = (raw_num or "").replace("\xa0", "").replace(" ", "").strip()
        if not s:
            return None
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                return float(s.replace(".", "").replace(",", "."))
            return float(s.replace(",", ""))
        if "," in s:
            parts = s.split(",")
            if len(parts) == 2 and len(parts[1]) == 3 and parts[0].isdigit():
                return float(parts[0] + parts[1])
            return float(s.replace(",", "."))
        if "." in s:
            parts = s.split(".")
            if (
                len(parts) == 2
                and len(parts[1]) == 3
                and parts[0].isdigit()
                and parts[1].isdigit()
            ):
                return float(parts[0] + parts[1])
            if len(parts) > 2 and all(p.isdigit() for p in parts):
                return float("".join(parts))
            return float(s)
        return float(s)
    except ValueError:
        return None


def _best_entity_in_window(window_lines: list[str]) -> tuple[str, float]:
    """Highest-scoring non-line-item title in a local cluster window."""
    best_name = ""
    best_es = 0.0
    best_key: tuple[float, int, int] = (0.0, 0, 0)
    for cand in window_lines:
        cand = cand.strip()
        if not cand or _is_line_item_entity(cand):
            continue
        if _AMENITY_CHROME_RE.search(cand):
            continue
        es = _entity_score(cand)
        if es < 0.35:
            continue
        words_n = len([w for w in cand.split() if w])
        key = (es, words_n, len(cand))
        if key > best_key:
            best_key = key
            best_es = es
            best_name = cand
    return best_name, best_es


def extract_eav_observations(
    text: str,
    *,
    price_hints: list[Any] | None = None,
    source_url: str = "",
    max_items: int = 24,
) -> list[dict[str, Any]]:
    """
    Build entity–attribute–value observations with confidence.

    Structure-aware: lines are grouped into clusters; entity↔price pairing prefers
    the same cluster (local relationship), not arbitrary proximity across the page.
    Line-item / SKU strings are never chosen as top-level entities.
    """
    lines = _split_extract_lines(text)
    clusters = _cluster_lines(lines)
    obs: list[dict[str, Any]] = []

    # Flat index → (cluster_idx, offset_in_cluster) for window evidence
    flat: list[tuple[int, int, str]] = []
    for ci, cluster in enumerate(clusters):
        for li, ln in enumerate(cluster):
            flat.append((ci, li, ln))

    for fi, (ci, li, ln) in enumerate(flat):
        for m in _AMOUNT_RE.finditer(ln):
            sign, raw_num = m.group(1) or "", m.group(2)
            value = _parse_amount(raw_num)
            if value is None:
                continue
            role = _classify_amount_role(ln, sign, value)
            price_s = f"{'−' if sign in ('-', '−', '–') else ''}€{raw_num.replace(' ', '')}"

            # Prefer entity inside the same cluster (structure-local relationship)
            cluster = clusters[ci]
            # Window: lines before the price line within cluster, then fallback to prior lines
            before = cluster[:li]
            best_name, best_es = _best_entity_in_window(before)
            if not best_name:
                # Fallback: a few lines before in flat order (still local)
                prior = [flat[j][2] for j in range(max(0, fi - 6), fi)]
                best_name, best_es = _best_entity_in_window(prior)

            conf = _pairing_confidence(
                entity_score=best_es,
                role=role,
                value=value,
                entity=best_name,
                source_url=source_url or "",
            )
            # Penalize if we still somehow paired a line-item
            if best_name and _is_line_item_entity(best_name):
                conf = min(conf, 0.2)
                best_es = min(best_es, 0.1)

            window = " | ".join(cluster[max(0, li - 3) : li + 2])
            obs.append(
                {
                    "entity": best_name[:120] if best_name else "",
                    "entity_score": round(best_es, 3),
                    "attribute": "offer_price" if role == "primary" else f"amount:{role}",
                    "value": price_s[:40],
                    "value_num": value,
                    "amount_role": role,
                    "confidence": round(conf, 3),
                    "marketing_penalty": round(_marketing_penalty(best_name), 3),
                    "is_line_item": bool(best_name and _is_line_item_entity(best_name)),
                    "cluster_size": len(cluster),
                    "source_url": (source_url or "")[:500],
                    "raw_evidence": window[:400],
                }
            )
            if len(obs) >= max_items:
                return obs

    # Optional: scan price_hints as extra amount signals without inventing entities
    if price_hints and len(obs) < max_items:
        for ph in price_hints[:15]:
            phs = str(ph)
            m = _AMOUNT_RE.search(phs)
            if not m:
                continue
            sign, raw_num = m.group(1) or "", m.group(2)
            value = _parse_amount(raw_num)
            if value is None:
                continue
            role = _classify_amount_role(phs, sign, value)
            obs.append(
                {
                    "entity": "",
                    "entity_score": 0.0,
                    "attribute": f"amount:{role}",
                    "value": f"€{raw_num.replace(' ', '')}"[:40],
                    "value_num": value,
                    "amount_role": role,
                    "confidence": 0.15 if role != "primary" else 0.25,
                    "is_line_item": False,
                    "source_url": (source_url or "")[:500],
                    "raw_evidence": phs[:200],
                }
            )
    return obs[:max_items]


def append_observation(run_dir: Path, observation: dict[str, Any]) -> None:
    path = run_dir / "observations.jsonl"
    row = dict(observation)
    row.setdefault("ts", datetime.now(timezone.utc).isoformat())
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def observations_as_prompt_text(run_dir: Path, max_chars: int = 3000) -> str:
    path = run_dir / "observations.jsonl"
    if not path.exists():
        return "(no observations)"
    lines: list[str] = []
    total = 0
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return "(observations unreadable)"
    for ln in raw_lines[-40:]:
        try:
            o = json.loads(ln)
        except Exception:
            continue
        s = (
            f"- conf={o.get('confidence')} role={o.get('amount_role')} "
            f"entity={o.get('entity') or '—'} value={o.get('value')} "
            f"[{str(o.get('raw_evidence') or '')[:80]}]"
        )
        if total + len(s) > max_chars:
            break
        lines.append(s)
        total += len(s)
    return "\n".join(lines) if lines else "(no observations)"


def harvest_invariant_from_browser_result(
    run_dir: Path,
    result: dict[str, Any],
    *,
    session: str = "",
    constraint_mismatches: list[str] | None = None,
    candidate_confidence_min: float = 0.72,
    entity_score_min: float = 0.62,
    max_auto_candidates_per_page: int = 5,
) -> dict[str, Any]:
    """
    Runtime harvest (retrieval only) — pure code, no LLM:

    1) Extract EAV observations from page text (all rows → observations.jsonl).
    2) Promote to shortlist ONLY when:
       - amount_role == primary
       - entity looks like a product title (entity_score / marketing gates)
       - confidence high enough
       - NO structural query-state mismatches on this page
    3) Mismatches / slogans / low-conf stay in observations only — never shortlist.

    Shortlist is the evidence buffer for ranking; observations are the raw layer.
    """
    if not isinstance(result, dict):
        return {"ok": False, "observations": 0, "added": 0, "updated": 0, "candidates": []}

    text = str(result.get("text") or "")
    if len(text) < 40 and result.get("error"):
        return {
            "ok": True,
            "observations": 0,
            "added": 0,
            "updated": 0,
            "candidates": [],
            "skipped": "error",
        }

    hints = result.get("price_hints") if isinstance(result.get("price_hints"), list) else []
    url = str(result.get("url") or "")
    eavs = extract_eav_observations(
        text, price_hints=hints, source_url=url, max_items=24
    )

    n_obs = 0
    for eav in eavs:
        append_observation(
            run_dir,
            {
                **eav,
                "session": session,
                "page_url": url,
            },
        )
        n_obs += 1

    mismatches = [str(x) for x in (constraint_mismatches or []) if x]
    # Structural query mismatch → learn from observations only; never pollute shortlist
    if mismatches:
        return {
            "ok": True,
            "observations": n_obs,
            "added": 0,
            "updated": 0,
            "count": len(load_shortlist(run_dir)),
            "candidates": [],
            "promoted": 0,
            "skipped_low_conf": n_obs,
            "skipped_reason": "query_state_mismatch",
            "mismatches": mismatches[:6],
        }

    # Promote: primary + strong multi-signal confidence (observations still keep all).
    # Never promote line-item / SKU / room-config strings as top-level candidates.
    promotable = [
        e
        for e in eavs
        if e.get("amount_role") == "primary"
        and (e.get("entity") or "").strip()
        and not e.get("is_line_item")
        and not _is_line_item_entity(str(e.get("entity") or ""))
        and float(e.get("entity_score") or 0) >= entity_score_min
        and float(e.get("confidence") or 0) >= candidate_confidence_min
        and float(e.get("marketing_penalty") or 0) < 0.30
        and len((e.get("entity") or "").split()) >= 2
        and not _SLOGAN_SHAPE_RE.search(str(e.get("entity") or ""))
        and not _AMENITY_CHROME_RE.search(str(e.get("entity") or ""))
    ]
    promotable.sort(key=lambda x: float(x.get("confidence") or 0), reverse=True)
    promotable = promotable[:max_auto_candidates_per_page]

    added = 0
    updated = 0
    entries: list[dict[str, Any]] = []

    for eav in promotable:
        unknown = [
            "task hard criteria not fully checked by runtime harvest",
        ]
        evidence = {
            "observed": {
                "entity": eav.get("entity"),
                "value": eav.get("value"),
                "amount_role": eav.get("amount_role"),
                "confidence": eav.get("confidence"),
                "entity_score": eav.get("entity_score"),
                "marketing_penalty": eav.get("marketing_penalty"),
                "source_url": eav.get("source_url") or url,
                "raw_evidence": eav.get("raw_evidence") or "",
            },
            "verified": {},
            "unknown": unknown,
        }
        res = add_to_shortlist(
            run_dir,
            name=str(eav.get("entity") or "").strip(),
            source_url=str(eav.get("source_url") or url),
            price=eav.get("value"),
            details=f"[auto-candidate conf={eav.get('confidence')}] {eav.get('raw_evidence') or ''}"[
                :500
            ],
            session=session,
            constraints_check={
                "match_status": "observed_only",
                "matched": [],
                "unmatched": [],
                "unknown": unknown,
                "notes": "Runtime EAV harvest (not LLM). Rank only after constraint verification.",
            },
            extra={
                "origin": "harvest_invariant",
                "evidence": evidence,
                "eav_confidence": eav.get("confidence"),
                "entity_score": eav.get("entity_score"),
                "amount_role": eav.get("amount_role"),
                "rankable": True,  # no mismatch; still observed_only until phase-2 verifies
            },
        )
        if res.get("ok"):
            if res.get("action") == "added":
                added += 1
            else:
                updated += 1
            entries.append(res.get("entry") or eav)

    return {
        "ok": True,
        "observations": n_obs,
        "added": added,
        "updated": updated,
        "count": len(load_shortlist(run_dir)),
        "candidates": [
            {
                "name": e.get("name"),
                "price": e.get("price"),
                "confidence": e.get("eav_confidence"),
                "rankable": e.get("rankable"),
            }
            for e in entries
        ],
        "promoted": len(promotable),
        "skipped_low_conf": max(0, n_obs - len(promotable)),
    }


# Back-compat alias used by older call sites / tests
def extract_observed_candidates(
    text: str,
    *,
    price_hints: list[Any] | None = None,
    source_url: str = "",
    max_candidates: int = 8,
) -> list[dict[str, Any]]:
    eavs = extract_eav_observations(
        text, price_hints=price_hints, source_url=source_url, max_items=max_candidates * 3
    )
    out: list[dict[str, Any]] = []
    for e in eavs:
        if e.get("amount_role") != "primary" or not e.get("entity"):
            continue
        if float(e.get("confidence") or 0) < 0.55:
            continue
        out.append(
            {
                "name": e["entity"],
                "price": e["value"],
                "source_url": e.get("source_url") or "",
                "raw_evidence": e.get("raw_evidence") or "",
                "confidence": e.get("confidence"),
            }
        )
        if len(out) >= max_candidates:
            break
    return out
