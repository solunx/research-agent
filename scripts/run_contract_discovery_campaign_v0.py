#!/usr/bin/env python3
"""
Contract Discovery campaign: CD0 vs CD1 vs CD2 across tasks.

Offline (heuristic, seconds):
  python scripts/run_contract_discovery_campaign_v0.py --campaign smoke \\
    --outdir ./evals/contract_discovery_campaign

Pilot + LLM (minutes–tens of minutes):
  python scripts/run_candidate_selection_campaign_v0.py  # unrelated
  python scripts/run_contract_discovery_campaign_v0.py --campaign pilot --llm \\
    --outdir ./evals/contract_discovery_campaign --max-hours 2

Resume-safe via manifest.
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


def load_manifest(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"jobs": {}, "created_at": utc_stamp()}


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def plan_jobs(campaign: str, use_llm: bool) -> list[dict[str, str]]:
    modes = ["CD0", "CD1", "CD2"]
    tasks = ["packages", "literature"]
    if campaign == "smoke":
        # heuristic-only matrix subset
        return [
            {"mode": "CD0", "task": "packages"},
            {"mode": "CD1", "task": "packages"},
            {"mode": "CD2", "task": "packages"},
        ]
    # pilot / full
    jobs = []
    for task in tasks:
        for mode in modes:
            jobs.append({"mode": mode, "task": task})
    return jobs


def run_one(
    mode: str,
    task: str,
    out_path: Path,
    use_llm: bool,
    timeout: int,
) -> dict[str, Any]:
    py = sys.executable
    argv = [
        py,
        str(SCRIPTS / "run_contract_discovery_mode_v0.py"),
        "--mode",
        mode,
        "--task",
        task,
        "--out",
        str(out_path),
    ]
    if use_llm:
        argv.append("--llm")
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
        metrics: dict[str, Any] = {}
        if out_path.exists():
            try:
                payload = json.loads(out_path.read_text(encoding="utf-8"))
                metrics = {
                    "validation_ok": (payload.get("validation") or {}).get("ok"),
                    "success_v0": payload.get("success_v0"),
                    "llm_calls": payload.get("llm_calls"),
                    "explains_run": (payload.get("gap_analysis") or {}).get(
                        "contract_explains_run"
                    ),
                    "decision_n": len((payload.get("contract") or {}).get("decisions") or []),
                    "jaccard": (
                        (payload.get("stability_provisional_to_final") or {}).get(
                            "jaccard_decisions"
                        )
                    ),
                    "go": (payload.get("go_no_go") or {}).get("go"),
                }
            except Exception:
                pass
        return {
            "status": "DONE" if proc.returncode == 0 else "FAILED",
            "exit_code": proc.returncode,
            "duration_s": round(dur, 2),
            "metrics": metrics,
            "stdout_tail": (proc.stdout or "")[-800:],
            "stderr_tail": (proc.stderr or "")[-400:],
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "exit_code": -1,
            "duration_s": round(time.monotonic() - t0, 2),
            "metrics": {},
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default="pilot", choices=["smoke", "pilot", "full"])
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--outdir", default="./evals/contract_discovery_campaign")
    ap.add_argument("--max-hours", type=float, default=2.0)
    ap.add_argument("--timeout-per-job", type=int, default=600)
    args = ap.parse_args()

    stamp = utc_stamp()
    camp_dir = Path(args.outdir) / f"{stamp}_{args.campaign}"
    camp_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = camp_dir / "campaign_manifest.json"
    manifest = load_manifest(manifest_path)
    manifest["campaign"] = args.campaign
    manifest["llm"] = bool(args.llm)
    manifest["started_at"] = manifest.get("started_at") or stamp

    jobs = plan_jobs(args.campaign, args.llm)
    print(f"Campaign dir: {camp_dir}")
    print(f"Planned jobs: {len(jobs)} (llm={args.llm})")

    deadline = time.monotonic() + args.max_hours * 3600
    counts = {"completed": 0, "failed": 0, "timeout": 0, "skipped": 0, "total_jobs": len(jobs)}

    for job in jobs:
        key = f"{job['mode']}__{job['task']}"
        prev = (manifest.get("jobs") or {}).get(key) or {}
        if prev.get("status") == "DONE":
            print(f">> skip {key} (already DONE)")
            counts["skipped"] += 1
            continue
        if time.monotonic() > deadline:
            print(f">> stop: max-hours reached before {key}")
            break
        out_path = camp_dir / f"{key}.json"
        print(f">> {key}")
        res = run_one(
            job["mode"],
            job["task"],
            out_path,
            use_llm=args.llm,
            timeout=args.timeout_per_job,
        )
        manifest.setdefault("jobs", {})[key] = {
            "mode": job["mode"],
            "task": job["task"],
            "status": res["status"],
            "exit_code": res["exit_code"],
            "duration_s": res["duration_s"],
            "out_path": str(out_path),
            "metrics": res.get("metrics") or {},
        }
        save_manifest(manifest_path, manifest)
        if res["status"] == "DONE":
            counts["completed"] += 1
        elif res["status"] == "TIMEOUT":
            counts["timeout"] += 1
        else:
            counts["failed"] += 1
        if res.get("stdout_tail"):
            print(res["stdout_tail"][-500:])

    # Report
    by_mode: dict[str, list] = {}
    for key, j in (manifest.get("jobs") or {}).items():
        m = j.get("mode") or key.split("__")[0]
        by_mode.setdefault(m, []).append(j.get("metrics") or {})

    summary_modes = {}
    for m, rows in by_mode.items():
        oks = [r for r in rows if r.get("validation_ok")]
        summary_modes[m] = {
            "n": len(rows),
            "validation_ok_rate": (len(oks) / len(rows)) if rows else 0.0,
            "avg_decision_n": (
                sum(float(r.get("decision_n") or 0) for r in rows) / len(rows) if rows else 0
            ),
            "avg_llm_calls": (
                sum(float(r.get("llm_calls") or 0) for r in rows) / len(rows) if rows else 0
            ),
        }

    report = {
        "schema_version": "contract-discovery-campaign-report-v0",
        "campaign_dir": str(camp_dir),
        "counts": counts,
        "by_mode": summary_modes,
        "jobs": manifest.get("jobs"),
        "note": (
            "CD0=task-only; CD1=task+samples one-shot; CD2=provisional→refine. "
            "Compare validation_ok, decision_n, explains_run, jaccard (CD2), llm_calls."
        ),
    }
    report_path = camp_dir / "campaign_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = Path(args.outdir) / "LATEST_REPORT.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== CONTRACT DISCOVERY CAMPAIGN REPORT ===")
    print(f"counts: {counts}")
    for m, s in summary_modes.items():
        print(f"  {m:4} n={s['n']} val_ok={s['validation_ok_rate']:.2f} "
              f"avg_decisions={s['avg_decision_n']:.1f} avg_llm_calls={s['avg_llm_calls']:.1f}")
    print(f"wrote {report_path}")
    return 0 if counts["failed"] == 0 and counts["timeout"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
