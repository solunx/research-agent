#!/usr/bin/env python3
"""
Campaign runner for Positive Evidence Trace v0 (independent subprocess jobs).

  # smoke — no LLM, structural D + fail-closed path
  python scripts/run_positive_evidence_trace_campaign_v0.py --campaign smoke \
    --outdir ./evals/evidence_trace

  # Test A — detail evidence (Costa Calma + Monica + IVI Mare)
  python scripts/run_positive_evidence_trace_campaign_v0.py --campaign detail --llm \
    --outdir ./evals/evidence_trace --flush-between-jobs --max-hours 2

  # Test B — offer-state + incomplete list controls
  python scripts/run_positive_evidence_trace_campaign_v0.py --campaign offer_state --llm \
    --outdir ./evals/evidence_trace --flush-between-jobs --max-hours 2

  # both
  python scripts/run_positive_evidence_trace_campaign_v0.py --campaign full --llm \
    --outdir ./evals/evidence_trace --flush-between-jobs --max-hours 4
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
EVALS = ROOT / "evals"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def plan_jobs(campaign: str) -> list[dict[str, Any]]:
    detail = {
        "job_id": "detail",
        "preset": "detail",
        "label": "Test A: detail-page AI evidence (simulated harvest)",
    }
    offer = {
        "job_id": "offer_state",
        "preset": "offer_state",
        "label": "Test B: offer-state vs incomplete list/hotel options",
    }
    if campaign == "smoke":
        return [detail]  # dry path without requiring LLM in campaign if --llm off
    if campaign == "detail":
        return [detail]
    if campaign == "offer_state":
        return [offer]
    if campaign == "full":
        return [detail, offer]
    return [detail, offer]


def run_job(
    job: dict[str, Any],
    out_path: Path,
    *,
    use_llm: bool,
    flush: bool,
    timeout: int,
) -> dict[str, Any]:
    py = sys.executable
    argv = [
        py,
        str(SCRIPTS / "run_positive_evidence_trace_v0.py"),
        "--preset",
        job["preset"],
        "--oracle",
        str(EVALS / "positive_evidence_trace_oracle_v0.jsonl"),
        "--out",
        str(out_path),
    ]
    if use_llm:
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
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if out_path.exists():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}
        go = bool((data.get("go_no_go") or {}).get("go")) if data else False
        # dry-run without llm still go on structural path
        status = "DONE" if out_path.exists() else "FAILED"
        if proc.returncode not in (0, 1) and not out_path.exists():
            status = "FAILED"
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
            "stdout_tail": stdout[-2000:],
            "stderr_tail": stderr[-1500:],
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
    ap.add_argument(
        "--campaign",
        choices=["smoke", "detail", "offer_state", "full"],
        default="smoke",
    )
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--flush-between-jobs", action="store_true")
    ap.add_argument("--outdir", type=Path, default=Path("./evals/evidence_trace"))
    ap.add_argument("--max-hours", type=float, default=4.0)
    ap.add_argument("--job-timeout-s", type=int, default=3600)
    args = ap.parse_args()

    jobs = plan_jobs(args.campaign)
    stamp = utc_stamp()
    camp_dir = args.outdir / f"{stamp}_{args.campaign}"
    camp_dir.mkdir(parents=True, exist_ok=True)
    log_path = camp_dir / "campaign.log"

    print(f"Campaign dir: {camp_dir}")
    print(f"Planned jobs: {len(jobs)} (llm={args.llm} flush={args.flush_between_jobs})")

    manifest = {
        "schema": "positive-evidence-trace-campaign-v0",
        "created_at": stamp,
        "campaign": args.campaign,
        "llm": args.llm,
        "flush_between_jobs": args.flush_between_jobs,
        "jobs": jobs,
    }
    (camp_dir / "campaign_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    results: list[dict[str, Any]] = []
    deadline = time.monotonic() + args.max_hours * 3600
    with log_path.open("w", encoding="utf-8") as log:
        for job in jobs:
            if time.monotonic() > deadline:
                results.append({"job_id": job["job_id"], "status": "SKIPPED_TIME", "go": False})
                log.write(f"SKIP time budget {job['job_id']}\n")
                continue
            out_path = camp_dir / f"{job['job_id']}.json"
            msg = f">> {job['job_id']} — {job.get('label')}\n"
            print(msg, end="")
            log.write(msg)
            log.flush()
            r = run_job(
                job,
                out_path,
                use_llm=args.llm,
                flush=args.flush_between_jobs,
                timeout=args.job_timeout_s,
            )
            results.append(r)
            line = (
                f"   status={r.get('status')} go={r.get('go')} "
                f"faults={r.get('fault_counts')} duration={r.get('duration_s')}s\n"
            )
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
        "skipped": sum(1 for r in results if str(r.get("status", "")).startswith("SKIP")),
        "total_jobs": len(jobs),
    }
    report = {
        "schema": "positive-evidence-trace-campaign-report-v0",
        "campaign_dir": str(camp_dir),
        "campaign": args.campaign,
        "counts": counts,
        "results": results,
        "hypothesis": (
            "If detail fixture GO with LLM: D→F works when literals present. "
            "If offer_state GO: selected booking-state AI passes; incomplete list/hotel options fail. "
            "Live harvest still required to prove B/C on real sites."
        ),
    }
    report_path = camp_dir / "campaign_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    latest = args.outdir / "LATEST_REPORT.json"
    latest.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== POSITIVE EVIDENCE TRACE CAMPAIGN ===")
    print(f"counts: {counts}")
    for r in results:
        print(
            f"  {r.get('job_id')}: status={r.get('status')} go={r.get('go')} "
            f"faults={r.get('fault_counts')}"
        )
    print(f"wrote {report_path}")
    # exit 0 if all DONE and (if llm) all go; smoke without llm may go true structurally
    if counts["failed"] or counts["timeout"]:
        return 1
    if args.llm and any(r.get("status") == "DONE" and not r.get("go") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
