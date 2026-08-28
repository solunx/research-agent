"""
Evidence acquisition v0 — gap-driven exploration without domain hardcoding.

Contract says what must be proven. Code measures UNKNOWN/FAIL gaps.
LLM (enum-only) may propose the next *allowed* action using only
affordances already observed on the page (literal text / href).
Code executes the enum, enforces max depth, and blocks irreversible actions.

Same loop is intended for web offers, marketplaces, literature folders, xlsx, etc.
Domain meaning stays in the LLM; code stays mechanical.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

ChatFnStr = Callable[[list[dict[str, str]]], str]

# ---------------------------------------------------------------------------
# Allowed action classes (closed enum — never free-form tool use)
# ---------------------------------------------------------------------------

ACTION_CLASSES = (
    "STOP",  # enough evidence, or no safe next step
    "OPEN_URL",  # navigate to an observed href
    "CLICK_TEXT",  # click control whose visible text was observed
    "CLICK_SELECTOR",  # rare: only if affordance also supplied a safe structural hint
    "SCROLL",  # reveal lazy content
    "WAIT",  # let dynamic UI settle
    "OPEN_FILE",  # future: path observed in FS observer (not implemented in browser)
)

# Substrings that must never be clicked / navigated toward (generic, multi-lingual).
# "Prijzen & boeken" / "Prices & book" tabs are informational and must NOT match —
# require action verbs / checkout intent, not the bare word "boeken/book".
_IRREVERSIBLE = re.compile(
    r"("
    r"boek\s*nu|book\s*now|reis\s*boeken|start\s*boeking|start\s*booking|"
    r"complete\s*booking|confirm\s*(payment|booking|order|purchase)|"
    r"bevestig\s*(betaling|boeking|bestelling)|"
    r"betalen|pay\s*now|checkout|place\s*order|bestelling\s*plaatsen|"
    r"koop\s*nu|buy\s*now|add\s*to\s*cart|in\s*winkelwagen|"
    r"proceed\s*to\s*(checkout|payment)|ga\s*naar\s*betalen|"
    r"delete\s*account|verwijder\s*account|unsubscribe|afmelden"
    r")",
    re.I,
)


def is_irreversible_text(text: str) -> bool:
    return bool(_IRREVERSIBLE.search(text or ""))


def gaps_from_eligibility(
    eligibility: dict[str, Any] | None,
    outcomes: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Mechanical gaps: required decisions that are UNKNOWN or FAIL.
    No domain knowledge — uses eligibility.details from code policy.
    """
    gaps: list[dict[str, Any]] = []
    details = (eligibility or {}).get("details") or []
    for d in details:
        res = d.get("result")
        if res in ("UNKNOWN", "FAIL"):
            gaps.append(
                {
                    "decision_id": d.get("decision_id"),
                    "result": res,
                    "observed": d.get("observed"),
                    "allowed": d.get("allowed"),
                }
            )
    # If no details but outcomes present, surface UNKNOWN keys
    if not gaps and outcomes:
        for k, v in outcomes.items():
            if v == "UNKNOWN":
                gaps.append(
                    {
                        "decision_id": k,
                        "result": "UNKNOWN",
                        "observed": v,
                        "allowed": None,
                    }
                )
    return gaps


def gaps_from_frozen_contract(
    frozen_contract: dict[str, Any] | None,
    outcomes: dict[str, str] | None = None,
    *,
    proven_labels: list[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Preferred production path: gaps from frozen contract sufficiency only.
    Delegates to sufficiency.gaps_for_acquisition (no domain knowledge).
    """
    from sufficiency import gaps_for_acquisition

    return gaps_for_acquisition(
        frozen_contract,
        outcomes,
        proven_labels=proven_labels,
    )


def sufficiency_stop(
    frozen_contract: dict[str, Any] | None,
    outcomes: dict[str, str] | None = None,
    *,
    proven_labels: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """
    Code STOP decision from frozen contract.
    LLM must not call this — callers in the acquisition loop do.
    """
    from sufficiency import evaluate_sufficiency

    return evaluate_sufficiency(
        frozen_contract,
        outcomes,
        proven_labels=proven_labels,
        require_frozen_flag=True,
    )



def filter_safe_affordances(
    affordances: list[dict[str, Any]],
    *,
    max_keep: int = 36,
) -> list[dict[str, Any]]:
    """
    Drop irreversible controls; prefer local/tab/button over global nav.
    Preserves scope tag for planner + audit.
    """
    safe: list[dict[str, Any]] = []
    for a in affordances or []:
        text = str(a.get("text") or "")
        href = str(a.get("href") or "")
        if is_irreversible_text(text) or is_irreversible_text(href):
            continue
        scope = str(a.get("scope") or "unknown")
        if scope not in ("local", "global", "unknown"):
            scope = "unknown"
        safe.append(
            {
                "kind": a.get("kind"),
                "text": text[:120],
                "href": href[:300],
                "role": a.get("role") or "",
                "scope": scope,
            }
        )

    def _rank(item: dict[str, Any]) -> tuple[int, int]:
        kind = str(item.get("kind") or "")
        scope = str(item.get("scope") or "unknown")
        # lower = better
        kind_rank = 0 if kind == "tab" else (1 if kind == "button" else 2)
        scope_rank = 0 if scope == "local" else (1 if scope == "unknown" else 2)
        return (scope_rank, kind_rank)

    safe.sort(key=_rank)
    return safe[:max_keep]


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None


def action_fingerprint(
    decision: dict[str, Any], *, page_url: str = ""
) -> str:
    """Stable key for anti-repeat: action + target (+ host path, not full query)."""
    action = str(decision.get("action_class") or "").strip().upper()
    target = (
        str(decision.get("target_text") or "").strip().lower()
        or str(decision.get("target_href") or "").strip().lower()
        or str(decision.get("target_path") or "").strip().lower()
        or ""
    )
    path = ""
    try:
        from urllib.parse import urlparse

        path = (urlparse(page_url or "").path or "").rstrip("/").lower()
    except Exception:
        path = ""
    return f"{action}|{target}|{path}"


def state_signature(
    *,
    url: str,
    text: str,
    affordances: list[dict[str, Any]] | None = None,
) -> str:
    """
    Cheap page-state fingerprint. Used only to detect no-progress after an action.
    Not semantic — URL + length + short text head + affordance labels.
    """
    import hashlib

    try:
        from urllib.parse import urlparse

        u = urlparse(url or "")
        url_key = f"{u.netloc}{u.path}".lower()
    except Exception:
        url_key = (url or "")[:200].lower()
    aff_labels = sorted(
        {
            str(a.get("text") or "").strip().lower()[:80]
            for a in (affordances or [])
            if a.get("text")
        }
    )[:40]
    head = re.sub(r"\s+", " ", (text or "")[:1200]).strip().lower()
    raw = f"{url_key}|chars={len(text or '')}|{head}|aff={','.join(aff_labels)}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def acquisition_decide(
    *,
    gaps: list[dict[str, Any]],
    affordances: list[dict[str, Any]],
    page_url: str,
    page_title: str,
    claim_preview: list[str],
    task_text: str,
    chat_fn: ChatFnStr | None,
    step_index: int,
    max_steps: int,
    blocked_action_keys: list[str] | None = None,
) -> dict[str, Any]:
    """
    Propose next action. Fail-closed to STOP when no LLM or invalid output.

    Output schema (enforced by code):
      action_class: one of ACTION_CLASSES
      target_text: optional visible label from affordances
      target_href: optional href from affordances
      for_decision_ids: which gaps this might resolve
      reason: short string

    blocked_action_keys: fingerprints of actions that produced no state change
    (or already failed). Code rejects repeats generically — no site rules.
    """
    safe = filter_safe_affordances(affordances)
    blocked = set(blocked_action_keys or [])
    if not gaps:
        return {
            "action_class": "STOP",
            "target_text": None,
            "target_href": None,
            "for_decision_ids": [],
            "reason": "no_gaps",
            "source": "code",
        }
    if step_index >= max_steps:
        return {
            "action_class": "STOP",
            "target_text": None,
            "target_href": None,
            "for_decision_ids": [g.get("decision_id") for g in gaps],
            "reason": "max_steps_reached",
            "source": "code",
        }
    if chat_fn is None:
        return {
            "action_class": "STOP",
            "target_text": None,
            "target_href": None,
            "for_decision_ids": [g.get("decision_id") for g in gaps],
            "reason": "no_llm_fail_closed",
            "source": "code",
            "affordances_seen": len(safe),
        }

    system = (
        "You are an evidence-acquisition planner for a research agent.\n"
        "The code already measured which contract outcomes are still UNKNOWN or FAIL.\n"
        "You must choose the next browser/file action that is most likely to surface "
        "missing evidence — using ONLY the listed affordances (visible controls/links).\n"
        "Do NOT invent selectors or URLs that are not listed.\n"
        "Do NOT choose irreversible actions (book, pay, checkout, buy).\n"
        "Prefer affordances with scope=local (same entity / same page surface) over "
        "scope=global (site-wide marketing, FAQ, login, destinations). "
        "Global pages rarely prove facts about the specific candidate under study.\n"
        "Prefer kind=tab or kind=button that stay on the current entity over distant links.\n"
        "Do NOT repeat an action listed under no_progress_actions — those already "
        "produced no useful page-state change.\n"
        "If no listed affordance is likely to help, choose STOP.\n"
        "Respond with exactly one JSON object, no markdown."
    )
    user = {
        "task_excerpt": (task_text or "")[:600],
        "page_url": page_url[:400],
        "page_title": (page_title or "")[:160],
        "gaps": gaps,
        "claim_preview": (claim_preview or [])[:20],
        "affordances": safe[:28],
        "no_progress_actions": list(blocked)[:20],
        "preference": "prefer scope=local tabs/buttons that open deeper offer/price/detail state for the current entity",
        "step_index": step_index,
        "max_steps": max_steps,
        "allowed_action_class": list(ACTION_CLASSES),
        "output_schema": {
            "action_class": "STOP|OPEN_URL|CLICK_TEXT|CLICK_SELECTOR|SCROLL|WAIT|OPEN_FILE",
            "target_text": "string|null — must match an affordance text if click",
            "target_href": "string|null — must match an affordance href if open_url",
            "for_decision_ids": ["decision ids this action aims to resolve"],
            "reason": "short",
        },
    }
    raw = chat_fn(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ]
    )
    obj = _parse_json_object(raw) or {}
    action = str(obj.get("action_class") or "STOP").strip().upper()
    if action not in ACTION_CLASSES:
        action = "STOP"
    target_text = obj.get("target_text")
    target_href = obj.get("target_href")
    if target_text is not None:
        target_text = str(target_text).strip()[:120] or None
    if target_href is not None:
        target_href = str(target_href).strip()[:300] or None

    # Enforce: targets must come from observed affordances (or STOP/SCROLL/WAIT)
    if action == "CLICK_TEXT":
        texts = {str(a.get("text") or "").strip().lower() for a in safe}
        if not target_text or target_text.strip().lower() not in texts:
            # soft match: substring
            matched = None
            if target_text:
                for a in safe:
                    t = str(a.get("text") or "")
                    if target_text.lower() in t.lower() or t.lower() in target_text.lower():
                        matched = t
                        break
            if matched:
                target_text = matched
            else:
                return {
                    "action_class": "STOP",
                    "target_text": None,
                    "target_href": None,
                    "for_decision_ids": [g.get("decision_id") for g in gaps],
                    "reason": "click_target_not_in_affordances",
                    "source": "code_reject",
                    "llm_raw": obj,
                }
        if is_irreversible_text(target_text or ""):
            return {
                "action_class": "STOP",
                "reason": "irreversible_blocked",
                "source": "code_reject",
                "for_decision_ids": [g.get("decision_id") for g in gaps],
            }
    if action == "OPEN_URL":
        hrefs = {str(a.get("href") or "").strip() for a in safe if a.get("href")}
        if not target_href or target_href not in hrefs:
            # allow if target_href is substring of an affordance href
            matched_h = None
            if target_href:
                for h in hrefs:
                    if target_href in h or h in target_href:
                        matched_h = h
                        break
            if matched_h:
                target_href = matched_h
            else:
                return {
                    "action_class": "STOP",
                    "reason": "href_not_in_affordances",
                    "source": "code_reject",
                    "for_decision_ids": [g.get("decision_id") for g in gaps],
                    "llm_raw": obj,
                }
        if is_irreversible_text(target_href or ""):
            return {
                "action_class": "STOP",
                "reason": "irreversible_url_blocked",
                "source": "code_reject",
                "for_decision_ids": [g.get("decision_id") for g in gaps],
            }
    if action == "OPEN_FILE":
        path = str(obj.get("target_path") or target_text or "").strip()
        if not path:
            return {
                "action_class": "STOP",
                "reason": "open_file_missing_path",
                "source": "code_reject",
                "for_decision_ids": [g.get("decision_id") for g in gaps],
            }
        candidate = {
            "action_class": "OPEN_FILE",
            "target_path": path,
            "target_text": target_text,
            "for_decision_ids": [g.get("decision_id") for g in gaps],
            "reason": str(obj.get("reason") or "")[:300],
            "source": "llm",
            "affordances_offered": len(safe),
        }
        fp = action_fingerprint(candidate, page_url=page_url)
        if fp in blocked:
            return {
                "action_class": "STOP",
                "reason": "no_progress_repeat_blocked",
                "source": "code_reject",
                "for_decision_ids": [g.get("decision_id") for g in gaps],
                "blocked_key": fp,
            }
        return candidate

    for_ids = obj.get("for_decision_ids") or [g.get("decision_id") for g in gaps]
    if not isinstance(for_ids, list):
        for_ids = [g.get("decision_id") for g in gaps]

    candidate = {
        "action_class": action,
        "target_text": target_text,
        "target_href": target_href,
        "for_decision_ids": for_ids,
        "reason": str(obj.get("reason") or "")[:300],
        "source": "llm",
        "affordances_offered": len(safe),
    }
    # Generic anti-repeat: never re-issue an action that already yielded no progress
    if action not in ("STOP", "WAIT"):
        fp = action_fingerprint(candidate, page_url=page_url)
        if fp in blocked:
            return {
                "action_class": "STOP",
                "target_text": None,
                "target_href": None,
                "for_decision_ids": for_ids,
                "reason": "no_progress_repeat_blocked",
                "source": "code_reject",
                "blocked_key": fp,
                "llm_raw": obj,
            }
        candidate["action_key"] = fp
    return candidate


def execute_acquisition_action(decision: dict[str, Any], *, max_chars: int = 20000) -> dict[str, Any]:
    """
    Execute an acquisition decision via browser tools.
    Returns page snapshot-like dict with ok flag.
    """
    from browser import (
        browser_click,
        browser_extract_text,
        browser_open,
        browser_scroll,
        browser_wait,
    )

    action = decision.get("action_class") or "STOP"
    if action == "STOP":
        return {"ok": True, "noop": True, "action_class": "STOP"}
    if action == "OPEN_FILE":
        from fs_observer import inspect_path, list_paths

        path = str(decision.get("target_path") or decision.get("target_text") or "").strip()
        if not path or path in (".", "inputs", "inputs/"):
            listing = list_paths(roots=["inputs", "."], patterns=["*.xlsx", "*.csv", "*.tsv", "*"])
            return {
                "ok": True,
                "action_class": "OPEN_FILE",
                "list": listing,
                "text": f"fs_list count={listing.get('count')} roots={listing.get('roots_tried')}",
            }
        meta = inspect_path(path)
        return {
            "ok": bool(meta.get("ok")),
            "action_class": "OPEN_FILE",
            "inspect": meta,
            "text": str(meta.get("content_summary") or meta),
        }
    if action == "WAIT":
        return browser_wait(2.0)
    if action == "SCROLL":
        return browser_scroll("down", 900)
    if action == "OPEN_URL":
        href = decision.get("target_href") or ""
        if not href:
            return {"ok": False, "error": "missing_href"}
        snap = browser_open(href, wait_seconds=3.0, max_chars=max_chars)
        snap["ok"] = not bool(snap.get("error")) and len(str(snap.get("text") or "")) > 40
        return snap
    if action == "CLICK_TEXT":
        text = decision.get("target_text") or ""
        if not text:
            return {"ok": False, "error": "missing_target_text"}
        # Playwright text selector — target is literal from page
        # Escape single quotes for has-text
        safe = text.replace("\\", "\\\\").replace("'", "\\'")
        selector = f"text={text}"
        # Prefer role-agnostic text engine
        snap = browser_click(selector, max_chars=max_chars)
        if not snap.get("ok"):
            # fallback has-text on button/link
            snap2 = browser_click(f"button:has-text('{safe}')", max_chars=max_chars)
            if snap2.get("ok"):
                return snap2
            snap3 = browser_click(f"a:has-text('{safe}')", max_chars=max_chars)
            if snap3.get("ok"):
                return snap3
        return snap
    if action == "CLICK_SELECTOR":
        # Intentionally conservative: only allow simple text= selectors from decision
        sel = str(decision.get("target_text") or decision.get("selector") or "")
        if not sel.startswith("text=") and not sel.startswith("button:") and not sel.startswith("a:"):
            return {"ok": False, "error": "selector_not_allowed"}
        return browser_click(sel, max_chars=max_chars)

    return {"ok": False, "error": f"unknown_action:{action}"}
