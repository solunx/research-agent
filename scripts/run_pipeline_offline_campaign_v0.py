#!/usr/bin/env python3
"""
Offline pipeline campaign — independent subprocess jobs per fixture.

  # smoke (no LLM)
  python scripts/run_pipeline_offline_campaign_v0.py --campaign smoke \\
    --outdir ./evals/pipeline_offline

  # pilot with LLM
  python scripts/run_pipeline_offline_campaign_v0.py --campaign pilot --llm \\
    --outdir ./evals/pipeline_offline --max-hours 4 --flush-between-jobs
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

FIXTURES = {
    "batch": EVALS / "vertical_slice_batch_fixture_v0.jsonl",
    "positive": EVALS / "vertical_slice_positive_fixture_v0.jsonl",
}

DEFAULT_RUN_DIR = Path("runs/2026-08-24T08-01-36_compare_packages_dec2026")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def plan_jobs(campaign: str, *, run_dir: Path | None = None) -> list[dict[str, Any]]:
    if campaign == "smoke":
        return [{"fixture_id": "batch", "path": str(FIXTURES["batch"]), "kind": "fixture"}]
    if campaign == "pilot":
        return [
            {"fixture_id": "batch", "path": str(FIXTURES["batch"]), "kind": "fixture"},
            {"fixture_id": "positive", "path": str(FIXTURES["positive"]), "kind": "fixture"},
        ]
    if campaign == "from_run":
        rd = run_dir or DEFAULT_RUN_DIR
        return [
            {
                "fixture_id": "from_run",
                "path": str(rd),
                "kind": "run_dir",
                "oracle": str(EVALS / "run_slice_oracle_v0.jsonl"),
            }
        ]
    if campaign == "full":
        jobs = plan_jobs("pilot")
        jobs.extend(plan_jobs("from_run", run_dir=run_dir))
        return jobs
    return plan_jobs("pilot")



def run_one_from_run(
    run_dir: str,
    out_path: Path,
    *,
    oracle: str | None,
    use_llm: bool,
    flush: bool,
    timeout: int,
) -> dict[str, Any]:
    py = sys.executable
    argv = [
        py,
        str(SCRIPTS / "run_pipeline_from_run_v0.py"),
        "--run-dir",
        run_dir,
        "--out",
        str(out_path),
        "--max-candidates",
        "15",
    ]
    if oracle:
        argv.extend(["--oracle", oracle])
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
        dur = time.monotonic() - t0
        metrics: dict[str, Any] = {}
        go = None
        if out_path.exists():
            try:
                payload = json.loads(out_path.read_text(encoding="utf-8"))
                metrics = payload.get("metrics") or {}
                go = (payload.get("go_no_go") or {}).get("go")
            except Exception:
                pass
        status = "DONE" if out_path.exists() else "FAILED"
        return {
            "status": status,
            "exit_code": proc.returncode,
            "duration_s": round(dur, 2),
            "metrics": metrics,
            "go": go,
            "stdout_tail": (proc.stdout or "")[-800:],
            "stderr_tail": (proc.stderr or "")[-400:],
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "exit_code": -1,
            "duration_s": round(time.monotonic() - t0, 2),
            "metrics": {},
            "go": None,
            "stdout_tail": "",
            "stderr_tail": "timeout",
        }


def run_one(
    fixture_id: str,
    fixture_path: str,
    out_path: Path,
    *,
    use_llm: bool,
    flush: bool,
    timeout: int,
) -> dict[str, Any]:
    py = sys.executable
    argv = [
        py,
        str(SCRIPTS / "run_pipeline_offline_experiment_v0.py"),
        "--fixture",
        fixture_path,
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
        dur = time.monotonic() - t0
        metrics: dict[str, Any] = {}
        go = None
        if out_path.exists():
            try:
                payload = json.loads(out_path.read_text(encoding="utf-8"))
                metrics = payload.get("metrics") or {}
                go = (payload.get("go_no_go") or {}).get("go")
            except Exception:
                pass
        status = "DONE" if out_path.exists() else "FAILED"
        return {
            "status": status,
            "exit_code": proc.returncode,
            "duration_s": round(dur, 2),
            "metrics": metrics,
            "go": go,
            "stdout_tail": (proc.stdout or "")[-800:],
            "stderr_tail": (proc.stderr or "")[-400:],
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "exit_code": -1,
            "duration_s": round(time.monotonic() - t0, 2),
            "metrics": {},
            "go": None,
            "stdout_tail": "",
            "stderr_tail": "timeout",
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default="pilot", choices=["smoke", "pilot", "full", "from_run"])
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--outdir", default="./evals/pipeline_offline")
    ap.add_argument("--max-hours", type=float, default=4.0)
    ap.add_argument("--timeout-per-job", type=int, default=3600)
    ap.add_argument("--flush-between-jobs", action="store_true")
    args = ap.parse_args()

    stamp = utc_stamp()
    camp_dir = Path(args.outdir) / f"{stamp}_{args.campaign}"
    camp_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = camp_dir / "campaign_manifest.json"
    log_path = camp_dir / "campaign.log"

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "jobs": {},
            "created_at": stamp,
            "campaign": args.campaign,
            "llm": bool(args.llm),
            "flush_between_jobs": bool(args.flush_between_jobs),
            "started_at": stamp,
        }

    jobs = plan_jobs(args.campaign, run_dir=args.run_dir)
    print(f"Campaign dir: {camp_dir}")
    print(f"Planned jobs: {len(jobs)} (llm={args.llm})")

    deadline = time.monotonic() + args.max_hours * 3600
    counts = {"completed": 0, "failed": 0, "timeout": 0, "skipped": 0, "total_jobs": len(jobs)}

    def log(msg: str) -> None:
        print(msg, flush=True)
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(msg if msg.endswith("\n") else msg + "\n")
        except OSError as e:
            print(f"[warn] log write failed: {e}", flush=True)

    for job in jobs:
        key = job["fixture_id"]
        prev = (manifest.get("jobs") or {}).get(key) or {}
        if prev.get("status") == "DONE":
            log(f">> skip {key}")
            counts["skipped"] += 1
            continue
        if time.monotonic() > deadline:
            log(f">> stop max-hours before {key}")
            break

        out_path = camp_dir / f"{key}.json"
        log(f">> {key}")
        if job.get("kind") == "run_dir":
            res = run_one_from_run(
                job["path"],
                out_path,
                oracle=job.get("oracle"),
                use_llm=args.llm,
                flush=args.flush_between_jobs,
                timeout=args.timeout_per_job,
            )
        else:
            res = run_one(
                job["fixture_id"],
                job["path"],
                out_path,
                use_llm=args.llm,
                flush=args.flush_between_jobs,
                timeout=args.timeout_per_job,
            )
        manifest.setdefault("jobs", {})[key] = {
            "fixture_id": job["fixture_id"],
            "path": job["path"],
            "status": res["status"],
            "exit_code": res["exit_code"],
            "duration_s": res["duration_s"],
            "out_path": str(out_path),
            "metrics": res.get("metrics") or {},
            "go": res.get("go"),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if res["status"] == "DONE":
            counts["completed"] += 1
        elif res["status"] == "TIMEOUT":
            counts["timeout"] += 1
        else:
            counts["failed"] += 1
        if res.get("stdout_tail"):
            log(res["stdout_tail"][-600:])
        if args.flush_between_jobs:
            time.sleep(1.0)

    manifest["counts"] = counts
    manifest["finished_at"] = utc_stamp()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = {
        "schema_version": "pipeline-offline-campaign-report-v0",
        "campaign_dir": str(camp_dir),
        "counts": counts,
        "jobs": manifest.get("jobs"),
        "hypothesis": (
            "Offline chain observation→CANDIDATE_UNIT→interpretation→code eligibility "
            "matches package fixture expectations without domain heuristics."
        ),
        "isolation": {
            "subprocess_per_job": True,
            "keep_alive_0": True,
            "flush_between_jobs": bool(args.flush_between_jobs),
        },
    }
    report_path = camp_dir / "campaign_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = Path(args.outdir) / "LATEST_REPORT.json"
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    log("=== PIPELINE OFFLINE CAMPAIGN ===")
    log(f"counts: {counts}")
    for k, j in (manifest.get("jobs") or {}).items():
        m = j.get("metrics") or {}
        log(
            f"  {k}: go={j.get('go')} match_rate={m.get('eligibility_match_rate')} "
            f"pos={m.get('positive_eligible_ok')}/{m.get('positive_n')} "
            f"neg={m.get('negative_not_eligible_ok')}/{m.get('negative_n')} "
            f"leaks={m.get('search_context_board_leaks')}"
        )
    log(f"wrote {report_path}")
    return 0 if counts["failed"] == 0 and counts["timeout"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
