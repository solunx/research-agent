"""
Offline research pipeline v0 — staged chain without live agent.

  observations (literal + channel)
       ↓
  CANDIDATE_UNIT (LLM)     — incomplete OK; task = relevance filter
       ↓
  INTERPRETATION (LLM)     — candidate_claim only; search_context excluded
       ↓
  ELIGIBILITY (CODE)       — AND over required outcomes; UNKNOWN fail-closed

Hard rules
----------
- No domain phrase lists in code for board/hotel/CTA.
- Channel filter is structural (provenance), not semantic classification.
- Each LLM call uses a fresh messages list (caller supplies chat_fn).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse, unquote

from interpretation import interpret_observation, interpret_observation_multi

ChatFnDict = Callable[[list[dict[str, Any]]], dict[str, Any]]
ChatFnStr = Callable[[list[dict[str, str]]], str]

# Optional --trace-interpret: truncate large claim text; keep a short hash.
_INTERPRET_TRACE_TEXT_MAX = 400


def _source_text_for_interpret_trace(text: str) -> dict[str, Any]:
    t = text or ""
    digest = hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]
    n = len(t)
    if n <= _INTERPRET_TRACE_TEXT_MAX:
        shown = t
    else:
        shown = t[:_INTERPRET_TRACE_TEXT_MAX] + f"…[+{n - _INTERPRET_TRACE_TEXT_MAX} chars]"
    return {
        "source_text": shown,
        "source_text_sha256_16": digest,
        "source_text_chars": n,
    }


def _append_interpret_trace(
    sink: list[dict[str, Any]] | None,
    *,
    observation: dict[str, Any],
    decision_id: str,
    outcome: str,
    confidence: str | None,
    reason: str | None = None,
    source: str | None = None,
) -> None:
    """Side-channel per (candidate × decision) call. No-op when sink is None."""
    if sink is None:
        return
    bind = _obs_binding_fields(observation)
    rec: dict[str, Any] = {
        "candidate_id": bind.get("candidate_id"),
        "decision_id": str(decision_id),
        "outcome": outcome,
        "confidence": confidence,
        **_source_text_for_interpret_trace(str(observation.get("text") or "")),
    }
    if reason:
        rec["reason"] = reason
    if source:
        rec["source"] = source
    sink.append(rec)

# ---------------------------------------------------------------------------
# EXPERIMENT FIXTURE only — packages offline / live_offer_state_slice.
# NOT the production ontology. Real tasks must get decisions from
# task.md → contract synthesis (see docs/FRAMEWORK_BOUNDARY.md).
# Do not add vertical-specific ids here and treat them as framework.
# ---------------------------------------------------------------------------

PACKAGES_DECISIONS: list[dict[str, Any]] = [
    {
        "id": "board_type",
        "question": (
            "What meal/board arrangement is evidenced by the observed text? "
            "Choose exactly one outcome."
        ),
        "outcomes": [
            "ALL_INCLUSIVE",
            "ROOM_ONLY",
            "BREAKFAST",
            "FULL_BOARD",
            "HALF_BOARD",
            "UNKNOWN",
        ],
        "definitions": {
            "ALL_INCLUSIVE": "Meals and typically drinks included.",
            "ROOM_ONLY": "Accommodation without meals (board plan, not occupancy).",
            "BREAKFAST": "Only breakfast included.",
            "FULL_BOARD": "Breakfast, lunch and dinner included.",
            "HALF_BOARD": "Breakfast and one other main meal.",
            "UNKNOWN": "Insufficient or ambiguous evidence.",
        },
        "notes": [
            "ROOM_ONLY is a meal plan, NOT room occupancy ('single room' alone → UNKNOWN).",
            "Do not infer board from search URL parameters; those are not in this text.",
        ],
        "allowed_channels": ["candidate_claim"],
        "required_for_eligibility": ["ALL_INCLUSIVE"],
    },
    {
        "id": "package_includes_flight",
        "question": (
            "Does the text evidence that a flight is included in the package? "
            "Choose exactly one outcome."
        ),
        "outcomes": ["FLIGHT_INCLUDED", "HOTEL_ONLY", "UNKNOWN"],
        "definitions": {
            "FLIGHT_INCLUDED": "Outbound/return or package flight is included.",
            "HOTEL_ONLY": "Explicitly accommodation only / own transport.",
            "UNKNOWN": "Insufficient evidence.",
        },
        "notes": [
            "Phrases like 'vlucht inbegrepen' or 'Heen- en terugvluchten' support FLIGHT_INCLUDED.",
            "Do not invent flight from hotel name alone.",
        ],
        "allowed_channels": ["candidate_claim"],
        "required_for_eligibility": ["FLIGHT_INCLUDED"],
    },
]

PACKAGES_TASK_TEXT = (
    "Find all-inclusive (or volpension) flight+hotel packages for 3 adults, "
    "departing Brussels (BRU/CRL), December 2026, with visible price and board type "
    "on the offer card."
)

# ---------------------------------------------------------------------------
# Observation packaging from fixture rows (no semantics)
# ---------------------------------------------------------------------------

_BOARDISH = re.compile(
    r"(all[-\s]?inclusive|volpension|enkel\s+kamer|room\s+only|ontbijt|breakfast|"
    r"half.?pension|full\s+board|half\s+board)",
    re.I,
)
_FLIGHTISH = re.compile(
    r"(vlucht|flight|heen-?\s*en\s*terug|retour|brussels|bru)",
    re.I,
)


def _split_raw(raw: str) -> list[str]:
    parts = re.split(r"\s*\|\s*", raw or "")
    return [p.strip() for p in parts if p and p.strip()]


def _meal_from_url(url: str) -> str | None:
    if not url:
        return None
    try:
        q = parse_qs(urlparse(url).query)
        for k, vals in q.items():
            if k.lower() in ("meal", "board", "catering"):
                return f"{k}={vals[0]}" if vals else k
    except Exception:
        return None
    return None


def observations_from_fixture_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Literal observations only. No outcome fields.
    Channels: candidate_claim | search_context | navigation
    """
    cid = str(row.get("entity") or row.get("candidate_id") or "unknown")
    raw = str(row.get("raw_evidence") or "")
    url = str(row.get("source_url") or row.get("page_url") or "")
    value = str(row.get("value") or "")
    obs: list[dict[str, Any]] = []

    # Identity + price as claims
    obs.append(
        {
            "candidate_id": cid,
            "text": cid,
            "channel": "candidate_claim",
            "scope": "card",
            "provenance": "fixture.entity",
        }
    )
    if value:
        obs.append(
            {
                "candidate_id": cid,
                "text": value,
                "channel": "candidate_claim",
                "scope": "card",
                "provenance": "fixture.value",
            }
        )
    for seg in _split_raw(raw):
        obs.append(
            {
                "candidate_id": cid,
                "text": seg,
                "channel": "candidate_claim",
                "scope": "card",
                "provenance": "fixture.raw_evidence",
            }
        )
    meal = _meal_from_url(url)
    if meal:
        obs.append(
            {
                "candidate_id": cid,
                "text": meal,
                "channel": "search_context",
                "scope": "url_query",
                "provenance": "fixture.source_url",
            }
        )
    if url:
        obs.append(
            {
                "candidate_id": cid,
                "text": url[:200],
                "channel": "navigation",
                "scope": "url",
                "provenance": "fixture.source_url",
            }
        )
    return obs


def load_packages_fixture(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Stage: CANDIDATE_UNIT
# ---------------------------------------------------------------------------

_CU_SYSTEM = """You are a candidate-unit selector for a research agent.

Decide only one of:
  ADMISSIBLE | NOT_ADMISSIBLE | UNKNOWN

Question (CANDIDATE_UNIT):
  Could this fragment/cluster be a meaningful evidence unit relevant to the USER TASK?
  Incomplete is OK — a named fragment can be ADMISSIBLE even without every supporting
  field present on this unit.

Rules:
- ADMISSIBLE = plausible primary content for the task (named fragment with supporting evidence).
- NOT_ADMISSIBLE = pure UI chrome, navigation chrome, empty marketing without substance, or clearly off-topic.
- UNKNOWN = insufficient information.
- Use ONLY the payload. Do not invent facts.
- Reply JSON only:
  {"decision":"ADMISSIBLE|NOT_ADMISSIBLE|UNKNOWN","reason":"...","confidence":"low|medium|high"}
"""


def _parse_cu(raw: str) -> tuple[str, str, str]:
    text = (raw or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return "UNKNOWN", "unparseable", "low"
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return "UNKNOWN", "invalid JSON", "low"
    d = str(obj.get("decision") or "UNKNOWN").upper()
    if d not in ("ADMISSIBLE", "NOT_ADMISSIBLE", "UNKNOWN"):
        d = "UNKNOWN"
    conf = str(obj.get("confidence") or "medium").lower()
    if conf not in ("low", "medium", "high"):
        conf = "medium"
    return d, str(obj.get("reason") or "")[:400], conf


def run_candidate_unit(
    *,
    candidate_id: str,
    observations: list[dict[str, Any]],
    task_text: str,
    chat_fn: ChatFnStr | None,
) -> dict[str, Any]:
    claims = [o["text"] for o in observations if o.get("channel") == "candidate_claim"]
    neighbors = claims[1:8]
    payload = {
        "decision_mode": "CANDIDATE_UNIT",
        "task": task_text,
        "unit_text": candidate_id,
        "neighbors": neighbors,
        "structure": {"element_type": "offer_or_entity"},
    }
    if chat_fn is None:
        return {
            "decision": "UNKNOWN",
            "reason": "no chat_fn; fail-closed UNKNOWN",
            "confidence": "low",
            "llm_calls": 0,
            "admitted": False,  # fail-closed: do not interpret without LLM
        }
    messages = [
        {"role": "system", "content": _CU_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        raw = chat_fn(messages)
        decision, reason, conf = _parse_cu(raw)
    except Exception as e:  # noqa: BLE001
        decision, reason, conf = "UNKNOWN", f"llm_error: {e}", "low"
    return {
        "decision": decision,
        "reason": reason,
        "confidence": conf,
        "llm_calls": 1,
        "admitted": decision == "ADMISSIBLE",
    }


# ---------------------------------------------------------------------------
# Stage: INTERPRETATION + ELIGIBILITY
# ---------------------------------------------------------------------------

def channel_allowed(decision: dict[str, Any], channel: str) -> bool:
    allowed = decision.get("allowed_channels")
    if not allowed:
        return True
    return channel in allowed


def _row_block_index(r: dict[str, Any]) -> int | None:
    v = r.get("block_index")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _row_item_href(r: dict[str, Any]) -> str:
    href = r.get("item_link_href")
    if href:
        return str(href).strip()
    link = r.get("item_link") or {}
    if isinstance(link, dict):
        return str(link.get("href") or "").strip()
    return ""


def subject_candidate_ref_from_rows(per_text: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    From subject_instance per_text rows, pick the best confirming row and
    return structural anchors (candidate_id, block_index, item_link_href, scope).
    """
    confirmed = [
        r
        for r in per_text
        if r.get("outcome")
        and str(r.get("outcome")) not in ("UNKNOWN", "MISMATCH", "NOT_FOUND", "")
        and not r.get("skipped")
        and not r.get("provenance_blocked")
    ]
    if not confirmed:
        return None
    # Prefer high confidence, then earlier list order
    for conf in ("high", "medium", "low"):
        for r in confirmed:
            if r.get("confidence") == conf:
                return {
                    "candidate_id": str(r.get("candidate_id") or "") or None,
                    "block_index": _row_block_index(r),
                    "item_link_href": _row_item_href(r) or None,
                    "scope": str(r.get("scope") or "") or None,
                }
    r = confirmed[0]
    return {
        "candidate_id": str(r.get("candidate_id") or "") or None,
        "block_index": _row_block_index(r),
        "item_link_href": _row_item_href(r) or None,
        "scope": str(r.get("scope") or "") or None,
    }


def _is_subject_bound(
    row: dict[str, Any],
    subject_ref: dict[str, Any] | None,
    *,
    block_cluster_k: int = 8,
) -> bool:
    """
    Structural binding only (Open #22): same candidate_id, nearby block_index,
    or same item_link href target. No domain lexicon.
    """
    if not subject_ref:
        return False
    cid = str(row.get("candidate_id") or "")
    s_cid = str(subject_ref.get("candidate_id") or "")
    if cid and s_cid and cid == s_cid:
        return True
    r_bi = _row_block_index(row)
    s_bi = subject_ref.get("block_index")
    if r_bi is not None and s_bi is not None:
        try:
            if abs(int(r_bi) - int(s_bi)) <= block_cluster_k:
                return True
        except (TypeError, ValueError):
            pass
    # Title/page_identity anchor (no unit block_index): bind only candidates
    # whose block_index is near the earliest observed content blocks.
    # Implemented via caller passing subject_ref with block_index=None and
    # optional "earliest_block_index" from the batch.
    earliest = subject_ref.get("earliest_block_index")
    if (
        s_bi is None
        and r_bi is not None
        and earliest is not None
        and str(subject_ref.get("scope") or "") in ("page_title", "page_identity", "")
    ):
        try:
            if int(r_bi) <= int(earliest) + block_cluster_k:
                return True
        except (TypeError, ValueError):
            pass
    r_href = _row_item_href(row)
    s_href = str(subject_ref.get("item_link_href") or "").strip()
    if r_href and s_href and r_href == s_href:
        return True
    return False


def aggregate_outcome(
    per_text: list[dict[str, Any]],
    *,
    preferred_outcomes: list[str] | set[str] | None = None,
    subject_candidate_ref: dict[str, Any] | None = None,
    require_subject_binding: bool = False,
) -> str:
    """
    Combine per-claim interpretation rows into one outcome for a decision.

    Confidence order is high > medium > low, but when *preferred_outcomes*
    is provided (typically decision.required_for_eligibility / sufficiency
    allowed set), a contract-satisfying label always outranks an absence /
    non-satisfying label — even if the absence row has higher confidence.

    Rationale (Open #19 follow-up, run 20260908T081349Z task 06): a high-
    confidence NOT_STATED on an irrelevant candidate must not erase
    FIGURE_FOUND on another candidate that actually answers the contract.

    Entity binding (Open #22, fase_d_binding 20260915T073132Z): when
    *require_subject_binding* is True and *subject_candidate_ref* is set,
    only rows structurally bound to the subject-confirming candidate are
    eligible. Unbound non-UNKNOWN rows (e.g. carousel board for another
    property) do **not** count — fail-closed to UNKNOWN if no bound answer.
    Domain-free: candidate_id / block_index / item_link only.
    """
    eligible_rows = [
        r
        for r in per_text
        if r.get("outcome")
        and r["outcome"] != "UNKNOWN"
        and not r.get("skipped")
        and not r.get("provenance_blocked")
    ]
    if not eligible_rows:
        return "UNKNOWN"

    if require_subject_binding and subject_candidate_ref is not None:
        bound = [r for r in eligible_rows if _is_subject_bound(r, subject_candidate_ref)]
        if bound:
            eligible_rows = bound
        else:
            # Cross-entity-only answers → fail closed (do not use Abora for Monica).
            return "UNKNOWN"

    pref_set = {str(x) for x in (preferred_outcomes or []) if x and str(x) != "UNKNOWN"}
    pool = eligible_rows
    if pref_set:
        satisfying = [r for r in eligible_rows if str(r.get("outcome")) in pref_set]
        if satisfying:
            pool = satisfying

    for conf in ("high", "medium", "low"):
        for r in pool:
            if r.get("confidence") == conf:
                return str(r["outcome"])
    return str(pool[0]["outcome"])


def _obs_surface(o: dict[str, Any]) -> str:
    prov = o.get("provenance") or {}
    if isinstance(prov, dict):
        return str(prov.get("surface") or "")
    return ""


def _obs_same_entity(o: dict[str, Any]) -> bool | None:
    prov = o.get("provenance") or {}
    if isinstance(prov, dict) and "same_entity_path" in prov:
        return bool(prov.get("same_entity_path"))
    return None


def _obs_binding_fields(o: dict[str, Any]) -> dict[str, Any]:
    """Structural fields copied onto interpretation rows for Open #22 binding."""
    prov = o.get("provenance") or {}
    bi = o.get("block_index")
    if bi is None and isinstance(prov, dict):
        bi = prov.get("block_index")
    link = o.get("item_link") if isinstance(o.get("item_link"), dict) else None
    href = ""
    if link:
        href = str(link.get("href") or "").strip()
    if not href and isinstance(prov, dict):
        href = str(prov.get("item_link_href") or "").strip()
    return {
        "candidate_id": str(o.get("candidate_id") or "") or None,
        "block_index": bi,
        "item_link": link,
        "item_link_href": href or None,
        "scope": str(o.get("scope") or "") or None,
    }


def _earliest_block_index(rows: list[dict[str, Any]]) -> int | None:
    bis = []
    for r in rows:
        bi = _row_block_index(r)
        if bi is not None:
            bis.append(bi)
    return min(bis) if bis else None


def _finalize_outcomes_with_binding(
    texts_by_did: dict[str, list[dict[str, Any]]],
    decisions: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any] | None]:
    """
    Two-pass aggregate: subject_instance without binding → ref → other decisions
    with require_subject_binding when a subject ref exists.
    """
    outcomes: dict[str, str] = {}
    traces: dict[str, Any] = {}
    subject_ref: dict[str, Any] | None = None

    # Pass 1: subject_instance (if present)
    if "subject_instance" in texts_by_did:
        rows = texts_by_did["subject_instance"]
        active = [r for r in rows if not r.get("skipped") and not r.get("provenance_blocked")]
        preferred = []
        for d in decisions:
            if d.get("id") == "subject_instance":
                preferred = list(d.get("required_for_eligibility") or [])
                break
        outcomes["subject_instance"] = aggregate_outcome(
            active, preferred_outcomes=preferred, require_subject_binding=False
        )
        subject_ref = subject_candidate_ref_from_rows(active)
        if subject_ref is not None:
            earliest = _earliest_block_index(
                [r for rows in texts_by_did.values() for r in rows]
            )
            if earliest is not None:
                subject_ref = {**subject_ref, "earliest_block_index": earliest}
        traces["subject_instance"] = {
            "per_text": rows,
            "aggregated": outcomes["subject_instance"],
            "preferred_outcomes": preferred,
            "subject_candidate_ref": subject_ref,
            "require_subject_binding": False,
        }

    # Pass 2: all other decisions
    for d in decisions:
        did = str(d.get("id") or "")
        if not did or did == "subject_instance":
            continue
        rows = texts_by_did.get(did) or []
        active = [r for r in rows if not r.get("skipped") and not r.get("provenance_blocked")]
        preferred = list(d.get("required_for_eligibility") or [])
        bind = subject_ref is not None
        outcomes[did] = aggregate_outcome(
            active,
            preferred_outcomes=preferred,
            subject_candidate_ref=subject_ref,
            require_subject_binding=bind,
        )
        traces[did] = {
            "per_text": rows,
            "aggregated": outcomes[did],
            "preferred_outcomes": preferred,
            "subject_candidate_ref": subject_ref,
            "require_subject_binding": bind,
        }

    # Decisions that never appeared in texts_by_did
    for d in decisions:
        did = str(d.get("id") or "")
        if did and did not in outcomes:
            outcomes[did] = "UNKNOWN"
            traces[did] = {
                "per_text": [],
                "aggregated": "UNKNOWN",
                "preferred_outcomes": list(d.get("required_for_eligibility") or []),
                "subject_candidate_ref": subject_ref,
                "require_subject_binding": subject_ref is not None and did != "subject_instance",
            }
    return outcomes, traces, subject_ref


def is_provenance_blocked_for_entity(o: dict[str, Any]) -> bool:
    """
    Hard guard: pure marketing / site-wide chrome cannot prove contract outcomes.

    Generic — no site-specific paths. Tagging happens upstream in the slice.

    Design note (2026-08-28):
    - Block surfaces that are explicitly marketing/chrome.
    - Do NOT hard-block solely on same_entity_path=False.
      When a task starts at a site root (or abstract entity like "one concrete
      bookable"), navigation to a list/results page always yields
      same_entity_path=False; those pages still contain admissible offer-bound
      evidence. Binding is expressed by surface tags (list_results /
      live_offer_state / live_detail), not by URL-path equality to start_url.
    """
    surface = _obs_surface(o)
    if surface in ("site_marketing", "site_wide", "global_marketing", "page_chrome"):
        return True
    return False


def eligibility_from_outcomes(
    outcomes: dict[str, str], decisions: list[dict[str, Any]]
) -> dict[str, Any]:
    details = []
    ok = True
    for d in decisions:
        did = d["id"]
        required = d.get("required_for_eligibility") or []
        observed = outcomes.get(did, "UNKNOWN")
        if not required:
            details.append({"decision_id": did, "result": "SKIP", "observed": observed})
            continue
        if observed == "UNKNOWN":
            ok = False
            details.append(
                {
                    "decision_id": did,
                    "result": "UNKNOWN",
                    "observed": observed,
                    "allowed": required,
                }
            )
        elif observed in required:
            details.append(
                {
                    "decision_id": did,
                    "result": "PASS",
                    "observed": observed,
                    "allowed": required,
                }
            )
        else:
            ok = False
            details.append(
                {
                    "decision_id": did,
                    "result": "FAIL",
                    "observed": observed,
                    "allowed": required,
                }
            )
    return {"eligible": ok, "details": details}


def _adapt_chat_fn(chat_fn: ChatFnStr | None) -> ChatFnDict | None:
    """interpretation.interpret_observation expects dict-returning chat_fn."""
    if chat_fn is None:
        return None

    def _fn(messages: list[dict[str, Any]]) -> dict[str, Any]:
        # Normalize to role/content strings
        norm = [{"role": m["role"], "content": m["content"]} for m in messages]
        content = chat_fn(norm)
        return {"content": content}

    return _fn


def _claim_priority(text: str, decision_id: str = "", *, list_index: int = 0) -> int:
    """
    Lower = interpret first.

    MOVE #11 (LOCKED): no decision_id-specific lexicon (board_type / flight /
    travel phrases). Stable order is FIFO on the original observation list
    (`list_index`). Optional domain-free length bias only: slightly prefer
    shorter snippets (cheaper LLM context), never regex on content words.
    """
    _ = decision_id  # call-site compat; unused — no lexicon boost
    t = text or ""
    # Base = list position (FIFO). index*10 dominates length nudge (±2).
    score = int(list_index) * 10
    if len(t) < 120:
        score -= 2
    return score


def run_interpretation(
    *,
    observations: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    chat_fn: ChatFnStr | None,
    max_llm_per_decision: int = 8,
    early_stop_on_high: bool = True,
    batch_decisions: bool = False,
    interpret_call_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Interpret candidate_claim observations against contract decisions.

    Default path (batch_decisions=False): one LLM call per (claim × decision)
    via interpret_observation — restored after live task-02 regression
    (board_type stuck UNKNOWN under multi-decision batch, 2026-09-14).

    Optional path (batch_decisions=True, Fase B): one LLM call per claim for
    ALL decisions (interpret_observation_multi). Available explicitly for
    experiments; not default until live parity on 02/06 is restored.

    Hard provenance: observations tagged site_marketing / site_wide /
    global_marketing / page_chrome are never sent to the LLM for contract
    outcomes and cannot contribute PASS.

    Cost control: claims ordered FIFO (#11); after max_llm_per_decision
    *claims* (batch) or *calls per decision* (legacy), or when every
    decision already has a high-confidence satisfying outcome, remaining
    claims are skipped. Fase A skip-satisfied (acquisition loop) is
    independent of this flag.

    interpret_call_trace: optional list filled with per-call records
    (candidate_id, decision_id, truncated source_text, outcome,
    confidence). Default None — no extra work, return dict unchanged.
    Callers write this to step_NNN_interpret_trace.json; never to
    events.jsonl.
    """
    if not batch_decisions:
        return _run_interpretation_legacy(
            observations=observations,
            decisions=decisions,
            chat_fn=chat_fn,
            max_llm_per_decision=max_llm_per_decision,
            early_stop_on_high=early_stop_on_high,
            interpret_call_trace=interpret_call_trace,
        )

    chat_dict = _adapt_chat_fn(chat_fn)
    search_ctx = [o for o in observations if o.get("channel") == "search_context"]
    provenance_blocked_n = 0
    llm_calls = 0

    # Per-decision row lists (filled as we process claims once).
    texts_by_did: dict[str, list[dict[str, Any]]] = {str(d["id"]): [] for d in decisions if d.get("id")}
    required_by_did: dict[str, set[str]] = {
        str(d["id"]): set(d.get("required_for_eligibility") or [])
        for d in decisions
        if d.get("id")
    }
    found_high_by_did: dict[str, bool] = {did: False for did in texts_by_did}

    # Build ordered claim list once (union of channel-allowed + not blocked).
    # A claim is kept if it is allowed for *any* decision and not provenance-blocked.
    ordered: list[dict[str, Any]] = []
    blocked_or_skipped_global: list[dict[str, Any]] = []
    for idx, o in enumerate(observations):
        ch = o.get("channel") or ""
        any_allowed = any(channel_allowed(d, ch) for d in decisions)
        if not any_allowed:
            blocked_or_skipped_global.append(
                {
                    "text": o.get("text"),
                    "channel": ch,
                    "skipped": True,
                    "reason": "channel_not_allowed",
                    "outcome": "UNKNOWN",
                }
            )
            continue
        if is_provenance_blocked_for_entity(o):
            provenance_blocked_n += 1
            blocked_or_skipped_global.append(
                {
                    "text": o.get("text"),
                    "channel": ch,
                    "skipped": True,
                    "reason": "provenance_blocked_site_marketing",
                    "outcome": "UNKNOWN",
                    "provenance_blocked": True,
                    "surface": _obs_surface(o),
                }
            )
            continue
        ordered.append({**o, "_obs_index": idx})

    ordered.sort(
        key=lambda o: _claim_priority(
            str(o.get("text") or ""),
            "",
            list_index=int(o.get("_obs_index") or 0),
        )
    )

    # Seed each decision's trace with global channel/provenance skips.
    for did in texts_by_did:
        texts_by_did[did].extend(dict(r) for r in blocked_or_skipped_global)

    claims_interpreted = 0
    for o in ordered:
        # Global early-stop: every decision already has high+satisfying evidence.
        if early_stop_on_high and texts_by_did and all(found_high_by_did.values()):
            for did in texts_by_did:
                texts_by_did[did].append(
                    {
                        "text": o.get("text"),
                        "channel": o.get("channel"),
                        "skipped": True,
                        "reason": "early_stop_all_decisions_high",
                        "outcome": "UNKNOWN",
                    }
                )
            continue
        if claims_interpreted >= max_llm_per_decision and chat_dict is not None:
            for did in texts_by_did:
                texts_by_did[did].append(
                    {
                        "text": o.get("text"),
                        "channel": o.get("channel"),
                        "skipped": True,
                        "reason": "max_llm_per_decision",
                        "outcome": "UNKNOWN",
                    }
                )
            continue

        prov = o.get("provenance") or {}
        page_context = {
            "page_url": prov.get("source_url") or o.get("source_url"),
            "surface": prov.get("surface") or o.get("surface"),
        }
        if "same_entity_path" in prov:
            page_context["same_entity_path"] = prov.get("same_entity_path")
        page_context = {k: v for k, v in page_context.items() if v is not None and v != ""}

        # Only ask the model for decisions this claim's channel is allowed for.
        decisions_for_claim = [
            d
            for d in decisions
            if d.get("id") and channel_allowed(d, o.get("channel") or "")
        ]
        multi = interpret_observation_multi(
            str(o.get("text") or ""),
            decisions=decisions_for_claim or decisions,
            chat_fn=chat_dict,
            page_context=page_context or None,
        )
        if chat_dict is not None:
            llm_calls += 1
            claims_interpreted += 1

        answered_ids = {str(d["id"]) for d in (decisions_for_claim or decisions) if d.get("id")}
        for did in texts_by_did:
            if did not in answered_ids:
                texts_by_did[did].append(
                    {
                        "text": o.get("text"),
                        "channel": o.get("channel"),
                        "skipped": True,
                        "reason": "channel_not_allowed_for_decision",
                        "outcome": "UNKNOWN",
                    }
                )
                continue
            ir = multi.get(did)
            bind = _obs_binding_fields(o)
            if ir is None:
                row = {
                    "text": o.get("text"),
                    "channel": o.get("channel"),
                    "skipped": False,
                    "outcome": "UNKNOWN",
                    "confidence": "low",
                    "reason": "missing from multi result",
                    "source": "error",
                    "surface": _obs_surface(o),
                    **bind,
                }
            else:
                row = {
                    "text": o.get("text"),
                    "channel": o.get("channel"),
                    "skipped": False,
                    "outcome": ir.outcome,
                    "confidence": ir.confidence,
                    "reason": ir.reason,
                    "source": ir.source,
                    "surface": _obs_surface(o),
                    **bind,
                }
            texts_by_did[did].append(row)
            _append_interpret_trace(
                interpret_call_trace,
                observation=o,
                decision_id=str(did),
                outcome=str(row.get("outcome") or "UNKNOWN"),
                confidence=row.get("confidence"),
                reason=row.get("reason"),
                source=row.get("source"),
            )
            required = required_by_did.get(did) or set()
            if (
                early_stop_on_high
                and row.get("confidence") == "high"
                and row.get("outcome")
                and row["outcome"] != "UNKNOWN"
                and (not required or row["outcome"] in required)
            ):
                found_high_by_did[did] = True

    outcomes, traces, _subject_ref = _finalize_outcomes_with_binding(texts_by_did, decisions)
    for did, tr in traces.items():
        tr["batch_decisions"] = True
        tr["llm_calls_this_decision"] = claims_interpreted

    elig = eligibility_from_outcomes(outcomes, decisions)
    return {
        "outcomes": outcomes,
        "eligibility": elig,
        "decision_traces": traces,
        "search_context_obs": [
            {"text": o.get("text"), "channel": o.get("channel")} for o in search_ctx
        ],
        "llm_calls": llm_calls,
        "provenance_blocked_n": provenance_blocked_n,
        "batch_decisions": True,
        "claims_interpreted": claims_interpreted,
        "subject_candidate_ref": _subject_ref,
    }


def _run_interpretation_legacy(
    *,
    observations: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    chat_fn: ChatFnStr | None,
    max_llm_per_decision: int = 8,
    early_stop_on_high: bool = True,
    interpret_call_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pre-Fase-B path: one LLM call per (claim × decision). For parity tests."""
    chat_dict = _adapt_chat_fn(chat_fn)
    llm_calls = 0
    provenance_blocked_n = 0
    search_ctx = [o for o in observations if o.get("channel") == "search_context"]
    texts_by_did: dict[str, list[dict[str, Any]]] = {
        str(d["id"]): [] for d in decisions if d.get("id")
    }
    calls_by_did: dict[str, int] = {did: 0 for did in texts_by_did}

    for d in decisions:
        did = d["id"]
        texts: list[dict[str, Any]] = texts_by_did[did]
        required = set(d.get("required_for_eligibility") or [])

        ordered: list[dict[str, Any]] = []
        for idx, o in enumerate(observations):
            ch = o.get("channel") or ""
            if not channel_allowed(d, ch):
                texts.append(
                    {
                        "text": o.get("text"),
                        "channel": ch,
                        "skipped": True,
                        "reason": "channel_not_allowed",
                        "outcome": "UNKNOWN",
                    }
                )
                continue
            if is_provenance_blocked_for_entity(o):
                provenance_blocked_n += 1
                texts.append(
                    {
                        "text": o.get("text"),
                        "channel": ch,
                        "skipped": True,
                        "reason": "provenance_blocked_site_marketing",
                        "outcome": "UNKNOWN",
                        "provenance_blocked": True,
                        "surface": _obs_surface(o),
                    }
                )
                continue
            ordered.append({**o, "_obs_index": idx})

        ordered.sort(
            key=lambda o: _claim_priority(
                str(o.get("text") or ""),
                did,
                list_index=int(o.get("_obs_index") or 0),
            )
        )

        found_high = False
        calls_this = 0
        for o in ordered:
            if found_high and early_stop_on_high:
                texts.append(
                    {
                        "text": o.get("text"),
                        "channel": o.get("channel"),
                        "skipped": True,
                        "reason": "early_stop_high_confidence",
                        "outcome": "UNKNOWN",
                    }
                )
                continue
            if calls_this >= max_llm_per_decision and chat_dict is not None:
                texts.append(
                    {
                        "text": o.get("text"),
                        "channel": o.get("channel"),
                        "skipped": True,
                        "reason": "max_llm_per_decision",
                        "outcome": "UNKNOWN",
                    }
                )
                continue

            prov = o.get("provenance") or {}
            page_context = {
                "page_url": prov.get("source_url") or o.get("source_url"),
                "surface": prov.get("surface") or o.get("surface"),
            }
            if "same_entity_path" in prov:
                page_context["same_entity_path"] = prov.get("same_entity_path")
            page_context = {k: v for k, v in page_context.items() if v is not None and v != ""}
            ir = interpret_observation(
                str(o.get("text") or ""),
                contract_decision=d,
                chat_fn=chat_dict,
                page_context=page_context or None,
            )
            if chat_dict is not None:
                llm_calls += 1
                calls_this += 1
            bind = _obs_binding_fields(o)
            row = {
                "text": o.get("text"),
                "channel": o.get("channel"),
                "skipped": False,
                "outcome": ir.outcome,
                "confidence": ir.confidence,
                "reason": ir.reason,
                "source": ir.source,
                "surface": _obs_surface(o),
                **bind,
            }
            texts.append(row)
            _append_interpret_trace(
                interpret_call_trace,
                observation=o,
                decision_id=str(did),
                outcome=str(ir.outcome),
                confidence=ir.confidence,
                reason=ir.reason,
                source=ir.source,
            )
            if (
                early_stop_on_high
                and ir.confidence == "high"
                and ir.outcome
                and ir.outcome != "UNKNOWN"
                and (not required or ir.outcome in required)
            ):
                found_high = True

        calls_by_did[did] = calls_this

    outcomes, traces, _subject_ref = _finalize_outcomes_with_binding(texts_by_did, decisions)
    for did, tr in traces.items():
        tr["batch_decisions"] = False
        tr["llm_calls_this_decision"] = calls_by_did.get(did, 0)

    elig = eligibility_from_outcomes(outcomes, decisions)
    return {
        "outcomes": outcomes,
        "eligibility": elig,
        "decision_traces": traces,
        "search_context_obs": [
            {"text": o.get("text"), "channel": o.get("channel")} for o in search_ctx
        ],
        "llm_calls": llm_calls,
        "provenance_blocked_n": provenance_blocked_n,
        "batch_decisions": False,
        "subject_candidate_ref": _subject_ref,
    }


# ---------------------------------------------------------------------------
# Full pipeline for one candidate
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    candidate_id: str
    expected_eligible: bool | None
    expected_role: str | None
    candidate_stage: dict[str, Any]
    interpretation_stage: dict[str, Any] | None
    eligible: bool
    skipped_interpretation: bool
    llm_calls: int
    safety: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_pipeline_one(
    row: dict[str, Any],
    *,
    chat_fn: ChatFnStr | None,
    task_text: str = PACKAGES_TASK_TEXT,
    decisions: list[dict[str, Any]] | None = None,
    require_candidate_admit: bool = True,
) -> PipelineResult:
    """
    If require_candidate_admit and CU does not admit → skip interpretation,
    eligible=False (fail-closed).

    ISOLATE #16: PACKAGES_DECISIONS is not a silent default. Callers must pass
    decisions=... explicitly (or this raises). Offline experiment scripts that
    historically relied on the packages fixture must pass PACKAGES_DECISIONS
    themselves.
    """
    if decisions is None:
        raise RuntimeError(
            "run_pipeline_one: decisions is required. Pass an explicit decision "
            "list (e.g. PACKAGES_DECISIONS for lab fixtures). Silent fallback "
            "disabled (FRAMEWORK_BOUNDARY ISOLATE #16)."
        )
    cid = str(row.get("entity") or row.get("candidate_id") or "unknown")
    expected_elig = row.get("expected_eligible")
    if expected_elig is not None:
        expected_elig = bool(expected_elig)
    expected_role = row.get("expected_role")
    obs = observations_from_fixture_row(row)

    cu = run_candidate_unit(
        candidate_id=cid,
        observations=obs,
        task_text=task_text,
        chat_fn=chat_fn,
    )
    llm_calls = int(cu.get("llm_calls") or 0)

    # Safety: meal= in search_context must never be the only path to AI
    search_texts = [
        o["text"] for o in obs if o.get("channel") == "search_context"
    ]
    claim_texts = [
        o["text"] for o in obs if o.get("channel") == "candidate_claim"
    ]

    if require_candidate_admit and not cu.get("admitted"):
        return PipelineResult(
            candidate_id=cid,
            expected_eligible=expected_elig,
            expected_role=str(expected_role) if expected_role else None,
            candidate_stage=cu,
            interpretation_stage=None,
            eligible=False,
            skipped_interpretation=True,
            llm_calls=llm_calls,
            safety={
                "search_context_present": bool(search_texts),
                "search_context_texts": search_texts,
                "candidate_claim_n": len(claim_texts),
            },
        )

    interp = run_interpretation(
        observations=obs, decisions=decisions, chat_fn=chat_fn
    )
    llm_calls += int(interp.get("llm_calls") or 0)

    # Safety check: board outcome must not come only from search_context traces
    board_trace = (interp.get("decision_traces") or {}).get("board_type") or {}
    board_from_search_only = False
    per = board_trace.get("per_text") or []
    active_board = [t for t in per if not t.get("skipped") and t.get("outcome") not in (None, "UNKNOWN")]
    if active_board and all(t.get("channel") == "search_context" for t in active_board):
        board_from_search_only = True

    return PipelineResult(
        candidate_id=cid,
        expected_eligible=expected_elig,
        expected_role=str(expected_role) if expected_role else None,
        candidate_stage=cu,
        interpretation_stage=interp,
        eligible=bool((interp.get("eligibility") or {}).get("eligible")),
        skipped_interpretation=False,
        llm_calls=llm_calls,
        safety={
            "search_context_present": bool(search_texts),
            "search_context_texts": search_texts,
            "candidate_claim_n": len(claim_texts),
            "board_from_search_context_only": board_from_search_only,
            "outcomes": interp.get("outcomes"),
        },
    )


def score_pipeline_batch(results: list[PipelineResult]) -> dict[str, Any]:
    n = len(results)
    with_exp = [r for r in results if r.expected_eligible is not None]
    match = sum(
        1 for r in with_exp if bool(r.eligible) == bool(r.expected_eligible)
    )
    positives = [r for r in with_exp if r.expected_eligible is True]
    negatives = [r for r in with_exp if r.expected_eligible is False]
    pos_ok = sum(1 for r in positives if r.eligible)
    neg_ok = sum(1 for r in negatives if not r.eligible)

    search_leak = sum(
        1
        for r in results
        if (r.safety or {}).get("board_from_search_context_only")
    )
    # Cross-talk heuristic: positive outcomes should not appear on pure marketing roles
    marketing_ai = 0
    for r in results:
        if (r.expected_role or "") in ("marketing",) and r.eligible:
            marketing_ai += 1

    eligibility_match_rate = (match / len(with_exp)) if with_exp else None
    return {
        "n": n,
        "n_with_expected": len(with_exp),
        "eligibility_match": match,
        "eligibility_match_rate": eligibility_match_rate,
        "positive_n": len(positives),
        "positive_eligible_ok": pos_ok,
        "negative_n": len(negatives),
        "negative_not_eligible_ok": neg_ok,
        "search_context_board_leaks": search_leak,
        "marketing_eligible_count": marketing_ai,
        "llm_calls_total": sum(r.llm_calls for r in results),
    }


def go_no_go(
    metrics: dict[str, Any],
    *,
    llm_enabled: bool,
    require_oracle: bool = False,
    n_candidates: int = 0,
) -> dict[str, Any]:
    reasons = []
    ok = True
    if require_oracle and metrics.get("n_with_expected", 0) == 0 and n_candidates > 0:
        ok = False
        reasons.append("missing oracle labels (n_with_expected=0) — experiment invalid")
    if metrics.get("search_context_board_leaks", 0) > 0:
        ok = False
        reasons.append("search_context leaked into board outcome")
    if metrics.get("marketing_eligible_count", 0) > 0:
        ok = False
        reasons.append("marketing entity marked eligible")
    if llm_enabled:
        if metrics.get("positive_n", 0) > 0 and metrics.get("positive_eligible_ok", 0) < metrics["positive_n"]:
            ok = False
            reasons.append("not all expected positives eligible")
        if metrics.get("negative_n", 0) > 0 and metrics.get("negative_not_eligible_ok", 0) < metrics["negative_n"]:
            ok = False
            reasons.append("some expected negatives were eligible")
        if (metrics.get("eligibility_match_rate") or 0) < 0.9 and metrics.get("n_with_expected", 0) >= 3:
            ok = False
            reasons.append(
                f"eligibility_match_rate={metrics.get('eligibility_match_rate')} < 0.9"
            )
    else:
        reasons.append("offline dry-run (UNKNOWN path); structural safety only")
        if metrics.get("search_context_board_leaks", 0) > 0:
            ok = False
        elif ok:
            reasons.append("no search_context board leak")
    if ok and not any(r.startswith("all GO") or "structural safety" in r or "no search_context" in r for r in reasons):
        if ok:
            reasons.append("all GO criteria met")
    elif ok and not reasons:
        reasons.append("all GO criteria met")
    return {"go": ok, "reasons": reasons}
