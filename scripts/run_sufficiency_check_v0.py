#!/usr/bin/env python3
"""
Offline sufficiency gate checks against frozen contracts.

Demonstrates code STOP vs CONTINUE without running the full agent.

Examples:

  # Simulate Monica property-level evidence against both contracts
  python scripts/run_sufficiency_check_v0.py \\
    --contract evals/contract_synthesis/.../contract_02_....json \\
    --outcomes board_type=ALL_INCLUSIVE,page_identity=CONFIRMED,evidence_clarity=EXPLICIT

  # Same outcomes against package contract → should NOT satisfy
  python scripts/run_sufficiency_check_v0.py \\
    --contract .../contract_01_....json \\
    --outcomes board_type=ALL_INCLUSIVE

Boundary: code only reads frozen contract + outcomes. No domain hardcoding.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sufficiency import evaluate_sufficiency  # noqa: E402


def _parse_outcomes(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            out[part] = "UNKNOWN"
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True, help="Path to contract_*.json (synthesis output)")
    ap.add_argument(
        "--outcomes",
        default="",
        help="Comma list decision_id=OUTCOME (e.g. board_type=ALL_INCLUSIVE)",
    )
    ap.add_argument(
        "--proven-labels",
        default="",
        help="Comma list of free-text proven labels",
    )
    ap.add_argument("--allow-unfrozen", action="store_true")
    args = ap.parse_args()

    raw = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    # Accept either synthesis wrapper or bare contract
    contract = raw.get("contract") if isinstance(raw.get("contract"), dict) else raw
    outcomes = _parse_outcomes(args.outcomes)
    labels = [x.strip() for x in args.proven_labels.split(",") if x.strip()]

    result = evaluate_sufficiency(
        contract,
        outcomes,
        proven_labels=labels,
        require_frozen_flag=not args.allow_unfrozen,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("satisfied") else 1


if __name__ == "__main__":
    raise SystemExit(main())
