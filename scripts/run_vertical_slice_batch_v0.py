#!/usr/bin/env python3
"""
Mini-batch vertical slice — candidate isolation / no cross-talk.

Processes 5–10 candidates through the SAME pipeline independently
(per-candidate observation set only; never concatenated multi-hotel prompt).

  python scripts/run_vertical_slice_batch_v0.py --fixture --llm \
    --out ./vertical_slice_batch_v0.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observation_builder import build_from_observations_jsonl  # noqa: E402
from interpretation import interpret_observation  # noqa: E402

# Reuse decisions from vertical slice (keep in sync conceptually)
SLICE_DECISIONS: list[dict[str, Any]] = [
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


def _make_chat_fn(model: str) -> Callable[[list[dict[str, Any]]], dict[str, Any]]:
    from llm import OllamaClient

    client = OllamaClient(model=model)

    def chat_fn(messages: list[dict[str, Any]]) -> dict[str, Any]:
        return client.chat(messages)

    return chat_fn


def channel_allowed(decision: dict[str, Any], channel: str) -> bool:
    allowed = decision.get("allowed_channels")
    if not allowed:
        return True
    return channel in allowed


def aggregate_outcome(per_text: list[dict[str, Any]]) -> str:
    non_unk = [r for r in per_text if r.get("outcome") and r["outcome"] != "UNKNOWN"]
    if not non_unk:
        return "UNKNOWN"
    for pref in ("high", "medium", "low"):
        for r in non_unk:
            if r.get("confidence") == pref:
                return r["outcome"]
    return non_unk[0]["outcome"]


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


def load_fixture_meta(path: Path) -> dict[str, dict[str, Any]]:
    """entity → expected_role, expected_eligible from jsonl extra fields."""
    meta = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        ent = str(row.get("entity") or "")
        meta[ent] = {
            "expected_role": row.get("expected_role"),
            "expected_eligible": row.get("expected_eligible"),
        }
    return meta


def interpret_one(
    candidate_id: str,
    obs: list[dict[str, Any]],
    chat_fn: Callable | None,
) -> dict[str, Any]:
    """Interpret using ONLY this candidate's observations (isolation)."""
    outcomes: dict[str, str] = {}
    traces: dict[str, Any] = {}
    for d in SLICE_DECISIONS:
        did = d["id"]
        texts = []
        for o in obs:
            if not channel_allowed(d, o["channel"]):
                texts.append(
                    {
                        "text": o["text"],
                        "channel": o["channel"],
                        "skipped": True,
                        "outcome": "UNKNOWN",
                    }
                )
                continue
            ir = interpret_observation(
                o["text"], contract_decision=d, chat_fn=chat_fn
            )
            texts.append(
                {
                    "text": o["text"],
                    "channel": o["channel"],
                    "skipped": False,
                    "outcome": ir.outcome,
                    "confidence": ir.confidence,
                    "reason": ir.reason,
                }
            )
        active = [t for t in texts if not t.get("skipped")]
        outcomes[did] = aggregate_outcome(active)
        traces[did] = {"per_text": texts, "aggregated": outcomes[did]}

    elig = eligibility_from_outcomes(outcomes, SLICE_DECISIONS)
    return {
        "candidate_id": candidate_id,
        "claim_texts": [
            o["text"] for o in obs if o["channel"] == "candidate_claim"
        ],
        "outcomes": outcomes,
        "eligibility": elig,
        "decision_traces": traces,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", action="store_true", default=True)
    ap.add_argument(
        "--observations",
        type=Path,
        default=ROOT / "evals" / "vertical_slice_batch_fixture_v0.jsonl",
    )
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--model", default="qwen3.8:27b")
    ap.add_argument("--min-entity-score", type=float, default=0.5)
    ap.add_argument("--out", type=Path, default=Path("vertical_slice_batch_v0.json"))
    args = ap.parse_args()

    obs_path = args.observations
    if not obs_path.exists():
        print(f"missing {obs_path}", file=sys.stderr)
        return 2

    meta = load_fixture_meta(obs_path)
    built = build_from_observations_jsonl(
        obs_path, min_entity_score=args.min_entity_score
    )
    by_cid: dict[str, list[dict[str, Any]]] = {}
    for o in built:
        by_cid.setdefault(o["candidate_id"], []).append(o)

    chat_fn = _make_chat_fn(args.model) if args.llm else None
    if not args.llm:
        print("[batch] no --llm → fail-closed UNKNOWN")

    results = []
    for cid, obs in by_cid.items():
        print(f"--- {cid} ---")
        r = interpret_one(cid, obs, chat_fn)
        m = meta.get(cid) or {}
        r["expected_role"] = m.get("expected_role")
        r["expected_eligible"] = m.get("expected_eligible")
        r["eligible_match"] = (
            r["expected_eligible"] is None
            or r["eligibility"]["eligible"] == r["expected_eligible"]
        )
        results.append(r)
        print(
            f"  outcomes={r['outcomes']} eligible={r['eligibility']['eligible']} "
            f"expected={r['expected_eligible']} match={r['eligible_match']}"
        )

    # --- Isolation / batch checks ---
    checks = []

    # 1. No meal= fed into board for any candidate
    meal_leaks = []
    for r in results:
        for t in r["decision_traces"]["board_type"]["per_text"]:
            if not t.get("skipped") and "meal=" in (t.get("text") or "").lower():
                meal_leaks.append(r["candidate_id"])
    checks.append(
        {"id": "no_search_context_board_leak", "ok": len(meal_leaks) == 0, "leaks": meal_leaks}
    )

    # 2. Cross-talk: negative/breakfast must NOT get ALL_INCLUSIVE on board
    crosstalk = []
    for r in results:
        role = r.get("expected_role") or ""
        bt = r["outcomes"].get("board_type")
        if role in ("negative_enkel", "breakfast", "destination") and bt == "ALL_INCLUSIVE":
            crosstalk.append(
                {
                    "candidate_id": r["candidate_id"],
                    "role": role,
                    "board_type": bt,
                    "claims": r["claim_texts"][:5],
                }
            )
        # marketing entity name may contain "All Inclusive" in entity string —
        # if board becomes AI only from entity name while raw has no board segment,
        # still record but soft: marketing expected not eligible
    checks.append(
        {
            "id": "no_crosstalk_ai_onto_non_ai_cards",
            "ok": len(crosstalk) == 0,
            "violations": crosstalk,
        }
    )

    # 3. Positive cases must be ALL_INCLUSIVE when llm
    if args.llm:
        pos_fail = []
        for r in results:
            if r.get("expected_role") == "positive_ai":
                if r["outcomes"].get("board_type") != "ALL_INCLUSIVE":
                    pos_fail.append(r["candidate_id"])
                if r["eligibility"]["eligible"] is not True:
                    pos_fail.append(f"{r['candidate_id']}:not_eligible")
        checks.append(
            {"id": "positives_eligible_ai", "ok": len(pos_fail) == 0, "fails": pos_fail}
        )

        neg_fail = []
        for r in results:
            if r.get("expected_role") in (
                "negative_enkel",
                "breakfast",
                "destination",
                "marketing",
            ):
                if r["eligibility"]["eligible"] is True:
                    neg_fail.append(r["candidate_id"])
        checks.append(
            {
                "id": "non_positives_not_eligible",
                "ok": len(neg_fail) == 0,
                "fails": neg_fail,
            }
        )

        # eligibility oracle match rate
        matched = sum(1 for r in results if r.get("eligible_match"))
        checks.append(
            {
                "id": "eligible_oracle_match",
                "ok": matched == len(results),
                "matched": matched,
                "n": len(results),
            }
        )
    else:
        checks.append(
            {
                "id": "dry_run_all_unknown_board",
                "ok": all(
                    r["outcomes"].get("board_type") == "UNKNOWN" for r in results
                ),
            }
        )

    # 4. Candidate count
    checks.append(
        {
            "id": "batch_size",
            "ok": 5 <= len(results) <= 15,
            "n": len(results),
        }
    )

    go = all(c["ok"] for c in checks)
    out = {
        "schema_version": "vertical-slice-batch-v0",
        "source": str(obs_path),
        "llm": bool(args.llm),
        "n_candidates": len(results),
        "results": results,
        "checks": checks,
        "go_no_go": {
            "go": go,
            "reasons": [c for c in checks if not c["ok"]]
            or ["all batch isolation checks met"],
        },
        "note": (
            "Each candidate is interpreted only on its own observation set "
            "(no multi-hotel concatenated prompt). Cross-talk check: "
            "non-AI cards must not receive ALL_INCLUSIVE."
        ),
    }

    written = None
    for cand in (args.out, Path("/tmp") / args.out.name):
        try:
            cand.write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            written = cand
            break
        except OSError:
            continue

    print("=== Vertical slice BATCH v0 ===")
    print(f"n={len(results)} GO={go}")
    for c in checks:
        print(f"  {c['id']}: ok={c['ok']}")
    print(f"wrote {written}")
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
