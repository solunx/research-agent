#!/usr/bin/env python3
"""
Task.md batch campaign v0 — multi-domain surface area for the generic agent.

Runs each selected task.md as an isolated job (subprocess agent.py), with optional
LLM and flush between jobs. Collects campaign_report.json + per-job logs.

This does **not** inject domain outcome enums. Contract content is expected to
come from task text + agent/contract-discovery paths over time.

Example
-------
docker compose run --rm research-agent \\
  python scripts/run_task_batch_campaign_v0.py \\
  --tasks-dir tasks/batch_v0 \\
  --outdir ./evals/task_batch \\
  --llm --flush-between-jobs \\
  --max-hours 6 --job-timeout-s 1800

Subset:
  --only 02_web_hotel_property_only,06_web_wiki_fact
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


def discover_tasks(tasks_dir: Path, only: set[str] | None) -> list[Path]:
    files = sorted(tasks_dir.glob("*.md"))
    files = [p for p in files if p.name.upper() != "README.MD" and p.name != "README.md"]
    if only:
        files = [
            p
            for p in files
            if p.stem in only or p.name in only or p.stem.split("_", 1)[-1] in only
        ]
    return files


def run_job(
    task_path: Path,
    job_outdir: Path,
    *,
    use_llm: bool,
    flush: bool,
    timeout: int,
    planned: bool,
    contract_dir: Path | None = None,
) -> dict:
    job_outdir.mkdir(parents=True, exist_ok=True)
    log_path = job_outdir / f"job_{task_path.stem}.log"
    if contract_dir is not None:
        # task.md → frozen contract → acquisition + code sufficiency gate
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "run_contract_driven_task_v0.py"),
            "--task",
            str(task_path),
            "--contract-dir",
            str(contract_dir),
            "--outdir",
            str(job_outdir),
        ]
        if use_llm:
            cmd.append("--llm")
    else:
        cmd = [
            sys.executable,
            str(ROOT / "agent.py"),
            "--task",
            str(task_path),
        ]
        if planned:
            cmd.append("--planned")
    env = None
    try:
        import os

        env = os.environ.copy()
        if flush:
            env["RESEARCH_AGENT_FLUSH_BETWEEN"] = "1"
        if use_llm:
            env["RESEARCH_AGENT_LLM"] = "1"
        if contract_dir is not None:
            env["RESEARCH_AGENT_CONTRACT_DIR"] = str(contract_dir)
    except Exception:
        env = None

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        duration = round(time.monotonic() - t0, 2)
        log_path.write_text(
            (proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or ""),
            encoding="utf-8",
        )
        status = "DONE" if proc.returncode == 0 else "FAILED"
        go = proc.returncode == 0
        return {
            "job_id": task_path.stem,
            "task_path": str(task_path.relative_to(ROOT)) if task_path.is_relative_to(ROOT) else str(task_path),
            "status": status,
            "go": go,
            "duration_s": duration,
            "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2500:],
            "stderr_tail": (proc.stderr or "")[-1500:],
            "log": str(log_path),
            "path_mode": "contract_driven" if contract_dir is not None else "agent_retrieval",
        }
    except subprocess.TimeoutExpired as e:
        duration = round(time.monotonic() - t0, 2)
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else ""
        log_path.write_text(out + "\n--- STDERR ---\n" + err + "\nTIMEOUT\n", encoding="utf-8")
        return {
            "job_id": task_path.stem,
            "task_path": str(task_path),
            "status": "TIMEOUT",
            "go": False,
            "duration_s": duration,
            "exit_code": -1,
            "stdout_tail": out[-2500:],
            "stderr_tail": err[-1500:],
            "log": str(log_path),
        }
    except Exception as e:
        duration = round(time.monotonic() - t0, 2)
        return {
            "job_id": task_path.stem,
            "task_path": str(task_path),
            "status": "ERROR",
            "go": False,
            "duration_s": duration,
            "exit_code": -2,
            "stdout_tail": "",
            "stderr_tail": str(e),
            "log": str(log_path),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch run tasks/*.md via agent.py")
    ap.add_argument("--tasks-dir", type=Path, default=ROOT / "tasks" / "batch_v0")
    ap.add_argument("--outdir", type=Path, default=ROOT / "evals" / "task_batch")
    ap.add_argument("--only", type=str, default="", help="Comma-separated stems or filenames")
    ap.add_argument("--llm", action="store_true", help="Hint env for LLM (agent config may still control)")
    ap.add_argument(
        "--contract-dir",
        type=Path,
        default=None,
        help=(
            "If set: each job uses run_contract_driven_task_v0 "
            "(frozen contract + acquisition + code sufficiency gate). "
            "If omitted: legacy agent.py retrieval path."
        ),
    )
    ap.add_argument("--flush-between-jobs", action="store_true")
    ap.add_argument("--planned", action="store_true", default=True)
    ap.add_argument("--no-planned", action="store_true")
    ap.add_argument("--job-timeout-s", type=int, default=1800)
    ap.add_argument("--max-hours", type=float, default=6.0)
    args = ap.parse_args()

    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    tasks_dir = args.tasks_dir
    if not tasks_dir.is_absolute():
        tasks_dir = ROOT / tasks_dir
    tasks = discover_tasks(tasks_dir, only)
    if not tasks:
        print(f"No tasks found in {tasks_dir}", file=sys.stderr)
        return 2

    stamp = utc_stamp()
    campaign_dir = args.outdir if args.outdir.is_absolute() else ROOT / args.outdir
    campaign_dir = campaign_dir / f"{stamp}_batch"
    campaign_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema": "task-batch-campaign-v0",
        "created_at": stamp,
        "tasks_dir": str(tasks_dir),
        "jobs": [{"job_id": p.stem, "path": str(p)} for p in tasks],
        "llm": bool(args.llm),
        "flush_between_jobs": bool(args.flush_between_jobs),
        "contract_dir": str(args.contract_dir) if args.contract_dir else None,
        "path_mode": "contract_driven" if args.contract_dir else "agent_retrieval",
    }
    (campaign_dir / "campaign_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(f"Campaign dir: {campaign_dir}")
    print(f"Planned jobs: {len(tasks)}")
    deadline = time.monotonic() + max(0.1, args.max_hours) * 3600
    results = []
    planned = not args.no_planned

    for i, task_path in enumerate(tasks):
        if time.monotonic() > deadline:
            print("max-hours reached; stopping campaign")
            break
        job_out = campaign_dir / task_path.stem
        print(f">> {task_path.stem} — {task_path.name}")
        cdir = args.contract_dir
        if cdir is not None and not cdir.is_absolute():
            cdir = ROOT / cdir
        r = run_job(
            task_path,
            job_out,
            use_llm=args.llm,
            flush=args.flush_between_jobs,
            timeout=args.job_timeout_s,
            planned=planned,
            contract_dir=cdir,
        )
        results.append(r)
        print(
            f"   status={r['status']} go={r['go']} duration={r['duration_s']}s exit={r['exit_code']}"
        )
        if args.flush_between_jobs:
            # Best-effort Ollama VRAM flush if helper exists
            try:
                flush_script = ROOT / "scripts" / "run_live_offer_state_slice_v0.py"
                # no-op import path: call ollama stop via shell if available
                subprocess.run(
                    ["ollama", "stop", "llama3.2"],
                    capture_output=True,
                    timeout=30,
                )
            except Exception:
                pass

    counts = {
        "completed": sum(1 for r in results if r["status"] == "DONE"),
        "failed": sum(1 for r in results if r["status"] == "FAILED"),
        "timeout": sum(1 for r in results if r["status"] == "TIMEOUT"),
        "error": sum(1 for r in results if r["status"] == "ERROR"),
        "total_jobs": len(results),
        "go_true": sum(1 for r in results if r.get("go")),
    }
    report = {
        "schema": "task-batch-campaign-report-v0",
        "campaign_dir": str(campaign_dir),
        "counts": counts,
        "results": results,
        "notes": [
            "go=true means agent exit_code 0; inspect per-job logs and runs/ for quality.",
            "Do not treat exit 0 as contract-satisfied until sufficiency gate is fully wired to frozen contracts.",
            "See docs/FRAMEWORK_BOUNDARY.md",
        ],
    }
    report_path = campaign_dir / "campaign_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    # also latest pointer
    latest = (args.outdir if args.outdir.is_absolute() else ROOT / args.outdir) / "LATEST_REPORT.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== TASK BATCH CAMPAIGN ===")
    print(f"counts: {counts}")
    for r in results:
        print(f"  {r['job_id']}: status={r['status']} go={r['go']}")
    print(f"wrote {report_path}")
    return 0 if counts["failed"] == 0 and counts["timeout"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
