#!/usr/bin/env python3
"""
Campaign runner: live offer-state / evidence acquisition.

  smoke   — open Monica, list affordances path via slice without LLM (force empty → STOP)
  lab     — Monica + Costa with lab force-click queue + LLM interpretation
  llm     — Costa/Monica pure acquisition LLM (no force list)
  full    — lab then llm presets

Example
-------
docker compose run --rm research-agent python scripts/run_live_offer_state_campaign_v0.py \\
  --campaign lab --llm --outdir ./evals/live_offer \\
  --flush-between-jobs --max-hours 3 --job-timeout-s 7200
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_job(
    job: dict,
    out_path: Path,
    *,
    use_llm: bool,
    flush: bool,
    timeout: int,
) -> dict:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_live_offer_state_slice_v0.py"),
        "--preset",
        job["preset"],
        "--out",
        str(out_path),
    ]
    if use_llm:
        cmd.append("--llm")
    if flush:
        cmd.append("--flush")

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = round(time.monotonic() - t0, 2)
        go = False
        fault_counts = None
        metrics = None
        if out_path.is_file():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
                go = bool((data.get("go_no_go") or {}).get("go"))
                fault_counts = data.get("fault_counts")
                metrics = data.get("metrics")
            except Exception:
                pass
        status = "DONE" if proc.returncode in (0, 1) else "FAILED"
        if proc.returncode not in (0, 1):
            go = False
        return {
            "job_id": job["job_id"],
            "status": status,
            "go": go,
            "fault_counts": fault_counts,
            "metrics": metrics,
            "duration_s": duration,
            "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-1500:],
        }
    except subprocess.TimeoutExpired as e:
        return {
            "job_id": job["job_id"],
            "status": "TIMEOUT",
            "go": False,
            "fault_counts": None,
            "duration_s": round(time.monotonic() - t0, 2),
            "stdout_tail": (e.stdout or "")[-1500:] if isinstance(e.stdout, str) else "",
            "stderr_tail": (e.stderr or "")[-1000:] if isinstance(e.stderr, str) else "",
        }


def jobs_for_campaign(name: str) -> list[dict]:
    name = name.lower().strip()
    if name == "smoke":
        return [
            {
                "job_id": "monica_smoke",
                "preset": "monica_lab",
                "label": "Monica open+force path without requiring LLM GO",
                "llm": False,
            }
        ]
    if name == "lab":
        return [
            {
                "job_id": "monica_lab",
                "preset": "monica_lab",
                "label": "Monica lab force clicks + LLM pipeline",
                "llm": True,
            },
            {
                "job_id": "costa_lab",
                "preset": "costa_lab",
                "label": "Costa lab force clicks + LLM pipeline",
                "llm": True,
            },
        ]
    if name == "llm":
        return [
            {
                "job_id": "monica_llm",
                "preset": "monica_llm",
                "label": "Monica pure acquisition LLM",
                "llm": True,
            },
            {
                "job_id": "costa_llm",
                "preset": "costa_llm",
                "label": "Costa pure acquisition LLM",
                "llm": True,
            },
        ]
    if name == "full":
        return jobs_for_campaign("lab") + jobs_for_campaign("llm")
    raise SystemExit(f"unknown campaign: {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default="lab", choices=["smoke", "lab", "llm", "full"])
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--outdir", type=Path, default=Path("./evals/live_offer"))
    ap.add_argument("--flush-between-jobs", action="store_true")
    ap.add_argument("--max-hours", type=float, default=4.0)
    ap.add_argument("--job-timeout-s", type=int, default=7200)
    args = ap.parse_args()

    jobs = jobs_for_campaign(args.campaign)
    camp_dir = Path(args.outdir) / f"{utc_stamp()}_{args.campaign}"
    camp_dir.mkdir(parents=True, exist_ok=True)
    print(f"Campaign dir: {camp_dir}")
    print(f"Planned jobs: {len(jobs)} (llm={args.llm})")

    manifest = {
        "schema": "live-offer-state-campaign-v0",
        "campaign": args.campaign,
        "llm": bool(args.llm),
        "jobs": jobs,
        "created_at": utc_stamp(),
    }
    (camp_dir / "campaign_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    results = []
    deadline = time.monotonic() + args.max_hours * 3600
    log_path = camp_dir / "campaign.log"
    with log_path.open("w", encoding="utf-8") as log:
        for job in jobs:
            if time.monotonic() > deadline:
                results.append({"job_id": job["job_id"], "status": "SKIPPED_TIME", "go": False})
                break
            out_path = camp_dir / f"{job['job_id']}.json"
            use_llm = bool(args.llm) and bool(job.get("llm", True)) and args.campaign != "smoke"
            msg = f">> {job['job_id']} — {job.get('label')} llm={use_llm}\n"
            print(msg, end="")
            log.write(msg)
            r = run_job(
                job,
                out_path,
                use_llm=use_llm,
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

    counts = {
        "completed": sum(1 for r in results if r.get("status") == "DONE"),
        "failed": sum(1 for r in results if r.get("status") == "FAILED"),
        "timeout": sum(1 for r in results if r.get("status") == "TIMEOUT"),
        "total_jobs": len(jobs),
    }
    report = {
        "schema": "live-offer-state-campaign-report-v0",
        "campaign": args.campaign,
        "counts": counts,
        "results": results,
        "hypothesis": (
            "Gap-driven acquisition (observe → interpret → if UNKNOWN, act on "
            "observed affordances only) can reach richer offer/price state without "
            "site-specific core rules. Lab force-clicks validate pipeline on known UI; "
            "llm preset tests generic planner."
        ),
    }
    (camp_dir / "campaign_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (camp_dir / "LATEST_REPORT.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print("=== LIVE OFFER STATE CAMPAIGN ===")
    print(f"counts: {counts}")
    for r in results:
        print(
            f"  {r.get('job_id')}: status={r.get('status')} go={r.get('go')} "
            f"faults={r.get('fault_counts')}"
        )
    print(f"wrote {camp_dir / 'campaign_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
