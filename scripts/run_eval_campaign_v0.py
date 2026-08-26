#!/usr/bin/env python3
"""
Long-running experimental campaign (one command, sequential, independent jobs).

Does NOT average results. Each experiment answers one research question.
Safe to run overnight / background:

  nohup python scripts/run_eval_campaign_v0.py --llm \\
    --observations runs/2026-08-24T08-01-36_compare_packages_dec2026/observations.jsonl \\
    --outdir ./evals/_campaign_out \\
    > ./evals/_campaign_out/campaign.log 2>&1 &

Phases:
  1 offline baseline (provenance, raw, admissibility)
  2 admissibility_recall + ablation   ← main research
  3 semantic regression (optional --llm)
  4 integration gate

Skip LLM-heavy work with --offline-only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run_job(
    name: str,
    argv: list[str],
    outdir: Path,
    timeout: int,
) -> dict[str, Any]:
    print(f"\n{'='*60}\n>> CAMPAIGN JOB: {name}\n{'='*60}", flush=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        dur = time.monotonic() - t0
        go = proc.returncode == 0
        # try parse GO from any json written to outdir matching name
        print(proc.stdout[-2000:] if proc.stdout else "", flush=True)
        if proc.returncode != 0 and proc.stderr:
            print(proc.stderr[-1500:], file=sys.stderr, flush=True)
        return {
            "name": name,
            "go": go,
            "exit_code": proc.returncode,
            "duration_s": round(dur, 2),
            "cmd": argv,
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "go": False,
            "exit_code": 124,
            "duration_s": timeout,
            "error": "timeout",
            "cmd": argv,
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--offline-only", action="store_true")
    ap.add_argument(
        "--observations",
        type=Path,
        default=ROOT
        / "runs"
        / "2026-08-24T08-01-36_compare_packages_dec2026"
        / "observations.jsonl",
    )
    ap.add_argument("--outdir", type=Path, default=ROOT / "evals" / "_campaign_out")
    ap.add_argument("--timeout-offline", type=int, default=120)
    ap.add_argument("--timeout-llm", type=int, default=900)
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    obs = str(args.observations)
    out = str(args.outdir)

    jobs: list[tuple[str, list[str], int]] = []

    # Phase 1 — offline baseline
    jobs.append(
        (
            "offline_suite",
            [
                py,
                str(SCRIPTS / "run_eval_suite_v0.py"),
                "--suite",
                "offline",
                "--observations",
                obs,
                "--outdir",
                out,
            ],
            args.timeout_offline * 3,
        )
    )

    # Phase 2 — research focus: recall + ablation
    jobs.append(
        (
            "admissibility_recall",
            [
                py,
                str(SCRIPTS / "run_admissibility_recall_v0.py"),
                "--observations",
                obs,
                "--out",
                str(args.outdir / "admissibility_recall_v0.json"),
            ],
            args.timeout_offline,
        )
    )
    jobs.append(
        (
            "admissibility_ablation",
            [
                py,
                str(SCRIPTS / "run_admissibility_ablation_v0.py"),
                "--observations",
                obs,
                "--out",
                str(args.outdir / "admissibility_ablation_v0.json"),
            ],
            args.timeout_offline,
        )
    )

    if not args.offline_only:
        # Phase 3 — semantic (independent; board failure is expected/known)
        jobs.append(
            (
                "semantic_suite",
                [
                    py,
                    str(SCRIPTS / "run_eval_suite_v0.py"),
                    "--suite",
                    "semantic",
                    *(["--llm"] if args.llm else []),
                    "--observations",
                    obs,
                    "--outdir",
                    out,
                ],
                args.timeout_llm * 4,
            )
        )
        # Phase 4 — integration
        jobs.append(
            (
                "integration_suite",
                [
                    py,
                    str(SCRIPTS / "run_eval_suite_v0.py"),
                    "--suite",
                    "integration",
                    *(["--llm"] if args.llm else []),
                    "--observations",
                    obs,
                    "--outdir",
                    out,
                ],
                args.timeout_llm * 2,
            )
        )

    results = []
    for name, argv, timeout in jobs:
        results.append(run_job(name, argv, args.outdir, timeout))

    report = {
        "schema_version": "eval-campaign-v0",
        "llm": bool(args.llm),
        "offline_only": bool(args.offline_only),
        "observations": obs,
        "results": results,
        "note": (
            "Each job is independent. interpretation_board may FAIL (Enkel kamer "
            "contract ambiguity) without invalidating vertical/batch/integration."
        ),
    }
    report_path = args.outdir / "campaign_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== CAMPAIGN SUMMARY ===")
    for r in results:
        print(f"  {'PASS' if r.get('go') else 'FAIL':4} {r['name']:28} {r.get('duration_s', 0):.0f}s")
    print(f"wrote {report_path}")
    # Campaign exit 0 if research jobs (recall+ablation) completed; don't require all green
    research_ok = all(
        r.get("exit_code") != 124
        for r in results
        if r["name"] in ("admissibility_recall", "admissibility_ablation")
    )
    return 0 if research_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
