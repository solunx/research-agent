#!/usr/bin/env python3
"""
Local Research Agent – general-purpose Phase 1+

- External notes + research_state (context stays smaller)
- Memory: site tactics + strategies (self-improving tool routing)
- Longer LLM timeout; forced report from notes on failure
- Optional Docker-only guard
- Tool timings in CLI
- Optional planner/executor mode (--planned): split task, flush LLM
  context between sub-tasks, synthesize at the end
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from llm import OllamaClient
from memory_store import MemoryStore
from storage import (
    add_to_shortlist,
    append_conversation,
    append_note,
    compact_session_handoff,
    create_run_dir,
    filter_rankable_shortlist,
    harvest_invariant_from_browser_result,
    load_notes,
    load_shortlist,
    notes_as_prompt_text,
    save_metadata,
    save_report,
    save_sources,
    save_state,
    save_task,
    shortlist_as_prompt_text,
)
from tools import TOOL_DEFINITIONS, execute_tool, tool_definitions_for_backend
from urllib.parse import urlparse
from inline_recon import run_inline_recon_burst


MAX_TOOL_RESULT_CHARS = 2500
MAX_SEARCH_ITEMS_IN_CONTEXT = 5

# Generic planner: respects task primary sources / funnel; sequential phases
PLANNER_SYSTEM = """You are a research planner. Given a user research task, split it into
a small number of sequential research phases.

Rules:
- Output ONLY a JSON array of strings (no markdown fences, no commentary).
- Maximum 3 phases. Prefer 2 when the task is already focused.
- If the task names primary sources or a required approach/funnel, phase 1 MUST be:
  work only on those primary sources until a shortlist of concrete candidates exists.
- Later phases verify or deepen that shortlist — they must not restart broad discovery
  on unrelated source types as if nothing was found yet.
- Final global ranking is done by a separate synthesizer — do not include ranking as a phase.
- Keep each phase concrete and scoped. Same language as the user task.
- Do not invent brand names or domains that are not in the task.
"""


def require_docker_or_exit(config: dict[str, Any]) -> None:
    safety = config.get("safety") or {}
    if not safety.get("require_docker", True):
        return
    if os.environ.get("ALLOW_HOST_RUN") == "1":
        return
    if not os.path.exists("/.dockerenv"):
        print(
            "STOP: agent must run inside Docker (no /.dockerenv).\n"
            "  Use: docker compose run --rm research-agent python agent.py --task ...\n"
            "  Or set ALLOW_HOST_RUN=1 / safety.require_docker: false for debug.",
            file=sys.stderr,
        )
        sys.exit(2)


def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_task(task_arg: str) -> str:
    p = Path(task_arg)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return task_arg.strip()


def browser_backend_prompt_addon(backend: str) -> str:
    """Extra system rules depending on browser backend (A/B experiment)."""
    backend = (backend or "playwright").strip().lower()
    if backend == "browser_use":
        return (
            "\n### Browser backend: Browser Use (tiered — last resort)\n"
            "Low-level browser_click/type/open tools are **disabled** in this run.\n"
            "**Escalation order per host (mandatory):**\n"
            "1. `web_search` / `web_fetch` (cheap)\n"
            "2. If 403 / empty JS shell / prefer_browser → still try `web_fetch` once more "
            "on a deep-link if you have one, then escalate\n"
            "3. `browser_use` ONLY when cheaper tools failed on that host — "
            "ONE narrow instruction (list packages OR open one detail), with `start_url`\n"
            "4. After success (research runs only): `add_to_shortlist`; "
            "use `web_fetch` on detail URLs when possible\n"
            "Never open a bare homepage with browser_use when a search/deep-link URL exists.\n"
            "Never combine filter+list+detail in one browser_use call.\n"
            "Runtime limits browser_use calls per host; timeouts burn the budget — do not retry "
            "the same failing instruction.\n"
        )
    return (
        "\n### Browser backend: Playwright (built-in)\n"
        "Escalation order per host: web_fetch → browser_open (deep-link) → limited clicks. "
        "Prefer deep-link URLs and memory patterns. "
        "Do not thrash forms; after 2 no-ops use URL params or abandon host.\n"
    )


def run_kind_prompt_addon(run_kind: str) -> str:
    """Hard separation: recon/learning vs retrieval/delivery (enforced in code too)."""
    kind = (run_kind or "retrieval").strip().lower()
    if kind == "research":
        kind = "retrieval"
    if kind == "recon":
        return (
            "\n### RUN KIND: RECON / LEARNING (not a research delivery)\n"
            "Optimize for **maximum learnable website structure at minimum cost** — "
            "NOT for completing a user booking or ranking deals.\n"
            "\n"
            "**FORBIDDEN:**\n"
            "- `add_to_shortlist` (runtime rejects it)\n"
            "- Ranking / shortlisting candidates for any user task\n"
            "- Treating relaxed probe hits as final answers\n"
            "- Going to checkout / payment / personal data\n"
            "\n"
            "**Three capability layers to learn per host (stop when each is clear or budget hits):**\n"
            "1. **Navigation** — preferred channel; search/list path; never homepage-first if a pattern exists\n"
            "2. **Semantics** — what each param/field does: destination, dates, pax, meal/filters; "
            "what is rewritten, ignored, or mis-typed (e.g. count stored as date)\n"
            "3. **Harvest** — after a results page: where names + prices + links appear "
            "(price_hints, visible list). One detail page is enough; not full booking.\n"
            "\n"
            "**Probe style (prefer several small probes over one 'easy booking'):**\n"
            "- Change one dimension at a time when possible (destination OR dates OR pax OR meal)\n"
            "- Compare requested URL vs final URL after open\n"
            "- Use broader/simpler values only so a **results list** appears (learning inventory, not the task)\n"
            "- Stop per host when navigation+key semantics+harvest signal are known, "
            "or after empty-inventory / no-op budgets\n"
            "\n"
            "When done: RESEARCH_COMPLETE with a **mechanism summary per host** "
            "(navigation / semantics / harvest / failures). No product ranking.\n"
        )
    return (
        "\n### RUN KIND: RETRIEVAL (task delivery; alias: research)\n"
        "This is the **web retrieval** phase of the research agent: find and structure "
        "evidence for the user task. Prefer global memory: navigation + semantics + harvest "
        "(recipes, param_warnings, URL patterns) from prior recon.\n"
        "\n"
        "**Harvest (runtime code, not you):**\n"
        "- Runtime writes **all** EAV signals to observations.jsonl.\n"
        "- Runtime promotes to shortlist ONLY high-confidence product-title↔primary-price pairs "
        "with no query-state mismatch. Slogans, adjustments, filter UI, and mismatched pages "
        "stay in observations — never in the shortlist.\n"
        "- You may enrich real candidates with `add_to_shortlist` + constraints_check. "
        "Never invent entities; never upgrade to full match without evidence.\n"
        "- Rank only from shortlist after constraint honesty.\n"
        "\n"
        "**Production stop boundary (no mini-recon in retrieval):**\n"
        "- Deep-link → list → harvest once → next host or RESEARCH_COMPLETE.\n"
        "- Query-param rewrite vs request, UI no-ops, or empty after valid deep-link: "
        "`needs_recon` + **stop form clicks** on that host; move on.\n"
        "- Do **not** rediscover hosts from the homepage when recipes exist.\n"
        "Full recon is only `--run-kind recon` (separate capability).\n"
    )


def load_system_prompt(
    prompts_dir: str = "prompts",
    memory_block: str = "",
    browser_backend: str = "playwright",
    run_kind: str = "research",
) -> str:
    path = Path(prompts_dir) / "system.md"
    base = (
        path.read_text(encoding="utf-8")
        if path.exists()
        else "You are a careful research agent. Cite sources. Never invent facts."
    )
    parts = [base]
    if memory_block:
        parts.append(memory_block)
    parts.append(browser_backend_prompt_addon(browser_backend))
    parts.append(run_kind_prompt_addon(run_kind))
    return "\n\n".join(parts)


def _page_looks_empty_inventory(result: dict[str, Any]) -> bool:
    """Heuristic: opened OK but no prices and empty-result language in text."""
    if not isinstance(result, dict) or result.get("error"):
        return False
    if result.get("price_hints"):
        return False
    text = (result.get("text") or "").lower()
    if not text or len(text) < 80:
        return True
    markers = (
        "0 resultaten",
        "geen resultaten",
        "no results",
        "0 results",
        "niente trovato",
        "keine treffer",
        "no se han encontrado",
    )
    return any(m in text for m in markers)


def strip_warned_params_from_url(url: str, memory: MemoryStore) -> tuple[str, list[str]]:
    """
    If site_recipes has param_warnings (e.g. participants[0][0] is date-like),
    drop those query keys when the agent tries to send small integers as occupancy.
    Returns (possibly rewritten url, list of stripped keys).
    """
    if not url or not memory:
        return url, []
    try:
        from urllib.parse import parse_qsl, urlencode, urlunparse

        domain = memory.touch_domain(url)
        recipes = memory.load_recipes()
        entry = recipes.get(domain) or {}
        warnings = entry.get("param_warnings") or []
        warn_params = {
            str(w.get("param") or "").lower()
            for w in warnings
            if w.get("kind") == "not_count_looks_like_date"
        }
        if not warn_params:
            return url, []
        p = urlparse(url)
        pairs = parse_qsl(p.query, keep_blank_values=True)
        kept: list[tuple[str, str]] = []
        stripped: list[str] = []
        for k, v in pairs:
            kl = k.lower()
            if kl in warn_params and _looks_like_small_count(v):
                stripped.append(k)
                continue
            kept.append((k, v))
        if not stripped:
            return url, []
        new_q = urlencode(kept, doseq=True)
        new_url = urlunparse(
            (p.scheme, p.netloc, p.path, p.params, new_q, p.fragment)
        )
        return new_url, stripped
    except Exception:
        return url, []


def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    return message.get("tool_calls") or []


def is_complete(message: dict[str, Any]) -> bool:
    content = (message.get("content") or "").upper()
    return "RESEARCH_COMPLETE" in content


def truncate_tool_result(name: str, result: Any, max_chars: int = MAX_TOOL_RESULT_CHARS) -> Any:
    """
    Keep tool results usable for the LLM without blind aggressive cuts.

    Always preserve: url, title, price_hints, error/blocked flags.
    Body text is truncated only when still oversized after that.
    """
    if name == "web_search" and isinstance(result, list):
        trimmed = []
        for item in result[:MAX_SEARCH_ITEMS_IN_CONTEXT]:
            trimmed.append(
                {
                    "title": (item.get("title") or "")[:200],
                    "url": item.get("url") or "",
                    "snippet": (item.get("snippet") or "")[:300],
                }
            )
        return trimmed

    if isinstance(result, dict):
        out: dict[str, Any] = {}
        for key in (
            "url",
            "title",
            "error",
            "status_code",
            "blocked",
            "prefer_browser",
            "ok",
            "cookies_dismissed",
            "host_abandoned",
            "advice",
            "blocked_host",
        ):
            if key in result:
                out[key] = result[key]
        # Price signals are high-value — keep them fully (bounded list)
        if isinstance(result.get("price_hints"), list):
            out["price_hints"] = result["price_hints"][:25]
        text = result.get("text")
        if isinstance(text, str):
            # Prefer a larger body budget for browser pages (lists/prices often mid-page)
            body_budget = max_chars
            if name.startswith("browser_"):
                body_budget = max(max_chars, 4000)
            if len(text) > body_budget:
                out["text"] = (
                    text[:body_budget]
                    + f"\n...[truncated {len(text)} -> {body_budget} chars; "
                    "scroll or open a more specific URL if you need lower content]"
                )
            else:
                out["text"] = text
        for k, v in result.items():
            if k in out or k in ("text", "price_hints"):
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v
        return out

    s = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
    if len(s) > max_chars:
        return s[:max_chars] + f"...[truncated {len(s)} chars]"
    return result


def _query_constraint_keys(qs: dict[str, list[str]]) -> dict[str, str]:
    """Map interesting constraint-like query keys → first value (lowercased)."""
    hints = (
        "participant",
        "adult",
        "pax",
        "person",
        "traveler",
        "traveller",
        "guest",
        "date",
        "depart",
        "arrival",
        "checkin",
        "checkout",
        "meal",
        "board",
        "duration",
        "night",
        "airport",
        "origin",
        "transport",
        "room",
        "from",
    )
    out: dict[str, str] = {}
    for k, vals in qs.items():
        kl = k.lower()
        if any(h in kl for h in hints):
            v = (vals[0] if vals else "") or ""
            out[kl] = str(v).strip().lower()[:80]
    return out


def _looks_like_iso_date(s: str) -> bool:
    """Heuristic: YYYY-MM-DD or similar (generic, not domain-specific)."""
    s = (s or "").strip()
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", s))


def _looks_like_small_count(s: str) -> bool:
    """Heuristic: occupancy-like small integer (1–20)."""
    s = (s or "").strip()
    if not re.match(r"^\d{1,2}$", s):
        return False
    try:
        return 1 <= int(s) <= 20
    except ValueError:
        return False


def detect_constraint_mismatch(
    requested_url: str,
    final_url: str,
) -> dict[str, Any] | None:
    """
    Generic check: if the agent asked for constraint-like query params and the
    site rewrote them to different values, the constraint is not applicable here.
    No domain keywords — only structural param comparison.
    Also flags type-like semantic mismatches (e.g. small count → ISO date).
    """
    if not requested_url or not final_url:
        return None
    try:
        from urllib.parse import parse_qs

        req = urlparse(requested_url)
        fin = urlparse(final_url)
        req_q = _query_constraint_keys(parse_qs(req.query, keep_blank_values=True))
        fin_q = _query_constraint_keys(parse_qs(fin.query, keep_blank_values=True))
    except Exception:
        return None
    if not req_q:
        return None
    mismatches: list[str] = []
    semantic_flags: list[dict[str, str]] = []
    for k, req_v in req_q.items():
        if not req_v:
            continue
        # same key present with different value
        if k in fin_q and fin_q[k] and fin_q[k] != req_v:
            mismatches.append(f"{k}: requested={req_v[:40]} final={fin_q[k][:40]}")
            # Count sent, date returned → param is not a headcount field
            if _looks_like_small_count(req_v) and _looks_like_iso_date(fin_q[k]):
                semantic_flags.append(
                    {
                        "param": k,
                        "kind": "not_count_looks_like_date",
                        "detail": (
                            f"Sending a small integer as `{k}` produced a date-like "
                            f"value ({fin_q[k][:20]}). Do not use this param for "
                            "party size / occupancy; set occupancy via UI or another param."
                        ),
                    }
                )
            continue
        # date-like key missing or replaced by another date key with different value
        if "date" in k or "depart" in k or "check" in k:
            other_dates = {
                fk: fv
                for fk, fv in fin_q.items()
                if ("date" in fk or "depart" in fk or "check" in fk) and fv
            }
            if other_dates and req_v not in other_dates.values():
                # requested date value nowhere in final date params
                if not any(req_v in fv or fv in req_v for fv in other_dates.values()):
                    mismatches.append(
                        f"{k}: requested={req_v[:40]} not reflected in final URL"
                    )
    if not mismatches:
        return None
    advice = (
        "The site rewrote or ignored some constraint query parameters. "
        "Do NOT reopen the exact same URL. "
        "If this page still shows useful candidates (names + prices), "
        "add them to the shortlist with match_status=partial and unmatched/unknown "
        "filled honestly — then continue on the current page or try another source. "
        "Do not hard-abandon the host while visible deals remain."
    )
    if semantic_flags:
        advice += " Param semantics: " + " | ".join(
            f["detail"] for f in semantic_flags[:3]
        )
    return {
        "constraint_mismatch": True,
        "mismatches": mismatches[:8],
        "semantic_flags": semantic_flags[:6],
        "advice": advice,
    }


def _message_text(message: dict[str, Any]) -> str:
    content = (message.get("content") or "").strip()
    if content:
        return content
    return (message.get("thinking") or "").strip()


def note_from_tool(
    name: str,
    arguments: dict[str, Any],
    result: Any,
) -> dict[str, Any] | None:
    """Compact evidence stored outside the LLM chat context."""
    if name == "web_search" and isinstance(result, list):
        # one note summarizing search hits
        urls = [r.get("url") for r in result if r.get("url")][:5]
        titles = [r.get("title") for r in result if r.get("title")][:5]
        return {
            "source_type": "search",
            "query": arguments.get("query"),
            "title": f"search: {arguments.get('query', '')[:80]}",
            "summary": "; ".join(t for t in titles if t)[:500],
            "url": urls[0] if urls else "",
            "urls": urls,
        }
    browser_like = (
        "web_fetch",
        "browser_open",
        "browser_extract_text",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_wait",
        "browser_dismiss_cookies",
        "browser_use",
    )
    if name in browser_like and isinstance(result, dict):
        url = result.get("url") or arguments.get("url") or ""
        title = result.get("title") or ""
        blocked = bool(result.get("blocked") or result.get("prefer_browser"))
        err = result.get("error")
        text = (result.get("text") or "").strip()
        hints = result.get("price_hints") or []

        if err and not text:
            return {
                "source_type": name,
                "title": title,
                "url": url,
                "summary": f"ERROR: {err}",
                "ok": False,
                "blocked": blocked,
            }
        if blocked and len(text) < 400:
            return {
                "source_type": name,
                "title": title,
                "url": url,
                "summary": (
                    f"BLOCKED/SHORT ({err or 'little text'}). "
                    "Treat claims from this URL as unverified until browser succeeds."
                ),
                "ok": False,
                "blocked": True,
            }
        summary = text[:800]
        if hints:
            summary = "PRICES: " + " | ".join(str(h) for h in hints[:8]) + "\n" + summary
        return {
            "source_type": name,
            "title": title,
            "url": url,
            "summary": summary[:1200],
            "ok": not bool(err),
            "blocked": blocked,
        }
    return None


def build_partial_report(
    messages: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    status: str,
    task_text: str,
    notes_text: str = "",
) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant":
            content = _message_text(m)
            if len(content) > 200:
                header = (
                    f"# Research Report (partial – status: {status})\n\n"
                    f"> Run did not complete normally. Best available draft below.\n\n"
                )
                return header + content

    lines = [
        f"# Research Report (partial – status: {status})",
        "",
        "## Research question",
        task_text[:800] + ("..." if len(task_text) > 800 else ""),
        "",
        "## Notes collected",
        notes_text or "(none)",
        "",
        "## Sources retrieved",
    ]
    seen: set[str] = set()
    for s in sources:
        url = s.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        title = s.get("title") or url
        err = s.get("error")
        if err:
            lines.append(f"- {title} — {url} (error: {err})")
        else:
            lines.append(f"- {title} — {url}")
    if not seen:
        lines.append("- (no sources retrieved)")
    lines += [
        "",
        "## Uncertainties & limitations",
        f"- Run ended with status: `{status}`",
        "- No complete agent report was produced.",
        "",
    ]
    return "\n".join(lines)


def try_forced_report(
    client: OllamaClient,
    run_dir: Path,
    task_text: str,
    system_prompt: str,
) -> str | None:
    """Synthesize primarily from shortlist.json; notes only as supporting evidence."""
    all_items = load_shortlist(run_dir)
    rankable_items = filter_rankable_shortlist(all_items)
    excluded_n = max(0, len(all_items) - len(rankable_items))
    # Prompt text still shows full shortlist, with NOT_RANKABLE tags
    shortlist_text = shortlist_as_prompt_text(run_dir, max_chars=8000)
    shortlist_items = all_items
    notes = load_notes(run_dir, limit=80)
    notes_text = notes_as_prompt_text(notes, max_chars=6000, prioritize=True)

    if rankable_items:
        ranking_rule = (
            "RANK only items that are NOT marked NOT_RANKABLE and that do not carry "
            "query_state_mismatch. Those are the only candidates eligible for the top table. "
            f"({len(rankable_items)} rankable / {len(all_items)} total"
            + (f", {excluded_n} excluded for structural mismatch" if excluded_n else "")
            + "). "
            "Do NOT claim excluded items 'meet hard criteria'. "
            "Partial matches may appear in Ranking only with explicit partial status. "
            "Never claim full compliance when all-inclusive/pax/date remain unverified.\n"
        )
    elif all_items:
        ranking_rule = (
            "All shortlist rows are NOT_RANKABLE (e.g. query_state_mismatch) or observed-only noise. "
            "Do NOT invent a ranking of compliant deals. Explain limitations; list excluded "
            "rows only under Uncertainties if useful.\n"
        )
    else:
        ranking_rule = (
            "The SHORTLIST is empty. Conclude that no concrete candidates were structured. "
            "Use notes only to explain limitations — do not invent names.\n"
        )

    force_messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Research question:\n{task_text}\n\n"
                f"## SHORTLIST (primary source for Ranking)\n{shortlist_text}\n\n"
                f"## Supporting notes (evidence / limitations only)\n{notes_text}\n\n"
                "STOP. No tools. Write the final Markdown report now.\n"
                "Rules:\n"
                f"- {ranking_rule}"
                "- Use ONLY facts from shortlist + notes. Invent nothing.\n"
                "- Every ranked item must come from the shortlist when rankable items exist.\n"
                "- Mark verification status honestly from the evidence you have.\n"
                "- When shortlist items have observed_at / claims, cite them "
                "(when verified, and on which date if present).\n"
                "First line exact: RESEARCH_COMPLETE\n"
                "Structure: Research question, Executive summary, Ranking, "
                "Details, Uncertainties, Sources."
            ),
        },
    ]
    try:
        print(
            f"[agent] Forced report (shortlist={len(shortlist_items)} items, "
            f"rankable={len(rankable_items)}, notes={len(notes)})..."
        )
        append_conversation(
            run_dir,
            {
                "type": "forced_report_request",
                "mode": "shortlist_first",
                "shortlist_count": len(shortlist_items),
            },
        )
        message = client.chat(force_messages, tools=None)
        append_conversation(run_dir, {"type": "forced_report_response", "message": message})
        content = _message_text(message)
        if len(content) > 100:
            if "RESEARCH_COMPLETE" not in content.upper():
                content = "RESEARCH_COMPLETE\n\n" + content
            return content
    except Exception as e:
        print(f"[agent] Forced report failed: {e}")
        append_conversation(run_dir, {"type": "forced_report_error", "error": str(e)})
    return None


def plan_subtasks(client: OllamaClient, task_text: str, run_dir: Path) -> list[str]:
    """
    Generic planner: one fresh LLM call → JSON list of independent sub-tasks.
    Falls back to a single sub-task (= full task) on parse failure.
    """
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {
            "role": "user",
            "content": (
                "Split this research task into independent sub-tasks.\n\n"
                f"TASK:\n{task_text}\n\n"
                "Respond with ONLY a JSON array of strings."
            ),
        },
    ]
    print("[agent] Planner: splitting task into sub-tasks...")
    append_conversation(run_dir, {"type": "planner_request"})
    try:
        message = client.chat(messages, tools=None)
        append_conversation(run_dir, {"type": "planner_response", "message": message})
        raw = _message_text(message).strip()
        # Allow optional markdown fence
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        # Find first JSON array
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            subtasks = [str(x).strip() for x in parsed if str(x).strip()]
            subtasks = subtasks[:3]
            if subtasks:
                print(f"[agent] Planner produced {len(subtasks)} sub-task(s)")
                for i, s in enumerate(subtasks, 1):
                    print(f"[agent]   {i}. {s[:120]}{'...' if len(s) > 120 else ''}")
                (run_dir / "plan.json").write_text(
                    json.dumps(subtasks, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                return subtasks
    except Exception as e:
        print(f"[agent] Planner failed ({e}); falling back to single session")
        append_conversation(run_dir, {"type": "planner_error", "error": str(e)})

    return [task_text]


def build_subtask_prompt(
    full_task: str,
    subtask: str,
    index: int,
    total: int,
    prior_handoff: str = "",
    shortlist_text: str = "",
) -> str:
    """Focused user message for one executor session (generic)."""
    handoff_block = ""
    if prior_handoff.strip():
        handoff_block = (
            "\n## Findings from previous phase (read-only)\n"
            f"{prior_handoff.strip()}\n"
        )
    shortlist_block = ""
    if shortlist_text.strip() and shortlist_text.strip() != "(shortlist empty)":
        shortlist_block = (
            "\n## Structured shortlist so far (authoritative candidates)\n"
            f"{shortlist_text.strip()}\n\n"
            "Your job in this phase is to **verify / deepen these items only** "
            "(reviews, facilities, price checks on secondary sources if the task allows). "
            "Do **not** start a broad new market scan or add unrelated new destinations.\n"
            "After each useful verification, call `add_to_shortlist` again with the "
            "same name and richer details / better source_url so the final report sees updates.\n"
            "Prefer hotel/package **detail pages** over search-result list URLs.\n"
        )
    elif index > 1:
        shortlist_block = (
            "\n## Structured shortlist so far\n(empty)\n"
            "Previous phase did not structure candidates. "
            "You may continue primary-source discovery if still in scope, "
            "or document limitations and complete.\n"
        )
    return (
        f"## Full research task (context only)\n{full_task}\n\n"
        f"## Your focus for this session ({index}/{total})\n{subtask}\n"
        f"{shortlist_block}"
        f"{handoff_block}\n"
        "Work only on this focus. "
        "When you see a concrete candidate (name + price and/or URL), call "
        "`add_to_shortlist` immediately — prefer a detail/booking URL over a search list. "
        "If form UI clicks fail twice with no page change, try **one** `browser_open` "
        "with task constraints as URL query parameters (persons, dates, …) instead of "
        "more clicks on the same controls. "
        "When this focus is done (enough verified info or clear dead end), "
        "output RESEARCH_COMPLETE with a short Markdown summary for this "
        "sub-task only (not the global final ranking)."
    )


def run_session(
    *,
    client: OllamaClient,
    config: dict[str, Any],
    system_prompt: str,
    user_content: str,
    run_dir: Path,
    memory: MemoryStore,
    mem_cfg: dict[str, Any],
    sources: list[dict[str, Any]],
    counters: dict[str, int],
    limits: dict[str, Any],
    start_time: float,
    max_runtime: float,
    verbose: bool,
    session_label: str = "main",
    session_llm_budget: int | None = None,
    active_tools: list[dict[str, Any]] | None = None,
    run_kind: str = "research",
) -> dict[str, Any]:
    """
    One tool-using research loop with its own message list (fresh context).
    Notes/sources append to the shared run_dir / sources list.
    Returns {status, stop_reason, final_content, messages}.
    run_kind: "retrieval"/"research" (task delivery) | "recon" (learn hosts only; no shortlist).
    """
    run_kind = (run_kind or "retrieval").strip().lower()
    if run_kind == "research":
        run_kind = "retrieval"
    is_recon = run_kind == "recon"
    tools_for_llm = active_tools if active_tools is not None else TOOL_DEFINITIONS
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    max_llm = limits.get("max_llm_calls", 80)
    max_tools = limits.get("max_tool_calls", 150)
    max_search = limits.get("max_search_calls", 60)
    max_tool_result_chars = int(
        config.get("limits", {}).get("max_tool_result_chars", MAX_TOOL_RESULT_CHARS)
    )
    session_llm_start = counters["llm_calls"]
    session_tool_fail_streak = 0
    # Per-host browser budget + no-op detection (generic thrash guard)
    max_browser_per_host = int(limits.get("max_browser_actions_per_host", 8))
    max_noops_per_host = int(limits.get("max_browser_noops_per_host", 2))
    max_browser_use_per_host = int(limits.get("max_browser_use_per_host", 2))
    host_browser_count: dict[str, int] = {}
    host_noop_count: dict[str, int] = {}
    host_browser_use_count: dict[str, int] = {}  # tier-3 expensive agent calls
    host_browser_use_blocked: set[str] = set()  # after timeout or budget
    host_blocked: set[str] = set()
    # Inline recon: at most one learning burst per host per retrieval session
    inline_recon_done: set[str] = set()
    # Hosts that already contributed shortlist items — get one softer abandon path
    host_shortlist_hits: set[str] = set()
    host_url_param_grace: set[str] = set()  # one extra browser_open allowed after no-ops
    last_browser_sig: dict[str, tuple[str, frozenset[str]]] = {}
    # Empty-inventory budget per host (0 results / no price_hints)
    host_empty_inventory: dict[str, int] = {}
    max_empty_inventory = int(limits.get("max_empty_inventory_per_host", 3))
    # Single source of truth for the live tab (updated after every successful browser tool)
    current_page_url: str = ""

    def prefer_browser(url: str) -> bool:
        return memory.preferred_tool_for_url(url) == "browser_open"

    def host_of(url: str | None) -> str:
        """Normalize host: lowercase, strip www. so blocks/grace/patterns align."""
        if not url:
            return ""
        try:
            h = (urlparse(url).hostname or "").lower()
        except Exception:
            return ""
        if h.startswith("www."):
            h = h[4:]
        return h

    def _is_rootish_url(url: str) -> bool:
        """True for bare homepage / locale home without search path or query."""
        try:
            p = urlparse(url)
        except Exception:
            return True
        path = (p.path or "/").rstrip("/") or "/"
        # locale-only paths still count as rootish
        if path in ("/",) or path.count("/") <= 1 and len(path) <= 4:
            # /nl, /en, /fr, /be, /de …
            if not p.query:
                return True
        if path in ("/nl", "/en", "/fr", "/de", "/be", "/nl-be", "/fr-be"):
            return not p.query
        return False

    def _looks_like_search_url(url: str) -> bool:
        try:
            p = urlparse(url)
        except Exception:
            return False
        if p.query and ("=" in p.query):
            return True
        low = (p.path or "").lower()
        return any(
            x in low
            for x in (
                "/zoeken",
                "/search",
                "/results",
                "/vakantie/",
                "/all-inclusive",
                "/serp",
                "/find",
            )
        )

    def refresh_host_shortlist_hits() -> None:
        """Mark hosts whose URLs appear in the current shortlist."""
        for it in load_shortlist(run_dir):
            for u in list(it.get("source_urls") or []) + [it.get("source_url") or ""]:
                hh = host_of(str(u) if u else None)
                if hh:
                    host_shortlist_hits.add(hh)

    status = "running"
    stop_reason: str | None = None
    final_content = ""

    append_conversation(
        run_dir,
        {"type": "session_start", "session": session_label, "user_preview": user_content[:200]},
    )

    try:
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_runtime:
                print(f"[agent] [{session_label}] Max runtime reached")
                status = "timeout_runtime"
                stop_reason = "limit"
                break
            if counters["llm_calls"] >= max_llm:
                print(f"[agent] [{session_label}] Max LLM calls reached")
                status = "timeout_llm"
                stop_reason = "limit"
                break
            if session_llm_budget is not None:
                used = counters["llm_calls"] - session_llm_start
                if used >= session_llm_budget:
                    print(
                        f"[agent] [{session_label}] Session LLM budget reached "
                        f"({used}/{session_llm_budget})"
                    )
                    status = "session_budget"
                    stop_reason = "session_budget"
                    break
            if counters["tool_calls"] >= max_tools:
                print(f"[agent] [{session_label}] Max tool calls reached")
                status = "timeout_tools"
                stop_reason = "limit"
                break

            counters["llm_calls"] += 1
            call_n = counters["llm_calls"]
            print(f"[agent] [{session_label}] LLM call #{call_n} ...")
            append_conversation(
                run_dir,
                {
                    "type": "llm_request",
                    "session": session_label,
                    "call": call_n,
                    "message_count": len(messages),
                },
            )

            try:
                t_llm = time.perf_counter()
                message = client.chat(messages, tools=tools_for_llm)
                llm_ms = (time.perf_counter() - t_llm) * 1000
                print(f"[agent] [{session_label}] LLM call #{call_n} done ({llm_ms:.0f} ms)")
            except Exception as e:
                print(f"[agent] [{session_label}] LLM error after retries: {e}")
                append_conversation(
                    run_dir,
                    {"type": "llm_error", "session": session_label, "error": str(e)},
                )
                status = "llm_error"
                stop_reason = "llm_error"
                break

            append_conversation(
                run_dir,
                {
                    "type": "llm_response",
                    "session": session_label,
                    "call": call_n,
                    "message": message,
                },
            )

            if verbose:
                thinking = (message.get("thinking") or "")[:400]
                if thinking:
                    print(f"[agent] thinking: {thinking}...")

            tool_calls = extract_tool_calls(message)
            if tool_calls:
                messages.append(message)

                for tc in tool_calls:
                    counters["tool_calls"] += 1
                    func = tc.get("function") or {}
                    name = func.get("name") or ""
                    raw_args = func.get("arguments") or "{}"

                    if isinstance(raw_args, str):
                        try:
                            arguments = json.loads(raw_args)
                        except json.JSONDecodeError:
                            arguments = {}
                    else:
                        arguments = raw_args

                    print(f"[agent] [{session_label}] Tool call: {name}({arguments})")

                    # --- Structured shortlist tool (no network) ---
                    if name == "add_to_shortlist":
                        t0 = time.perf_counter()
                        if is_recon:
                            result = {
                                "ok": False,
                                "error": (
                                    "add_to_shortlist is disabled in --run-kind recon. "
                                    "This run only learns host mechanisms (URLs, params). "
                                    "Nothing may enter the research shortlist or ranking."
                                ),
                                "run_kind": "recon",
                            }
                            duration_ms = (time.perf_counter() - t0) * 1000
                            print(
                                f"[agent] [{session_label}] Tool {name} BLOCKED (recon mode) "
                                f"in {duration_ms:.0f} ms"
                            )
                            append_conversation(
                                run_dir,
                                {
                                    "type": "tool_result",
                                    "session": session_label,
                                    "tool": name,
                                    "arguments": arguments,
                                    "duration_ms": round(duration_ms, 1),
                                    "result_preview": str(result)[:500],
                                },
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "content": json.dumps(result, ensure_ascii=False),
                                    "name": name,
                                }
                            )
                            continue
                        cc = arguments.get("constraints_check")
                        if not isinstance(cc, dict):
                            cc = None
                        claims_arg = arguments.get("claims")
                        if not isinstance(claims_arg, list):
                            claims_arg = None
                        result = add_to_shortlist(
                            run_dir,
                            name=str(arguments.get("name") or ""),
                            source_url=str(arguments.get("source_url") or ""),
                            price=arguments.get("price"),
                            details=str(arguments.get("details") or ""),
                            session=session_label,
                            constraints_check=cc,
                            match_status=str(arguments.get("match_status") or "") or None,
                            claims=claims_arg,
                        )
                        if result.get("ok"):
                            counters["shortlist_adds"] = counters.get("shortlist_adds", 0) + 1
                        duration_ms = (time.perf_counter() - t0) * 1000
                        su = str(arguments.get("source_url") or "")
                        hh = host_of(su)
                        if hh:
                            host_shortlist_hits.add(hh)
                        refresh_host_shortlist_hits()
                        if result.get("ok"):
                            print(
                                f"[agent] [{session_label}] Tool {name} finished in "
                                f"{duration_ms:.0f} ms → {result.get('action')} "
                                f"(count={result.get('count')})"
                            )
                        else:
                            print(
                                f"[agent] [{session_label}] Tool {name} rejected in "
                                f"{duration_ms:.0f} ms → {result.get('error')}"
                            )
                        append_note(
                            run_dir,
                            {
                                "source_type": "shortlist",
                                "title": arguments.get("name"),
                                "summary": (
                                    f"{result.get('action')}: price={arguments.get('price')} "
                                    f"url={arguments.get('source_url')} "
                                    f"{str(arguments.get('details') or '')[:200]}"
                                ),
                                "url": arguments.get("source_url") or "",
                                "session": session_label,
                                "ok": bool(result.get("ok")),
                            },
                        )
                        counters["notes_count"] += 1
                        append_conversation(
                            run_dir,
                            {
                                "type": "tool_result",
                                "session": session_label,
                                "tool": name,
                                "arguments": arguments,
                                "duration_ms": round(duration_ms, 1),
                                "result_preview": str(result)[:500],
                            },
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "content": json.dumps(result, ensure_ascii=False),
                                "name": name,
                            }
                        )
                        continue

                    # --- Pre-check: host budget / blacklist for browser tools ---
                    pre_host = ""
                    # browser_use: resolve host from start_url (tier-3 budget)
                    if name == "browser_use":
                        bu_url = (
                            arguments.get("start_url")
                            or current_page_url
                            or ""
                        )
                        pre_host = host_of(str(bu_url)) if bu_url else ""
                        # If no URL, still allow but count under "_unknown"
                        bu_key = pre_host or "_unknown"
                        if bu_key in host_browser_use_blocked or (
                            host_browser_use_count.get(bu_key, 0) >= max_browser_use_per_host
                        ):
                            result = {
                                "error": (
                                    f"browser_use budget exhausted for host "
                                    f"{bu_key} (max {max_browser_use_per_host}/session). "
                                    "Use web_fetch on known detail URLs, another primary "
                                    "source, or RESEARCH_COMPLETE."
                                ),
                                "blocked_host": bu_key,
                                "advice": (
                                    "Do not retry the same browser_use instruction. "
                                    "Escalate only once per host after cheaper tools failed."
                                ),
                            }
                            duration_ms = 0.0
                            print(
                                f"[agent] [{session_label}] Skip browser_use on "
                                f"{bu_key} (budget/blocked)"
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "content": json.dumps(result, ensure_ascii=False),
                                    "name": name,
                                }
                            )
                            append_conversation(
                                run_dir,
                                {
                                    "type": "tool_result",
                                    "session": session_label,
                                    "tool": name,
                                    "arguments": arguments,
                                    "duration_ms": 0,
                                    "result_preview": str(result)[:500],
                                },
                            )
                            continue

                    if name.startswith("browser_"):
                        # Prefer explicit URL arg (browser_open); else live tab URL
                        pre_url = arguments.get("url") or current_page_url or ""
                        pre_host = host_of(str(pre_url)) if pre_url else ""
                        if pre_host and pre_host in host_blocked:
                            # Grace: ONE browser_open with a *search-like* different URL
                            # (not another homepage). Not tied to shortlist hits.
                            grace_url = str(arguments.get("url") or "")
                            allow_grace = (
                                name == "browser_open"
                                and pre_host not in host_url_param_grace
                                and grace_url
                                and grace_url != current_page_url
                                and _looks_like_search_url(grace_url)
                                and not _is_rootish_url(grace_url)
                            )
                            if allow_grace:
                                host_url_param_grace.add(pre_host)
                                host_blocked.discard(pre_host)
                                host_noop_count[pre_host] = 0
                                print(
                                    f"[agent] [{session_label}] Grace browser_open on "
                                    f"{pre_host} (URL-param / deep-link recovery)"
                                )
                            else:
                                result = {
                                    "error": (
                                        f"Host {pre_host} abandoned this session "
                                        f"(budget or repeated no-ops). "
                                        "Try another primary source or RESEARCH_COMPLETE."
                                    ),
                                    "blocked_host": pre_host,
                                    "advice": (
                                        "Do not keep clicking the same form. "
                                        "Grace only accepts a search/deep-link URL "
                                        "(query params or search path), not another homepage."
                                    ),
                                }
                                duration_ms = 0.0
                                print(
                                    f"[agent] [{session_label}] Skip browser on blocked host "
                                    f"{pre_host}"
                                )
                                messages.append(
                                    {
                                        "role": "tool",
                                        "content": json.dumps(result, ensure_ascii=False),
                                        "name": name,
                                    }
                                )
                                append_conversation(
                                    run_dir,
                                    {
                                        "type": "tool_result",
                                        "session": session_label,
                                        "tool": name,
                                        "arguments": arguments,
                                        "duration_ms": 0,
                                        "result_preview": str(result)[:500],
                                    },
                                )
                                continue
                        # Memory-first: refuse root/homepage open when learned search patterns exist
                        if (
                            name == "browser_open"
                            and pre_host
                            and isinstance(arguments.get("url"), str)
                            and _is_rootish_url(str(arguments.get("url")))
                        ):
                            patterns = memory.load_url_patterns()
                            # match host or parent
                            pat = patterns.get(pre_host)
                            if not pat:
                                for k, v in patterns.items():
                                    if pre_host == k or pre_host.endswith("." + k) or k.endswith("." + pre_host):
                                        pat = v
                                        break
                            if pat and (pat.get("param_names") or pat.get("path_hints")):
                                paths = ", ".join((pat.get("path_hints") or [])[:3])
                                params = ", ".join((pat.get("param_names") or [])[:10])
                                result = {
                                    "error": (
                                        f"Memory-first: host {pre_host} has learned search URL "
                                        f"patterns. Do not open the bare homepage first."
                                    ),
                                    "blocked_root_open": True,
                                    "advice": (
                                        "Build a deep-link/search URL using learned path + params, "
                                        "with values from the current task constraints. "
                                        f"paths=[{paths}] params=[{params}]. "
                                        "Only use the homepage if that deep-link fails (404/empty)."
                                    ),
                                    "learned_path_hints": (pat.get("path_hints") or [])[:5],
                                    "learned_param_names": (pat.get("param_names") or [])[:15],
                                }
                                duration_ms = 0.0
                                counters["memory_first_rejects"] = (
                                    counters.get("memory_first_rejects", 0) + 1
                                )
                                print(
                                    f"[agent] [{session_label}] Memory-first: reject root open "
                                    f"on {pre_host} (patterns known)"
                                )
                                messages.append(
                                    {
                                        "role": "tool",
                                        "content": json.dumps(result, ensure_ascii=False),
                                        "name": name,
                                    }
                                )
                                append_conversation(
                                    run_dir,
                                    {
                                        "type": "tool_result",
                                        "session": session_label,
                                        "tool": name,
                                        "arguments": arguments,
                                        "duration_ms": 0,
                                        "result_preview": str(result)[:500],
                                    },
                                )
                                continue

                        if pre_host and host_browser_count.get(pre_host, 0) >= max_browser_per_host:
                            host_blocked.add(pre_host)
                            result = {
                                "error": (
                                    f"max_browser_actions_per_host ({max_browser_per_host}) "
                                    f"reached for {pre_host}. Abandon this host."
                                ),
                                "blocked_host": pre_host,
                            }
                            duration_ms = 0.0
                            print(
                                f"[agent] [{session_label}] Host budget exhausted: {pre_host}"
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "content": json.dumps(result, ensure_ascii=False),
                                    "name": name,
                                }
                            )
                            continue

                        # Param-warning guard: strip occupancy integers on date-like keys
                        if name == "browser_open" and isinstance(arguments.get("url"), str):
                            new_u, stripped = strip_warned_params_from_url(
                                str(arguments["url"]), memory
                            )
                            if stripped:
                                arguments = dict(arguments)
                                arguments["url"] = new_u
                                print(
                                    f"[agent] [{session_label}] Stripped warned params "
                                    f"{stripped} from deep-link (param_warnings)"
                                )

                    if name == "web_search":
                        counters["search_calls"] += 1
                        if counters["search_calls"] > max_search:
                            result = {"error": "max_search_calls exceeded"}
                            duration_ms = 0.0
                        else:
                            result, duration_ms = execute_tool(
                                name, arguments, config, prefer_browser_for_url=prefer_browser
                            )
                    else:
                        result, duration_ms = execute_tool(
                            name, arguments, config, prefer_browser_for_url=prefer_browser
                        )

                    print(
                        f"[agent] [{session_label}] Tool {name} finished in {duration_ms:.0f} ms"
                    )

                    url = None
                    ok = True
                    blocked = False
                    err = None
                    if isinstance(result, dict):
                        url = result.get("url") or arguments.get("url") or arguments.get(
                            "start_url"
                        )
                        err = result.get("error")
                        blocked = bool(result.get("blocked") or result.get("policy_stop"))
                        ok = not err or (result.get("text") and not blocked)
                        # Web policy / CAPTCHA: stop host for this research session
                        if result.get("policy_stop") and url:
                            ph = host_of(str(url))
                            if ph:
                                host_blocked.add(ph)
                                print(
                                    f"[agent] [{session_label}] Policy stop on {ph}: "
                                    f"{result.get('policy_reason') or 'blocked'}"
                                )
                                if mem_cfg.get("enabled", True):
                                    try:
                                        memory.mark_needs_recon(
                                            ph,
                                            reason=str(
                                                result.get("policy_reason")
                                                or "policy_stop"
                                            )[:200],
                                        )
                                    except Exception:
                                        pass
                    if name == "web_search":
                        ok = isinstance(result, list) and len(result) > 0
                        if isinstance(result, list) and result:
                            non_notice = [
                                r
                                for r in result
                                if (r.get("title") or "") != "Query notice"
                            ]
                            ok = len(non_notice) > 0 and not (
                                len(non_notice) == 1
                                and (non_notice[0].get("title") or "") == "Search error"
                            )
                        url = None

                    # --- browser_use: count toward per-host tier-3 budget ---
                    if name == "browser_use":
                        bu_url = (
                            (url if isinstance(url, str) else None)
                            or arguments.get("start_url")
                            or current_page_url
                            or ""
                        )
                        bu_key = host_of(str(bu_url)) if bu_url else "_unknown"
                        host_browser_use_count[bu_key] = (
                            host_browser_use_count.get(bu_key, 0) + 1
                        )
                        timed_out = bool(
                            err
                            and (
                                "timed out" in str(err).lower()
                                or "timeout" in str(err).lower()
                            )
                        )
                        if timed_out or not ok:
                            # One failure/timeout is enough to stop further heavy calls
                            # on this host for the rest of the session
                            host_browser_use_blocked.add(bu_key)
                            print(
                                f"[agent] [{session_label}] browser_use failed/timeout on "
                                f"{bu_key} — further browser_use blocked for this host"
                            )
                            if mem_cfg.get("enabled", True):
                                memory.record_tier_outcome(
                                    bu_key,
                                    tier="browser_use",
                                    success=False,
                                    reason=str(err or "browser_use failed")[:200],
                                )
                        elif ok:
                            if mem_cfg.get("enabled", True):
                                memory.record_tier_outcome(
                                    bu_key,
                                    tier="browser_use",
                                    success=True,
                                    reason="browser_use returned text",
                                )
                        if host_browser_use_count[bu_key] >= max_browser_use_per_host:
                            host_browser_use_blocked.add(bu_key)

                    # --- Live tab URL + host budget + no-op tracking ---
                    if name.startswith("browser_") and isinstance(result, dict):
                        # Always refresh current_page_url from the real tab when present
                        result_url = result.get("url")
                        if isinstance(result_url, str) and result_url.startswith("http"):
                            current_page_url = result_url
                        elif (
                            name == "browser_open"
                            and isinstance(arguments.get("url"), str)
                            and not err
                        ):
                            current_page_url = str(arguments["url"])

                        h = host_of(current_page_url) or host_of(
                            url if isinstance(url, str) else None
                        ) or pre_host
                        if h:
                            host_browser_count[h] = host_browser_count.get(h, 0) + 1
                            hints = result.get("price_hints") or []
                            hint_set = frozenset(str(x) for x in hints[:20])
                            page_url = current_page_url or (
                                result_url if isinstance(result_url, str) else ""
                            )
                            sig = (page_url, hint_set)
                            prev = last_browser_sig.get(h)
                            is_noop = False
                            # Consent iframe / pointer-intercept failures do not burn no-op budget
                            exempt = bool(
                                isinstance(result, dict) and result.get("no_op_exempt")
                            )
                            if prev is not None and not exempt:
                                prev_url, prev_hints = prev
                                # same URL and no new price hints → functional no-op
                                if page_url and page_url == prev_url and hint_set <= prev_hints:
                                    is_noop = True
                                if err and not (
                                    isinstance(err, str)
                                    and (
                                        "intercepts pointer" in err
                                        or "consent_iframe" in err
                                    )
                                ):
                                    is_noop = True
                            last_browser_sig[h] = sig
                            if is_noop:
                                host_noop_count[h] = host_noop_count.get(h, 0) + 1
                            else:
                                host_noop_count[h] = 0
                            if host_noop_count.get(h, 0) >= max_noops_per_host:
                                refresh_host_shortlist_hits()
                                host_blocked.add(h)
                                counters["host_abandons"] = (
                                    counters.get("host_abandons", 0) + 1
                                )
                                print(
                                    f"[agent] [{session_label}] Host {h} abandoned "
                                    f"after {max_noops_per_host} no-ops"
                                )
                                # Production stop boundary: no mini-recon in retrieve
                                if not is_recon:
                                    try:
                                        memory.mark_needs_recon(
                                            h,
                                            reason=(
                                                f"repeated UI no-ops in research "
                                                f"(session={session_label})"
                                            ),
                                        )
                                    except Exception:
                                        pass
                                if isinstance(result, dict):
                                    result = dict(result)
                                    result["host_abandoned"] = True
                                    if is_recon:
                                        result["advice"] = (
                                            f"Stop clicking the same controls on {h}. "
                                            "Note what failed (selector/param) for host "
                                            "learnings; move to next host probe."
                                        )
                                    else:
                                        result["advice"] = (
                                            f"Stop learning UI on {h} during research. "
                                            "Host marked needs_recon. Use any candidates "
                                            "already auto-harvested or shortlisted; move to "
                                            "another primary source or RESEARCH_COMPLETE. "
                                            "Do not keep form-clicking."
                                        )
                            if host_browser_count.get(h, 0) >= max_browser_per_host:
                                host_blocked.add(h)

                    # Generic: repeated tool failures → stop thrashing this session
                    tool_failed = bool(err) or blocked or not ok
                    if name.startswith("browser_"):
                        if tool_failed:
                            session_tool_fail_streak += 1
                        else:
                            session_tool_fail_streak = 0
                    if session_tool_fail_streak >= 3:
                        print(
                            f"[agent] [{session_label}] "
                            "3 consecutive browser failures — ending session early"
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "content": json.dumps(
                                    {
                                        "error": (
                                            "Repeated browser interaction failures. "
                                            "Stop UI retries; call add_to_shortlist for "
                                            "any concrete finds, then RESEARCH_COMPLETE."
                                        )
                                    },
                                    ensure_ascii=False,
                                ),
                                "name": name,
                            }
                        )
                        session_tool_fail_streak = 0

                    if mem_cfg.get("enabled", True):
                        memory.record_tool_result(
                            tool=name,
                            url=url if isinstance(url, str) else None,
                            ok=ok,
                            duration_ms=duration_ms,
                            error=err if isinstance(err, str) else None,
                            blocked=blocked,
                        )

                    note = note_from_tool(name, arguments, result)
                    if note:
                        note["session"] = session_label
                        append_note(run_dir, note)
                        counters["notes_count"] += 1

                    if name == "web_search" and isinstance(result, list):
                        for r in result:
                            if r.get("url"):
                                sources.append(
                                    {
                                        "url": r["url"],
                                        "title": r.get("title", ""),
                                        "source_type": "search_result",
                                        "retrieved_at": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                        "snippet": r.get("snippet", ""),
                                        "session": session_label,
                                    }
                                )
                    elif name in (
                        "web_fetch",
                        "browser_open",
                        "browser_extract_text",
                        "browser_click",
                        "browser_type",
                        "browser_scroll",
                        "browser_wait",
                        "browser_dismiss_cookies",
                    ) and isinstance(result, dict):
                        if result.get("url"):
                            entry = {
                                "url": result["url"],
                                "title": result.get("title", ""),
                                "source_type": (
                                    "page" if name == "web_fetch" else "browser"
                                ),
                                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                "error": result.get("error"),
                                "session": session_label,
                            }
                            if result.get("price_hints"):
                                entry["price_hints"] = result["price_hints"][:15]
                            sources.append(entry)

                    # Constraint mismatch first (so harvest can tag candidates)
                    page_mismatches: list[str] = []
                    if (
                        name == "browser_open"
                        and isinstance(result, dict)
                        and isinstance(arguments.get("url"), str)
                        and isinstance(result.get("url"), str)
                    ):
                        mm = detect_constraint_mismatch(
                            str(arguments["url"]),
                            str(result["url"]),
                        )
                        if mm:
                            page_mismatches = list(mm.get("mismatches") or [])
                            counters["constraint_mismatches"] = (
                                counters.get("constraint_mismatches", 0) + 1
                            )
                            try:
                                memory.record_url_pattern_outcome(
                                    str(result["url"]),
                                    success=False,
                                    reason="; ".join(page_mismatches)[:200],
                                )
                            except Exception:
                                pass
                            for flag in mm.get("semantic_flags") or []:
                                try:
                                    memory.record_param_warning(
                                        str(result["url"]),
                                        param=str(flag.get("param") or ""),
                                        kind=str(flag.get("kind") or ""),
                                        detail=str(flag.get("detail") or "")[:300],
                                    )
                                except Exception:
                                    pass
                            if isinstance(result, dict):
                                result = dict(result)
                                result["constraint_mismatch"] = True
                                result["constraint_mismatches"] = page_mismatches
                                result["param_semantics"] = mm.get("semantic_flags")
                                result["advice"] = mm.get("advice")

                            h_mm = host_of(str(result.get("url"))) or pre_host
                            has_prices = bool(result.get("price_hints"))
                            if is_recon:
                                print(
                                    f"[agent] [{session_label}] Constraint mismatch on "
                                    f"{h_mm or '?'} — soft (keep page; recon learn only)"
                                )
                            elif h_mm and not has_prices and h_mm not in host_shortlist_hits:
                                host_blocked.add(h_mm)
                                counters["host_abandons"] = (
                                    counters.get("host_abandons", 0) + 1
                                )
                                print(
                                    f"[agent] [{session_label}] Constraint mismatch on "
                                    f"{h_mm} — host abandoned (no price signals)"
                                )
                            elif h_mm:
                                # Retrieval: structural filter rewrite → one harvest, then stop UI
                                try:
                                    memory.mark_needs_recon(
                                        h_mm,
                                        reason=(
                                            "query params rewritten vs request: "
                                            + "; ".join(page_mismatches)[:180]
                                        ),
                                    )
                                except Exception:
                                    pass
                                host_blocked.add(h_mm)
                                counters["host_abandons"] = (
                                    counters.get("host_abandons", 0) + 1
                                )
                                print(
                                    f"[agent] [{session_label}] Constraint mismatch on "
                                    f"{h_mm} — needs_recon + host done for retrieval "
                                    f"(no further UI; harvest once if prices visible)"
                                )
                                result["advice"] = (
                                    f"Structural query mismatch on {h_mm}. "
                                    "Do not click forms to 'fix' filters in retrieval. "
                                    "Host marked needs_recon. Use auto-candidates if any, "
                                    "then move to another primary source."
                                )
                                # Inline recon skeleton: separate process, memory-only,
                                # invisible to retrieval LLM (no messages appended).
                                if h_mm not in inline_recon_done:
                                    inline_recon_done.add(h_mm)
                                    try:

                                        def _browser_open_probe(u: str) -> dict:
                                            res, _ms = execute_tool(
                                                "browser_open",
                                                {"url": u},
                                                config,
                                            )
                                            return res if isinstance(res, dict) else {"error": str(res)}

                                        ir = run_inline_recon_burst(
                                            host=h_mm,
                                            memory=memory,
                                            browser_open_fn=_browser_open_probe,
                                            max_probes=2,
                                            session_label=f"inline_recon:{h_mm}",
                                        )
                                        counters["inline_recon"] = (
                                            counters.get("inline_recon", 0) + 1
                                        )
                                        print(
                                            f"[agent] [{session_label}] Inline recon "
                                            f"{h_mm}: probes={ir.get('probes')} "
                                            f"cleared={ir.get('cleared_needs_recon')} "
                                            f"(memory only; shortlist untouched)"
                                        )
                                        # One retrieval retry allowed after recon learned
                                        if ir.get("cleared_needs_recon"):
                                            host_blocked.discard(h_mm)
                                            result["advice"] = (
                                                f"Inline recon updated memory for {h_mm}. "
                                                "You may retry ONE deep-link using learned "
                                                "patterns; still no form thrash."
                                            )
                                    except Exception as ir_err:
                                        print(
                                            f"[agent] [{session_label}] Inline recon "
                                            f"skipped: {ir_err}"
                                        )

                    # Harvest: observations always; shortlist only high-conf primary EAV
                    if (
                        not is_recon
                        and name
                        in (
                            "browser_open",
                            "browser_extract_text",
                            "browser_click",
                            "browser_scroll",
                            "browser_wait",
                        )
                        and isinstance(result, dict)
                        and not result.get("error")
                        and (result.get("text") or result.get("price_hints"))
                    ):
                        try:
                            hv = harvest_invariant_from_browser_result(
                                run_dir,
                                result,
                                session=session_label,
                                constraint_mismatches=page_mismatches or None,
                            )
                            n_obs = int(hv.get("observations") or 0)
                            if n_obs or hv.get("added") or hv.get("updated"):
                                print(
                                    f"[agent] [{session_label}] Harvest: "
                                    f"obs={n_obs} promoted=+{hv.get('added', 0)} "
                                    f"~{hv.get('updated', 0)} "
                                    f"(shortlist={hv.get('count')}, "
                                    f"low_conf_skipped={hv.get('skipped_low_conf', 0)})"
                                )
                            if hv.get("added") or hv.get("updated"):
                                counters["shortlist_adds"] = (
                                    counters.get("shortlist_adds", 0)
                                    + int(hv.get("added") or 0)
                                )
                                # useful = promoted candidates only (not raw observations)
                                counters["useful_actions"] = (
                                    counters.get("useful_actions", 0)
                                    + int(hv.get("added") or 0)
                                )
                                refresh_host_shortlist_hits()
                            if isinstance(result, dict) and (n_obs or hv.get("added")):
                                result = dict(result)
                                result["harvest_invariant"] = {
                                    "observations": n_obs,
                                    "added": hv.get("added"),
                                    "updated": hv.get("updated"),
                                    "candidates": hv.get("candidates"),
                                    "skipped_low_conf": hv.get("skipped_low_conf"),
                                }
                        except Exception as _hv_err:
                            print(
                                f"[agent] [{session_label}] Harvest invariant error: "
                                f"{_hv_err}"
                            )

                    result_for_context = truncate_tool_result(
                        name, result, max_chars=max_tool_result_chars
                    )
                    if (
                        isinstance(result, dict)
                        and result.get("constraint_mismatch")
                        and isinstance(result_for_context, dict)
                    ):
                        result_for_context = dict(result_for_context)
                        result_for_context["constraint_mismatch"] = True
                        result_for_context["constraint_mismatches"] = result.get(
                            "constraint_mismatches"
                        )
                        result_for_context["advice"] = result.get("advice")
                        if is_recon:
                            result_for_context["system_nudge"] = (
                                "RECON: params rewritten. Record final URL + param semantics; "
                                "no shortlist. Next host when done."
                            )

                    # Learn search URL patterns + capability layers (generic)
                    if (
                        name.startswith("browser_")
                        and isinstance(result, dict)
                        and not err
                        and isinstance(result.get("url"), str)
                    ):
                        try:
                            useful = bool(
                                result.get("price_hints")
                                or "zoeken" in str(result.get("url")).lower()
                                or "search" in str(result.get("url")).lower()
                            )
                            memory.record_search_url(
                                str(result["url"]),
                                useful=useful,
                            )
                            if name == "browser_open" and useful:
                                from urllib.parse import urlparse as _up

                                path = _up(str(result["url"])).path or ""
                                memory.record_navigation_success(
                                    str(result["url"]),
                                    channel="browser_open",
                                    path_hint=path or None,
                                )
                            if result.get("price_hints"):
                                memory.record_harvest_hint(
                                    str(result["url"]),
                                    hint="list/detail page yields price_hints in extract",
                                    has_price_signals=True,
                                    has_name_list=None,
                                )
                        except Exception:
                            pass

                    # Empty inventory budget: stop thrashing hosts that return 0 results
                    if (
                        name == "browser_open"
                        and isinstance(result, dict)
                        and not result.get("error")
                    ):
                        h_empty = host_of(str(result.get("url") or arguments.get("url") or ""))
                        if h_empty and _page_looks_empty_inventory(result):
                            host_empty_inventory[h_empty] = (
                                host_empty_inventory.get(h_empty, 0) + 1
                            )
                            n_empty = host_empty_inventory[h_empty]
                            result_for_context = dict(
                                result_for_context
                                if isinstance(result_for_context, dict)
                                else result
                            )
                            if n_empty >= max_empty_inventory:
                                host_blocked.add(h_empty)
                                counters["host_abandons"] = (
                                    counters.get("host_abandons", 0) + 1
                                )
                                result_for_context["empty_inventory"] = True
                                result_for_context["advice"] = (
                                    f"Host {h_empty}: {n_empty} opens with empty inventory "
                                    "(0 results / no prices). Host done for this session — "
                                    "try another primary source or RESEARCH_COMPLETE."
                                )
                                print(
                                    f"[agent] [{session_label}] Empty inventory cap on "
                                    f"{h_empty} ({n_empty}) — host abandoned"
                                )
                            elif n_empty == 1:
                                result_for_context["empty_inventory"] = True
                                result_for_context["system_nudge"] = (
                                    "0 results / no price signals. One more attempt allowed "
                                    "with *fewer* filters (broader dates or fewer constraints). "
                                    "If still empty, leave this host."
                                )
                                print(
                                    f"[agent] [{session_label}] Empty inventory on "
                                    f"{h_empty} (1/{max_empty_inventory}) — prune filters once"
                                )

                    # Soft nudge: prices visible but nothing promoted to shortlist
                    if (
                        not is_recon
                        and name.startswith("browser_")
                        and isinstance(result_for_context, dict)
                        and result_for_context.get("price_hints")
                        and not load_shortlist(run_dir)
                    ):
                        result_for_context = dict(result_for_context)
                        result_for_context["system_nudge"] = (
                            "Price-like signals exist but no high-confidence entity↔price "
                            "pair was promoted (observations may still be in observations.jsonl). "
                            "Scroll/extract for clearer product titles next to primary prices, "
                            "or call add_to_shortlist yourself with evidence — "
                            "do not invent entities."
                        )
                    elif (
                        not is_recon
                        and name.startswith("browser_")
                        and isinstance(result_for_context, dict)
                        and result_for_context.get("harvest_invariant")
                    ):
                        result_for_context = dict(result_for_context)
                        hi = result_for_context["harvest_invariant"] or {}
                        n_auto = hi.get("added") or 0
                        if n_auto:
                            result_for_context["system_nudge"] = (
                                f"Runtime promoted {n_auto} candidate(s) "
                                f"(obs={hi.get('observations')}). Enrich via add_to_shortlist "
                                "with constraints_check; do not treat observed_only as full match."
                            )

                    append_conversation(
                        run_dir,
                        {
                            "type": "tool_result",
                            "session": session_label,
                            "tool": name,
                            "arguments": arguments,
                            "duration_ms": round(duration_ms, 1),
                            "result_preview": str(result_for_context)[:500],
                        },
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                result_for_context, ensure_ascii=False
                            ),
                            "name": name,
                        }
                    )

                save_state(
                    run_dir,
                    {
                        "status": "running",
                        "session": session_label,
                        "llm_calls": counters["llm_calls"],
                        "tool_calls": counters["tool_calls"],
                        "sources_count": len(sources),
                        "notes_count": counters["notes_count"],
                        "progress": f"{session_label} after LLM {call_n}",
                        "key_findings": "",
                    },
                )
                continue

            content = message.get("content") or ""
            messages.append(message)

            if is_complete(message):
                print(f"[agent] [{session_label}] RESEARCH_COMPLETE")
                final_content = content
                status = "completed"
                break

            # Model replied without tools and without complete — nudge once via loop continue
            # (avoid infinite empty replies: treat as soft complete if long enough)
            if len(content) > 500 and "RESEARCH_COMPLETE" not in content.upper():
                # Ask model to either tool-call or finish — by appending a short user nudge
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue with tools if more evidence is needed, "
                            "or finish with RESEARCH_COMPLETE and a short summary for this focus."
                        ),
                    }
                )
                continue

    except KeyboardInterrupt:
        print(f"\n[agent] [{session_label}] Interrupted")
        status = "cancelled"
        stop_reason = "cancelled"
        raise
    except Exception as e:
        print(f"[agent] [{session_label}] Unexpected error: {e}")
        append_conversation(
            run_dir,
            {"type": "fatal_error", "session": session_label, "error": str(e)},
        )
        status = "error"
        stop_reason = "error"

    append_conversation(
        run_dir,
        {
            "type": "session_end",
            "session": session_label,
            "status": status,
            "stop_reason": stop_reason,
        },
    )
    # Drop message list — context flush for next session
    return {
        "status": status,
        "stop_reason": stop_reason,
        "final_content": final_content,
        "messages": messages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Research Agent")
    parser.add_argument("--task", required=True, help="Path to task file or task string")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--verbose", action="store_true", help="Print thinking snippets")
    parser.add_argument(
        "--planned",
        action="store_true",
        help=(
            "Planner/executor mode: split task into sub-tasks, fresh LLM context "
            "per sub-task (flush), synthesize report from notes at the end"
        ),
    )
    parser.add_argument(
        "--browser-backend",
        choices=("playwright", "browser_use"),
        default=None,
        help=(
            "Browser execution backend for A/B tests: "
            "playwright (built-in click/type) or browser_use (high-level agent tool). "
            "Default from config tools.browser.backend or playwright."
        ),
    )
    parser.add_argument(
        "--run-kind",
        choices=("retrieval", "research", "recon"),
        default="retrieval",
        help=(
            "retrieval (preferred) / research (alias) = fulfill the task "
            "(shortlist + report) using memory-first web retrieval. "
            "recon = learn host mechanisms only (no shortlist; nothing enters ranking). "
            "Use recon first on new hosts, then retrieval with the same task file."
        ),
    )
    args = parser.parse_args()

    config = load_config(args.config)
    require_docker_or_exit(config)

    task_text = load_task(args.task)
    verbose = args.verbose or bool(config.get("verbose"))
    planned = bool(args.planned)
    # Normalize: research is legacy alias for retrieval (delivery run)
    run_kind = str(args.run_kind or "retrieval").strip().lower()
    if run_kind == "research":
        run_kind = "retrieval"
    browser_backend = (
        args.browser_backend
        or ((config.get("tools") or {}).get("browser") or {}).get("backend")
        or "playwright"
    )
    browser_backend = str(browser_backend).strip().lower()
    active_tools = tool_definitions_for_backend(browser_backend)

    mem_cfg = config.get("memory") or {}
    memory = MemoryStore(config.get("storage", {}).get("memory_dir", "memory"))
    if mem_cfg.get("enabled", True):
        memory.ensure_seed_strategies()
        memory_block = memory.prompt_block(
            max_tactics=int(mem_cfg.get("max_tactics_in_prompt", 40)),
            max_strategies=int(mem_cfg.get("max_strategies_in_prompt", 15)),
            retest_after_days=int(mem_cfg.get("retest_after_days", 30)),
        )
    else:
        memory_block = ""

    system_prompt = load_system_prompt(
        memory_block=memory_block,
        browser_backend=browser_backend,
        run_kind=run_kind,
    )

    llm_cfg = config.get("llm", {})
    limits = config.get("limits", {})
    storage_cfg = config.get("storage", {})

    client = OllamaClient(
        base_url=llm_cfg.get("base_url", "http://172.17.0.1:11434"),
        model=llm_cfg.get("model", "qwen3.8:27b"),
        temperature=llm_cfg.get("temperature", 0.2),
        timeout=llm_cfg.get("timeout_seconds", 480),
        max_retries=llm_cfg.get("max_retries", 2),
        retry_backoff_seconds=llm_cfg.get("retry_backoff_seconds", 2.0),
    )

    task_slug = Path(args.task).stem if Path(args.task).exists() else "research"
    run_dir = create_run_dir(storage_cfg.get("runs_dir", "runs"), task_slug)
    save_task(run_dir, task_text)

    print(f"[agent] Run directory: {run_dir}")
    print(f"[agent] Model: {client.model}")
    print(f"[agent] Timeout: {client.timeout}s")
    print(f"[agent] Task loaded ({len(task_text)} chars)")
    print(f"[agent] Mode: {'planned (planner/executor/critic)' if planned else 'single session'}")
    print(f"[agent] Run kind: {run_kind}"
          + (" (learning only — shortlist disabled)" if run_kind == "recon" else " (task delivery)"))
    print(f"[agent] Browser backend: {browser_backend} ({len(active_tools)} tools exposed)")
    if mem_cfg.get("enabled", True):
        print(f"[agent] Memory: {memory.root} (tactics+strategies loaded)")

    sources: list[dict[str, Any]] = []
    start_time = time.time()
    counters = {
        "llm_calls": 0,
        "tool_calls": 0,
        "search_calls": 0,
        "notes_count": 0,
        "shortlist_adds": 0,
        "constraint_mismatches": 0,
        "sessions_skipped": 0,
        "memory_first_rejects": 0,
        "host_abandons": 0,
    }
    max_runtime = limits.get("max_runtime_minutes", 120) * 60
    status = "running"
    final_report = ""
    last_messages: list[dict[str, Any]] = []
    stop_reason: str | None = None

    append_conversation(
        run_dir,
        {
            "type": "run_start",
            "model": client.model,
            "mode": "planned" if planned else "single",
            "run_kind": run_kind,
            "browser_backend": browser_backend,
            "task_preview": task_text[:300],
        },
    )
    save_state(
        run_dir,
        {
            "status": "running",
            "mode": "planned" if planned else "single",
            "run_kind": run_kind,
            "llm_calls": 0,
            "tool_calls": 0,
            "sources_count": 0,
            "notes_count": 0,
            "progress": "started",
            "key_findings": "",
        },
    )

    try:
        if planned:
            subtasks = plan_subtasks(client, task_text, run_dir)
            counters["llm_calls"] += 1  # planner used one call
            n_subs = max(len(subtasks), 1)
            # Reserve headroom for planner (done) + critic (~1) + margin
            remaining = max(limits.get("max_llm_calls", 80) - counters["llm_calls"] - 4, n_subs * 8)
            per_sub_budget = max(8, remaining // n_subs)
            print(f"[agent] Per-sub LLM budget: ~{per_sub_budget} (sequential phases: {n_subs})")

            prior_handoff = ""
            for i, sub in enumerate(subtasks, 1):
                if time.time() - start_time > max_runtime:
                    status = "timeout_runtime"
                    stop_reason = "limit"
                    break
                # After phase 1: if shortlist still empty, skip further executor
                # phases (they would re-do discovery). Critic will explain gaps.
                if i > 1 and not load_shortlist(run_dir):
                    print(
                        f"[agent] Skipping session sub{i}/{len(subtasks)} — "
                        "shortlist empty after phase 1 (no candidates to verify)"
                    )
                    append_conversation(
                        run_dir,
                        {
                            "type": "session_skipped",
                            "session": f"sub{i}",
                            "reason": "empty_shortlist_after_phase1",
                        },
                    )
                    counters["sessions_skipped"] = counters.get("sessions_skipped", 0) + 1
                    continue
                label = f"sub{i}"
                print(f"\n[agent] === Executor session {i}/{len(subtasks)} ===")
                user_content = build_subtask_prompt(
                    task_text,
                    sub,
                    i,
                    len(subtasks),
                    prior_handoff=prior_handoff,
                    shortlist_text=shortlist_as_prompt_text(run_dir),
                )
                result = run_session(
                    client=client,
                    config=config,
                    system_prompt=system_prompt,
                    user_content=user_content,
                    run_dir=run_dir,
                    memory=memory,
                    mem_cfg=mem_cfg,
                    sources=sources,
                    counters=counters,
                    limits=limits,
                    start_time=start_time,
                    max_runtime=max_runtime,
                    verbose=verbose,
                    session_label=label,
                    session_llm_budget=per_sub_budget,
                    active_tools=active_tools,
                    run_kind=run_kind,
                )
                last_messages = result.get("messages") or []
                # Handoff: compact notes from this session for the next phase
                prior_handoff = compact_session_handoff(
                    load_notes(run_dir, limit=80), label, max_chars=2500
                )
                if result["status"] == "cancelled":
                    status = "cancelled"
                    stop_reason = "cancelled"
                    break
                if result["status"] == "llm_error":
                    print(f"[agent] Session {label} hit llm_error; continuing if possible")
                    stop_reason = "llm_error"
                    continue
                if result["status"] in (
                    "timeout_runtime",
                    "timeout_llm",
                    "timeout_tools",
                ):
                    status = result["status"]
                    stop_reason = "limit"
                    break
                # session_budget → continue to next phase (intentional)

            # Critic / synthesis — always from notes (flush-safe)
            print("\n[agent] === Critic: synthesize from notes ===")
            if run_kind == "recon":
                # No research ranking — write mechanism summary only
                learnings = memory.summarize_host_learnings()
                final_report = (
                    "RECON_COMPLETE\n\n"
                    "# Host mechanism learning (not a research delivery)\n\n"
                    "This run was `--run-kind recon`. No shortlist candidates. "
                    "Transport knowledge is stored in global memory for later research runs.\n\n"
                    + (learnings.get("text") or "(no host learnings yet)\n")
                )
                status = "completed" if stop_reason is None else f"{stop_reason}+recon_report"
                print("[agent] Recon report from host_learnings (shortlist skipped)")
            else:
                forced = try_forced_report(client, run_dir, task_text, system_prompt)
                rankable_n = len(filter_rankable_shortlist(load_shortlist(run_dir)))
                if forced:
                    final_report = forced
                    # Failure taxonomy: backend crash ≠ research failure when we have deliverable
                    if stop_reason is None:
                        status = "RESEARCH_COMPLETE" if rankable_n else "completed"
                    elif stop_reason == "llm_error":
                        status = (
                            "PARTIAL_SUCCESS"
                            if rankable_n > 0
                            else "RUN_FAILED_LLM+forced_report"
                        )
                    elif stop_reason == "limit":
                        status = (
                            "PARTIAL_SUCCESS"
                            if rankable_n > 0
                            else f"{stop_reason}+forced_report"
                        )
                    else:
                        status = f"{stop_reason}+forced_report"
                else:
                    if stop_reason == "llm_error":
                        status = "RUN_FAILED_LLM"
                    else:
                        status = status if status != "running" else "error"
                    if stop_reason is None:
                        stop_reason = "critic_failed"
        else:
            result = run_session(
                client=client,
                config=config,
                system_prompt=system_prompt,
                user_content=task_text,
                run_dir=run_dir,
                memory=memory,
                active_tools=active_tools,
                mem_cfg=mem_cfg,
                sources=sources,
                counters=counters,
                limits=limits,
                start_time=start_time,
                max_runtime=max_runtime,
                verbose=verbose,
                session_label="main",
                run_kind=run_kind,
            )
            last_messages = result.get("messages") or []
            status = result["status"]
            stop_reason = result.get("stop_reason")
            final_report = result.get("final_content") or ""

            if not final_report and stop_reason in ("limit", "llm_error"):
                forced = try_forced_report(client, run_dir, task_text, system_prompt)
                if forced:
                    final_report = forced
                    rankable_n = len(filter_rankable_shortlist(load_shortlist(run_dir)))
                    if stop_reason == "llm_error":
                        status = (
                            "PARTIAL_SUCCESS"
                            if rankable_n > 0
                            else "RUN_FAILED_LLM+forced_report"
                        )
                    elif status != "completed":
                        status = (
                            "PARTIAL_SUCCESS"
                            if rankable_n > 0
                            else f"{status}+forced_report"
                        )

    except KeyboardInterrupt:
        print("\n[agent] Interrupted by user")
        status = "cancelled"
        stop_reason = "cancelled"
    except Exception as e:
        print(f"[agent] Unexpected error: {e}")
        append_conversation(run_dir, {"type": "fatal_error", "error": str(e)})
        status = "error"
        stop_reason = "error"

    elapsed = time.time() - start_time
    notes_text = notes_as_prompt_text(load_notes(run_dir), max_chars=4000)

    if not final_report:
        final_report = build_partial_report(
            last_messages, sources, status, task_text, notes_text=notes_text
        )
        print(f"[agent] Writing partial report (status={status})")

    save_report(run_dir, final_report)
    save_sources(run_dir, sources)
    save_state(
        run_dir,
        {
            "status": status,
            "mode": "planned" if planned else "single",
            "llm_calls": counters["llm_calls"],
            "tool_calls": counters["tool_calls"],
            "sources_count": len(sources),
            "notes_count": counters["notes_count"],
            "progress": "finished",
            "key_findings": "",
        },
    )

    shortlist_n = len(load_shortlist(run_dir))
    tool_calls_n = counters["tool_calls"]
    useful = counters.get("shortlist_adds", 0)

    # Global host learnings (cross-task) — always write so the operator sees the loop
    learnings = memory.summarize_host_learnings()
    learnings_path = run_dir / "host_learnings.md"
    try:
        learnings_path.write_text(learnings.get("text") or "", encoding="utf-8")
    except Exception as e:
        print(f"[agent] Warning: could not write host_learnings.md: {e}")

    # Recon must never leave research candidates
    if run_kind == "recon":
        try:
            sl_path = run_dir / "shortlist.json"
            if sl_path.exists():
                sl_path.write_text("[]\n", encoding="utf-8")
        except Exception:
            pass
        if not final_report.startswith("RECON"):
            learnings = memory.summarize_host_learnings()
            final_report = (
                "RECON_COMPLETE\n\n"
                "# Host mechanism learning (not a research delivery)\n\n"
                + (learnings.get("text") or "")
            )
            save_report(run_dir, final_report)

    metadata = {
        "run_id": run_dir.name,
        "status": status,
        "mode": "planned" if planned else "single",
        "run_kind": run_kind,
        "browser_backend": browser_backend,
        "model": client.model,
        "started_at": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "llm_calls": counters["llm_calls"],
        "tool_calls": tool_calls_n,
        "search_calls": counters["search_calls"],
        "sources_count": len(sources),
        "notes_count": counters["notes_count"],
        "shortlist_count": shortlist_n,
        "rankable_count": len(filter_rankable_shortlist(load_shortlist(run_dir))),
        "shortlist_adds": useful,
        "constraint_mismatches": counters.get("constraint_mismatches", 0),
        "sessions_skipped": counters.get("sessions_skipped", 0),
        "memory_first_rejects": counters.get("memory_first_rejects", 0),
        "host_abandons": counters.get("host_abandons", 0),
        "useful_actions": useful,
        "useful_action_ratio": (
            round(useful / tool_calls_n, 3) if tool_calls_n else 0.0
        ),
        # candidate_precision ≈ rankable / shortlist (1.0 = no junk in shortlist)
        "candidate_precision": (
            round(
                len(filter_rankable_shortlist(load_shortlist(run_dir))) / shortlist_n,
                3,
            )
            if shortlist_n
            else None
        ),
        "host_domains_touched": learnings.get("domains") or [],
        "human_setup_candidates": learnings.get("human_setup_candidates") or [],
        "limits": limits,
    }
    save_metadata(run_dir, metadata)
    append_conversation(run_dir, {"type": "run_end", "status": status, "metadata": metadata})

    print(f"\n[agent] Finished with status: {status}")
    print(f"[agent] Report written to: {run_dir / 'report.md'}")
    print(
        f"[agent] Duration: {elapsed/60:.1f} min | LLM: {counters['llm_calls']} | "
        f"Tools: {tool_calls_n} | Notes: {counters['notes_count']} | "
        f"Shortlist: {shortlist_n} | useful_ratio={metadata['useful_action_ratio']}"
    )
    print(f"[agent] Memory tactics: {memory.tactics_path}")
    print(f"[agent] Memory recipes: {memory.recipes_path}")
    print(f"[agent] Host learnings: {learnings_path}")
    human = learnings.get("human_setup_candidates") or []
    if human:
        print(
            "[agent] HUMAN_SETUP candidates (global): "
            + ", ".join(human)
            + " — see host_learnings.md"
        )

    return 0 if status == "completed" or status.endswith("+forced_report") else 1


if __name__ == "__main__":
    sys.exit(main())
