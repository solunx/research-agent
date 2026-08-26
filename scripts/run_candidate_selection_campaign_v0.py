#!/usr/bin/env python3
"""
Candidate selection campaign runner (structural vs LLM vs hybrid).

Pilot (default, minutes):
  python scripts/run_candidate_selection_campaign_v0.py --campaign pilot \\
    --outdir ./evals/candidate_campaign

Pilot + LLM methods:
  python scripts/run_candidate_selection_campaign_v0.py --campaign pilot --llm \\
    --outdir ./evals/candidate_campaign

Full matrix (longer; still pilot datasets only in v0):
  python scripts/run_candidate_selection_campaign_v0.py --campaign full --llm \\
    --outdir ./evals/candidate_campaign --max-hours 2

Resume-safe: skips jobs already DONE in manifest.
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

# Pilot matrix: cheap methods always; LLM methods only with --llm
STRUCTURAL_METHODS = ["S0_structural", "S1_structural_heuristics"]
LLM_METHODS = ["S2_llm_raw", "S3_llm_grounded", "S5_hybrid"]
ALL_METHODS = STRUCTURAL_METHODS + LLM_METHODS
DATASETS = [
    "pilot_web_travel",
    "pilot_literature",
    "pilot_code",
    "pilot_documents",
]


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
    methods = list(STRUCTURAL_METHODS)
    if use_llm:
        methods.extend(LLM_METHODS)
    if campaign == "smoke":
        # minimal: one domain × structural + one LLM if enabled
        jobs = [
            {"method": "S0_structural", "dataset": "pilot_web_travel"},
            {"method": "S1_structural_heuristics", "dataset": "pilot_web_travel"},
        ]
        if use_llm:
            jobs.append({"method": "S3_llm_grounded", "dataset": "pilot_web_travel"})
            jobs.append({"method": "S3_llm_grounded", "dataset": "pilot_literature"})
        return jobs
    # pilot / full: all datasets × selected methods (full == pilot datasets for v0)
    jobs = []
    for ds in DATASETS:
        for m in methods:
            jobs.append({"method": m, "dataset": ds})
    return jobs


def run_one(
    method: str,
    dataset: str,
    out_path: Path,
    use_llm: bool,
    timeout: int,
) -> dict[str, Any]:
    py = sys.executable
    argv = [
        py,
        str(SCRIPTS / "run_candidate_selection_experiment_v0.py"),
        "--method",
        method,
        "--dataset",
        dataset,
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
        metrics = {}
        if out_path.exists():
            try:
                payload = json.loads(out_path.read_text(encoding="utf-8"))
                metrics = payload.get("metrics") or {}
            except json.JSONDecodeError:
                pass
        print(proc.stdout[-1500:] if proc.stdout else "", flush=True)
        if proc.returncode != 0 and proc.stderr:
            print(proc.stderr[-800:], file=sys.stderr, flush=True)
        return {
            "status": "DONE" if proc.returncode == 0 else "FAILED",
            "exit_code": proc.returncode,
            "duration_s": round(dur, 2),
            "out_path": str(out_path),
            "metrics": {
                "precision": metrics.get("precision"),
                "recall": metrics.get("recall"),
                "f1": metrics.get("f1"),
                "fnr": metrics.get("false_negative_rate"),
                "fpr": metrics.get("false_positive_rate"),
            },
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "exit_code": 124,
            "duration_s": timeout,
            "out_path": str(out_path),
            "metrics": {},
        }


def domain_of(dataset: str) -> str:
    if "web" in dataset:
        return "web"
    if "literature" in dataset:
        return "literature"
    if "code" in dataset:
        return "code"
    if "document" in dataset:
        return "documents"
    return "other"


def build_report(manifest: dict[str, Any], campaign_dir: Path) -> dict[str, Any]:
    by_domain: dict[str, dict[str, list]] = {}
    by_method: dict[str, list] = {}
    completed = failed = timeout = skipped = 0
    for jid, job in manifest.get("jobs", {}).items():
        st = job.get("status")
        if st == "DONE":
            completed += 1
        elif st == "FAILED":
            failed += 1
        elif st == "TIMEOUT":
            timeout += 1
        elif st == "SKIPPED":
            skipped += 1
        method = job.get("method", "")
        dataset = job.get("dataset", "")
        dom = domain_of(dataset)
        by_domain.setdefault(dom, {}).setdefault(method, []).append(job.get("metrics") or {})
        by_method.setdefault(method, []).append(job.get("metrics") or {})

    def avg_field(rows: list[dict], key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    method_summary = {
        m: {
            "n": len(rows),
            "avg_precision": avg_field(rows, "precision"),
            "avg_recall": avg_field(rows, "recall"),
            "avg_f1": avg_field(rows, "f1"),
            "avg_fnr": avg_field(rows, "fnr"),
            "avg_fpr": avg_field(rows, "fpr"),
        }
        for m, rows in by_method.items()
    }
    domain_summary = {}
    for dom, methods in by_domain.items():
        domain_summary[dom] = {
            m: {
                "avg_precision": avg_field(rows, "precision"),
                "avg_recall": avg_field(rows, "recall"),
                "avg_f1": avg_field(rows, "f1"),
            }
            for m, rows in methods.items()
        }

    return {
        "schema_version": "candidate-selection-campaign-report-v0",
        "campaign_dir": str(campaign_dir),
        "counts": {
            "completed": completed,
            "failed": failed,
            "timeout": timeout,
            "skipped": skipped,
            "total_jobs": len(manifest.get("jobs", {})),
        },
        "by_method": method_summary,
        "by_domain": domain_summary,
        "jobs": manifest.get("jobs", {}),
        "note": (
            "Per-domain metrics matter more than overall averages. "
            "Structural methods cost ~0 LLM calls; compare FNR carefully."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", choices=["smoke", "pilot", "full"], default="pilot")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--outdir", type=Path, default=ROOT / "evals" / "candidate_campaign")
    ap.add_argument("--max-hours", type=float, default=2.0)
    ap.add_argument("--timeout-per-job", type=int, default=300)
    ap.add_argument("--force", action="store_true", help="re-run DONE jobs")
    args = ap.parse_args()

    stamp = utc_stamp()
    campaign_dir = args.outdir / f"{stamp}_{args.campaign}"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = campaign_dir / "campaign_manifest.json"
    manifest = load_manifest(manifest_path)
    manifest["campaign"] = args.campaign
    manifest["llm"] = bool(args.llm)
    manifest["started_at"] = manifest.get("started_at") or stamp

    jobs = plan_jobs(args.campaign, args.llm)
    deadline = time.monotonic() + args.max_hours * 3600

    print(f"Campaign dir: {campaign_dir}")
    print(f"Planned jobs: {len(jobs)} (llm={args.llm})")

    for spec in jobs:
        if time.monotonic() > deadline:
            jid = f"{spec['method']}__{spec['dataset']}"
            manifest["jobs"][jid] = {
                **spec,
                "status": "SKIPPED",
                "reason": "max_hours",
            }
            continue
        jid = f"{spec['method']}__{spec['dataset']}"
        existing = manifest["jobs"].get(jid)
        if existing and existing.get("status") == "DONE" and not args.force:
            print(f"  skip DONE {jid}")
            continue

        print(f"\n>> {jid}", flush=True)
        out_path = campaign_dir / f"{jid}.json"
        result = run_one(
            spec["method"],
            spec["dataset"],
            out_path,
            use_llm=args.llm,
            timeout=args.timeout_per_job,
        )
        manifest["jobs"][jid] = {**spec, **result}
        save_manifest(manifest_path, manifest)

    report = build_report(manifest, campaign_dir)
    report_path = campaign_dir / "campaign_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # also write latest pointer
    latest = args.outdir / "LATEST_REPORT.json"
    try:
        latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass

    print("\n=== CAMPAIGN REPORT ===")
    print(f"counts: {report['counts']}")
    for m, s in report["by_method"].items():
        print(
            f"  {m:28} n={s['n']} P={s['avg_precision']} R={s['avg_recall']} F1={s['avg_f1']}"
        )
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
