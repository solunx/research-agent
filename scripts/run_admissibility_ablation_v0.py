#!/usr/bin/env python3
"""
Admissibility ablation — which structural inputs improve decisions?

Variants (same oracle, different feature masks):
  A entity_only
  B entity_attribute
  C entity_raw
  D full (entity + attribute + raw + url + scores)  ← current gate

  python scripts/run_admissibility_ablation_v0.py \
    --observations runs/.../observations.jsonl \
    --out ./admissibility_ablation_v0.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from candidate_admissibility import (  # noqa: E402
    ADMISSIBLE,
    NOT_ADMISSIBLE,
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


def mask_row(row: dict[str, Any], variant: str) -> dict[str, Any]:
    """Return a copy with only the features allowed for this ablation variant."""
    base = {
        "entity": row.get("entity"),
        "entity_score": 0.5,
        "marketing_penalty": 0.0,
        "confidence": 0.5,
        "attribute": "",
        "raw_evidence": "",
        "source_url": "",
        "page_url": "",
        "is_line_item": False,
        "cluster_size": 0,
    }
    if variant == "A_entity_only":
        base["entity"] = row.get("entity")
        return base
    if variant == "B_entity_attribute":
        base["entity"] = row.get("entity")
        base["attribute"] = row.get("attribute") or "offer_price"
        base["entity_score"] = float(row.get("entity_score") or 0.5)
        return base
    if variant == "C_entity_raw":
        base["entity"] = row.get("entity")
        base["raw_evidence"] = row.get("raw_evidence") or ""
        base["entity_score"] = float(row.get("entity_score") or 0.5)
        base["attribute"] = row.get("attribute") or "offer_price"
        return base
    # D_full
    return dict(row)


def synthetic_row(entity: str, obs_by: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if entity in obs_by:
        return obs_by[entity]
    return {
        "entity": entity,
        "entity_score": 0.85,
        "marketing_penalty": 0.0,
        "confidence": 0.9,
        "attribute": "offer_price",
        "raw_evidence": f"{entity} | All-inclusive | Heen- en terugvluchten | € 999",
        "source_url": "https://example.com/s/tsx?meal=all-inclusive",
        "is_line_item": True,
        "cluster_size": 1,
    }


def score_variant(
    oracle: list[dict[str, Any]],
    obs_by: dict[str, dict[str, Any]],
    variant: str,
) -> dict[str, Any]:
    n_hotel = n_hotel_ok = 0
    n_noise = n_noise_ok = 0
    n_long = n_long_ok = 0
    leaks = []
    killed_hotels = []

    for o in oracle:
        ent = str(o["entity"])
        exp = str(o["oracle"])
        bucket = str(o.get("bucket") or "")
        row = mask_row(synthetic_row(ent, obs_by), variant)
        pred = decide_admissibility(row)["decision"]

        if exp == ADMISSIBLE:
            n_hotel += 1
            if pred == ADMISSIBLE:
                n_hotel_ok += 1
            else:
                killed_hotels.append({"entity": ent, "pred": pred, "bucket": bucket})
            if bucket == "hotel_long":
                n_long += 1
                if pred == ADMISSIBLE:
                    n_long_ok += 1
        if exp == NOT_ADMISSIBLE:
            n_noise += 1
            if pred == NOT_ADMISSIBLE:
                n_noise_ok += 1
            if pred == ADMISSIBLE:
                leaks.append(ent)

    return {
        "variant": variant,
        "hotel_recall": (n_hotel_ok / n_hotel) if n_hotel else 1.0,
        "long_hotel_recall": (n_long_ok / n_long) if n_long else 1.0,
        "noise_rejection": (n_noise_ok / n_noise) if n_noise else 1.0,
        "noise_leaks": leaks,
        "n_killed_hotels": len(killed_hotels),
        "killed_hotels_sample": killed_hotels[:12],
        "n_hotel": n_hotel,
        "n_noise": n_noise,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument(
        "--oracle",
        type=Path,
        default=ROOT / "evals" / "admissibility_recall_oracle_v0.jsonl",
    )
    ap.add_argument("--out", type=Path, default=Path("admissibility_ablation_v0.json"))
    args = ap.parse_args()

    oracle = load_jsonl(args.oracle)
    obs_by = best_row_per_entity(load_jsonl(args.observations)) if args.observations.exists() else {}

    variants = [
        "A_entity_only",
        "B_entity_attribute",
        "C_entity_raw",
        "D_full",
    ]
    results = [score_variant(oracle, obs_by, v) for v in variants]

    # Rank by hotel_recall primary, noise_rejection secondary
    best = max(results, key=lambda r: (r["hotel_recall"], r["noise_rejection"]))
    worst = min(results, key=lambda r: (r["hotel_recall"], r["noise_rejection"]))

    out = {
        "schema_version": "admissibility-ablation-v0",
        "variants": results,
        "best_variant": best["variant"],
        "worst_variant": worst["variant"],
        "delta_hotel_recall_D_minus_A": results[3]["hotel_recall"] - results[0]["hotel_recall"],
        "interpretation": (
            "If D_full >> A_entity_only on hotel_recall without raising noise leaks, "
            "invest in richer harvest provenance/raw_evidence. "
            "If all variants similar and long_hotel_recall low, the bottleneck is "
            "name-length heuristics not missing fields."
        ),
        "go_no_go": {
            "go": True,
            "reasons": [
                "ablation is measurement-only; always GO when completed",
            ],
        },
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

    print("=== Admissibility ablation v0 ===")
    for r in results:
        print(
            f"  {r['variant']:22} hotel_recall={r['hotel_recall']:.3f} "
            f"long={r['long_hotel_recall']:.3f} noise_rej={r['noise_rejection']:.3f} "
            f"leaks={len(r['noise_leaks'])}"
        )
    print(f"best={best['variant']} worst={worst['variant']}")
    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
