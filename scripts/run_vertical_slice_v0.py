#!/usr/bin/env python3
"""
Vertical slice v0 — real harvest → observations → interpretation → eligibility.

No agent refactor. Notes off. Search_context is NOT fed to board/flight interpretation.

  python scripts/run_vertical_slice_v0.py \
    --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026 \
    --llm --out ./vertical_slice_v0.json

  # offline dry-run (all UNKNOWN, eligibility fail-closed):
  python scripts/run_vertical_slice_v0.py --run-dir ... --out ./vertical_slice_v0.json
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

# Minimal multi-decision contract for this slice (frozen for the experiment).
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
    """Prefer first non-UNKNOWN high/medium; else any non-UNKNOWN; else UNKNOWN."""
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
            details.append(
                {"decision_id": did, "result": "SKIP", "observed": observed}
            )
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


def pick_candidates(
    built: list[dict[str, Any]],
    *,
    fixture_mode: bool = False,
) -> list[dict[str, Any]]:
    """Sercotel negative; positive AI card when card text (not URL) has all-inclusive."""
    by_cid: dict[str, list[dict[str, Any]]] = {}
    for o in built:
        by_cid.setdefault(o["candidate_id"], []).append(o)

    picks: list[dict[str, Any]] = []

    def claims_blob(obs: list[dict[str, Any]]) -> str:
        return " | ".join(
            o["text"] for o in obs if o["channel"] == "candidate_claim"
        ).lower()

    # Positive: card-level AI (fixture or real)
    for cid, obs in by_cid.items():
        blob = claims_blob(obs)
        if "all-inclusive" in blob or "all inclusive" in blob:
            # skip pure marketing chrome entities
            cl = cid.lower()
            if any(
                m in cl
                for m in (
                    "vragen",
                    "contact",
                    "ruim aanbod",
                    "smullen",
                    "halfpension of",
                    "populair",
                    "dagje ",
                )
            ):
                continue
            picks.append({"candidate_id": cid, "role": "positive_ai_card", "obs": obs})
            break

    # Negative: Sercotel / Enkel kamer
    for cid, obs in by_cid.items():
        if any(p["candidate_id"] == cid for p in picks):
            continue
        if "sercotel" in cid.lower() or "enkel kamer" in claims_blob(obs):
            if "sercotel" in cid.lower():
                picks.append(
                    {"candidate_id": cid, "role": "negative_enkel_kamer", "obs": obs}
                )
                break
    if fixture_mode:
        for cid, obs in by_cid.items():
            if any(p["candidate_id"] == cid for p in picks):
                continue
            if "sunrise" in cid.lower() or "ontbijt" in claims_blob(obs):
                picks.append(
                    {"candidate_id": cid, "role": "breakfast_control", "obs": obs}
                )
                break

    if not fixture_mode:
        for cid, obs in by_cid.items():
            if cid == "Gran Canaria":
                picks.append({"candidate_id": cid, "role": "destination", "obs": obs})
                break

    return picks


def interpret_candidate(
    cand: dict[str, Any],
    chat_fn: Callable | None,
) -> dict[str, Any]:
    obs = cand["obs"]
    # Prove search_context is excluded from board interpretation
    search_ctx = [o for o in obs if o["channel"] == "search_context"]
    decision_traces: dict[str, Any] = {}
    outcomes: dict[str, str] = {}

    for d in SLICE_DECISIONS:
        did = d["id"]
        texts: list[dict[str, Any]] = []
        for o in obs:
            if not channel_allowed(d, o["channel"]):
                texts.append(
                    {
                        "text": o["text"],
                        "channel": o["channel"],
                        "skipped": True,
                        "reason": "channel_not_allowed",
                        "outcome": "UNKNOWN",
                    }
                )
                continue
            if chat_fn is None:
                ir = interpret_observation(o["text"], contract_decision=d, chat_fn=None)
            else:
                ir = interpret_observation(o["text"], contract_decision=d, chat_fn=chat_fn)
            texts.append(
                {
                    "text": o["text"],
                    "channel": o["channel"],
                    "skipped": False,
                    "outcome": ir.outcome,
                    "confidence": ir.confidence,
                    "reason": ir.reason,
                    "source": ir.source,
                }
            )
        # Aggregate only non-skipped
        active = [t for t in texts if not t.get("skipped")]
        outcomes[did] = aggregate_outcome(active)
        decision_traces[did] = {"per_text": texts, "aggregated": outcomes[did]}

    elig = eligibility_from_outcomes(outcomes, SLICE_DECISIONS)
    return {
        "candidate_id": cand["candidate_id"],
        "role": cand["role"],
        "search_context_obs": [
            {"text": o["text"], "channel": o["channel"]} for o in search_ctx
        ],
        "outcomes": outcomes,
        "eligibility": elig,
        "decision_traces": decision_traces,
        "causal_chain_summary": _causal_summary(cand, outcomes, elig, search_ctx),
    }


def _causal_summary(
    cand: dict[str, Any],
    outcomes: dict[str, str],
    elig: dict[str, Any],
    search_ctx: list[dict[str, Any]],
) -> list[str]:
    claims = [
        o["text"]
        for o in cand["obs"]
        if o["channel"] == "candidate_claim"
    ]
    lines = [
        f"candidate={cand['candidate_id']}",
        f"raw_claims={claims[:6]}",
        f"search_context={[o['text'] for o in search_ctx]} (not used for board/flight interp)",
        f"board_type={outcomes.get('board_type')} flight={outcomes.get('package_includes_flight')}",
        f"required board∈{SLICE_DECISIONS[0]['required_for_eligibility']} "
        f"flight∈{SLICE_DECISIONS[1]['required_for_eligibility']}",
        f"eligible={elig['eligible']}",
    ]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--observations", type=Path, default=None)
    ap.add_argument(
        "--fixture",
        action="store_true",
        help="Use evals/vertical_slice_positive_fixture_v0.jsonl (pos+neg+breakfast)",
    )
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--model", default="qwen3.8:27b")
    ap.add_argument("--min-entity-score", type=float, default=0.7)
    ap.add_argument("--out", type=Path, default=Path("vertical_slice_v0.json"))
    args = ap.parse_args()

    fixture_path = ROOT / "evals" / "vertical_slice_positive_fixture_v0.jsonl"
    if args.fixture:
        obs_path = fixture_path
        fixture_mode = True
        run_label = str(fixture_path)
    else:
        if not args.run_dir and not args.observations:
            print("Need --run-dir, --observations, or --fixture", file=sys.stderr)
            return 2
        obs_path = args.observations or (args.run_dir / "observations.jsonl")
        fixture_mode = False
        run_label = str(args.run_dir or obs_path)

    if not obs_path.exists():
        print(f"missing {obs_path}", file=sys.stderr)
        return 2

    built = build_from_observations_jsonl(
        obs_path, min_entity_score=args.min_entity_score
    )
    picks = pick_candidates(built, fixture_mode=fixture_mode)
    if not picks:
        print("no candidates picked", file=sys.stderr)
        return 2

    chat_fn = _make_chat_fn(args.model) if args.llm else None
    if not args.llm:
        print("[vertical_slice] no --llm → fail-closed UNKNOWN outcomes")

    results = []
    for cand in picks:
        print(f"--- {cand['role']}: {cand['candidate_id']} ---")
        r = interpret_candidate(cand, chat_fn)
        results.append(r)
        for line in r["causal_chain_summary"]:
            print(f"  {line}")
        print(
            f"  eligible={r['eligibility']['eligible']} details={r['eligibility']['details']}"
        )

    checks = []
    # Always: search_context not fed into board for any result
    meal_leaks = []
    for r in results:
        for t in r["decision_traces"]["board_type"]["per_text"]:
            if (
                not t.get("skipped")
                and "meal=" in (t.get("text") or "").lower()
            ):
                meal_leaks.append(r["candidate_id"])
    checks.append(
        {
            "id": "search_context_not_fed_to_board",
            "ok": len(meal_leaks) == 0,
            "leaks": meal_leaks,
        }
    )

    pos = next((r for r in results if r["role"] == "positive_ai_card"), None)
    ser = next((r for r in results if r["role"] == "negative_enkel_kamer"), None)
    brk = next((r for r in results if r["role"] == "breakfast_control"), None)

    if args.llm:
        if pos:
            checks.append(
                {
                    "id": "positive_eligible",
                    "ok": pos["eligibility"]["eligible"] is True,
                    "outcomes": pos["outcomes"],
                }
            )
            checks.append(
                {
                    "id": "positive_board_all_inclusive",
                    "ok": pos["outcomes"].get("board_type") == "ALL_INCLUSIVE",
                    "board_type": pos["outcomes"].get("board_type"),
                }
            )
            checks.append(
                {
                    "id": "positive_flight_included",
                    "ok": pos["outcomes"].get("package_includes_flight")
                    == "FLIGHT_INCLUDED",
                    "flight": pos["outcomes"].get("package_includes_flight"),
                }
            )
        elif fixture_mode:
            checks.append({"id": "positive_present", "ok": False})

        if ser:
            checks.append(
                {
                    "id": "negative_not_eligible",
                    "ok": ser["eligibility"]["eligible"] is False,
                    "outcomes": ser["outcomes"],
                }
            )
            checks.append(
                {
                    "id": "negative_board_not_all_inclusive",
                    "ok": ser["outcomes"].get("board_type") != "ALL_INCLUSIVE",
                    "board_type": ser["outcomes"].get("board_type"),
                }
            )
        if brk and args.llm:
            checks.append(
                {
                    "id": "breakfast_not_eligible",
                    "ok": brk["eligibility"]["eligible"] is False,
                    "outcomes": brk["outcomes"],
                }
            )
    else:
        checks.append(
            {
                "id": "dry_run_unknown",
                "ok": all(
                    r["outcomes"].get("board_type") == "UNKNOWN" for r in results
                ),
            }
        )

    go = all(c["ok"] for c in checks)
    out = {
        "schema_version": "vertical-slice-v0.1",
        "run_dir": run_label,
        "fixture_mode": fixture_mode,
        "llm": bool(args.llm),
        "decisions": [
            {"id": d["id"], "required": d.get("required_for_eligibility")}
            for d in SLICE_DECISIONS
        ],
        "results": results,
        "checks": checks,
        "go_no_go": {
            "go": go,
            "reasons": [c for c in checks if not c["ok"]]
            or ["all vertical-slice checks met"],
        },
        "note": (
            "This run had no real hotel card with All-inclusive in raw_evidence; "
            "use --fixture for positive path. Marketing entities with AI in name are excluded."
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

    print("=== Vertical slice v0 ===")
    print(f"candidates={len(results)} GO={go}")
    for c in checks:
        print(f"  {c['id']}: ok={c['ok']}")
    print(f"wrote {written}")
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
