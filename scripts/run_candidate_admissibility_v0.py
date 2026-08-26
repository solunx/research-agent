#!/usr/bin/env python3
"""
Candidate Admissibility v0 — structural only, no LLM.

  python scripts/run_candidate_admissibility_v0.py \
    --observations runs/.../observations.jsonl \
    --out ./candidate_admissibility_v0.json

  # or attachment / any jsonl harvest dump
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
    UNKNOWN,
    decide_admissibility,
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
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

        prev = by.get(ent)
        if prev is None or rank(r) > rank(prev):
            by[ent] = r
    return by


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument(
        "--oracle",
        type=Path,
        default=ROOT / "evals" / "candidate_admissibility_oracle_v0.jsonl",
    )
    ap.add_argument("--out", type=Path, default=Path("candidate_admissibility_v0.json"))
    args = ap.parse_args()

    if not args.observations.exists():
        print(f"missing {args.observations}", file=sys.stderr)
        return 2

    rows = load_jsonl(args.observations)
    by_ent = best_row_per_entity(rows)

    results = []
    for ent, row in sorted(by_ent.items(), key=lambda x: x[0].lower()):
        dec = decide_admissibility(row)
        results.append(
            {
                "entity": ent,
                "decision": dec["decision"],
                "reasons": dec["reasons"],
                "features": {
                    k: dec["features"][k]
                    for k in (
                        "entity_score",
                        "marketing_penalty",
                        "confidence",
                        "attribute",
                        "pipe_segments",
                        "named_offer_shape",
                        "url_is_search_list",
                    )
                    if k in dec["features"]
                },
            }
        )

    counts = {
        ADMISSIBLE: 0,
        NOT_ADMISSIBLE: 0,
        UNKNOWN: 0,
    }
    for r in results:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1

    # Oracle evaluation (labels are evaluation-only; engine does not hardcode them)
    oracle_rows = load_jsonl(args.oracle) if args.oracle.exists() else []
    oracle_eval = []
    for o in oracle_rows:
        ent = str(o.get("entity") or "")
        exp = str(o.get("expected") or "")
        got = next((r["decision"] for r in results if r["entity"] == ent), None)
        if got is None:
            # try case-insensitive / partial
            got = next(
                (
                    r["decision"]
                    for r in results
                    if r["entity"].lower() == ent.lower()
                ),
                None,
            )
        ok = got == exp
        oracle_eval.append(
            {
                "entity": ent,
                "role": o.get("role"),
                "expected": exp,
                "actual": got,
                "ok": ok,
                "missing": got is None,
            }
        )

    # GO criteria (structural gate quality, not perfect hotel classifier)
    hotel_cards = [x for x in oracle_eval if x.get("role") == "hotel_card"]
    chrome_mkt = [
        x
        for x in oracle_eval
        if x.get("role") in ("chrome", "marketing", "cta", "generic_label")
    ]
    hotel_recall = (
        sum(1 for x in hotel_cards if x["actual"] == ADMISSIBLE) / len(hotel_cards)
        if hotel_cards
        else 1.0
    )
    noise_rejected = (
        sum(1 for x in chrome_mkt if x["actual"] == NOT_ADMISSIBLE) / len(chrome_mkt)
        if chrome_mkt
        else 1.0
    )
    # No semantic enums in reasons
    semantic_leak = any(
        any(
            t in " ".join(r["reasons"]).lower()
            for t in ("all_inclusive", "room_only", "breakfast", "board_type")
        )
        for r in results
    )

    checks = [
        {
            "id": "hotel_card_recall",
            "ok": hotel_recall >= 0.8,
            "recall": hotel_recall,
            "n": len(hotel_cards),
        },
        {
            "id": "noise_not_admissible_rate",
            "ok": noise_rejected >= 0.7,
            "rate": noise_rejected,
            "n": len(chrome_mkt),
        },
        {
            "id": "no_semantic_reason_codes",
            "ok": not semantic_leak,
        },
        {
            "id": "unknown_allowed",
            "ok": True,
            "n_unknown": counts.get(UNKNOWN, 0),
            "detail": "UNKNOWN is a valid structural outcome",
        },
    ]
    go = all(c["ok"] for c in checks)

    out = {
        "schema_version": "candidate-admissibility-v0",
        "source": str(args.observations),
        "n_entities": len(results),
        "counts": counts,
        "results": results,
        "oracle_eval": oracle_eval,
        "checks": checks,
        "go_no_go": {
            "go": go,
            "reasons": [c for c in checks if not c["ok"]]
            or ["admissibility v0 checks met"],
        },
        "note": (
            "Structural only. Destinations may be UNKNOWN. "
            "If many UNKNOWN: harvest lacks structure — improve provenance, not executor."
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

    print("=== Candidate Admissibility v0 ===")
    print(f"entities={len(results)} counts={counts}")
    print(f"hotel_card_recall={hotel_recall:.2f} noise_reject={noise_rejected:.2f}")
    for x in oracle_eval:
        mark = "OK" if x["ok"] else "FAIL"
        print(
            f"  [{mark}] {x['entity'][:45]!r} exp={x['expected']} got={x['actual']}"
        )
    print(f"GO={go}")
    print(f"wrote {written}")
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
