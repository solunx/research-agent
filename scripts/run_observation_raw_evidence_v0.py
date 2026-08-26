#!/usr/bin/env python3
"""
Inspect + build observations from harvest observations.jsonl (raw_evidence).

No LLM. No semantic outcomes.

  python scripts/run_observation_raw_evidence_v0.py \
    --observations path/to/observations.jsonl \
    --out ./observation_raw_evidence_v0.json

  python scripts/run_observation_raw_evidence_v0.py \
    --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026 \
    --out ./observation_raw_evidence_v0.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observation_builder import (  # noqa: E402
    build_from_observations_jsonl,
    build_from_run_dir_rich,
    split_raw_evidence,
)


def _load_rows(path: Path, limit: int | None = None) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if limit and len(rows) >= limit:
            break
    return rows


def inspect_sample(rows: list[dict], n: int = 8) -> list[dict]:
    """Human-readable sample: entity, raw_evidence, segments."""
    # prefer high score + offer_price
    ranked = sorted(
        rows,
        key=lambda r: (
            float(r.get("entity_score") or 0),
            1 if r.get("attribute") == "offer_price" else 0,
            len(str(r.get("raw_evidence") or "")),
        ),
        reverse=True,
    )
    seen = set()
    samples = []
    for r in ranked:
        ent = str(r.get("entity") or "").strip()
        if not ent or ent in seen:
            continue
        seen.add(ent)
        raw = str(r.get("raw_evidence") or "")
        samples.append(
            {
                "entity": ent,
                "entity_score": r.get("entity_score"),
                "value": r.get("value"),
                "raw_evidence": raw,
                "segments": split_raw_evidence(raw),
                "source_url_tail": (str(r.get("source_url") or ""))[:120],
            }
        )
        if len(samples) >= n:
            break
    return samples


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observations", type=Path, default=None)
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--min-entity-score", type=float, default=0.7)
    ap.add_argument("--out", type=Path, default=Path("observation_raw_evidence_v0.json"))
    args = ap.parse_args()

    obs_path: Path | None = args.observations
    if args.run_dir:
        obs_path = args.run_dir / "observations.jsonl"

    if not obs_path or not obs_path.exists():
        # fallback: attachment paste if present in workspace
        alt = Path("/home/workdir/attachments/pasted-text.txt")
        if alt.exists():
            obs_path = alt
            print(f"[raw_evidence] using attachment {obs_path}")
        else:
            print("Need --observations or --run-dir with observations.jsonl", file=sys.stderr)
            return 2

    rows = _load_rows(obs_path)
    samples = inspect_sample(rows, n=10)

    if args.run_dir and (args.run_dir / "observations.jsonl").exists():
        built = build_from_run_dir_rich(
            args.run_dir,
            include_notes=False,
            include_shortlist=False,
            min_entity_score=args.min_entity_score,
        )
    else:
        built = build_from_observations_jsonl(
            obs_path, min_entity_score=args.min_entity_score
        )

    channel_counts: dict[str, int] = {}
    for o in built:
        channel_counts[o["channel"]] = channel_counts.get(o["channel"], 0) + 1

    # Checks: literal recovery markers (not outcomes)
    claim_texts = " | ".join(
        o["text"] for o in built if o["channel"] == "candidate_claim"
    ).lower()
    checks = [
        {
            "id": "has_candidates",
            "ok": len({o["candidate_id"] for o in built}) >= 1,
            "n": len({o["candidate_id"] for o in built}),
        },
        {
            "id": "flight_literal_recovered",
            "ok": "vlucht" in claim_texts or "flight" in claim_texts,
            "detail": "substring vlucht|flight in some candidate_claim",
        },
        {
            "id": "boardish_literal_recovered",
            "ok": any(
                x in claim_texts
                for x in ("enkel kamer", "ontbijt", "all-inclusive", "volpension", "room only")
            ),
            "detail": "board-ish literal present as text only",
        },
        {
            "id": "no_meal_eq_as_candidate_claim",
            "ok": not any(
                o["channel"] == "candidate_claim" and "meal=" in o["text"].lower()
                for o in built
            ),
        },
        {
            "id": "search_context_present",
            "ok": channel_counts.get("search_context", 0) > 0,
            "n": channel_counts.get("search_context", 0),
        },
        {
            "id": "no_outcome_fields",
            "ok": not any("outcome" in o or "board_type" in o for o in built),
        },
        {
            "id": "sercotel_enkel_if_present",
            "ok": True,  # soft: set below
            "detail": None,
        },
    ]
    sercotel_claims = [
        o["text"]
        for o in built
        if "sercotel" in o["candidate_id"].lower() and o["channel"] == "candidate_claim"
    ]
    if any("sercotel" in o["candidate_id"].lower() for o in built):
        checks[-1] = {
            "id": "sercotel_enkel_if_present",
            "ok": any("enkel" in t.lower() for t in sercotel_claims),
            "detail": sercotel_claims[:8],
        }

    go = all(c["ok"] for c in checks)
    out = {
        "source": str(obs_path),
        "rows_loaded": len(rows),
        "inspect_samples": samples,
        "built_n": len(built),
        "candidates": sorted({o["candidate_id"] for o in built}),
        "channel_counts": channel_counts,
        "built_preview": built[:40],
        "built": built,
        "checks": checks,
        "go_no_go": {
            "go": go,
            "reasons": [c for c in checks if not c["ok"]] or ["all checks met"],
        },
        "note": "Literal text only; interpretation remains separate.",
    }

    written = None
    for cand in (args.out, Path("/tmp") / args.out.name):
        try:
            cand.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            written = cand
            break
        except OSError:
            continue

    print("=== Observation from raw_evidence v0 ===")
    print(f"source={obs_path}")
    print(f"rows={len(rows)} built_n={len(built)} candidates={len(out['candidates'])}")
    print(f"channels={channel_counts}")
    print("--- inspect samples (entity | segments) ---")
    for s in samples[:6]:
        print(f"  {s['entity'][:40]!r} → {s['segments']}")
    for c in checks:
        print(f"  check {c['id']}: ok={c['ok']}")
    print(f"GO={go}")
    print(f"wrote {written}")
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
