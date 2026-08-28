"""
Positive Evidence Trace v0 — localize where offer evidence is lost (A→F).

Stages
------
A  site / oracle verified that evidence can exist online
B  retrieval found a relevant URL (or simulated detail harvest)
C  page/state was fetched (or simulated)
D  observations contain literal claim texts (board/flight/price scope)
E  CANDIDATE_UNIT + INTERPRETATION produce normalized outcomes
F  CODE eligibility matches expected_eligible

Modes
-----
- fixture: inject observations as if harvest succeeded (tests D→F when evidence present)
- incomplete controls: list/hotel-option without selected offer (must stay not eligible)

No new board heuristics. Reuses pipeline_offline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from pipeline_offline import (
    PACKAGES_DECISIONS,
    PACKAGES_TASK_TEXT,
    go_no_go,
    observations_from_fixture_row,
    run_pipeline_one,
    score_pipeline_batch,
)

ChatFnStr = Callable[[list[dict[str, str]]], str]

_BOARD_HINT = re.compile(
    r"all[-\s]?inclusive|volpension|ultra\s+all|full\s+board|half.?pension|"
    r"enkel\s+kamer|room\s+only|ontbijt|breakfast",
    re.I,
)
_FLIGHT_HINT = re.compile(
    r"vlucht|flight|heen-?\s*en\s*terug|retour|vanaf\s+brussel|bru\b",
    re.I,
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_oracle(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for row in load_jsonl(path):
        key = str(row.get("entity") or "").strip()
        if key:
            out[key] = row
    return out


def _claim_texts(row: dict[str, Any]) -> list[str]:
    obs = observations_from_fixture_row(row)
    return [str(o.get("text") or "") for o in obs if o.get("channel") == "candidate_claim"]


def stage_d_observation(row: dict[str, Any]) -> dict[str, Any]:
    """Literal presence only — no semantic outcomes."""
    claims = _claim_texts(row)
    blob = " | ".join(claims)
    boardish = [c for c in claims if _BOARD_HINT.search(c)]
    flightish = [c for c in claims if _FLIGHT_HINT.search(c)]
    kind = str(row.get("evidence_kind") or "")
    return {
        "status": "PRESENT" if claims else "ABSENT",
        "evidence_kind": kind,
        "candidate_claim_n": len(claims),
        "boardish_literal_present": bool(boardish),
        "boardish_samples": boardish[:5],
        "flightish_literal_present": bool(flightish),
        "flightish_samples": flightish[:5],
        "claim_preview": claims[:12],
        "blob_len": len(blob),
    }


def localize_fault(
    *,
    expected_eligible: bool | None,
    eligible: bool,
    stage_d: dict[str, Any],
    pipeline: dict[str, Any],
) -> str:
    """
    Return first stage that explains failure vs expectation.
    """
    if expected_eligible is None:
        return "no_oracle"
    if expected_eligible is True:
        if stage_d.get("status") != "PRESENT":
            return "D_observation_empty"
        if not stage_d.get("boardish_literal_present"):
            return "D_missing_board_literal"
        cu = (pipeline.get("candidate_stage") or {}).get("decision")
        if cu != "ADMISSIBLE":
            return f"E_candidate_{cu or 'UNKNOWN'}"
        outcomes = ((pipeline.get("safety") or {}).get("outcomes")) or {}
        if not outcomes and pipeline.get("interpretation_stage"):
            outcomes = (pipeline["interpretation_stage"].get("outcomes") or {})
        board = outcomes.get("board_type", "UNKNOWN")
        flight = outcomes.get("package_includes_flight", "UNKNOWN")
        if board == "UNKNOWN":
            return "E_board_UNKNOWN"
        if board != "ALL_INCLUSIVE":
            return f"E_board_{board}"
        if flight == "UNKNOWN":
            return "E_flight_UNKNOWN"
        if flight != "FLIGHT_INCLUDED":
            return f"E_flight_{flight}"
        if not eligible:
            return "F_eligibility_false"
        return "none"
    # expected not eligible
    if eligible:
        if (pipeline.get("safety") or {}).get("board_from_search_context_only"):
            return "F_search_context_leak"
        return "F_false_eligible"
    return "none"


def trace_one(
    row: dict[str, Any],
    *,
    chat_fn: ChatFnStr | None,
    oracle: dict[str, dict[str, Any]] | None = None,
    mode: str = "fixture_simulated_harvest",
) -> dict[str, Any]:
    oracle = oracle or {}
    cid = str(row.get("entity") or row.get("candidate_id") or "unknown")
    okey = str(row.get("oracle_entity") or cid)
    orec = oracle.get(okey) or oracle.get(cid) or {}

    a_status = "PRESENT" if orec.get("verified_online") or orec.get("site_status", "").startswith("A_") else (
        "PRESENT" if row.get("expected_eligible") is not None else "UNKNOWN"
    )
    if orec.get("site_status"):
        a_status = str(orec["site_status"])

    stage_d = stage_d_observation(row)
    pr = run_pipeline_one(row, chat_fn=chat_fn, task_text=PACKAGES_TASK_TEXT)
    pr_d = pr.to_dict()
    outcomes = {}
    if pr.interpretation_stage:
        outcomes = pr.interpretation_stage.get("outcomes") or {}
    elif pr.safety:
        outcomes = (pr.safety or {}).get("outcomes") or {}

    expected = pr.expected_eligible
    fault = localize_fault(
        expected_eligible=expected,
        eligible=pr.eligible,
        stage_d=stage_d,
        pipeline=pr_d,
    )

    return {
        "entity": cid,
        "mode": mode,
        "evidence_kind": row.get("evidence_kind"),
        "expected_eligible": expected,
        "expected_role": pr.expected_role,
        "stages": {
            "A_site": {
                "status": a_status,
                "oracle_entity": okey if orec else None,
                "detail_url": orec.get("detail_url") or row.get("source_url"),
            },
            "B_retrieval": {
                "status": "SIMULATED_SUCCESS" if mode.startswith("fixture") else "UNKNOWN",
                "note": "Fixture injects detail/offer observations; not a live crawl.",
            },
            "C_page_or_state": {
                "status": "SIMULATED_SUCCESS" if mode.startswith("fixture") else "UNKNOWN",
                "evidence_kind": row.get("evidence_kind"),
            },
            "D_observation": stage_d,
            "E_candidate_interpretation": {
                "candidate_unit": (pr.candidate_stage or {}).get("decision"),
                "admitted": (pr.candidate_stage or {}).get("admitted"),
                "outcomes": outcomes,
                "skipped_interpretation": pr.skipped_interpretation,
            },
            "F_eligibility": {
                "eligible": pr.eligible,
                "expected_eligible": expected,
                "match": (None if expected is None else bool(pr.eligible) == bool(expected)),
                "details": (
                    (pr.interpretation_stage or {}).get("eligibility", {}).get("details")
                    if pr.interpretation_stage
                    else None
                ),
            },
        },
        "fault_localization": fault,
        "llm_calls": pr.llm_calls,
        "safety": pr.safety,
        "pipeline": pr_d,
    }


def run_trace_batch(
    rows: list[dict[str, Any]],
    *,
    chat_fn: ChatFnStr | None,
    oracle: dict[str, dict[str, Any]] | None = None,
    mode: str = "fixture_simulated_harvest",
) -> dict[str, Any]:
    traces = [
        trace_one(r, chat_fn=chat_fn, oracle=oracle, mode=mode) for r in rows
    ]
    # Rebuild PipelineResult-like scoring via run_pipeline_one again is wasteful;
    # score from traces.
    from pipeline_offline import PipelineResult

    results = []
    for t, r in zip(traces, rows):
        pr = PipelineResult(
            candidate_id=t["entity"],
            expected_eligible=t["expected_eligible"],
            expected_role=t.get("expected_role"),
            candidate_stage=(t["pipeline"] or {}).get("candidate_stage") or {},
            interpretation_stage=(t["pipeline"] or {}).get("interpretation_stage"),
            eligible=bool(t["stages"]["F_eligibility"]["eligible"]),
            skipped_interpretation=bool(
                (t["pipeline"] or {}).get("skipped_interpretation")
            ),
            llm_calls=int(t.get("llm_calls") or 0),
            safety=t.get("safety") or {},
        )
        results.append(pr)

    metrics = score_pipeline_batch(results)
    faults = [t["fault_localization"] for t in traces]
    fault_counts: dict[str, int] = {}
    for f in faults:
        fault_counts[f] = fault_counts.get(f, 0) + 1

    llm_enabled = chat_fn is not None
    gng = go_no_go(metrics, llm_enabled=llm_enabled, require_oracle=True, n_candidates=len(rows))

    # Extra GO: detail positives should localize to none when LLM on
    if llm_enabled:
        detail_pos = [
            t
            for t in traces
            if t.get("expected_eligible") is True
            and str(t.get("evidence_kind") or "").startswith("detail")
        ]
        if detail_pos and any(t["fault_localization"] != "none" for t in detail_pos):
            gng = {
                "go": False,
                "reasons": list(gng.get("reasons") or [])
                + [
                    "detail positive fault_localization != none: "
                    + ", ".join(
                        f"{t['entity']}={t['fault_localization']}"
                        for t in detail_pos
                        if t["fault_localization"] != "none"
                    )
                ],
            }

    return {
        "schema": "positive-evidence-trace-v0",
        "mode": mode,
        "n": len(traces),
        "metrics": metrics,
        "fault_counts": fault_counts,
        "go_no_go": gng,
        "traces": traces,
        "decisions": [d["id"] for d in PACKAGES_DECISIONS],
        "task_text": PACKAGES_TASK_TEXT,
    }
