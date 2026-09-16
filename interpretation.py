"""
Semantic Interpretation v0 — offline experiment.

Hypothesis
----------
Meaning belongs to the LLM; certainty belongs to code.

1. Discovery (elsewhere) freezes a contract with typed outcomes.
2. Interpretation LLM maps *raw observation text* → one contract outcome
   (or UNKNOWN). It answers: "Is this evidence for one of *these* outcomes?"
3. Generic code only compares normalized outcomes to requirements.
   It never learns that "Enkel kamer" means ROOM_ONLY.

This module is intentionally isolated from agent.py / harvest / eligibility.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

ChatFn = Callable[[list[dict[str, Any]]], dict[str, Any]]

OUTCOME_UNKNOWN = "UNKNOWN"
VALID_CONFIDENCE = frozenset({"high", "medium", "low"})


# ---------------------------------------------------------------------------
# Fixed mini-contract for the v0 experiment (not task discovery)
# ---------------------------------------------------------------------------

BOARD_TYPE_CONTRACT: dict[str, Any] = {
    "schema_version": "interpretation-v0",
    "decision": {
        "id": "board_type",
        "question": (
            "What meal/board arrangement is evidenced by the observed text? "
            "Choose exactly one outcome from the allowed list."
        ),
        "outcomes": [
            "ALL_INCLUSIVE",
            "ROOM_ONLY",
            "BREAKFAST",
            "FULL_BOARD",
            "UNKNOWN",
        ],
        "definitions": {
            "ALL_INCLUSIVE": "Meals and typically drinks included in the stay price.",
            "ROOM_ONLY": "Accommodation without meals included (board arrangement).",
            "BREAKFAST": "Only breakfast included; other meals not included.",
            "FULL_BOARD": "Breakfast, lunch and dinner included (not necessarily drinks/all-inclusive).",
            "UNKNOWN": "Insufficient or ambiguous evidence for any other outcome.",
        },
        "notes": [
            "ROOM_ONLY is a meal plan, NOT a room occupancy type.",
            "'Single room' / 'eenpersoonskamer' describes occupancy, not board → UNKNOWN unless meal plan is also stated.",
            "Do not invent board type from language alone when the text is only about room type.",
        ],
    },
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class InterpretationResult:
    source_text: str
    outcome: str
    confidence: str = "low"
    reason: str = ""
    source: str = "llm"  # llm | heuristic_stub | error
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    """Dumb code gate: normalized evidence vs required outcome(s)."""

    decision_id: str
    result: str  # PASS | FAIL | UNKNOWN
    required: list[str]
    observed_outcome: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Interpretation LLM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a semantic interpretation coprocessor for a research agent.

You receive:
- one decision from a frozen research contract (id, question, allowed outcomes, definitions)
- one raw observation string (website text snippet)

Your job: decide whether the observation is evidence for EXACTLY ONE of the allowed outcomes.

Rules:
1. Output EXACTLY one JSON object. No markdown fences, no commentary outside JSON.
2. Schema:
   {"outcome": "<one of allowed outcomes>", "confidence": "high"|"medium"|"low", "reason": "<short>", "source_text": "<echo input>"}
3. outcome MUST be one of the allowed outcomes list (including UNKNOWN).
4. Prefer UNKNOWN over guessing when the text is ambiguous or only related, not equivalent.
5. Use ONLY the definitions supplied with this decision; do not equate labels that the
   definitions treat as distinct categories.
6. Do not use outside knowledge to invent facts not supported by the snippet.
"""

# Multi-decision batch (Fase B): one observation → outcomes for ALL decisions
# in a single LLM call. Same fail-closed rules; response is a map by decision id.
SYSTEM_PROMPT_MULTI = """You are a semantic interpretation coprocessor for a research agent.

You receive:
- several decisions from a frozen research contract (each: id, question, allowed outcomes, definitions)
- one raw observation string (website text snippet)

Your job: for EACH decision independently, decide whether the observation is evidence
for EXACTLY ONE of that decision's allowed outcomes.

Rules:
1. Output EXACTLY one JSON object. No markdown fences, no commentary outside JSON.
2. Schema:
   {"outcomes": {
      "<decision_id>": {"outcome": "<one of that decision's allowed outcomes>",
                        "confidence": "high"|"medium"|"low",
                        "reason": "<short>"},
      ...
   }}
3. Include an entry for EVERY decision id supplied. Do not omit keys.
4. For each decision, outcome MUST be one of that decision's allowed outcomes list
   (including UNKNOWN if listed or when evidence is insufficient).
5. Prefer UNKNOWN over guessing when the text is ambiguous or only related, not equivalent.
6. Use ONLY the definitions supplied with each decision; do not equate labels that the
   definitions treat as distinct categories.
7. Do not use outside knowledge to invent facts not supported by the snippet.
8. Evaluate each decision independently — evidence for one decision does not force
   an outcome on another.
"""


def build_user_prompt(
    contract_decision: dict[str, Any],
    source_text: str,
    page_context: dict[str, Any] | None = None,
) -> str:
    """
    Build the user JSON payload for one observation × one decision.

    page_context (optional): structural fields only — page_url, surface,
    same_entity_path — so page-identity decisions (e.g. subject_instance)
    can see which URL was observed. No new semantics; omitted when None
    (backwards-compatible with prior call sites).
    """
    observation: dict[str, Any] = {"source_text": source_text}
    if page_context:
        for key in ("page_url", "surface", "same_entity_path"):
            if key in page_context and page_context[key] is not None:
                observation[key] = page_context[key]
    payload = {
        "decision": {
            "id": contract_decision.get("id"),
            "question": contract_decision.get("question"),
            "outcomes": contract_decision.get("outcomes"),
            "definitions": contract_decision.get("definitions") or {},
            "notes": contract_decision.get("notes") or [],
        },
        "observation": observation,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_user_prompt_multi(
    decisions: list[dict[str, Any]],
    source_text: str,
    page_context: dict[str, Any] | None = None,
) -> str:
    """
    Build user payload for one observation × many decisions (Fase B).

    Same observation / page_context shape as build_user_prompt; decisions is a
    list of full decision objects (id, question, outcomes, definitions, notes).
    """
    observation: dict[str, Any] = {"source_text": source_text}
    if page_context:
        for key in ("page_url", "surface", "same_entity_path"):
            if key in page_context and page_context[key] is not None:
                observation[key] = page_context[key]
    payload = {
        "decisions": [
            {
                "id": d.get("id"),
                "question": d.get("question"),
                "outcomes": d.get("outcomes"),
                "definitions": d.get("definitions") or {},
                "notes": d.get("notes") or [],
            }
            for d in decisions
            if isinstance(d, dict) and d.get("id")
        ],
        "observation": observation,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def interpret_observation(
    source_text: str,
    *,
    contract_decision: dict[str, Any] | None = None,
    chat_fn: ChatFn | None = None,
    page_context: dict[str, Any] | None = None,
) -> InterpretationResult:
    """
    Map raw text → contract outcome via LLM.
    Without chat_fn: returns UNKNOWN (fail-closed), for offline dry-run of the gate.

    page_context: optional structural dict (page_url, surface, same_entity_path)
    forwarded into the user prompt so page-identity decisions can ground on URL.
    """
    # ISOLATE #17 / FRAMEWORK_BOUNDARY P0.2: no silent BOARD_TYPE_CONTRACT
    # fallback. Production must pass contract_decision from the frozen contract.
    # Lab scripts (e.g. run_interpretation_v0.py) pass an explicit decision dict
    # — never rely on BOARD_TYPE_CONTRACT as an implicit default here.
    if contract_decision is None:
        return InterpretationResult(
            source_text=source_text,
            outcome=OUTCOME_UNKNOWN,
            confidence="low",
            reason=(
                "no contract_decision; fail-closed UNKNOWN "
                "(BOARD_TYPE_CONTRACT silent fallback disabled — P0.2)"
            ),
            source="heuristic_stub",
        )
    decision = contract_decision
    outcomes = [str(o) for o in (decision.get("outcomes") or [])]
    if OUTCOME_UNKNOWN not in outcomes:
        outcomes = list(outcomes) + [OUTCOME_UNKNOWN]

    if chat_fn is None:
        return InterpretationResult(
            source_text=source_text,
            outcome=OUTCOME_UNKNOWN,
            confidence="low",
            reason="no chat_fn; fail-closed UNKNOWN",
            source="heuristic_stub",
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_user_prompt(decision, source_text, page_context=page_context),
        },
    ]
    try:
        msg = chat_fn(messages)
        content = (msg.get("content") if isinstance(msg, dict) else str(msg)) or ""
        data = _extract_json(content)
        outcome = str(data.get("outcome") or OUTCOME_UNKNOWN).strip()
        if outcome not in outcomes:
            return InterpretationResult(
                source_text=source_text,
                outcome=OUTCOME_UNKNOWN,
                confidence="low",
                reason=f"model returned non-enum outcome {outcome!r}",
                source="llm",
                raw_response=content[:500],
            )
        conf = str(data.get("confidence") or "low").lower()
        if conf not in VALID_CONFIDENCE:
            conf = "low"
        return InterpretationResult(
            source_text=source_text,
            outcome=outcome,
            confidence=conf,
            reason=str(data.get("reason") or "")[:300],
            source="llm",
            raw_response=content[:500],
        )
    except Exception as e:
        return InterpretationResult(
            source_text=source_text,
            outcome=OUTCOME_UNKNOWN,
            confidence="low",
            reason=f"interpretation error: {type(e).__name__}: {e}",
            source="error",
            raw_response="",
        )


def interpret_observation_multi(
    source_text: str,
    *,
    decisions: list[dict[str, Any]],
    chat_fn: ChatFn | None = None,
    page_context: dict[str, Any] | None = None,
) -> dict[str, InterpretationResult]:
    """
    Map one raw text → outcomes for ALL decisions in a single LLM call (Fase B).

    Returns {decision_id: InterpretationResult}. Missing / invalid entries
    fail-closed to UNKNOWN. Without chat_fn: all UNKNOWN (dry-run safe).

    Single-decision interpret_observation() remains for lab callers; production
    run_interpretation uses this path by default.
    """
    results: dict[str, InterpretationResult] = {}
    clean_decisions = [d for d in decisions if isinstance(d, dict) and d.get("id")]
    if not clean_decisions:
        return results

    allowed_by_id: dict[str, list[str]] = {}
    for d in clean_decisions:
        did = str(d["id"])
        outs = [str(o) for o in (d.get("outcomes") or [])]
        if OUTCOME_UNKNOWN not in outs:
            outs = list(outs) + [OUTCOME_UNKNOWN]
        allowed_by_id[did] = outs
        results[did] = InterpretationResult(
            source_text=source_text,
            outcome=OUTCOME_UNKNOWN,
            confidence="low",
            reason="pending",
            source="heuristic_stub",
        )

    if chat_fn is None:
        for did in results:
            results[did] = InterpretationResult(
                source_text=source_text,
                outcome=OUTCOME_UNKNOWN,
                confidence="low",
                reason="no chat_fn; fail-closed UNKNOWN",
                source="heuristic_stub",
            )
        return results

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_MULTI},
        {
            "role": "user",
            "content": build_user_prompt_multi(
                clean_decisions, source_text, page_context=page_context
            ),
        },
    ]
    try:
        msg = chat_fn(messages)
        content = (msg.get("content") if isinstance(msg, dict) else str(msg)) or ""
        data = _extract_json(content)
        # Accept {"outcomes": {...}} or a bare map of decision_id → {...}
        raw_map = data.get("outcomes") if isinstance(data.get("outcomes"), dict) else data
        if not isinstance(raw_map, dict):
            raise ValueError("multi response missing outcomes map")
        for did, allowed in allowed_by_id.items():
            entry = raw_map.get(did)
            if not isinstance(entry, dict):
                results[did] = InterpretationResult(
                    source_text=source_text,
                    outcome=OUTCOME_UNKNOWN,
                    confidence="low",
                    reason=f"missing key {did!r} in multi response",
                    source="llm",
                    raw_response=content[:500],
                )
                continue
            outcome = str(entry.get("outcome") or OUTCOME_UNKNOWN).strip()
            if outcome not in allowed:
                results[did] = InterpretationResult(
                    source_text=source_text,
                    outcome=OUTCOME_UNKNOWN,
                    confidence="low",
                    reason=f"model returned non-enum outcome {outcome!r} for {did}",
                    source="llm",
                    raw_response=content[:500],
                )
                continue
            conf = str(entry.get("confidence") or "low").lower()
            if conf not in VALID_CONFIDENCE:
                conf = "low"
            results[did] = InterpretationResult(
                source_text=source_text,
                outcome=outcome,
                confidence=conf,
                reason=str(entry.get("reason") or "")[:300],
                source="llm",
                raw_response=content[:500],
            )
        return results
    except Exception as e:
        for did in allowed_by_id:
            results[did] = InterpretationResult(
                source_text=source_text,
                outcome=OUTCOME_UNKNOWN,
                confidence="low",
                reason=f"multi interpretation error: {type(e).__name__}: {e}",
                source="error",
                raw_response="",
            )
        return results


# ---------------------------------------------------------------------------
# Dumb gate (code only — no domain knowledge)
# ---------------------------------------------------------------------------

def execute_normalized(
    observed_outcome: str,
    *,
    decision_id: str = "board_type",
    required: list[str] | None = None,
    accept_unknown_as_pass: bool = False,
) -> GateResult:
    """
    Compare normalized outcome to required outcome set.

    - If observed is UNKNOWN → UNKNOWN (unless accept_unknown_as_pass)
    - If observed in required → PASS
    - Else → FAIL
    """
    required = list(required or [])
    obs = str(observed_outcome or OUTCOME_UNKNOWN)

    if obs == OUTCOME_UNKNOWN:
        if accept_unknown_as_pass:
            return GateResult(
                decision_id=decision_id,
                result="PASS",
                required=required,
                observed_outcome=obs,
                reason="UNKNOWN accepted by policy",
            )
        return GateResult(
            decision_id=decision_id,
            result="UNKNOWN",
            required=required,
            observed_outcome=obs,
            reason="normalized evidence is UNKNOWN",
        )

    if not required:
        return GateResult(
            decision_id=decision_id,
            result="PASS",
            required=required,
            observed_outcome=obs,
            reason="no required outcomes; any concrete outcome recorded",
        )

    if obs in required:
        return GateResult(
            decision_id=decision_id,
            result="PASS",
            required=required,
            observed_outcome=obs,
            reason=f"{obs} in required {required}",
        )

    return GateResult(
        decision_id=decision_id,
        result="FAIL",
        required=required,
        observed_outcome=obs,
        reason=f"{obs} not in required {required}",
    )


# ---------------------------------------------------------------------------
# Golden set evaluation
# ---------------------------------------------------------------------------

def load_golden(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def score_interpretations(
    results: list[InterpretationResult],
    golden: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Golden row: { "source_text": "...", "expected_outcome": "ROOM_ONLY", "critical": true }
    critical=true cells are near-miss / synonym tests that must not regress.
    """
    by_text = {r.source_text: r for r in results}
    n = 0
    correct = 0
    critical_n = 0
    critical_ok = 0
    details: list[dict[str, Any]] = []
    confusions: list[dict[str, Any]] = []

    for row in golden:
        text = str(row.get("source_text") or "")
        exp = str(row.get("expected_outcome") or OUTCOME_UNKNOWN)
        critical = bool(row.get("critical"))
        r = by_text.get(text)
        n += 1
        if critical:
            critical_n += 1
        if r is None:
            details.append({**row, "actual": None, "ok": False, "note": "missing result"})
            continue
        ok = r.outcome == exp
        if ok:
            correct += 1
            if critical:
                critical_ok += 1
        else:
            confusions.append(
                {
                    "source_text": text,
                    "expected": exp,
                    "actual": r.outcome,
                    "critical": critical,
                    "reason": r.reason,
                }
            )
        if critical and ok:
            pass
        details.append(
            {
                **row,
                "actual_outcome": r.outcome,
                "confidence": r.confidence,
                "ok": ok,
                "interp_reason": r.reason,
            }
        )

    # Special gate demo: task requires ALL_INCLUSIVE
    gate_rows = []
    for r in results:
        g = execute_normalized(r.outcome, required=["ALL_INCLUSIVE"])
        gate_rows.append({"source_text": r.source_text, "normalized": r.outcome, **g.to_dict()})

    return {
        "n": n,
        "correct": correct,
        "accuracy": (correct / n) if n else 0.0,
        "critical_n": critical_n,
        "critical_correct": critical_ok,
        "critical_accuracy": (critical_ok / critical_n) if critical_n else None,
        "confusions": confusions,
        "details": details,
        "gate_requires_all_inclusive": gate_rows,
    }


def go_no_go(metrics: dict[str, Any]) -> dict[str, Any]:
    """
    GO if:
      - accuracy >= 0.8 on full golden (when n >= 10)
      - critical_accuracy >= 0.85 (near-miss + synonym cells)
      - single-room style cells not labeled ROOM_ONLY (checked via confusions on critical)
    """
    reasons = []
    ok = True
    n = metrics.get("n") or 0
    acc = metrics.get("accuracy") or 0.0
    cacc = metrics.get("critical_accuracy")
    if n >= 10 and acc < 0.8:
        ok = False
        reasons.append(f"accuracy={acc:.3f} < 0.8")
    if cacc is not None and cacc < 0.85:
        ok = False
        reasons.append(f"critical_accuracy={cacc:.3f} < 0.85")
    # hard fail: expected UNKNOWN (single room) predicted ROOM_ONLY
    for c in metrics.get("confusions") or []:
        if c.get("critical") and c.get("expected") == OUTCOME_UNKNOWN and c.get("actual") == "ROOM_ONLY":
            ok = False
            reasons.append(f"critical false ROOM_ONLY on {c.get('source_text')!r}")
    if not reasons:
        reasons.append("all GO criteria met")
    return {"go": ok, "reasons": reasons}
