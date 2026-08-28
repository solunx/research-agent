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

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse, unquote

from interpretation import interpret_observation

ChatFnDict = Callable[[list[dict[str, Any]]], dict[str, Any]]
ChatFnStr = Callable[[list[dict[str, str]]], str]

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
  Incomplete is OK — a hotel name can be ADMISSIBLE even without price/board/dates on this unit.

Rules:
- ADMISSIBLE = plausible primary content (offer card, hotel name, package fragment).
- NOT_ADMISSIBLE = pure UI chrome, navigation, marketing slogan without offer substance, or clearly off-topic.
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


def aggregate_outcome(per_text: list[dict[str, Any]]) -> str:
    # Hard provenance: site_marketing / cross-entity evidence may never
    # contribute a PASS-grade outcome for entity-level decisions.
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
    for pref in ("high", "medium", "low"):
        for r in eligible_rows:
            if r.get("confidence") == pref:
                return str(r["outcome"])
    return str(eligible_rows[0]["outcome"])


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


def is_provenance_blocked_for_entity(o: dict[str, Any]) -> bool:
    """
    Hard guard: marketing / left-entity surfaces cannot prove entity outcomes.
    Generic — no site-specific paths. Tagging happens upstream in the slice.
    """
    surface = _obs_surface(o)
    if surface in ("site_marketing", "site_wide", "global_marketing"):
        return True
    same = _obs_same_entity(o)
    if same is False:
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


def _claim_priority(text: str, decision_id: str) -> int:
    """
    Lower = interpret first. Prefer lines that look relevant to the decision
    so we can early-stop and avoid 30×N LLM calls on every page.
    Structural heuristics only (regex shape), not domain outcome mapping.
    """
    t = (text or "").lower()
    score = 50
    if decision_id == "board_type":
        if re.search(
            r"all[-\s]?inclusive|volpension|half.?pension|full\s+board|"
            r"room\s+only|enkel\s+kamer|ontbijt|breakfast",
            t,
        ):
            score = 0
        elif re.search(r"verzorging|meal|board|pension|inclusive", t):
            score = 10
    elif decision_id == "package_includes_flight":
        if re.search(
            r"vlucht\s*\+|pakketreis\s+met\s+vlucht|heen-?\s*en\s*terug|"
            r"flight\s+included|vlucht\s+inbegrepen|directe\s+vlucht|"
            r"brussels\s+airlines|vluchtnummer|vertrek.*aankomst",
            t,
        ):
            score = 0
        elif re.search(r"vlucht|flight|bru\b|airport|luchthaven|airline", t):
            score = 10
        elif re.search(r"vanaf\s+brussel|fly\s*&\s*go|pakket", t):
            score = 15
    # shorter, denser claims slightly preferred
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
) -> dict[str, Any]:
    """
    Interpret candidate_claim observations per decision.

    Hard provenance: observations tagged site_marketing / same_entity_path=False
    are never sent to the LLM for entity outcomes and cannot contribute PASS.

    Cost control: claims are prioritized; after max_llm_per_decision calls or a
    high-confidence non-UNKNOWN on a required outcome, remaining claims are
    skipped (logged as early_stop). This cuts wall-time from ~12min to ~1-2min
    per page on local models without changing the contract semantics.
    """
    chat_dict = _adapt_chat_fn(chat_fn)
    outcomes: dict[str, str] = {}
    traces: dict[str, Any] = {}
    llm_calls = 0
    provenance_blocked_n = 0
    search_ctx = [o for o in observations if o.get("channel") == "search_context"]

    for d in decisions:
        did = d["id"]
        texts: list[dict[str, Any]] = []
        required = set(d.get("required_for_eligibility") or [])

        # Order: allowed-channel + not provenance-blocked, by priority
        ordered: list[dict[str, Any]] = []
        for o in observations:
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
            ordered.append(o)

        ordered.sort(
            key=lambda o: _claim_priority(str(o.get("text") or ""), did)
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

            ir = interpret_observation(
                str(o.get("text") or ""),
                contract_decision=d,
                chat_fn=chat_dict,
            )
            if chat_dict is not None:
                llm_calls += 1
                calls_this += 1
            row = {
                "text": o.get("text"),
                "channel": o.get("channel"),
                "skipped": False,
                "outcome": ir.outcome,
                "confidence": ir.confidence,
                "reason": ir.reason,
                "source": ir.source,
                "surface": _obs_surface(o),
            }
            texts.append(row)
            if (
                early_stop_on_high
                and ir.confidence == "high"
                and ir.outcome
                and ir.outcome != "UNKNOWN"
                and (not required or ir.outcome in required)
            ):
                found_high = True

        active = [t for t in texts if not t.get("skipped") and not t.get("provenance_blocked")]
        outcomes[did] = aggregate_outcome(active)
        traces[did] = {
            "per_text": texts,
            "aggregated": outcomes[did],
            "llm_calls_this_decision": calls_this,
        }

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
    """
    decisions = decisions or PACKAGES_DECISIONS
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
