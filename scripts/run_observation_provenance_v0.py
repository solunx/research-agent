#!/usr/bin/env python3
"""
Observation provenance/scope fixture test — no LLM.

  python scripts/run_observation_provenance_v0.py
  python scripts/run_observation_provenance_v0.py --out ./observation_provenance_v0.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observation_builder import build_from_fixture_cases  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "evals" / "observation_provenance_fixture_v0.json",
    )
    ap.add_argument("--out", type=Path, default=Path("observation_provenance_v0.json"))
    args = ap.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    built = build_from_fixture_cases(cases)

    def match(o: dict, exp: dict) -> bool:
        if exp.get("candidate_id") and o["candidate_id"] != exp["candidate_id"]:
            return False
        if exp.get("channel") and o["channel"] != exp["channel"]:
            return False
        if exp.get("scope") and o.get("scope") != exp["scope"]:
            return False
        needle = (exp.get("text_contains") or "").lower()
        if needle and needle not in (o.get("text") or "").lower():
            return False
        return True

    expectation_results = []
    for exp in fixture.get("expectations") or []:
        hits = [o for o in built if match(o, exp)]
        expectation_results.append(
            {"id": exp["id"], "ok": len(hits) >= 1, "hits": len(hits), "exp": exp}
        )

    forbidden_results = []
    for forb in fixture.get("forbiddens") or []:
        if forb.get("forbid_keys"):
            bad = []
            for o in built:
                for k in forb["forbid_keys"]:
                    if k in o:
                        bad.append(o)
            forbidden_results.append(
                {"id": forb["id"], "ok": len(bad) == 0, "violations": len(bad)}
            )
            continue
        viol = [o for o in built if match(o, forb)]
        forbidden_results.append(
            {
                "id": forb["id"],
                "ok": len(viol) == 0,
                "violations": len(viol),
                "samples": viol[:3],
            }
        )

    channel_counts: dict[str, int] = {}
    for o in built:
        channel_counts[o["channel"]] = channel_counts.get(o["channel"], 0) + 1

    all_ok = all(r["ok"] for r in expectation_results) and all(
        r["ok"] for r in forbidden_results
    )

    out = {
        "built_n": len(built),
        "built": built,
        "channel_counts": channel_counts,
        "expectations": expectation_results,
        "forbiddens": forbidden_results,
        "go_no_go": {
            "go": all_ok,
            "reasons": (
                [r for r in expectation_results if not r["ok"]]
                + [r for r in forbidden_results if not r["ok"]]
            )
            or ["all provenance checks met"],
        },
        "notes_policy": "notes not used in this fixture path",
    }

    # Prefer cwd write; fallback /tmp
    written = None
    for cand in (args.out, Path("/tmp") / args.out.name):
        try:
            cand.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            written = cand
            break
        except OSError:
            continue

    print("=== Observation provenance v0 ===")
    print(f"built_n={len(built)} channels={channel_counts}")
    for r in expectation_results:
        print(f"  expect {r['id']}: ok={r['ok']}")
    for r in forbidden_results:
        print(f"  forbid {r['id']}: ok={r['ok']}")
    print(f"GO={all_ok}")
    print(f"wrote {written}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
