#!/usr/bin/env python3
"""
Offline Candidate extraction experiment (no browser, no LLM, no planner).

Purpose
-------
Verify the missing abstraction in isolation:

  page_text (+ optional affordances)
       → structural packaging
       → first-class Candidates
       → bound evidence + primary_action

Success criteria (scientific, not product):
  - Multiple distinct candidates on multi-offer list pages (not one spilled unit).
  - At least some candidates have primary_action (item link).
  - Evidence lines co-occur (name-ish + price-ish / date-ish in same candidate)
    without domain enums in code.
  - Single-entity detail pages still produce a coherent candidate with identity_hints.

Usage
-----
  # From a live trace artifacts folder (step_000_page_text.txt + affordances):
  python scripts/run_candidate_extraction_offline_v0.py \\
    --artifacts-dir path/to/step_artifacts \\
    --outdir ./evals/candidate_offline

  # Explicit files:
  python scripts/run_candidate_extraction_offline_v0.py \\
    --page-text step_000_page_text.txt \\
    --affordances step_000_affordances.json \\
    --url https://example/ \\
    --label 01_list \\
    --outdir ./evals/candidate_offline

  # Multiple labeled jobs from a manifest JSON:
  # [ {"label": "...", "page_text": "...", "affordances": "...", "url": "...", "surface": "..."} ]
  python scripts/run_candidate_extraction_offline_v0.py \\
    --manifest fixtures/candidate_offline_manifest.json \\
    --outdir ./evals/candidate_offline
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# repo root on path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from candidates import (  # noqa: E402
    candidates_preview,
    candidates_to_jsonable,
    extract_candidates,
    rank_candidates,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _run_one(
    *,
    label: str,
    page_text: str,
    affordances: list[dict],
    url: str,
    surface: str,
    max_candidates: int,
) -> dict:
    cands = extract_candidates(
        text=page_text,
        affordances=affordances,
        page_url=url,
        surface=surface,
        max_candidates=max_candidates,
    )
    cands = rank_candidates(cands)
    with_action = sum(1 for c in cands if c.has_action())
    with_identity = sum(1 for c in cands if c.identity_hints)
    dense = sum(1 for c in cands if c.structural_density() > 0)
    return {
        "label": label,
        "url": url,
        "surface": surface,
        "text_chars": len(page_text or ""),
        "affordance_n": len(affordances),
        "candidate_n": len(cands),
        "with_primary_action": with_action,
        "with_identity_hints": with_identity,
        "with_density": dense,
        "preview": candidates_preview(cands),
        "candidates": candidates_to_jsonable(cands),
    }


def _jobs_from_artifacts_dir(d: Path, label: str | None) -> list[dict]:
    """Discover step_*_page_text.txt + matching affordances in a trace dir."""
    jobs = []
    texts = sorted(d.glob("step_*_page_text.txt"))
    for tp in texts:
        # step_000_page_text.txt → step_000
        stem = tp.name.replace("_page_text.txt", "")
        aff_p = d / f"{stem}_affordances.json"
        aff = _load_json(aff_p) if aff_p.is_file() else []
        if isinstance(aff, dict) and "affordances" in aff:
            aff = aff["affordances"]
        if not isinstance(aff, list):
            aff = []
        # optional meta
        url = ""
        surface = ""
        meta_p = d / "meta.json"
        if meta_p.is_file():
            try:
                meta = _load_json(meta_p)
                url = str((meta.get("meta") or {}).get("start_url") or meta.get("start_url") or "")
            except Exception:
                pass
        jobs.append(
            {
                "label": label or f"{d.name}_{stem}",
                "page_text": str(tp),
                "affordances": str(aff_p) if aff_p.is_file() else "",
                "url": url,
                "surface": surface,
            }
        )
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page-text", default="", help="Path to page text file")
    ap.add_argument("--affordances", default="", help="Path to affordances JSON (list or {affordances:[]})")
    ap.add_argument("--url", default="", help="Source URL for provenance")
    ap.add_argument("--surface", default="", help="Optional surface tag")
    ap.add_argument("--label", default="job", help="Label for single job")
    ap.add_argument("--artifacts-dir", default="", help="Trace dir with step_*_page_text.txt")
    ap.add_argument("--manifest", default="", help="JSON list of jobs")
    ap.add_argument("--outdir", default="./evals/candidate_offline", help="Output directory")
    ap.add_argument("--max-candidates", type=int, default=3)
    args = ap.parse_args()

    jobs: list[dict] = []
    if args.manifest:
        jobs = _load_json(Path(args.manifest))
        if not isinstance(jobs, list):
            raise SystemExit("manifest must be a JSON list")
    elif args.artifacts_dir:
        jobs = _jobs_from_artifacts_dir(Path(args.artifacts_dir), args.label if args.label != "job" else None)
    elif args.page_text:
        jobs = [
            {
                "label": args.label,
                "page_text": args.page_text,
                "affordances": args.affordances,
                "url": args.url,
                "surface": args.surface,
            }
        ]
    else:
        ap.print_help()
        return 2

    out_root = Path(args.outdir)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    campaign_dir = out_root / f"{ts}_candidate_offline"
    campaign_dir.mkdir(parents=True, exist_ok=True)

    results = []
    print(f"Campaign dir: {campaign_dir}")
    print(f"Planned jobs: {len(jobs)}")

    for job in jobs:
        label = str(job.get("label") or "job")
        pt_path = Path(str(job.get("page_text") or ""))
        if not pt_path.is_file():
            print(f">> {label}  MISSING page_text={pt_path}")
            results.append({"label": label, "error": f"missing page_text: {pt_path}"})
            continue
        page_text = _load_text(pt_path)
        aff: list = []
        aff_s = str(job.get("affordances") or "")
        if aff_s and Path(aff_s).is_file():
            raw = _load_json(Path(aff_s))
            if isinstance(raw, list):
                aff = raw
            elif isinstance(raw, dict):
                aff = list(raw.get("affordances") or raw.get("all") or [])
        url = str(job.get("url") or args.url or "")
        surface = str(job.get("surface") or args.surface or "")

        result = _run_one(
            label=label,
            page_text=page_text,
            affordances=aff,
            url=url,
            surface=surface,
            max_candidates=args.max_candidates,
        )
        results.append(result)
        out_file = campaign_dir / f"candidates_{label}_{ts}.json"
        out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f">> {label}  candidates={result['candidate_n']} "
            f"action={result['with_primary_action']} "
            f"identity={result['with_identity_hints']} dens={result['with_density']}"
        )
        for line in result.get("preview") or []:
            print(f"   {line}")

    report = {
        "schema": "candidate-extraction-offline-v0",
        "created_at": ts,
        "campaign_dir": str(campaign_dir),
        "job_n": len(jobs),
        "results_summary": [
            {
                "label": r.get("label"),
                "candidate_n": r.get("candidate_n"),
                "with_primary_action": r.get("with_primary_action"),
                "with_identity_hints": r.get("with_identity_hints"),
                "error": r.get("error"),
            }
            for r in results
        ],
    }
    report_path = campaign_dir / f"campaign_report_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # also write full results
    (campaign_dir / f"all_results_{ts}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
