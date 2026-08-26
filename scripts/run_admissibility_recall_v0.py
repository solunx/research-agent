#!/usr/bin/env python3
"""
Admissibility recall experiment — measures hotel retention vs noise rejection.

Research question:
  Of all oracle-ADMISSIBLE entities, how many does the structural gate keep?
  Of all oracle-NOT_ADMISSIBLE noise, how many leak as ADMISSIBLE?

  python scripts/run_admissibility_recall_v0.py \
    --observations runs/.../observations.jsonl \
    --out ./admissibility_recall_v0.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from candidate_admissibility import (  # noqa: E402
    ADMISSIBLE,
    NOT_ADMISSIBLE,
    UNKNOWN,
    decide_admissibility,
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def best_row_per_entity(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        ent = str(r.get("entity") or "").strip()
        if not ent:
            continue

        def rank(x: dict[str, Any]) -> tuple:
            return (
                float(x.get("entity_score") or 0),
                float(x.get("confidence") or 0),
                len(str(x.get("raw_evidence") or "")),
            )

        if ent not in by or rank(r) > rank(by[ent]):
            by[ent] = r
    return by


def synthetic_row(entity: str, obs_by: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Use harvest row when present; else minimal synthetic for fixture-only names."""
    if entity in obs_by:
        return obs_by[entity]
    # Minimal structure so gate still runs (fixture-only hotels)
    return {
        "entity": entity,
        "entity_score": 0.85,
        "marketing_penalty": 0.0,
        "confidence": 0.9,
        "attribute": "offer_price",
        "raw_evidence": f"{entity} | All-inclusive | Heen- en terugvluchten vanaf Brussel | € 999",
        "source_url": "https://example.com/s/tsx?meal=all-inclusive",
        "is_line_item": True,
        "cluster_size": 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument(
        "--oracle",
        type=Path,
        default=ROOT / "evals" / "admissibility_recall_oracle_v0.jsonl",
    )
    ap.add_argument("--out", type=Path, default=Path("admissibility_recall_v0.json"))
    args = ap.parse_args()

    oracle = load_jsonl(args.oracle)
    obs_by = best_row_per_entity(load_jsonl(args.observations)) if args.observations.exists() else {}

    confusion: dict[str, Counter] = defaultdict(Counter)  # oracle -> pred count
    details = []
    bucket_stats: dict[str, dict[str, int]] = defaultdict(lambda: Counter())

    for o in oracle:
        ent = str(o["entity"])
        exp = str(o["oracle"])
        bucket = str(o.get("bucket") or "other")
        row = synthetic_row(ent, obs_by)
        from_harvest = ent in obs_by
        pred = decide_admissibility(row)["decision"]
        reasons = decide_admissibility(row)["reasons"]
        confusion[exp][pred] += 1
        bucket_stats[bucket][pred] += 1
        details.append(
            {
                "entity": ent,
                "bucket": bucket,
                "oracle": exp,
                "predicted": pred,
                "ok": pred == exp,
                "from_harvest": from_harvest,
                "reasons": reasons,
            }
        )

    # Metrics focused on research question
    oracle_a = [d for d in details if d["oracle"] == ADMISSIBLE]
    oracle_n = [d for d in details if d["oracle"] == NOT_ADMISSIBLE]
    hotel_long = [d for d in details if d["bucket"] == "hotel_long"]
    hotel_short = [d for d in details if d["bucket"] == "hotel_short"]

    def recall(group: list[dict], target: str = ADMISSIBLE) -> float:
        if not group:
            return 1.0
        return sum(1 for d in group if d["predicted"] == target) / len(group)

    hotel_recall = recall(oracle_a, ADMISSIBLE)
    # "survived" = not NOT_ADMISSIBLE (ADMISSIBLE or UNKNOWN kept for fail-closed ranking)
    hotel_not_killed = (
        sum(1 for d in oracle_a if d["predicted"] != NOT_ADMISSIBLE) / len(oracle_a)
        if oracle_a
        else 1.0
    )
    noise_rejection = (
        sum(1 for d in oracle_n if d["predicted"] == NOT_ADMISSIBLE) / len(oracle_n)
        if oracle_n
        else 1.0
    )
    noise_leak = (
        sum(1 for d in oracle_n if d["predicted"] == ADMISSIBLE) / len(oracle_n)
        if oracle_n
        else 0.0
    )
    long_hotel_recall = recall(hotel_long, ADMISSIBLE)
    short_hotel_recall = recall(hotel_short, ADMISSIBLE)

    checks = [
        {
            "id": "noise_leak_zero",
            "ok": noise_leak == 0.0,
            "noise_leak": noise_leak,
        },
        {
            "id": "noise_rejection_high",
            "ok": noise_rejection >= 0.85,
            "rate": noise_rejection,
        },
        {
            "id": "hotel_recall_report_only",
            "ok": True,  # informational — do not fail suite on low recall yet
            "hotel_recall_strict": hotel_recall,
            "hotel_not_killed": hotel_not_killed,
            "long_hotel_recall": long_hotel_recall,
            "short_hotel_recall": short_hotel_recall,
        },
        {
            "id": "has_oracle_rows",
            "ok": len(details) >= 20,
            "n": len(details),
        },
    ]
    # Soft GO: noise control is hard requirement; recall is measured not gated yet
    go = all(
        c["ok"]
        for c in checks
        if c["id"] in ("noise_leak_zero", "noise_rejection_high", "has_oracle_rows")
    )

    out = {
        "schema_version": "admissibility-recall-v0",
        "n_oracle": len(details),
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "metrics": {
            "hotel_admissible_recall": hotel_recall,
            "hotel_not_killed_rate": hotel_not_killed,
            "noise_rejection": noise_rejection,
            "noise_leak_as_admissible": noise_leak,
            "long_hotel_recall": long_hotel_recall,
            "short_hotel_recall": short_hotel_recall,
            "n_oracle_admissible": len(oracle_a),
            "n_oracle_noise": len(oracle_n),
        },
        "bucket_pred_counts": {k: dict(v) for k, v in bucket_stats.items()},
        "details": details,
        "checks": checks,
        "go_no_go": {
            "go": go,
            "reasons": [c for c in checks if not c["ok"] and c["id"] != "hotel_recall_report_only"]
            or ["noise control OK; hotel recall reported in metrics"],
        },
        "research_note": (
            "Low hotel_admissible_recall with high noise_rejection indicates "
            "over-aggressive structural heuristics (e.g. word_count), not semantic failure."
        ),
    }

    written = None
    for cand in (args.out, Path("/tmp") / args.out.name):
        try:
            cand.parent.mkdir(parents=True, exist_ok=True)
            cand.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            written = cand
            break
        except OSError:
            continue

    m = out["metrics"]
    print("=== Admissibility recall v0 ===")
    print(f"n={len(details)}")
    print(f"hotel_admissible_recall={m['hotel_admissible_recall']:.3f}")
    print(f"hotel_not_killed={m['hotel_not_killed_rate']:.3f}")
    print(f"long_hotel_recall={m['long_hotel_recall']:.3f} short={m['short_hotel_recall']:.3f}")
    print(f"noise_rejection={m['noise_rejection']:.3f} leak={m['noise_leak_as_admissible']:.3f}")
    print(f"confusion={out['confusion']}")
    print(f"GO={go}")
    print(f"wrote {written}")
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
