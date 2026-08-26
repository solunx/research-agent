"""
Candidate selection methods S0–S5.

Hard rule: no domain string matching (hotel, paper, RCT, all-inclusive, …).
Structural signals only, or LLM with task+text(+structure).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from .contract import (
    CandidateDecision,
    CandidateUnit,
    SelectionResult,
    TaskContext,
)

ChatFn = Callable[[list[dict[str, str]]], str]


# ---------------------------------------------------------------------------
# S0 — structure only
# ---------------------------------------------------------------------------
def select_s0_structural(task: TaskContext, unit: CandidateUnit) -> SelectionResult:
    t0 = time.monotonic()
    et = (unit.element_type or "").lower()
    text = (unit.text or "").strip()
    wc = len(text.split())
    reasons: list[str] = []

    # Clear chrome-like structural types
    chrome_types = {
        "nav",
        "navigation",
        "footer",
        "header",
        "button",
        "cta",
        "chrome",
        "menu",
        "filter_ui",
        "ui_label",
    }
    if et in chrome_types:
        return SelectionResult(
            unit_id=unit.unit_id,
            decision=CandidateDecision.NOT_ADMISSIBLE,
            reason=f"element_type={et} treated as chrome",
            confidence="high",
            evidence_refs=["element_type"],
            method_id="S0_structural",
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    # Very empty
    if not text or wc == 0:
        return SelectionResult(
            unit_id=unit.unit_id,
            decision=CandidateDecision.NOT_ADMISSIBLE,
            reason="empty text",
            confidence="high",
            method_id="S0_structural",
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    # Card / title / result-like structural roles
    content_types = {
        "card_title",
        "result_title",
        "heading",
        "h1",
        "h2",
        "h3",
        "title",
        "paper_title",
        "function_def",
        "table_row",
        "list_item",
        "paragraph",
        "abstract",
        "entity",
        "offer_card",
    }
    score = unit.entity_score
    has_neighbors = bool(unit.neighbors)
    has_raw = bool(unit.raw_evidence and len(unit.raw_evidence) > 10)

    if et in content_types and (has_neighbors or has_raw or (score is not None and score >= 0.7)):
        reasons.append(f"content_type={et}")
        if has_neighbors:
            reasons.append("has_neighbors")
        if has_raw:
            reasons.append("has_raw_evidence")
        if score is not None:
            reasons.append(f"score={score:.2f}")
        return SelectionResult(
            unit_id=unit.unit_id,
            decision=CandidateDecision.ADMISSIBLE,
            reason="; ".join(reasons),
            confidence="medium",
            evidence_refs=["element_type"] + (["neighbors"] if has_neighbors else []),
            method_id="S0_structural",
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    if et in content_types:
        return SelectionResult(
            unit_id=unit.unit_id,
            decision=CandidateDecision.UNKNOWN,
            reason=f"content_type={et} but weak supporting structure",
            confidence="low",
            method_id="S0_structural",
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    # No useful structure
    return SelectionResult(
        unit_id=unit.unit_id,
        decision=CandidateDecision.UNKNOWN,
        reason="insufficient structural signal",
        confidence="low",
        method_id="S0_structural",
        latency_ms=(time.monotonic() - t0) * 1000,
    )


# ---------------------------------------------------------------------------
# S1 — structure + generic heuristics (still domain-free)
# ---------------------------------------------------------------------------
_GENERIC_CTA = re.compile(
    r"^(view|see|click|next|previous|sort|filter|search|login|sign\s*in|"
    r"contact|help|cookie|privacy|terms)\b",
    re.I,
)
_GENERIC_CTA_NL = re.compile(
    r"^(bekijk|sorteer|filter|zoek|contact|vragen|cookies|privacy|voorwaarden)\b",
    re.I,
)


def select_s1_structural_heuristics(task: TaskContext, unit: CandidateUnit) -> SelectionResult:
    t0 = time.monotonic()
    base = select_s0_structural(task, unit)
    text = (unit.text or "").strip()
    wc = len(text.split())

    # Generic CTA / chrome phrase shape (language-agnostic-ish function words)
    if wc <= 4 and (_GENERIC_CTA.search(text) or _GENERIC_CTA_NL.search(text)):
        return SelectionResult(
            unit_id=unit.unit_id,
            decision=CandidateDecision.NOT_ADMISSIBLE,
            reason="generic short CTA/chrome phrase shape",
            confidence="medium",
            evidence_refs=["text_shape"],
            method_id="S1_structural_heuristics",
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    # Extremely long single-line slogans without structural content type
    et = (unit.element_type or "").lower()
    if wc >= 12 and et not in {
        "card_title",
        "result_title",
        "heading",
        "h1",
        "h2",
        "title",
        "paper_title",
        "paragraph",
        "abstract",
        "offer_card",
        "entity",
    }:
        return SelectionResult(
            unit_id=unit.unit_id,
            decision=CandidateDecision.NOT_ADMISSIBLE,
            reason="long phrase without content element_type",
            confidence="medium",
            method_id="S1_structural_heuristics",
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    # If S0 already decided, keep but retag method
    base.method_id = "S1_structural_heuristics"
    base.latency_ms = (time.monotonic() - t0) * 1000
    return base


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------
_LLM_SYSTEM = """You are a candidate selector for a research agent.
Given a USER TASK and one candidate UNIT, decide only:
  ADMISSIBLE | NOT_ADMISSIBLE | UNKNOWN

Rules:
- ADMISSIBLE = this unit is plausible evidence/candidate for answering the task.
- NOT_ADMISSIBLE = clearly irrelevant chrome, navigation, boilerplate, or off-topic.
- UNKNOWN = insufficient information to decide.
- Do NOT interpret domain outcomes (do not label board types, study designs, etc.).
- Do NOT invent facts not present in the unit.
- Reply with JSON only:
  {"decision":"ADMISSIBLE|NOT_ADMISSIBLE|UNKNOWN","reason":"...","confidence":"low|medium|high"}
"""


def _parse_llm_decision(raw: str) -> tuple[CandidateDecision, str, str]:
    text = (raw or "").strip()
    # extract JSON object
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return CandidateDecision.UNKNOWN, "unparseable LLM response", "low"
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return CandidateDecision.UNKNOWN, "invalid JSON from LLM", "low"
    d = str(obj.get("decision") or "UNKNOWN").upper()
    if d not in {x.value for x in CandidateDecision}:
        d = "UNKNOWN"
    reason = str(obj.get("reason") or "")[:400]
    conf = str(obj.get("confidence") or "medium").lower()
    if conf not in ("low", "medium", "high"):
        conf = "medium"
    return CandidateDecision(d), reason, conf


def _llm_select(
    task: TaskContext,
    unit: CandidateUnit,
    *,
    method_id: str,
    include_structure: bool,
    chat_fn: ChatFn | None,
) -> SelectionResult:
    t0 = time.monotonic()
    if chat_fn is None:
        return SelectionResult(
            unit_id=unit.unit_id,
            decision=CandidateDecision.UNKNOWN,
            reason="no chat_fn; fail-closed UNKNOWN",
            confidence="low",
            method_id=method_id,
            latency_ms=(time.monotonic() - t0) * 1000,
            llm_calls=0,
        )

    payload: dict[str, Any] = {
        "task": task.task_text,
        "unit_text": unit.text,
    }
    if include_structure:
        payload["structure"] = {
            "element_type": unit.element_type,
            "parent_id": unit.parent_id,
            "source_url": unit.source_url,
            "path": unit.path,
            "neighbors": unit.neighbors[:8],
            "attributes": {k: unit.attributes[k] for k in list(unit.attributes)[:12]},
            "entity_score": unit.entity_score,
            "raw_evidence_preview": (unit.raw_evidence or "")[:300],
        }

    messages = [
        {"role": "system", "content": _LLM_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        raw = chat_fn(messages)
        decision, reason, conf = _parse_llm_decision(raw)
        return SelectionResult(
            unit_id=unit.unit_id,
            decision=decision,
            reason=reason,
            confidence=conf,
            evidence_refs=["unit_text"] + (["structure"] if include_structure else []),
            method_id=method_id,
            latency_ms=(time.monotonic() - t0) * 1000,
            llm_calls=1,
            input_tokens=max(1, len(json.dumps(payload)) // 4),
            output_tokens=max(1, len(raw or "") // 4),
        )
    except Exception as e:  # noqa: BLE001
        return SelectionResult(
            unit_id=unit.unit_id,
            decision=CandidateDecision.UNKNOWN,
            reason=f"llm_error: {e}",
            confidence="low",
            method_id=method_id,
            latency_ms=(time.monotonic() - t0) * 1000,
            llm_calls=1,
            error=str(e),
        )


def select_s2_llm_raw(
    task: TaskContext, unit: CandidateUnit, chat_fn: ChatFn | None = None
) -> SelectionResult:
    return _llm_select(task, unit, method_id="S2_llm_raw", include_structure=False, chat_fn=chat_fn)


def select_s3_llm_grounded(
    task: TaskContext, unit: CandidateUnit, chat_fn: ChatFn | None = None
) -> SelectionResult:
    return _llm_select(task, unit, method_id="S3_llm_grounded", include_structure=True, chat_fn=chat_fn)


# ---------------------------------------------------------------------------
# S5 — hybrid: structural prefilter → LLM only on ADMISSIBLE+UNKNOWN
# ---------------------------------------------------------------------------
def select_s5_hybrid(
    task: TaskContext, unit: CandidateUnit, chat_fn: ChatFn | None = None
) -> SelectionResult:
    t0 = time.monotonic()
    pre = select_s1_structural_heuristics(task, unit)
    if pre.decision == CandidateDecision.NOT_ADMISSIBLE:
        pre.method_id = "S5_hybrid"
        pre.reason = "prefilter_NOT: " + pre.reason
        pre.latency_ms = (time.monotonic() - t0) * 1000
        return pre
    # LLM decides for ADMISSIBLE/UNKNOWN from prefilter
    llm = select_s3_llm_grounded(task, unit, chat_fn=chat_fn)
    llm.method_id = "S5_hybrid"
    llm.reason = f"prefilter={pre.decision.value}; llm: {llm.reason}"
    llm.latency_ms = (time.monotonic() - t0) * 1000
    llm.llm_calls = llm.llm_calls
    return llm


METHODS: dict[str, Any] = {
    "S0_structural": select_s0_structural,
    "S1_structural_heuristics": select_s1_structural_heuristics,
    "S2_llm_raw": select_s2_llm_raw,
    "S3_llm_grounded": select_s3_llm_grounded,
    "S5_hybrid": select_s5_hybrid,
}
