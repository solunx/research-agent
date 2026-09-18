"""
Live offer-state / evidence-acquisition slice v0.

Loop (domain-agnostic):
  OPEN start_url
    → OBSERVE + affordances
    → CANDIDATE → INTERPRET → eligibility (frozen)
    → while gaps and steps < max:
         acquisition_decide (LLM enum OR lab force-list)
         execute_action
         re-observe + re-interpret
    → STOP (never book)

Lab mode may pass force_acquisition_hints (list of CLICK_TEXT targets) for
controlled experiments without baking those strings into core policy.
Production path should leave hints empty and rely on LLM + observed affordances.
"""
from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from candidates import (
    candidates_preview,
    candidates_to_observations,
    extract_candidates,
)
from candidate_units import (
    count_price_like_lines,
    line_is_price_like,
    package_candidate_units,
    unit_claim_preview,
    unit_item_link_targets,
    units_to_observations,
)
from evidence_acquisition import (
    acquisition_decide,
    action_fingerprint,
    execute_acquisition_action,
    gaps_from_eligibility,
    gaps_from_frozen_contract,
    state_signature,
    sufficiency_stop,
)
from live_detail_slice import (
    page_text_to_observations,
    stage_d_from_obs,
)
from pipeline_offline import (
    PACKAGES_DECISIONS,
    PACKAGES_TASK_TEXT,
    eligibility_from_outcomes,
    run_candidate_unit,
    run_interpretation,
)
from sufficiency import evaluate_sufficiency

from run_ledger import RunLedger
from trace_session import TraceSession

ChatFnStr = Callable[[list[dict[str, str]]], str]

# Surface density: glyph ∨ D2c via shared candidate_units helpers (Fase 3).
# Replaces language-specific _PRICE_LINE (vanaf/from/p.p.) — FRAMEWORK_BOUNDARY #10.
# Provisional list-density threshold (Open #10 — NOT locked).
# Recalibrated 2026-09-18: D2c no longer counts bare 4+ digit identifiers or
# 1-decimal scores (Monica 8,1 / arXiv 2609.18128). Measured after that:
#   abs 062211Z = 1, abs 102344Z = 1, synthetic list = 3, arXiv search = 3,
#   Monica remaining 3-digit prices ≈10, Flamenco ≈9.
# T=3 then separates single-record abs from multi-item lists on both families.
# step==0 + same_entity → live_detail short-circuit remains the property-page guard.
_PRICE_LIKE_LIST_THRESHOLD = 3  # provisional; see Open #10 in FRAMEWORK_BOUNDARY.md


def _classify_surface(
    *,
    start_url: str,
    cur_url: str,
    text: str,
    step: int,
) -> tuple[str, bool]:
    """
    Structural surface tag for provenance.

    Returns (surface, same_entity_path).
    - list_results when the page shows multi-item price density
    - site_marketing only when path left the start entity AND no list density
    - never site-specific host/path string matching
    """
    try:
        start_parts = urlparse(start_url)
        cur_parts = urlparse(cur_url)
        start_path = start_parts.path.rstrip("/")
        cur_path = cur_parts.path.rstrip("/")
        start_host = (start_parts.netloc or "").lower()
        cur_host = (cur_parts.netloc or "").lower()
        if start_path:
            same_entity = bool(
                cur_path
                and (
                    cur_path == start_path
                    or cur_path.startswith(start_path + "/")
                    or start_path.startswith(cur_path + "/")
                )
            )
        else:
            # Site-root start: path nesting is undefined. Same host is still
            # on-site (abs/search); leaving host is marketing. No site-name
            # strings — netloc equality only.
            same_entity = bool(start_host and start_host == cur_host)
    except Exception:
        same_entity = step == 0

    # glyph ∨ D2c line count (shared helper — no third density implementation)
    price_hits = count_price_like_lines(text or "")
    # Open #10: provisional threshold, not validated across diverse page types — not locked
    dense_list = price_hits >= _PRICE_LIKE_LIST_THRESHOLD

    if step == 0 and same_entity:
        return "live_detail", True
    if dense_list:
        return "list_results", same_entity
    if same_entity:
        return "live_offer_state", True
    if step == 0:
        # Root / search home: treat as list if dense, else live_detail seed
        return ("list_results" if dense_list else "live_detail"), same_entity
    # Left start path, no dense offer evidence → marketing/chrome surface
    return "site_marketing", False


def _pipeline_on_obs(
    *,
    entity: str,
    obs: list[dict[str, Any]],
    chat_fn: ChatFnStr | None,
    task_text: str,
    decisions: list[dict[str, Any]],
    interpret_even_if_not_admitted: bool = True,
    batch_decisions: bool = False,
) -> dict[str, Any]:
    """
    CANDIDATE_UNIT ranks whether the fragment is a primary unit.
    INTERPRET maps evidence → contract decision outcomes.

    These are separate concerns:
      - NOT_ADMISSIBLE must NOT wipe outcomes when candidate claims exist.
      - Contract sufficiency needs outcomes even on list/home pages that are
        not yet a full "primary offer unit".
    Fail-closed only when there are zero candidate_claim observations.
    """
    cu = run_candidate_unit(
        candidate_id=entity, observations=obs, task_text=task_text, chat_fn=chat_fn
    )
    claim_n = sum(1 for o in obs if o.get("channel") == "candidate_claim")
    should_interpret = bool(cu.get("admitted")) or (
        interpret_even_if_not_admitted and claim_n > 0
    )
    outcomes: dict[str, str] = {}
    elig: dict[str, Any] = {"eligible": False, "details": []}
    interp = None
    skipped_reason: str | None = None
    if should_interpret:
        interp = run_interpretation(
            observations=obs,
            decisions=decisions,
            chat_fn=chat_fn,
            batch_decisions=batch_decisions,
        )
        outcomes = interp.get("outcomes") or {}
        elig = interp.get("eligibility") or eligibility_from_outcomes(outcomes, decisions)
    else:
        skipped_reason = (
            "no_candidate_claims"
            if claim_n == 0
            else "not_admitted_and_interpret_blocked"
        )
    return {
        "candidate_unit": cu,
        "outcomes": outcomes,
        "eligibility": elig,
        "eligible": bool(elig.get("eligible")),
        "interpretation": interp,
        "interpreted": should_interpret,
        "claim_n": claim_n,
        "skipped_interpretation_reason": skipped_reason,
    }


def _decisions_from_frozen_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Use decisions from a frozen contract. Optionally annotate required_for_eligibility
    from machine-checkable sufficiency.required entries (decision_id forms only).
    """
    decisions = [dict(d) for d in (contract.get("decisions") or []) if isinstance(d, dict)]
    # Build id → allowed outcomes from sufficiency.required
    required = (contract.get("sufficiency") or {}).get("required") or []
    from sufficiency import _parse_required_entry, _decision_ids

    ids = _decision_ids(contract)
    for entry in required:
        spec = _parse_required_entry(str(entry), ids)
        did = spec.get("decision_id")
        if not did:
            continue
        for d in decisions:
            if d.get("id") != did:
                continue
            if spec.get("kind") in ("decision_eq", "decision_in") and spec.get("allowed"):
                d["required_for_eligibility"] = list(spec["allowed"])
            elif spec.get("kind") == "decision_known":
                # any non-UNKNOWN — eligibility_from_outcomes needs explicit list;
                # leave required_for_eligibility empty and rely on sufficiency gate
                pass
            break
    return decisions


def _merge_outcomes(
    best: dict[str, dict[str, Any]],
    new_outcomes: dict[str, str],
    step: int,
) -> dict[str, dict[str, Any]]:
    """
    Behoud het sterkste eerder-bevestigde outcome per decision_id over
    acquisition-stappen heen. Puur structureel: confirming outcomes
    worden niet overschreven door een latere UNKNOWN/NOT_STATED — een stap
    die de info niet meer toont mag niet eerder bewijs laten "verdwijnen".

    Een latere, ANDERE confirming waarde (echte tegenspraak, ander concreet
    label) overschrijft wel — de nieuwste concrete waarneming wint bij een
    conflict. Geen domeinkennis: enkel weak (UNKNOWN / NOT_STATED) vs
    confirming, en gelijkheid van strings.

    Open #11: "tegenspraak wint"-regel is provisional (getest op 01/02
    pattern only).
    """
    # Weak = absence / no positive claim. NOT_STATED is treated like UNKNOWN
    # for persistence: a later page that simply does not repeat evidence must
    # not erase an earlier confirmed label (run 20260831T063112Z pattern).
    _WEAK = {"UNKNOWN", "NOT_STATED", ""}
    for decision_id, outcome in (new_outcomes or {}).items():
        outcome = str(outcome or "UNKNOWN")
        cur = best.get(decision_id)
        if outcome in _WEAK:
            # Never overwrite a better (confirming) outcome with weak absence.
            if cur is None:
                best[decision_id] = {"outcome": outcome, "step": step}
            continue
        if (
            cur is None
            or str(cur.get("outcome") or "") in _WEAK
            or cur.get("outcome") != outcome
        ):
            best[decision_id] = {"outcome": outcome, "step": step}
    return best


_WEAK_OUTCOMES = frozenset({"UNKNOWN", "NOT_STATED", ""})


def _url_path(url: str) -> str:
    try:
        return urlparse(url or "").path.rstrip("/")
    except Exception:
        return ""


def _normalize_href(href: str, page_url: str = "") -> str:
    h = str(href or "").strip()
    if not h:
        return ""
    try:
        return urljoin(page_url or "", h)
    except Exception:
        return h


def _href_in_preferred(
    href: str,
    preferred_item_links: list[dict[str, str]] | None,
    page_url: str,
) -> bool:
    """True when href matches a preferred_item_link (path or full URL)."""
    nh = _normalize_href(href, page_url)
    np = _url_path(nh)
    if not np and not nh:
        return False
    for p in preferred_item_links or []:
        ph = _normalize_href(str(p.get("href") or ""), page_url)
        if not ph:
            continue
        if nh == ph or _url_path(ph) == np:
            return True
    return False


def _path_last_segment(path: str) -> str:
    parts = [x for x in (path or "").split("/") if x]
    return parts[-1] if parts else ""


def _paths_same_record(path_a: str, path_b: str) -> bool:
    """
    Same bound record, different view (abs vs html vs pdf of the same id).
    Structural: last path segments equal, or one is a prefix of the other.
    Distinct ids (2609.19059 vs 2601.14696) do not match.
    """
    if path_a == path_b:
        return True
    sa, sb = _path_last_segment(path_a), _path_last_segment(path_b)
    if not sa or not sb:
        return False
    return sa == sb or sa.startswith(sb) or sb.startswith(sa)


def _reset_post_bind_outcomes(
    best: dict[str, dict[str, Any]],
    bound_step: int | None,
) -> dict[str, dict[str, Any]]:
    """Drop outcomes written at/after the current candidate bind; keep pre-bind."""
    if bound_step is None:
        return dict(best or {})
    out: dict[str, dict[str, Any]] = {}
    for k, v in (best or {}).items():
        try:
            si = int((v or {}).get("step"))
        except (TypeError, ValueError):
            si = -1
        if si < bound_step:
            out[k] = v
    return out


def _has_nonsatisfying_concrete(
    best: dict[str, dict[str, Any]],
    decisions: list[dict[str, Any]] | None,
) -> bool:
    """
    True when any required decision has a concrete outcome outside its
    sufficiency-satisfying set (contract data, no decision_id names).
    """
    for d in decisions or []:
        preferred = {
            str(x)
            for x in (d.get("required_for_eligibility") or [])
            if x and str(x) not in _WEAK_OUTCOMES
        }
        if not preferred:
            continue
        did = str(d.get("id") or "")
        obs = str((best.get(did) or {}).get("outcome") or "")
        if obs and obs not in _WEAK_OUTCOMES and obs not in preferred:
            return True
    return False


def apply_candidate_scope_after_action(
    *,
    best_outcomes: dict[str, dict[str, Any]],
    active_candidate_path: str | None,
    candidate_bound_step: int | None,
    action_class: str,
    target_href: str | None,
    page_url_before: str,
    new_url: str,
    ok: bool,
    surface_before: str,
    preferred_item_links: list[dict[str, str]] | None,
    decisions: list[dict[str, Any]] | None,
    next_step: int,
) -> tuple[dict[str, dict[str, Any]], str | None, int | None, str]:
    """
    Open #26: after a successful navigation, bind / switch / unbind the
    active candidate path and reset post-bind best_outcomes when the
    underlying record changed.

    Bind only via preferred_item_links (not every itemish link — Search
    would otherwise look like a new candidate). Same-record deepening
    (html/pdf of the same last path segment) does not unbind.

    Returns (best_outcomes, active_candidate_path, candidate_bound_step, event)
    event ∈ {"", "bind", "switch", "unbind"}.
    """
    best = dict(best_outcomes or {})
    if not ok:
        return best, active_candidate_path, candidate_bound_step, ""
    action = str(action_class or "").strip().upper()
    if action in ("STOP", "WAIT", "SCROLL", "OPEN_FILE"):
        return best, active_candidate_path, candidate_bound_step, ""

    if action == "FILL_AND_SUBMIT":
        if active_candidate_path is not None:
            best = _reset_post_bind_outcomes(best, candidate_bound_step)
            return best, None, None, "unbind"
        return best, active_candidate_path, candidate_bound_step, ""

    href = str(target_href or new_url or "").strip()
    path_before = _url_path(page_url_before)
    path_after = _url_path(new_url)
    dest_path = _url_path(_normalize_href(href, page_url_before)) or path_after
    is_pref = _href_in_preferred(href, preferred_item_links, page_url_before)
    left_page = bool(dest_path and dest_path != path_before)

    if is_pref and left_page:
        if active_candidate_path and _paths_same_record(dest_path, active_candidate_path):
            return best, active_candidate_path, candidate_bound_step, ""
        from_list = str(surface_before or "") == "list_results" and active_candidate_path is None
        different = bool(
            active_candidate_path
            and dest_path != active_candidate_path
            and not _paths_same_record(dest_path, active_candidate_path)
        )
        if from_list or different:
            switching = different
            fail = bool(active_candidate_path) and _has_nonsatisfying_concrete(
                best, decisions
            )
            event = "bind"
            if switching or fail:
                best = _reset_post_bind_outcomes(best, candidate_bound_step)
                event = "switch"
            return best, dest_path, next_step, event

    if active_candidate_path is not None:
        still_on = path_after == active_candidate_path or _paths_same_record(
            path_after, active_candidate_path
        )
        if not still_on:
            best = _reset_post_bind_outcomes(best, candidate_bound_step)
            return best, None, None, "unbind"

    return best, active_candidate_path, candidate_bound_step, ""


def _decision_is_satisfied(
    decision: dict[str, Any],
    best_outcomes: dict[str, dict[str, Any]],
) -> bool:
    """
    True when best_outcomes already holds a contract-satisfying label for
    this decision (required_for_eligibility from frozen-contract sufficiency).

    Domain-free: preferred set is data on the decision object, not hardcoded
    outcome strings. If required_for_eligibility is empty, never treat as
    satisfied here (must keep interpreting until gaps/sufficiency say stop).
    """
    did = str(decision.get("id") or "")
    if not did:
        return False
    preferred = {
        str(x)
        for x in (decision.get("required_for_eligibility") or [])
        if x and str(x) not in ("UNKNOWN", "NOT_STATED", "")
    }
    if not preferred:
        return False
    cur = best_outcomes.get(did) or {}
    outcome = str(cur.get("outcome") or "")
    return outcome in preferred


def _decisions_pending_interpretation(
    decisions: list[dict[str, Any]],
    best_outcomes: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Split decisions into those still needing interpret vs already satisfied.

    Perf (Fase A): skip re-interpreting decision_ids that already have a
    sufficiency-satisfying outcome in best_outcomes. Trade-off: a later page
    that would *contradict* that label is not re-checked (documented Open #19).
    """
    pending: list[dict[str, Any]] = []
    skipped: list[str] = []
    for d in decisions:
        did = str(d.get("id") or "")
        if _decision_is_satisfied(d, best_outcomes):
            if did:
                skipped.append(did)
            continue
        pending.append(d)
    return pending, skipped


def run_acquisition_loop(
    *,
    entity: str,
    start_url: str,
    chat_fn: ChatFnStr | None,
    backend: str = "playwright",
    wait_seconds: float = 3.5,
    max_acquisition_steps: int = 3,
    max_claim_lines: int = 28,
    task_text: str = PACKAGES_TASK_TEXT,
    decisions: list[dict[str, Any]] | None = None,
    frozen_contract: dict[str, Any] | None = None,
    expected_eligible: bool | None = True,
    # Lab-only: ordered click texts to try when LLM unavailable or as first attempts
    force_click_texts: list[str] | None = None,
    ledger: RunLedger | None = None,
    trace: TraceSession | None = None,
    # ISOLATE #16: PACKAGES_DECISIONS only when explicitly opted in
    allow_lab_fixture: bool = False,
    # Fase B opt-in: multi-decision interpret per claim (default False — P0 freeze)
    batch_decisions: bool = False,
) -> dict[str, Any]:
    """
    backend must be playwright for multi-step (session preserved).
    force_click_texts is experimental scaffolding — not a product site rule engine.
    When `trace` is provided, every observe/affordance/gap/decision/action is
    recorded to events.jsonl + artifacts (forensic, non-steering).

    When frozen_contract is set (production path):
      decisions come from the contract; STOP is decided by sufficiency_stop (code),
      not by match_status or shortlist length.
    When frozen_contract is None: require explicit decisions=... or
      allow_lab_fixture=True (PACKAGES_DECISIONS). Silent fallback removed (ISOLATE #16).
    """
    if frozen_contract is not None:
        decisions = _decisions_from_frozen_contract(frozen_contract)
    elif decisions is not None:
        pass  # caller-supplied decisions (explicit)
    elif allow_lab_fixture:
        decisions = PACKAGES_DECISIONS
    else:
        raise RuntimeError(
            "run_acquisition_loop: frozen_contract is None and no decisions supplied. "
            "Pass frozen_contract=... (production) or decisions=... / "
            "allow_lab_fixture=True (lab only). "
            "Silent PACKAGES_DECISIONS fallback is disabled (FRAMEWORK_BOUNDARY ISOLATE)."
        )
    ledger = ledger or RunLedger(
        task_text=task_text,
        run_kind="live_offer_state_slice",
        meta={
            "entity": entity,
            "backend": backend,
            "has_frozen_contract": frozen_contract is not None,
        },
    )

    if backend != "playwright":
        ledger.set_stop("BACKEND_MUST_BE_PLAYWRIGHT_FOR_ACQUISITION")
        if trace:
            trace.log_stop("BACKEND_MUST_BE_PLAYWRIGHT_FOR_ACQUISITION")
        return {
            "entity": entity,
            "ok": False,
            "stop_reason": "BACKEND_MUST_BE_PLAYWRIGHT_FOR_ACQUISITION",
            "ledger": ledger.to_dict(),
            "trace_dir": str(trace.root) if trace else None,
        }

    from browser import browser_list_affordances, browser_open

    print(f"[acquisition] OPEN {entity}: {start_url[:110]}...", flush=True)
    ledger.log_action("OPEN_URL", payload={"url": start_url, "backend": backend})
    if trace:
        trace.log_action("OPEN_URL", payload={"url": start_url, "backend": backend})
    page = browser_open(start_url, wait_seconds=wait_seconds, headless=True, max_chars=22000)
    err = page.get("error")
    text = str(page.get("text") or "")
    html = str(page.get("html") or "")
    final_url = str(page.get("url") or start_url)
    title = str(page.get("title") or "")

    ledger.log_action(
        "OBSERVE_PAGE",
        payload={"url": final_url, "step": 0},
        result_summary={"title": title[:120], "text_chars": len(text), "error": err},
        ok=not bool(err) and len(text) > 50,
        error=str(err) if err else None,
    )
    if trace:
        trace.set_step(0)
        trace.log_observe(
            url=final_url,
            title=title,
            text=text,
            text_chars=len(text),
            html=html,
            html_chars=int(page.get("html_chars") or len(html)),
            error=str(err) if err else None,
            backend=backend,
        )

    if err or len(text) < 40:
        ledger.set_stop("FETCH_FAILED_OR_EMPTY")
        if trace:
            trace.log_stop("FETCH_FAILED_OR_EMPTY")
            trace.finalize({"entity": entity, "ok": False})
        return {
            "entity": entity,
            "ok": False,
            "stop_reason": "FETCH_FAILED_OR_EMPTY",
            "page": page,
            "ledger": ledger.to_dict(),
            "trace_dir": str(trace.root) if trace else None,
        }

    force_queue = list(force_click_texts or [])
    steps_log: list[dict[str, Any]] = []
    last_pipe: dict[str, Any] = {}
    # Strongest confirmed outcome per decision_id across steps (Open #19).
    best_outcomes: dict[str, dict[str, Any]] = {}
    acquisition_steps = 0
    # Generic anti-loop: fingerprints of actions that produced no state change
    blocked_action_keys: list[str] = []
    surfaces_seen: list[str] = []
    # Open #26: bound item path (list→detail); None until first preferred-item bind
    active_candidate_path: str | None = None
    candidate_bound_step: int | None = None
    prev_state_sig: str | None = None

    for step in range(0, max_acquisition_steps + 1):
        if trace:
            trace.set_step(step)
        aff = browser_list_affordances(max_items=60)
        affordances = aff.get("affordances") or []
        ledger.log_action(
            "LIST_AFFORDANCES",
            payload={"step": step},
            result_summary={"n": len(affordances), "sample": [a.get("text") for a in affordances[:8]]},
            ok=bool(aff.get("ok")),
            error=aff.get("error"),
        )
        if trace:
            trace.log_affordances(affordances, full=True)

        cur_sig = state_signature(url=final_url, text=text, affordances=affordances)
        if prev_state_sig is not None and cur_sig == prev_state_sig and steps_log:
            # Last action left the page unchanged — already recorded on that action key
            pass
        prev_state_sig = cur_sig

        # Surface taxonomy (generic, no site names):
        #   live_detail      — starting detail page
        #   live_offer_state — deeper same-entity surface
        #   list_results     — multi-item listing / search results with
        #                      offer-like density (prices, repeated cards)
        #   site_marketing   — left entity path AND no dense item evidence
        surface, same_entity = _classify_surface(
            start_url=start_url,
            cur_url=final_url,
            text=text,
            step=step,
        )
        if surface and surface not in surfaces_seen:
            surfaces_seen.append(str(surface))

        # Candidate layer (2026-08-28): structural extract → quality select →
        # observations bound by candidate_id. Interpretation sees top-K candidates
        # instead of whole-page claim soup. No domain merge required for this step.
        # Provisional budget (FRAMEWORK_BOUNDARY Open #6 — not locked across page types).
        # Fase 1b defaults: max_candidates=3, max_units=6 (token-volume target ~≤550).
        # Was temporarily raised to 6/16 during candidate-layer debugging; restore defaults.
        selected = extract_candidates(
            text=text,
            affordances=affordances,
            page_url=final_url,
            surface=surface,
            max_candidates=3,
            max_units=6,
            html=html,
        )
        preferred_links = [
            {
                "text": str((c.primary_action or {}).get("text") or "")[:120],
                "href": str((c.primary_action or {}).get("href") or "")[:400],
            }
            for c in selected
            if c.has_action()
        ]
        # de-dupe preferred links
        _seen_pref: set[str] = set()
        _pref_clean: list[dict[str, str]] = []
        for p in preferred_links:
            k = f"{(p.get('text') or '').lower()}|{(p.get('href') or '').lower()}"
            if k in _seen_pref or (not p.get("text") and not p.get("href")):
                continue
            _seen_pref.add(k)
            _pref_clean.append(p)
        preferred_links = _pref_clean
        cand_preview = candidates_preview(selected)
        # legacy unit artifacts for comparison / regression
        units = package_candidate_units(
            text=text,
            affordances=affordances,
            page_url=final_url,
            max_units=6,  # align with extract_candidates provisional budget (Open #6)
            max_lines_per_unit=8,
        )
        unit_preview = unit_claim_preview(units)

        # Open #6: extract_candidates already applied the provisional budget
        # (max_candidates=3, max_units=6). Open #27 may splice one extra
        # long-text candidate, so len(selected) can be 4. Do not recap here
        # with a hardcoded 3 — that dropped spliced c3 in 20260917T102344Z
        # before interpret ever saw the abstract.
        obs = candidates_to_observations(selected)
        if title:
            obs.insert(
                0,
                {
                    "observation_id": "live-title",
                    "candidate_id": entity,
                    "text": title[:300],
                    "channel": "candidate_claim",
                    "scope": "page_title",
                    "provenance": {
                        "origin": "browser_title",
                        "source_url": final_url,
                        "surface": surface,
                    },
                },
            )
        # Detail pages: keep a few ranked line observations as safety net if
        # candidate set is very small (should be rare after quality v1).
        if surface != "list_results" and len(selected) < 2:
            line_obs = page_text_to_observations(
                candidate_id=entity,
                url=final_url,
                title=title,
                text=text,
                max_claim_lines=min(12, max_claim_lines),
            )
            obs.extend(line_obs)

        for o in obs:
            prov = o.setdefault("provenance", {})
            prov["surface"] = surface
            prov["acquisition_step"] = step
            prov["same_entity_path"] = same_entity
        ledger.log_observations(obs)
        stage_d = stage_d_from_obs(obs)
        if trace:
            claims_preview = [
                o["text"] for o in obs if o.get("channel") == "candidate_claim"
            ][:24]
            trace.save_artifact(
                f"step_{step:03d}_claims.json",
                {
                    "url": final_url,
                    "stage_d": stage_d,
                    "claim_preview": claims_preview,
                    "candidates_preview": cand_preview,
                    "candidate_units": units[:8],
                    "unit_preview": unit_preview,
                    "obs_n": len(obs),
                },
            )
            try:
                from candidates import candidates_to_jsonable

                trace.save_artifact(
                    f"step_{step:03d}_candidates.json",
                    {
                        "url": final_url,
                        "surface": surface,
                        "candidates": candidates_to_jsonable(selected),
                        "preview": cand_preview,
                    },
                )
                trace.save_artifact(
                    f"step_{step:03d}_candidate_units.json",
                    {"url": final_url, "surface": surface, "units": units[:8]},
                )
            except Exception:
                pass

        import time as _time

        # Fase A: do not re-interpret decisions already confirmed to a
        # contract-satisfying outcome in best_outcomes (Open #19 perf).
        pending_decisions, skipped_satisfied = _decisions_pending_interpretation(
            decisions, best_outcomes
        )
        t_interp0 = _time.monotonic()
        if pending_decisions:
            pipe = _pipeline_on_obs(
                entity=entity,
                obs=obs,
                chat_fn=chat_fn,
                task_text=task_text,
                decisions=pending_decisions,
                # Contract path: interpret whenever claims exist (CU is ranking only)
                interpret_even_if_not_admitted=True,
                batch_decisions=batch_decisions,
            )
        else:
            # All decisions already satisfied — no interpret LLM calls this step.
            pipe = {
                "candidate_unit": {"decision": "SKIPPED_ALL_SATISFIED", "llm_calls": 0},
                "outcomes": {},
                "eligibility": {"eligible": True, "details": []},
                "eligible": True,
                "interpretation": {"llm_calls": 0, "outcomes": {}, "decision_traces": {}},
                "interpreted": False,
                "claim_n": sum(1 for o in obs if o.get("channel") == "candidate_claim"),
                "skipped_interpretation_reason": "all_decisions_already_satisfied",
            }
        interp_duration = round(_time.monotonic() - t_interp0, 3)
        # Re-attach already-satisfied outcomes so this step's view is complete
        # (correctness: final merge still uses best_outcomes; this is for logs).
        step_outcomes = dict(pipe.get("outcomes") or {})
        for did in skipped_satisfied:
            held = best_outcomes.get(did) or {}
            if held.get("outcome") is not None:
                step_outcomes[did] = str(held["outcome"])
        pipe = dict(pipe)
        pipe["outcomes"] = step_outcomes
        pipe["skipped_satisfied_decisions"] = list(skipped_satisfied)
        last_pipe = pipe
        best_outcomes = _merge_outcomes(
            best_outcomes, pipe.get("outcomes") or {}, step
        )
        interp_meta = pipe.get("interpretation") or {}
        llm_calls_step = int(interp_meta.get("llm_calls") or 0)
        # Count CU call when interpretation was skipped (still 1 CU llm call)
        cu_meta = pipe.get("candidate_unit") or {}
        if not pipe.get("interpreted"):
            llm_calls_step = int(cu_meta.get("llm_calls") or 0)
        else:
            llm_calls_step = int(cu_meta.get("llm_calls") or 0) + int(
                interp_meta.get("llm_calls") or 0
            )
        prov_blocked = int(interp_meta.get("provenance_blocked_n") or 0)
        for did, outc in (pipe.get("outcomes") or {}).items():
            ledger.log_decision("interpretation", decision_id=did, outcome=str(outc))
        ledger.log_decision(
            "eligibility",
            outcome="ELIGIBLE" if pipe.get("eligible") else "NOT_ELIGIBLE",
            raw=pipe.get("eligibility") or {},
        )
        if trace:
            trace.log_interpret(
                pipe.get("outcomes") or {},
                eligible=bool(pipe.get("eligible")),
                llm_calls=llm_calls_step,
                duration_s=interp_duration,
                provenance_blocked_n=prov_blocked,
            )
            trace.log_eligibility(pipe.get("eligibility") or {})

        # Prefer frozen-contract sufficiency (production). Legacy eligibility only
        # when no frozen contract (PACKAGES fixture path).
        # Use merged best_outcomes so earlier confirming labels survive pages that
        # no longer repeat the evidence (Open #19 / run 20260831T063112Z).
        merged_flat = {k: v["outcome"] for k, v in best_outcomes.items()}
        if frozen_contract is not None:
            gaps = gaps_from_frozen_contract(frozen_contract, merged_flat)
            suf = sufficiency_stop(frozen_contract, merged_flat)
            contract_satisfied = bool(suf.get("satisfied"))
        else:
            gaps = gaps_from_eligibility(
                pipe.get("eligibility"), merged_flat or (pipe.get("outcomes") or {})
            )
            suf = None
            contract_satisfied = bool(pipe.get("eligible"))

        if trace:
            trace.log_gaps(gaps, outcomes=merged_flat or (pipe.get("outcomes") or {}))
        claims = [o["text"] for o in obs if o.get("channel") == "candidate_claim"]
        step_rec = {
            "step": step,
            "url": final_url,
            "text_chars": len(text),
            "candidate_unit": (pipe.get("candidate_unit") or {}).get("decision"),
            "interpreted": pipe.get("interpreted"),
            "claim_n": pipe.get("claim_n"),
            "outcomes": pipe.get("outcomes"),
            "eligible": pipe.get("eligible"),
            "contract_satisfied": contract_satisfied,
            "sufficiency": suf,
            "gaps": gaps,
            "stage_d": stage_d,
            "affordance_n": len(affordances),
            "interp_llm_calls": llm_calls_step,
            "interp_duration_s": interp_duration,
            "provenance_blocked_n": prov_blocked,
            "surface": surface,
            "same_entity_path": same_entity,
            "state_sig": cur_sig,
            "blocked_actions_n": len(blocked_action_keys),
            "candidate_units_n": len(units),
            "preferred_item_links_n": len(preferred_links),
            "unit_preview": unit_preview[:4],
        }
        steps_log.append(step_rec)
        print(
            f"[acquisition] step={step} eligible={pipe.get('eligible')} "
            f"contract_satisfied={contract_satisfied} gaps={len(gaps)} "
            f"outcomes={pipe.get('outcomes')} "
            f"cu={(pipe.get('candidate_unit') or {}).get('decision')} "
            f"interpreted={pipe.get('interpreted')} "
            f"llm_calls={llm_calls_step} interp_s={interp_duration} "
            f"surface={surface} prov_blocked={prov_blocked} "
            f"blocked_n={len(blocked_action_keys)} "
            f"cands={len(selected)} units={len(units)} item_links={len(preferred_links)} "
            f"skip_satisfied={skipped_satisfied or []}",
            flush=True,
        )

        if contract_satisfied:
            stop_msg = (
                suf.get("stop_reason")
                if isinstance(suf, dict)
                else "ALL_REQUIRED_OUTCOMES_PROVEN"
            ) or "CONTRACT_SATISFIED"
            ledger.set_stop(stop_msg)
            if trace:
                trace.log_stop(stop_msg)
            break
        if step >= max_acquisition_steps:
            ledger.set_stop("MAX_ACQUISITION_STEPS")
            if trace:
                trace.log_stop("MAX_ACQUISITION_STEPS")
            break
        if not gaps:
            ledger.set_stop("NO_GAPS_BUT_NOT_ELIGIBLE")
            if trace:
                trace.log_stop("NO_GAPS_BUT_NOT_ELIGIBLE")
            break

        # --- decide next action ---
        decision: dict[str, Any]
        if force_queue:
            t = force_queue.pop(0)
            decision = {
                "action_class": "CLICK_TEXT",
                "target_text": t,
                "target_href": None,
                "for_decision_ids": [g.get("decision_id") for g in gaps],
                "reason": "lab_force_click_queue",
                "source": "lab_force",
            }
            # Skip force target if already known no-progress
            fp_force = action_fingerprint(decision, page_url=final_url)
            if fp_force in blocked_action_keys:
                decision = {
                    "action_class": "STOP",
                    "reason": "no_progress_repeat_blocked_force",
                    "source": "code_reject",
                    "for_decision_ids": [g.get("decision_id") for g in gaps],
                    "blocked_key": fp_force,
                }
        else:
            decision = acquisition_decide(
                gaps=gaps,
                affordances=affordances,
                page_url=final_url,
                page_title=title,
                claim_preview=claims[:20],
                task_text=task_text,
                chat_fn=chat_fn,
                step_index=acquisition_steps,
                max_steps=max_acquisition_steps,
                blocked_action_keys=blocked_action_keys,
                preferred_item_links=preferred_links,
                candidate_unit_preview=unit_preview,
                current_page_outcomes=pipe.get("outcomes") or {},
                surfaces_seen=surfaces_seen,
            )

        ledger.log_decision(
            "acquisition",
            decision_id=",".join(str(x) for x in (decision.get("for_decision_ids") or [])),
            outcome=str(decision.get("action_class")),
            raw=decision,
        )
        known_ctx = {
            k: v
            for k, v in (pipe.get("outcomes") or {}).items()
            if v and v != "UNKNOWN"
        }
        unknown_ctx = [g.get("decision_id") for g in gaps]
        actions_sample = [
            f"{a.get('scope','?')}:{a.get('kind','?')}:{a.get('text')}"
            for a in (affordances or [])[:12]
        ]
        if trace:
            trace.log_acquisition_decision(
                decision,
                known=known_ctx,
                unknown=unknown_ctx,
                available_actions_sample=actions_sample,
            )
            if decision.get("source") in ("code_reject", "code"):
                trace.log_code_policy(
                    action_class=str(decision.get("action_class")),
                    allowed=decision.get("action_class") != "STOP"
                    or "reject" not in str(decision.get("source") or ""),
                    reason=str(decision.get("reason") or ""),
                    target_text=decision.get("target_text"),
                    target_href=decision.get("target_href"),
                    extra={"source": decision.get("source"), "llm_raw": decision.get("llm_raw")},
                )
        step_rec["acquisition_decision"] = decision
        step_rec["decision_context"] = {
            "known": known_ctx,
            "unknown": unknown_ctx,
            "actions_sample": actions_sample,
        }

        if decision.get("action_class") == "STOP":
            # Framework rule: LLM (or soft code) STOP is not final while the
            # frozen contract still has gaps. Only code-owned terminal reasons
            # may end the loop early; otherwise keep searching.
            stop_reason_raw = str(decision.get("reason") or "")
            src = str(decision.get("source") or "")
            # True terminal only when code says there is nothing left to try
            # (or hard safety). Repeat-blocked is NOT terminal: loop continues
            # so the planner can pick a different affordance with the blocked list.
            code_terminal = src in ("code", "code_reject") and stop_reason_raw in (
                "no_gaps",
                "max_steps_reached",
                "no_llm_fail_closed",
            )
            if gaps and frozen_contract is not None and not code_terminal:
                print(
                    f"[acquisition] REJECT llm/soft STOP while contract gaps={len(gaps)} "
                    f"reason={stop_reason_raw[:120]}",
                    flush=True,
                )
                if trace:
                    trace.log_code_policy(
                        action_class="STOP",
                        allowed=False,
                        reason="stop_rejected_contract_gaps",
                        target_text=None,
                        target_href=None,
                        extra={
                            "gaps_n": len(gaps),
                            "llm_reason": stop_reason_raw[:300],
                            "source": src,
                        },
                    )
                step_rec["stop_rejected"] = {
                    "reason": stop_reason_raw[:300],
                    "source": src,
                    "gaps_n": len(gaps),
                }
                # Treat as a no-op step; loop continues until max steps or true terminal
                acquisition_steps += 1
                if acquisition_steps >= max_acquisition_steps:
                    ledger.set_stop("MAX_ACQUISITION_STEPS")
                    if trace:
                        trace.log_stop("MAX_ACQUISITION_STEPS")
                    break
                continue
            ledger.set_stop(f"ACQUISITION_STOP:{stop_reason_raw}")
            if trace:
                trace.log_stop(f"ACQUISITION_STOP:{stop_reason_raw}")
            break

        print(
            f"[acquisition] execute {decision.get('action_class')} "
            f"target={decision.get('target_text') or decision.get('target_href')}",
            flush=True,
        )
        ledger.log_action(
            "ACQUIRE",
            payload=decision,
        )
        if trace:
            trace.log_action("ACQUIRE", payload=decision)
        pre_sig = cur_sig
        action_key = action_fingerprint(decision, page_url=final_url)
        snap = execute_acquisition_action(decision, max_chars=22000)
        acquisition_steps += 1
        if snap.get("download"):
            step_rec["download"] = {
                "filename": str(snap.get("download_filename") or "")[:200],
                "url": str(
                    snap.get("download_url") or snap.get("requested_href") or ""
                )[:400],
                "kept_page": True,
            }
            print(
                f"[acquisition] download_kept_page "
                f"file={step_rec['download']['filename'] or '(unnamed)'} "
                f"— staying on current page, will try other affordances",
                flush=True,
            )
        ok = bool(snap.get("ok")) and not snap.get("noop")
        new_text = str(snap.get("text") or "")
        new_html = str(snap.get("html") or "")
        new_url = str(snap.get("url") or final_url)
        # Re-list affordances cheaply for signature (or use text-only if list fails)
        try:
            aff_after = browser_list_affordances(max_items=60)
            aff_after_list = aff_after.get("affordances") or []
        except Exception:
            aff_after_list = []
        post_sig = state_signature(
            url=new_url, text=new_text, affordances=aff_after_list
        )
        no_progress = bool(ok) and post_sig == pre_sig
        # Anti-repeat: always block this action_key after one attempt.
        # UI toggles (open↔close filter) change state_sig without research progress;
        # signature-only no-progress is not enough (2026-08-28 VERTREKPERIODE loop).
        if action_key and action_key not in blocked_action_keys:
            blocked_action_keys.append(action_key)
        step_rec["no_progress"] = no_progress
        step_rec["action_key"] = action_key
        step_rec["blocked_after_execute"] = True
        print(
            f"[acquisition] no_progress={no_progress} blocked_key={action_key} "
            f"blocked_n={len(blocked_action_keys)}",
            flush=True,
        )
        if trace and (no_progress or not ok):
            trace.log_action(
                "NO_PROGRESS" if no_progress else "ACTION_FAILED",
                payload={
                    "action_key": action_key,
                    "pre_sig": pre_sig,
                    "post_sig": post_sig,
                    "blocked_n": len(blocked_action_keys),
                },
                ok=False,
            )
        elif trace:
            trace.log_action(
                "ACTION_DONE",
                payload={
                    "action_key": action_key,
                    "pre_sig": pre_sig,
                    "post_sig": post_sig,
                    "blocked_n": len(blocked_action_keys),
                    "anti_repeat": "key_blocked_after_one_use",
                },
                ok=ok,
            )
        ledger.log_action(
            "OBSERVE_PAGE",
            payload={"step": step + 1, "after": decision.get("action_class")},
            result_summary={
                "ok": ok,
                "text_chars": len(new_text),
                "url": snap.get("url"),
                "error": snap.get("error"),
                "no_progress": no_progress,
                "action_key": action_key,
            },
            ok=ok,
            error=str(snap.get("error") or "") or None,
        )
        if trace:
            trace.set_step(step + 1)
            trace.log_observe(
                url=new_url,
                title=str(snap.get("title") or title),
                text=new_text,
                text_chars=len(new_text),
                html=new_html,
                html_chars=int(snap.get("html_chars") or len(new_html)),
                error=str(snap.get("error") or "") or None,
                backend=backend,
            )
            trace.log_action(
                "OBSERVE_PAGE",
                payload={"step": step + 1, "after": decision.get("action_class")},
                result={
                    "ok": ok,
                    "text_chars": len(new_text),
                    "url": snap.get("url"),
                    "no_progress": no_progress,
                },
                ok=ok,
                error=str(snap.get("error") or "") or None,
            )
        if not ok or len(new_text) < 40:
            # Soft-fail (2026-08-28): one broken click must not kill the run.
            # Keep previous page state; action_key already blocked so the
            # planner will try a different affordance on the next iteration.
            # Terminal only when the loop budget is exhausted (handled by the
            # for-range / max_acquisition_steps check at the top of next step).
            step_rec["execute_error"] = snap.get("error") or "empty_after_action"
            step_rec["soft_fail"] = True
            print(
                f"[acquisition] soft_fail action={action_key} "
                f"err={(snap.get('error') or 'empty')[:120]!s} "
                f"— keeping prior page, will try other affordances",
                flush=True,
            )
            continue

        if no_progress:
            # State unchanged: keep text/url, do not waste a "successful" transition
            # but allow the loop to pick a different action next iteration.
            continue

        page_url_before = final_url
        text = new_text
        html = new_html
        final_url = new_url
        title = str(snap.get("title") or title)
        best_outcomes, active_candidate_path, candidate_bound_step, scope_event = (
            apply_candidate_scope_after_action(
                best_outcomes=best_outcomes,
                active_candidate_path=active_candidate_path,
                candidate_bound_step=candidate_bound_step,
                action_class=str(decision.get("action_class") or ""),
                target_href=str(decision.get("target_href") or "") or None,
                page_url_before=str(page_url_before),
                new_url=new_url,
                ok=ok,
                surface_before=str(surface or ""),
                preferred_item_links=preferred_links,
                decisions=decisions,
                next_step=step + 1,
            )
        )
        if scope_event:
            step_rec["candidate_scope"] = {
                "event": scope_event,
                "active_candidate_path": active_candidate_path,
                "candidate_bound_step": candidate_bound_step,
            }
            print(
                f"[acquisition] candidate_scope event={scope_event} "
                f"path={active_candidate_path} bound_step={candidate_bound_step} "
                f"best_n={len(best_outcomes)}",
                flush=True,
            )

    eligible = bool(last_pipe.get("eligible"))
    # Prefer persisted best outcomes; fall back to last step if merge is empty
    # (e.g. 0 interpretable steps) so step-0 CONTRACT_SATISFIED still works.
    outcomes = (
        {k: v["outcome"] for k, v in best_outcomes.items()}
        or (last_pipe.get("outcomes") or {})
    )

    # Final sufficiency from frozen contract (production) or last step_rec
    final_suf = None
    contract_satisfied = False
    if frozen_contract is not None:
        final_suf = sufficiency_stop(frozen_contract, outcomes)
        contract_satisfied = bool(final_suf.get("satisfied"))
        # Align stop reason if loop exited for max steps but contract already ok
        if contract_satisfied and not (ledger.stop_reason or "").startswith("CONTRACT"):
            ledger.set_stop(final_suf.get("stop_reason") or "CONTRACT_SATISFIED")
    elif steps_log:
        contract_satisfied = bool(steps_log[-1].get("contract_satisfied"))

    fault = "none"
    if frozen_contract is not None:
        # Generic: gaps from contract only — no domain outcome names
        if expected_eligible is True and not contract_satisfied:
            n_gaps = len((final_suf or {}).get("gaps") or [])
            fault = f"CONTRACT_GAPS_n={n_gaps}"
    elif expected_eligible is True and not eligible:
        # Lab fixture path only (PACKAGES_DECISIONS experiment)
        if outcomes.get("board_type") not in ("ALL_INCLUSIVE",):
            fault = f"E_board_{outcomes.get('board_type', 'MISSING')}"
        elif outcomes.get("package_includes_flight") not in ("FLIGHT_INCLUDED",):
            fault = f"E_flight_{outcomes.get('package_includes_flight', 'MISSING')}"
        else:
            fault = "F_not_eligible"

    ledger.pipeline_summary = {
        "entity": entity,
        "eligible": eligible,
        "contract_satisfied": contract_satisfied,
        "outcomes": outcomes,
        "sufficiency": final_suf,
        "fault_localization": fault,
        "stop_reason": ledger.stop_reason,
        "acquisition_steps": acquisition_steps,
        "steps_n": len(steps_log),
        "has_frozen_contract": frozen_contract is not None,
    }
    ledger.metrics = {
        "eligible": eligible,
        "contract_satisfied": contract_satisfied,
        "acquisition_steps": acquisition_steps,
        "fault": fault,
        "llm_enabled": chat_fn is not None,
        "has_frozen_contract": frozen_contract is not None,
    }
    ledger.trace_stages = {
        "steps": steps_log,
        "final_url": final_url,
        "final_outcomes": outcomes,
        "sufficiency": final_suf,
    }

    # Cost scaling metric (2026-09-08): interpret cost grows ~linear with
    # number of contract decisions × candidates/units per step. Surface this
    # without changing behaviour — early warning for complex contracts.
    total_llm = sum(int(s.get("interp_llm_calls") or 0) for s in steps_log)
    total_interp_s = sum(float(s.get("interp_duration_s") or 0) for s in steps_log)
    n_decisions = 0
    if frozen_contract is not None:
        n_decisions = len(
            [
                d
                for d in (frozen_contract.get("decisions") or [])
                if isinstance(d, dict) and d.get("id")
            ]
        )
    llm_calls_per_decision: float | None = None
    if n_decisions > 0 and total_llm > 0:
        llm_calls_per_decision = round(total_llm / n_decisions, 2)

    ledger.metrics["llm_calls_total"] = total_llm
    ledger.metrics["n_decisions"] = n_decisions
    ledger.metrics["llm_calls_per_decision"] = llm_calls_per_decision
    ledger.metrics["interpret_duration_s"] = round(total_interp_s, 3)

    trace_info: dict[str, Any] | None = None
    if trace:
        phase_durations = {
            "interpret_llm_s": round(total_interp_s, 3),
            "wall_total_s": round(trace.duration_s(), 3),
        }
        trace.log_timing_summary(
            phase_durations,
            llm_calls_total=total_llm,
            n_decisions=n_decisions,
            llm_calls_per_decision=llm_calls_per_decision,
            acquisition_steps=acquisition_steps,
            note=(
                "interpret_llm_s dominates on local models; cost scales with "
                "n_decisions × candidates/units per step (see LEARNING_LOG 2026-09-08)"
            ),
        )
        trace_info = trace.finalize(
            {
                "entity": entity,
                "eligible": eligible,
                "contract_satisfied": contract_satisfied,
                "outcomes": outcomes,
                "sufficiency": final_suf,
                "fault": fault,
                "stop_reason": ledger.stop_reason,
                "acquisition_steps": acquisition_steps,
                "final_url": final_url,
                "llm_calls_total": total_llm,
                "n_decisions": n_decisions,
                "llm_calls_per_decision": llm_calls_per_decision,
                "interpret_duration_s": round(total_interp_s, 3),
                "has_frozen_contract": frozen_contract is not None,
            }
        )

    return {
        "entity": entity,
        "ok": True,
        "stop_reason": ledger.stop_reason,
        "fault_localization": fault,
        "eligible": eligible,
        "contract_satisfied": contract_satisfied,
        "sufficiency": final_suf,
        "expected_eligible": expected_eligible,
        "match": (
            None
            if expected_eligible is None
            else (
                bool(contract_satisfied) == bool(expected_eligible)
                if frozen_contract is not None
                else bool(eligible) == bool(expected_eligible)
            )
        ),
        "outcomes": outcomes,
        "acquisition_steps": acquisition_steps,
        "steps": steps_log,
        "final_url": final_url,
        "candidate_unit": last_pipe.get("candidate_unit"),
        "has_frozen_contract": frozen_contract is not None,
        "llm_calls_total": total_llm,
        "n_decisions": n_decisions,
        "llm_calls_per_decision": llm_calls_per_decision,
        "interpret_duration_s": round(total_interp_s, 3),
        "ledger": ledger.to_dict(),
        "trace_dir": str(trace.root) if trace else None,
        "trace": trace_info,
    }


def run_acquisition_batch(
    targets: list[dict[str, Any]],
    *,
    chat_fn: ChatFnStr | None,
    max_acquisition_steps: int = 3,
    task_text: str = PACKAGES_TASK_TEXT,
    frozen_contract: dict[str, Any] | None = None,
    trace_root: str | None = None,
) -> dict[str, Any]:
    """
    Run one or more entities. When `trace_root` is set, each entity gets a
    TraceSession under `<trace_root>/<safe_entity>/` with events.jsonl + audit.

    When frozen_contract is set, STOP is decided by code sufficiency gate only
    (see docs/FRAMEWORK_BOUNDARY.md). Per-target frozen_contract key overrides batch.
    """
    from pathlib import Path

    results = []
    for t in targets:
        entity = str(t.get("entity") or "unknown")
        url = str(t.get("detail_url") or t.get("url") or t.get("start_url") or "")
        fc = t.get("frozen_contract") if t.get("frozen_contract") is not None else frozen_contract
        ledger = RunLedger(
            task_text=task_text,
            run_kind="live_offer_state_slice",
            meta={
                "entity": entity,
                "has_frozen_contract": fc is not None,
                "contract_decision_ids": [
                    d.get("id")
                    for d in ((fc or {}).get("decisions") or [])
                    if isinstance(d, dict)
                ],
            },
        )
        trace: TraceSession | None = None
        if trace_root:
            safe = entity.replace(" ", "_").replace("/", "_")[:60]
            tdir = Path(trace_root) / safe
            trace = TraceSession(
                tdir,
                task_text=task_text,
                run_kind="live_offer_state_slice",
                meta={
                    "entity": entity,
                    "start_url": url,
                    "force_click": bool(t.get("force_click_texts")),
                    "llm": chat_fn is not None,
                    "has_frozen_contract": fc is not None,
                },
            )
        r = run_acquisition_loop(
            entity=entity,
            start_url=url,
            chat_fn=chat_fn,
            max_acquisition_steps=int(t.get("max_acquisition_steps") or max_acquisition_steps),
            expected_eligible=t.get("expected_eligible", True),
            force_click_texts=t.get("force_click_texts"),
            task_text=task_text,
            frozen_contract=fc,
            ledger=ledger,
            trace=trace,
            # Lab campaign may omit frozen_contract; explicit opt-in (ISOLATE #16)
            allow_lab_fixture=(fc is None),
        )
        r["has_frozen_contract"] = fc is not None
        results.append(r)
        print(
            f"[acquisition] done {entity}: eligible={r.get('eligible')} "
            f"contract_satisfied={r.get('contract_satisfied')} "
            f"fault={r.get('fault_localization')} steps={r.get('acquisition_steps')} "
            f"stop={r.get('stop_reason')}"
            + (f" trace={r.get('trace_dir')}" if r.get("trace_dir") else ""),
            flush=True,
        )

    pos = [r for r in results if r.get("expected_eligible") is True and r.get("ok")]
    pos_ok = sum(1 for r in pos if r.get("eligible"))
    faults: dict[str, int] = {}
    for r in results:
        f = str(r.get("fault_localization") or "n/a")
        faults[f] = faults.get(f, 0) + 1

    go = True
    reasons = []
    if chat_fn is None and not any(t.get("force_click_texts") for t in targets):
        reasons.append("no LLM and no lab force clicks — structural only")
        go = all(r.get("ok") for r in results) if results else False
    elif pos and pos_ok < len(pos):
        go = False
        reasons.append(f"positives eligible {pos_ok}/{len(pos)}")
    else:
        reasons.append("batch complete")

    return {
        "schema": "live-offer-state-slice-v0",
        "n": len(results),
        "metrics": {
            "positive_n": len(pos),
            "positive_eligible_ok": pos_ok,
            "avg_acquisition_steps": (
                sum(r.get("acquisition_steps") or 0 for r in results) / len(results)
                if results
                else 0
            ),
        },
        "fault_counts": faults,
        "go_no_go": {"go": go, "reasons": reasons},
        "results": results,
        "task_text": task_text,
        "trace_root": trace_root,
    }
