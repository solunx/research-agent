#!/usr/bin/env python3
"""
Campaign: live detail slice jobs (subprocess isolation + optional flush).

  # smoke: costa only, no LLM (fetch/B-C structural)
  python scripts/run_live_detail_campaign_v0.py --campaign smoke \
    --outdir ./evals/live_detail

  # pilot: costa+monica with LLM
  python scripts/run_live_detail_campaign_v0.py --campaign pilot --llm \
    --outdir ./evals/live_detail --flush-between-jobs --max-hours 2

  # primary: costa+monica+ivi
  python scripts/run_live_detail_campaign_v0.py --campaign primary --llm \
    --outdir ./evals/live_detail --flush-between-jobs --max-hours 3
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def plan_jobs(campaign: str) -> list[dict[str, Any]]:
    if campaign == "smoke":
        return [
            {
                "job_id": "costa_fetch",
                "preset": None,
                "entities": ["SBH Costa Calma Beach Resort"],
                "llm": False,
                "label": "Costa Calma fetch only (B/C)",
            }
        ]
    if campaign == "pilot":
        return [
            {
                "job_id": "costa_monica",
                "preset": "costa_monica",
                "entities": [],
                "llm": True,
                "label": "Costa + Monica live detail + LLM",
            }
        ]
    if campaign == "primary":
        return [
            {
                "job_id": "primary_detail",
                "preset": "primary_detail",
                "entities": [],
                "llm": True,
                "label": "Costa + Monica + IVI Mare live detail + LLM",
            }
        ]
    if campaign == "full":
        return plan_jobs("smoke") + plan_jobs("pilot")
    return plan_jobs("pilot")


def run_job(job: dict[str, Any], out_path: Path, *, use_llm: bool, flush: bool, backend: str, timeout: int) -> dict[str, Any]:
    py = sys.executable
    argv = [
        py,
        str(SCRIPTS / "run_live_detail_slice_v0.py"),
        "--backend",
        backend,
        "--out",
        str(out_path),
    ]
    if job.get("preset"):
        argv.extend(["--preset", job["preset"]])
    for ent in job.get("entities") or []:
        argv.extend(["--entities", ent])
    # campaign may force llm; job.llm is preferred when campaign llm flag set
    if use_llm and job.get("llm", True):
        argv.append("--llm")
    if flush:
        argv.append("--flush-model")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["OLLAMA_NOHISTORY"] = "1"
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
        duration = time.monotonic() - t0
        data = {}
        if out_path.exists():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        go = bool((data.get("go_no_go") or {}).get("go")) if data else False
        status = "DONE" if out_path.exists() else "FAILED"
        return {
            "job_id": job["job_id"],
            "label": job.get("label"),
            "status": status,
            "exit_code": proc.returncode,
            "duration_s": round(duration, 2),
            "go": go,
            "metrics": data.get("metrics"),
            "fault_counts": data.get("fault_counts"),
            "out": str(out_path),
            "stdout_tail": (proc.stdout or "")[-2500:],
            "stderr_tail": (proc.stderr or "")[-1500:],
        }
    except subprocess.TimeoutExpired:
        return {
            "job_id": job["job_id"],
            "status": "TIMEOUT",
            "duration_s": round(time.monotonic() - t0, 2),
            "go": False,
            "out": str(out_path),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", choices=["smoke", "pilot", "primary", "full"], default="smoke")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--backend", choices=["playwright", "fetch"], default="playwright")
    ap.add_argument("--flush-between-jobs", action="store_true")
    ap.add_argument("--outdir", type=Path, default=Path("./evals/live_detail"))
    ap.add_argument("--max-hours", type=float, default=3.0)
    ap.add_argument(
        "--job-timeout-s",
        type=int,
        default=7200,
        help="Per-job timeout seconds (default 2h; 1800 caused false TIMEOUT on 2 hotels)",
    )
    args = ap.parse_args()

    jobs = plan_jobs(args.campaign)
    # smoke jobs never need llm even if --llm passed
    stamp = utc_stamp()
    camp_dir = args.outdir / f"{stamp}_{args.campaign}"
    camp_dir.mkdir(parents=True, exist_ok=True)

    print(f"Campaign dir: {camp_dir}")
    print(f"Planned jobs: {len(jobs)} (llm={args.llm} backend={args.backend})")

    manifest = {
        "schema": "live-detail-campaign-v0",
        "created_at": stamp,
        "campaign": args.campaign,
        "llm": args.llm,
        "backend": args.backend,
        "jobs": jobs,
    }
    (camp_dir / "campaign_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    results = []
    deadline = time.monotonic() + args.max_hours * 3600
    log_path = camp_dir / "campaign.log"
    with log_path.open("w", encoding="utf-8") as log:
        for job in jobs:
            if time.monotonic() > deadline:
                results.append({"job_id": job["job_id"], "status": "SKIPPED_TIME", "go": False})
                break
            out_path = camp_dir / f"{job['job_id']}.json"
            # smoke: ignore --llm
            use_llm = bool(args.llm) and bool(job.get("llm", True)) and args.campaign != "smoke"
            if job["job_id"] == "costa_fetch":
                use_llm = False
            msg = f">> {job['job_id']} — {job.get('label')} llm={use_llm}\n"
            print(msg, end="")
            log.write(msg)
            r = run_job(
                job,
                out_path,
                use_llm=use_llm,
                flush=args.flush_between_jobs,
                backend=args.backend,
                timeout=args.job_timeout_s,
            )
            results.append(r)
            line = f"   status={r.get('status')} go={r.get('go')} faults={r.get('fault_counts')} duration={r.get('duration_s')}s\n"
            print(line, end="")
            log.write(line)
            if r.get("stdout_tail"):
                log.write(r["stdout_tail"] + "\n")
            if r.get("stderr_tail"):
                log.write("STDERR:\n" + r["stderr_tail"] + "\n")
            log.flush()

    counts = {
        "completed": sum(1 for r in results if r.get("status") == "DONE"),
        "failed": sum(1 for r in results if r.get("status") == "FAILED"),
        "timeout": sum(1 for r in results if r.get("status") == "TIMEOUT"),
        "total_jobs": len(jobs),
    }
    report = {
        "schema": "live-detail-campaign-report-v0",
        "campaign_dir": str(camp_dir),
        "campaign": args.campaign,
        "counts": counts,
        "results": results,
        "hypothesis": (
            "Live OPEN detail_url → observations → frozen pipeline. "
            "If GO with LLM: B/C can feed proven D–F. "
            "If D_missing_board_literal: page text lacks AI claims (extract/depth). "
            "If FETCH_FAILED: retrieval/browser capability boundary."
        ),
    }
    (camp_dir / "campaign_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (args.outdir / "LATEST_REPORT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("=== LIVE DETAIL CAMPAIGN ===")
    print(f"counts: {counts}")
    for r in results:
        print(f"  {r.get('job_id')}: status={r.get('status')} go={r.get('go')} faults={r.get('fault_counts')}")
    print(f"wrote {camp_dir / 'campaign_report.json'}")
    if counts["failed"] or counts["timeout"]:
        return 1
    if args.llm and args.campaign != "smoke" and any(
        r.get("status") == "DONE" and not r.get("go") for r in results
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
