#!/usr/bin/env python3
"""
Offline unit tests for evidence_acquisition (no browser).

  - gaps_from_eligibility
  - irreversible filter
  - acquisition_decide fail-closed without LLM
  - affordance target enforcement (mock LLM proposing illegal target → STOP)

python scripts/run_acquisition_unit_v0.py --out ./evals/live_offer/acquisition_unit_v0.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evidence_acquisition import (  # noqa: E402
    ACTION_CLASSES,
    acquisition_decide,
    filter_safe_affordances,
    gaps_from_eligibility,
    is_irreversible_text,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("./evals/live_offer/acquisition_unit_v0.json"))
    args = ap.parse_args()

    checks = []

    # 1 gaps
    elig = {
        "eligible": False,
        "details": [
            {"decision_id": "board_type", "result": "PASS", "observed": "ALL_INCLUSIVE"},
            {
                "decision_id": "package_includes_flight",
                "result": "UNKNOWN",
                "observed": "UNKNOWN",
                "allowed": ["FLIGHT_INCLUDED"],
            },
        ],
    }
    gaps = gaps_from_eligibility(elig)
    checks.append(
        {
            "id": "gaps_unknown_only",
            "ok": len(gaps) == 1 and gaps[0]["decision_id"] == "package_includes_flight",
            "gaps": gaps,
        }
    )

    # 2 irreversible
    checks.append(
        {
            "id": "irreversible_book",
            "ok": is_irreversible_text("Reis boeken") and is_irreversible_text("Buy now"),
        }
    )
    checks.append(
        {
            "id": "safe_prices_tab",
            "ok": not is_irreversible_text("Prijzen & boeken"),
        }
    )

    # 3 filter strips book now
    aff = [
        {"kind": "button", "text": "Reis boeken", "href": ""},
        {"kind": "tab", "text": "Prijzen & boeken", "href": ""},
        {"kind": "link", "text": "Vlucht", "href": "https://example.com/flight"},
    ]
    safe = filter_safe_affordances(aff)
    checks.append(
        {
            "id": "filter_drops_book",
            "ok": all(a["text"] != "Reis boeken" for a in safe) and len(safe) == 2,
            "safe": safe,
        }
    )

    # 4 no LLM → STOP
    d = acquisition_decide(
        gaps=gaps,
        affordances=safe,
        page_url="https://example.com/x",
        page_title="X",
        claim_preview=["All Inclusive"],
        task_text="find packages",
        chat_fn=None,
        step_index=0,
        max_steps=3,
    )
    checks.append(
        {
            "id": "no_llm_stop",
            "ok": d.get("action_class") == "STOP" and d.get("source") == "code",
            "decision": d,
        }
    )

    # 5 mock LLM illegal target → code reject
    def bad_llm(_messages):
        return json.dumps(
            {
                "action_class": "CLICK_TEXT",
                "target_text": "SecretAdminPanel",
                "target_href": None,
                "for_decision_ids": ["package_includes_flight"],
                "reason": "hallucinated",
            }
        )

    d2 = acquisition_decide(
        gaps=gaps,
        affordances=safe,
        page_url="https://example.com/x",
        page_title="X",
        claim_preview=["All Inclusive"],
        task_text="find packages",
        chat_fn=bad_llm,
        step_index=0,
        max_steps=3,
    )
    checks.append(
        {
            "id": "reject_hallucinated_target",
            "ok": d2.get("action_class") == "STOP"
            and d2.get("source") == "code_reject",
            "decision": d2,
        }
    )

    # 6 mock LLM legal click
    def good_llm(_messages):
        return json.dumps(
            {
                "action_class": "CLICK_TEXT",
                "target_text": "Prijzen & boeken",
                "for_decision_ids": ["package_includes_flight"],
                "reason": "price calculation may show included flight",
            }
        )

    d3 = acquisition_decide(
        gaps=gaps,
        affordances=safe,
        page_url="https://example.com/x",
        page_title="X",
        claim_preview=["All Inclusive"],
        task_text="find packages",
        chat_fn=good_llm,
        step_index=0,
        max_steps=3,
    )
    checks.append(
        {
            "id": "accept_observed_click",
            "ok": d3.get("action_class") == "CLICK_TEXT"
            and d3.get("target_text") == "Prijzen & boeken"
            and d3.get("source") == "llm",
            "decision": d3,
        }
    )

    # 7 enum closed
    checks.append({"id": "enum_has_stop", "ok": "STOP" in ACTION_CLASSES})

    # 8 irreversible expanded (Start boeking / confirm) but not "Prijzen & boeken"
    checks.append(
        {
            "id": "irreversible_start_boeking",
            "ok": is_irreversible_text("Start boeking")
            and is_irreversible_text("Confirm payment")
            and not is_irreversible_text("Prijzen & boeken")
            and not is_irreversible_text("Vlucht"),
        }
    )

    # 9 hard provenance: site_marketing observations cannot yield PASS
    from pipeline_offline import (  # noqa: E402
        aggregate_outcome,
        is_provenance_blocked_for_entity,
        run_interpretation,
        PACKAGES_DECISIONS,
    )

    marketing_obs = {
        "text": "Corendon pakketreizen bevatten altijd vlucht + hotel All Inclusive",
        "channel": "candidate_claim",
        "provenance": {"surface": "site_marketing", "same_entity_path": False},
    }
    entity_obs = {
        "text": "All Inclusive - Aparthotel",
        "channel": "candidate_claim",
        "provenance": {"surface": "live_detail", "same_entity_path": True},
    }
    checks.append(
        {
            "id": "provenance_blocks_marketing",
            "ok": is_provenance_blocked_for_entity(marketing_obs)
            and not is_provenance_blocked_for_entity(entity_obs),
        }
    )

    # aggregate must ignore provenance_blocked rows even if outcome set
    fake_rows = [
        {
            "outcome": "FLIGHT_INCLUDED",
            "confidence": "high",
            "provenance_blocked": True,
            "skipped": False,
        },
        {"outcome": "UNKNOWN", "confidence": "low", "skipped": False},
    ]
    checks.append(
        {
            "id": "aggregate_ignores_blocked",
            "ok": aggregate_outcome(fake_rows) == "UNKNOWN",
        }
    )

    # run_interpretation with only marketing claims → UNKNOWN (no LLM needed)
    interp = run_interpretation(
        observations=[marketing_obs],
        decisions=PACKAGES_DECISIONS,
        chat_fn=None,
    )
    checks.append(
        {
            "id": "marketing_only_stays_unknown",
            "ok": (interp.get("outcomes") or {}).get("package_includes_flight")
            == "UNKNOWN"
            and (interp.get("provenance_blocked_n") or 0) >= 1,
            "outcomes": interp.get("outcomes"),
            "blocked": interp.get("provenance_blocked_n"),
        }
    )

    go = all(c.get("ok") for c in checks)
    report = {
        "schema": "acquisition-unit-v0",
        "go_no_go": {"go": go, "reasons": ["all unit checks passed"] if go else ["see failed checks"]},
        "checks": checks,
    }
    args.out = Path(args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("=== Acquisition unit v0 ===")
    for c in checks:
        print(f"  [{'OK' if c.get('ok') else 'FAIL'}] {c['id']}")
    print(f"GO={go} wrote {args.out}")
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
