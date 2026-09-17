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
    "FILL_AND_SUBMIT",  # fill observed input_field with LLM-chosen query text + Enter
    "SCROLL",  # reveal lazy content
    "WAIT",  # let dynamic UI settle
    "OPEN_FILE",  # future: path observed in FS observer (not implemented in browser)
)

# Substrings that must never be clicked / navigated toward (generic, multi-lingual).
# "Prijzen & boeken" / "Prices & book" tabs are informational and must NOT match —
# require action verbs / checkout intent, not the bare word "boeken/book".
# Safety only (FRAMEWORK_BOUNDARY OK-fw-exc BROADEN): NL/EN + DE/FR/ES/IT.
_IRREVERSIBLE = re.compile(
    r"("
    # NL / EN
    r"boek\s*nu|book\s*now|reis\s*boeken|start\s*boeking|start\s*booking|"
    r"complete\s*booking|confirm\s*(payment|booking|order|purchase)|"
    r"bevestig\s*(betaling|boeking|bestelling)|"
    r"betalen|pay\s*now|checkout|place\s*order|bestelling\s*plaatsen|"
    r"koop\s*nu|buy\s*now|add\s*to\s*cart|in\s*winkelwagen|"
    r"proceed\s*to\s*(checkout|payment)|ga\s*naar\s*betalen|"
    r"delete\s*account|verwijder\s*account|unsubscribe|afmelden|"
    # DE
    r"jetzt\s*buchen|zahlungspflichtig\s*bestellen|zur\s*kasse|"
    r"bestellung\s*abschicken|jetzt\s*bezahlen|\bkaufen\b|"
    # FR
    r"r[eé]server\s*maintenant|payer\s*maintenant|passer\s*commande|"
    r"valider\s*le\s*paiement|acheter\s*maintenant|"
    # ES
    r"reservar\s*ahora|pagar\s*ahora|finalizar\s*compra|realizar\s*pedido|"
    r"comprar\s*ahora|"
    # IT
    r"prenota\s*ora|acquista\s*ora|procedi\s*al\s*pagamento|completa\s*ordine"
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
    preferred_item_links: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Drop irreversible controls; prefer local/tab/button over global nav.
    When preferred_item_links is provided (from candidate-unit packaging),
    boost matching local links so the planner sees concrete item targets first.

    Structural only — no domain vocabulary.
    """
    pref_texts = {
        str(p.get("text") or "").strip().lower()
        for p in (preferred_item_links or [])
        if p.get("text")
    }
    pref_hrefs = {
        str(p.get("href") or "").strip().lower()
        for p in (preferred_item_links or [])
        if p.get("href")
    }

    safe: list[dict[str, Any]] = []
    for a in affordances or []:
        text = str(a.get("text") or "")
        href = str(a.get("href") or "")
        if is_irreversible_text(text) or is_irreversible_text(href):
            continue
        scope = str(a.get("scope") or "unknown")
        if scope not in ("local", "global", "unknown"):
            scope = "unknown"
        is_pref = False
        tl = text.strip().lower()
        hl = href.strip().lower()
        if tl and tl in pref_texts:
            is_pref = True
        if hl and hl in pref_hrefs:
            is_pref = True
        if not is_pref and tl and pref_texts:
            # soft substring match on preferred labels
            is_pref = any(tl in p or p in tl for p in pref_texts if len(p) >= 4)
        item = {
            "kind": a.get("kind"),
            "text": text[:120],
            "href": href[:300],
            "role": a.get("role") or "",
            "scope": scope,
            "preferred_item": is_pref,
        }
        # Pass through structural metadata for input_field (locator building)
        if str(a.get("kind") or "") == "input_field":
            for k in ("tag", "type", "name", "id", "placeholder", "aria_label"):
                if a.get(k):
                    item[k] = str(a.get(k))[:120]
        safe.append(item)

    def _rank(item: dict[str, Any]) -> tuple[int, int, int]:
        kind = str(item.get("kind") or "")
        scope = str(item.get("scope") or "unknown")
        # lower = better
        pref_rank = 0 if item.get("preferred_item") else 1
        # tabs > buttons > input_fields > rest
        if kind == "tab":
            kind_rank = 0
        elif kind == "button":
            kind_rank = 1
        elif kind == "input_field":
            kind_rank = 2
        else:
            kind_rank = 3
        scope_rank = 0 if scope == "local" else (1 if scope == "unknown" else 2)
        return (pref_rank, scope_rank, kind_rank)

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
    """Stable key for anti-repeat: action + target (+ query_text for FILL) (+ path).

    For FILL_AND_SUBMIT the fingerprint includes query_text so the same
    (affordance-target, query) pair is blocked after one no-progress attempt,
    while a different query on the same field remains allowed.
    """
    action = str(decision.get("action_class") or "").strip().upper()
    target = (
        str(decision.get("target_text") or "").strip().lower()
        or str(decision.get("target_href") or "").strip().lower()
        or str(decision.get("target_path") or "").strip().lower()
        or ""
    )
    # Structural id/name from input_field affordance (more stable than display text)
    if action == "FILL_AND_SUBMIT":
        extra = (
            str(decision.get("target_id") or "").strip().lower()
            or str(decision.get("target_name") or "").strip().lower()
            or ""
        )
        if extra:
            target = f"{target}|{extra}" if target else extra
        q = str(decision.get("query_text") or "").strip().lower()[:120]
        target = f"{target}|q={q}" if target else f"q={q}"
    path = ""
    try:
        from urllib.parse import urlparse

        path = (urlparse(page_url or "").path or "").rstrip("/").lower()
    except Exception:
        path = ""
    return f"{action}|{target}|{path}"


# Object-rejection labels (not mere absence). Absence stays UNKNOWN / NOT_STATED /
# NOT_VISIBLE and must not trigger "leave this object and re-search".
# These strings appear as *contract* outcomes (subject_instance on task 05/06);
# code only notices a FAIL that is a concrete rejection, not a domain taxonomy.
_PAGE_OBJECT_REJECTED = frozenset({"NOT_RELEVANT", "REJECTED"})


def object_rejected_on_current_page(
    current_page_outcomes: dict[str, str] | None,
    gaps: list[dict[str, Any]] | None,
) -> dict[str, str] | None:
    """
    Return {decision_id, observed} when a required-gap decision's *current-page*
    outcome is an object-rejection label. Else None.

    Uses current-page outcomes, not merged best_outcomes: a homepage
    NOT_RELEVANT must not keep firing after a later page confirms the subject.
    """
    fail_ids = {
        str(g.get("decision_id") or "")
        for g in (gaps or [])
        if g.get("result") == "FAIL" and g.get("decision_id")
    }
    for did, observed in (current_page_outcomes or {}).items():
        obs = str(observed or "")
        if obs in _PAGE_OBJECT_REJECTED and str(did) in fail_ids:
            return {"decision_id": str(did), "observed": obs}
    return None


def should_hint_refine_search(
    *,
    current_page_outcomes: dict[str, str] | None,
    gaps: list[dict[str, Any]] | None,
    surfaces_seen: list[str] | None,
) -> dict[str, Any] | None:
    """
    True-shaped hint when this page rejected the object AND this run already
    visited a list_results surface (search/results). No query text is invented.
    """
    rejected = object_rejected_on_current_page(current_page_outcomes, gaps)
    if not rejected:
        return None
    if "list_results" not in {str(s or "") for s in (surfaces_seen or [])}:
        return None
    return rejected


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
    preferred_item_links: list[dict[str, str]] | None = None,
    candidate_unit_preview: list[str] | None = None,
    current_page_outcomes: dict[str, str] | None = None,
    surfaces_seen: list[str] | None = None,
) -> dict[str, Any]:
    """
    Propose next action. Fail-closed to STOP when no LLM or invalid output.

    Output schema (enforced by code):
      action_class: one of ACTION_CLASSES
      target_text: optional visible label from affordances
      target_href: optional href from affordances
      query_text: FREE string for FILL_AND_SUBMIT only — LLM formulates it;
                 code never auto-copies from gaps/contract
      for_decision_ids: which gaps this might resolve
      reason: short string

    blocked_action_keys: fingerprints of actions that produced no state change
    (or already failed). Code rejects repeats generically — no site rules.
    For FILL_AND_SUBMIT the fingerprint includes (target, query_text) so the
    same query on the same field is blocked once, but a refined query is allowed.

    preferred_item_links / candidate_unit_preview: optional structural hints from
    candidate-unit packaging (co-occurring text clusters + their item links).
    When gaps remain, prefer opening a concrete unit link over re-running search
    — unless the *current page* rejected the object (see refine_search hint).

    current_page_outcomes / surfaces_seen: optional. When a required decision
    on *this* page is NOT_RELEVANT/REJECTED and this run already saw
    list_results, the planner is told it may FILL_AND_SUBMIT again with a
    *new* query_text (LLM-formulated; code never writes the query). Same
    query_text on the same field stays blocked via blocked_action_keys.
    """
    safe = filter_safe_affordances(
        affordances, preferred_item_links=preferred_item_links
    )
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

    rejected = should_hint_refine_search(
        current_page_outcomes=current_page_outcomes,
        gaps=gaps,
        surfaces_seen=surfaces_seen,
    )
    has_input = any(str(a.get("kind") or "") == "input_field" for a in safe)
    refine_search = rejected is not None

    stay_on_entity = (
        "Prefer affordances with scope=local (same entity / same page surface) over "
        "scope=global (site-wide marketing, FAQ, login, destinations). "
        "Global pages rarely prove facts about the specific candidate under study.\n"
        "When candidate_units list concrete item clusters with links, and gaps remain, "
        "prefer opening one of those item links (preferred_item=true) over repeating "
        "search/filter controls. Exploring a concrete unit yields bound evidence.\n"
        "Prefer kind=tab or kind=button that stay on the current entity over distant links "
        "when no preferred item link is available.\n"
    )
    leave_rejected_object = (
        "The current page's object-identity decision is a concrete rejection "
        "(NOT_RELEVANT or REJECTED) — this is not mere absence of a field. "
        "Do NOT keep clicking related/local controls on this same rejected object "
        "(related items, alternate views of the same record, back-to-abstract on "
        "the same URL). Those will not turn a rejected instance into a matching one.\n"
        "This run already visited a list_results surface. You MAY search again: "
        "if kind=input_field is listed, choose FILL_AND_SUBMIT with a NEW query_text "
        "that YOU formulate (free text; code does not write the query). The new "
        "query_text must differ from any FILL already listed under no_progress_actions "
        "(identical query on the same field is blocked). "
        "If no input_field is listed, first use a listed affordance that reaches a "
        "search/list surface (do not invent URLs), then fill on a later step.\n"
    )
    fill_rule = (
        "When gaps suggest missing search results and an affordance with kind=input_field "
        "is listed, you may choose FILL_AND_SUBMIT: set target_text to the input_field's "
        "text/placeholder (must match a listed affordance), and set query_text to a short "
        "search string that YOU formulate from the task/gaps (free text — code does not "
        "fill this for you). Code will type query_text into that field and press Enter.\n"
    )
    system = (
        "You are an evidence-acquisition planner for a research agent.\n"
        "The code already measured which contract outcomes are still UNKNOWN or FAIL.\n"
        "You must choose the next browser/file action that is most likely to surface "
        "missing evidence — using ONLY the listed affordances (visible controls/links).\n"
        "Do NOT invent selectors or URLs that are not listed.\n"
        "Do NOT choose irreversible actions (book, pay, checkout, buy).\n"
        + (leave_rejected_object if refine_search else stay_on_entity)
        + fill_rule
        + "Do NOT repeat an action listed under no_progress_actions — those already "
        "produced no useful page-state change.\n"
        "If no listed affordance is likely to help, choose STOP.\n"
        "Respond with exactly one JSON object, no markdown."
    )
    if refine_search:
        pref_note = (
            "current page rejected the object; do not deepen this same record; "
            "if kind=input_field is present, FILL_AND_SUBMIT with a new query_text "
            "you formulate (must not match a blocked identical query); "
            "else use a listed affordance to reach a search surface — no invented URLs"
        )
    else:
        pref_note = (
            "prefer preferred_item=true local links that open a concrete candidate unit; "
            "else prefer local tabs/buttons that deepen the current surface; "
            "when search is needed and kind=input_field is present, prefer FILL_AND_SUBMIT "
            "with a query_text you formulate from task/gaps"
        )
    user = {
        "task_excerpt": (task_text or "")[:600],
        "page_url": page_url[:400],
        "page_title": (page_title or "")[:160],
        "gaps": gaps,
        "claim_preview": (claim_preview or [])[:20],
        "candidate_units": (candidate_unit_preview or [])[:8],
        "preferred_item_links": (preferred_item_links or [])[:8],
        "affordances": safe[:28],
        "no_progress_actions": list(blocked)[:20],
        "preference": pref_note,
        "current_page_outcomes": current_page_outcomes or {},
        "surfaces_seen": list(surfaces_seen or [])[:20],
        "page_object_rejected": rejected,
        "refine_search_after_reject": refine_search,
        "input_field_listed": has_input,
        "step_index": step_index,
        "max_steps": max_steps,
        "allowed_action_class": list(ACTION_CLASSES),
        "output_schema": {
            "action_class": "STOP|OPEN_URL|CLICK_TEXT|CLICK_SELECTOR|FILL_AND_SUBMIT|SCROLL|WAIT|OPEN_FILE",
            "target_text": "string|null — must match an affordance text if click/fill",
            "target_href": "string|null — must match an affordance href if open_url",
            "query_text": "string|null — FREE text for FILL_AND_SUBMIT only; LLM formulates the search query from task/gaps (code does not auto-fill this)",
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

    # FILL_AND_SUBMIT: target must match an input_field affordance; query_text is
    # free text formulated by the LLM (never auto-copied from gaps by code).
    query_text = None
    target_id = None
    target_name = None
    target_type = None
    if action == "FILL_AND_SUBMIT":
        input_affs = [a for a in safe if str(a.get("kind") or "") == "input_field"]
        if not input_affs:
            return {
                "action_class": "STOP",
                "reason": "fill_no_input_field_affordance",
                "source": "code_reject",
                "for_decision_ids": [g.get("decision_id") for g in gaps],
                "llm_raw": obj,
            }
        # Match target_text against input_field text / placeholder / aria_label / name / id
        matched_aff = None
        if target_text:
            tt = target_text.strip().lower()
            for a in input_affs:
                candidates = [
                    str(a.get("text") or ""),
                    str(a.get("placeholder") or ""),
                    str(a.get("aria_label") or ""),
                    str(a.get("name") or ""),
                    str(a.get("id") or ""),
                ]
                for c in candidates:
                    if not c:
                        continue
                    cl = c.strip().lower()
                    if tt == cl or tt in cl or cl in tt:
                        matched_aff = a
                        break
                if matched_aff:
                    break
        if matched_aff is None and len(input_affs) == 1:
            # Single visible input_field: accept even if target_text is approximate
            matched_aff = input_affs[0]
        if matched_aff is None:
            return {
                "action_class": "STOP",
                "reason": "fill_target_not_in_input_fields",
                "source": "code_reject",
                "for_decision_ids": [g.get("decision_id") for g in gaps],
                "llm_raw": obj,
            }
        # Canonicalise target_text to the affordance display text
        target_text = str(matched_aff.get("text") or target_text or "")[:120] or None
        target_id = str(matched_aff.get("id") or "")[:80] or None
        target_name = str(matched_aff.get("name") or "")[:80] or None
        target_type = str(matched_aff.get("type") or matched_aff.get("tag") or "")[:30] or None
        # query_text: free field from LLM — code does NOT invent or copy from gaps
        query_text = obj.get("query_text")
        if query_text is not None:
            query_text = str(query_text).strip()[:200] or None
        if not query_text:
            return {
                "action_class": "STOP",
                "reason": "fill_missing_query_text",
                "source": "code_reject",
                "for_decision_ids": [g.get("decision_id") for g in gaps],
                "llm_raw": obj,
            }

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
    if action == "FILL_AND_SUBMIT":
        candidate["query_text"] = query_text
        if target_id:
            candidate["target_id"] = target_id
        if target_name:
            candidate["target_name"] = target_name
        if target_type:
            candidate["target_type"] = target_type
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


def _fill_locator_from_decision(decision: dict[str, Any]) -> str | None:
    """
    Build a safe Playwright locator for FILL_AND_SUBMIT from structural
    affordance metadata only (id / name / placeholder / type). No free CSS
    from the LLM.
    """
    tid = str(decision.get("target_id") or "").strip()
    tname = str(decision.get("target_name") or "").strip()
    ttype = str(decision.get("target_type") or "").strip().lower()
    ttext = str(decision.get("target_text") or "").strip()

    if tid:
        # Prefer exact id
        return f"#{tid}" if re.match(r"^[A-Za-z_][\w\-:.]*$", tid) else f'[id="{tid}"]'
    if tname:
        esc = tname.replace("\\", "\\\\").replace('"', '\\"')
        if ttype == "textarea":
            return f'textarea[name="{esc}"]'
        if ttype and ttype not in ("", "text"):
            return f'input[type="{ttype}"][name="{esc}"]'
        return f'input[name="{esc}"], textarea[name="{esc}"]'
    if ttext and ttext not in ("(unnamed input)",):
        esc = ttext.replace("\\", "\\\\").replace('"', '\\"')
        # placeholder or aria-label match
        return (
            f'input[placeholder="{esc}"], textarea[placeholder="{esc}"], '
            f'input[aria-label="{esc}"], textarea[aria-label="{esc}"]'
        )
    # Last resort: first visible text-like input
    if ttype == "textarea":
        return "textarea"
    if ttype and ttype not in ("", "text"):
        return f'input[type="{ttype}"]'
    return 'input[type="search"], input[type="text"], input:not([type]), textarea'


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
        browser_type,
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
        # Relative hrefs (path-only) must be resolved against the live page URL
        # before Page.goto — see browser._resolve_navigation_url.
        from browser import _resolve_navigation_url  # local import avoids cycles at module load

        resolved = _resolve_navigation_url(str(href))
        snap = browser_open(resolved, wait_seconds=3.0, max_chars=max_chars)
        snap["requested_href"] = str(href)[:400]
        snap["resolved_url"] = resolved[:400]
        if snap.get("download"):
            # Download is a handled outcome: keep the current document.
            snap["ok"] = len(str(snap.get("text") or "")) > 40
            snap["error"] = None
            snap["action_class"] = "OPEN_URL"
            return snap
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
    if action == "FILL_AND_SUBMIT":
        query = str(decision.get("query_text") or "").strip()
        if not query:
            return {"ok": False, "error": "missing_query_text", "action_class": "FILL_AND_SUBMIT"}
        selector = _fill_locator_from_decision(decision)
        if not selector:
            return {"ok": False, "error": "fill_no_locator", "action_class": "FILL_AND_SUBMIT"}
        snap = browser_type(selector, query, press_enter=True, max_chars=max_chars)
        snap["action_class"] = "FILL_AND_SUBMIT"
        snap["filled_selector"] = selector[:200]
        snap["query_text"] = query[:200]
        if not snap.get("ok"):
            # Soft fallback: try a broader text-like input if specific locator failed
            fallback = 'input[type="search"], input[type="text"], input:not([type]), textarea'
            if selector != fallback:
                snap2 = browser_type(fallback, query, press_enter=True, max_chars=max_chars)
                snap2["action_class"] = "FILL_AND_SUBMIT"
                snap2["filled_selector"] = fallback
                snap2["query_text"] = query[:200]
                snap2["fallback_from"] = selector[:200]
                return snap2
        return snap

    return {"ok": False, "error": f"unknown_action:{action}"}
