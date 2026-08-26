#!/usr/bin/env python3
"""
Multi-suite eval runner v0 — independent tests, no blended scores.

Suites
  offline      — no LLM (fast)
  semantic     — LLM interpretation / vertical / batch
  integration  — admissibility → semantic pipeline (optional; needs LLM)
  all          — offline then semantic then integration

Each test:
  - own subprocess
  - own output JSON under --outdir/<test_id>.json
  - GO from exit code + go_no_go in JSON when present
  - never averaged into a single "overall accuracy"

Usage:
  python scripts/run_eval_suite_v0.py --suite offline
  python scripts/run_eval_suite_v0.py --suite semantic --llm
  python scripts/run_eval_suite_v0.py --suite all --llm
  python scripts/run_eval_suite_v0.py --only provenance,admissibility
  python scripts/run_eval_suite_v0.py --list

Environment defaults match the packages benchmark run used in experiments.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
EVALS = ROOT / "evals"

DEFAULT_RUN_DIR = ROOT / "runs" / "2026-08-24T08-01-36_compare_packages_dec2026"
DEFAULT_OBS = DEFAULT_RUN_DIR / "observations.jsonl"


@dataclass
class TestSpec:
    id: str
    suite: str  # offline | semantic | integration
    script: str
    needs_llm: bool = False
    description: str = ""
    # Extra argv factory: (ctx) -> list[str]
    build_args: Any = None
    # If True, suite still runs without LLM but expects fail-closed dry-run GO
    allow_dry_run: bool = True


@dataclass
class TestResult:
    id: str
    suite: str
    go: bool | None
    exit_code: int
    duration_s: float
    out_path: str | None
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _py() -> str:
    return sys.executable


def _ctx(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = Path(args.run_dir) if args.run_dir else DEFAULT_RUN_DIR
    obs = Path(args.observations) if args.observations else (
        run_dir / "observations.jsonl" if (run_dir / "observations.jsonl").exists() else DEFAULT_OBS
    )
    return {
        "run_dir": run_dir,
        "observations": obs,
        "llm": bool(args.llm),
        "model": args.model,
        "outdir": Path(args.outdir),
        "root": ROOT,
    }


def registry() -> list[TestSpec]:
    """Declare tests. build_args receives ctx dict."""

    def args_provenance(ctx: dict) -> list[str]:
        return ["--out", str(ctx["outdir"] / "observation_provenance_v0.json")]

    def args_raw(ctx: dict) -> list[str]:
        a = ["--out", str(ctx["outdir"] / "observation_raw_evidence_v0.json")]
        if ctx["observations"].exists():
            a += ["--observations", str(ctx["observations"])]
        elif ctx["run_dir"].exists():
            a += ["--run-dir", str(ctx["run_dir"])]
        return a

    def args_admissibility(ctx: dict) -> list[str]:
        a = ["--out", str(ctx["outdir"] / "candidate_admissibility_v0.json")]
        if ctx["observations"].exists():
            a += ["--observations", str(ctx["observations"])]
        else:
            a += ["--observations", str(DEFAULT_OBS)]
        return a

    def args_interpretation_board(ctx: dict) -> list[str]:
        a = [
            "--out",
            str(ctx["outdir"] / "interpretation_board_v0.json"),
            "--golden",
            str(EVALS / "interpretation_board_type_golden.jsonl"),
        ]
        if ctx["llm"]:
            a.append("--llm")
        return a

    def args_vertical_fixture(ctx: dict) -> list[str]:
        a = [
            "--fixture",
            "--out",
            str(ctx["outdir"] / "vertical_slice_positive_v0.json"),
        ]
        if ctx["llm"]:
            a.append("--llm")
        return a

    def args_batch(ctx: dict) -> list[str]:
        a = [
            "--fixture",
            "--out",
            str(ctx["outdir"] / "vertical_slice_batch_v0.json"),
        ]
        if ctx["llm"]:
            a.append("--llm")
        return a

    def args_vertical_run(ctx: dict) -> list[str]:
        a = ["--out", str(ctx["outdir"] / "vertical_slice_from_run_v0.json")]
        if ctx["run_dir"].exists():
            a += ["--run-dir", str(ctx["run_dir"])]
        if ctx["llm"]:
            a.append("--llm")
        return a

    def args_integration_admissibility_batch(ctx: dict) -> list[str]:
        # Integration is implemented by this suite runner itself when script is special
        return []

    return [
        TestSpec(
            id="provenance",
            suite="offline",
            script="run_observation_provenance_v0.py",
            description="Channel/scope isolation on fixture cards",
            build_args=args_provenance,
        ),
        TestSpec(
            id="raw_evidence",
            suite="offline",
            script="run_observation_raw_evidence_v0.py",
            description="Literal segments from harvest raw_evidence",
            build_args=args_raw,
        ),
        TestSpec(
            id="admissibility",
            suite="offline",
            script="run_candidate_admissibility_v0.py",
            description="Structural ADMISSIBLE/NOT/UNKNOWN gate",
            build_args=args_admissibility,
        ),
        TestSpec(
            id="interpretation_board",
            suite="semantic",
            script="run_interpretation_v0.py",
            needs_llm=True,
            allow_dry_run=True,
            description="Board-type golden interpretation + dumb gate",
            build_args=args_interpretation_board,
        ),
        TestSpec(
            id="vertical_positive",
            suite="semantic",
            script="run_vertical_slice_v0.py",
            needs_llm=True,
            allow_dry_run=True,
            description="Positive AI + negative enkel + breakfast fixture",
            build_args=args_vertical_fixture,
        ),
        TestSpec(
            id="batch_isolation",
            suite="semantic",
            script="run_vertical_slice_batch_v0.py",
            needs_llm=True,
            allow_dry_run=True,
            description="10-candidate isolation / no cross-talk",
            build_args=args_batch,
        ),
        TestSpec(
            id="vertical_from_run",
            suite="semantic",
            script="run_vertical_slice_v0.py",
            needs_llm=True,
            allow_dry_run=True,
            description="Vertical slice on real run observations (if present)",
            build_args=args_vertical_run,
        ),
        TestSpec(
            id="integration_admissible_batch",
            suite="integration",
            script="__integration_admissible_batch__",
            needs_llm=True,
            allow_dry_run=True,
            description="Admissibility filter then batch-like eligibility on fixture",
            build_args=args_integration_admissibility_batch,
        ),
    ]


def extract_go(out_path: Path | None, exit_code: int) -> tuple[bool | None, dict[str, Any]]:
    summary: dict[str, Any] = {"exit_code": exit_code}
    if out_path and out_path.exists():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            summary["parse_error"] = str(e)
            return (exit_code == 0), summary

        gng = data.get("go_no_go") or data.get("go")
        if isinstance(gng, dict):
            go = bool(gng.get("go"))
            summary["go_no_go"] = gng
        elif isinstance(gng, bool):
            go = gng
        else:
            go = exit_code == 0

        # Machine-readable extras when present
        for key in (
            "counts",
            "checks",
            "n_candidates",
            "n_entities",
            "oracle_eval",
            "unknown_rate",
            "schema_version",
        ):
            if key in data:
                val = data[key]
                if key == "oracle_eval" and isinstance(val, list):
                    summary["oracle_n"] = len(val)
                    summary["oracle_ok"] = sum(1 for x in val if x.get("ok"))
                elif key == "checks" and isinstance(val, list):
                    summary["checks_failed"] = [
                        c.get("id") for c in val if not c.get("ok")
                    ]
                else:
                    summary[key] = val
        return go, summary

    return (exit_code == 0 if exit_code is not None else None), summary


def run_subprocess_test(
    spec: TestSpec, ctx: dict[str, Any], timeout: int
) -> TestResult:
    out_name = {
        "provenance": "observation_provenance_v0.json",
        "raw_evidence": "observation_raw_evidence_v0.json",
        "admissibility": "candidate_admissibility_v0.json",
        "interpretation_board": "interpretation_board_v0.json",
        "vertical_positive": "vertical_slice_positive_v0.json",
        "batch_isolation": "vertical_slice_batch_v0.json",
        "vertical_from_run": "vertical_slice_from_run_v0.json",
    }.get(spec.id, f"{spec.id}.json")
    out_path = ctx["outdir"] / out_name

    script_path = SCRIPTS / spec.script
    if not script_path.exists():
        return TestResult(
            id=spec.id,
            suite=spec.suite,
            go=False,
            exit_code=127,
            duration_s=0.0,
            out_path=None,
            error=f"missing script {script_path}",
        )

    argv = [_py(), str(script_path)] + list(spec.build_args(ctx) or [])
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
        duration = time.monotonic() - t0
        go, summary = extract_go(out_path if out_path.exists() else None, proc.returncode)
        summary["cmd"] = argv
        if proc.returncode != 0 and proc.stderr:
            summary["stderr_tail"] = proc.stderr[-800:]
        if proc.stdout:
            summary["stdout_tail"] = proc.stdout[-600:]
        return TestResult(
            id=spec.id,
            suite=spec.suite,
            go=go,
            exit_code=proc.returncode,
            duration_s=round(duration, 2),
            out_path=str(out_path) if out_path.exists() else None,
            summary=summary,
        )
    except subprocess.TimeoutExpired:
        return TestResult(
            id=spec.id,
            suite=spec.suite,
            go=False,
            exit_code=124,
            duration_s=round(time.monotonic() - t0, 2),
            out_path=None,
            error=f"timeout after {timeout}s",
        )
    except OSError as e:
        return TestResult(
            id=spec.id,
            suite=spec.suite,
            go=False,
            exit_code=1,
            duration_s=round(time.monotonic() - t0, 2),
            out_path=None,
            error=str(e),
        )


def run_integration_admissible_batch(ctx: dict[str, Any]) -> TestResult:
    """
    Integration v0: structural admissibility on batch fixture entities,
    then only ADMISSIBLE rows go through vertical batch interpretation path.

    Does not mutate harvest. Uses fixture jsonl + candidate_admissibility.
    """
    t0 = time.monotonic()
    out_path = ctx["outdir"] / "integration_admissible_batch_v0.json"
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from candidate_admissibility import ADMISSIBLE, decide_admissibility
        from observation_builder import build_from_observations_jsonl  # noqa: F401
    except ImportError as e:
        return TestResult(
            id="integration_admissible_batch",
            suite="integration",
            go=False,
            exit_code=1,
            duration_s=0.0,
            out_path=None,
            error=str(e),
        )

    fixture = EVALS / "vertical_slice_batch_fixture_v0.jsonl"
    if not fixture.exists():
        return TestResult(
            id="integration_admissible_batch",
            suite="integration",
            go=False,
            exit_code=2,
            duration_s=0.0,
            out_path=None,
            error=f"missing {fixture}",
        )

    rows = []
    for line in fixture.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))

    adm_results = []
    admitted_entities: list[str] = []
    for row in rows:
        dec = decide_admissibility(row)
        ent = str(row.get("entity") or "")
        adm_results.append(
            {
                "entity": ent,
                "decision": dec["decision"],
                "reasons": dec["reasons"],
                "expected_role": row.get("expected_role"),
                "expected_eligible": row.get("expected_eligible"),
            }
        )
        if dec["decision"] == ADMISSIBLE:
            admitted_entities.append(ent)

    # Noise that must not be admitted
    noise_roles = {"marketing", "destination"}
    noise_admitted = [
        a
        for a in adm_results
        if a.get("expected_role") in noise_roles and a["decision"] == ADMISSIBLE
    ]
    # Hotel-like positives/negatives we want retained when structure allows
    hotel_roles = {"positive_ai", "negative_enkel", "breakfast"}
    hotel_rows = [a for a in adm_results if a.get("expected_role") in hotel_roles]
    hotel_admitted = [a for a in hotel_rows if a["decision"] == ADMISSIBLE]

    # Optional: run batch script only on full fixture is existing path;
    # integration GO focuses on gate effect metrics.
    checks = [
        {
            "id": "no_marketing_or_destination_admitted",
            "ok": len(noise_admitted) == 0,
            "noise_admitted": [x["entity"] for x in noise_admitted],
        },
        {
            "id": "some_hotel_like_admitted",
            "ok": len(hotel_admitted) >= 1,
            "n": len(hotel_admitted),
            "entities": [x["entity"] for x in hotel_admitted],
        },
        {
            "id": "admitted_subset_of_input",
            "ok": len(admitted_entities) < len(rows),
            "admitted": len(admitted_entities),
            "input": len(rows),
        },
    ]

    # If LLM: run batch isolation (full fixture still — documents semantic still OK);
    # plus report which admitted set would proceed.
    semantic_go = None
    if ctx["llm"]:
        batch_out = ctx["outdir"] / "integration_batch_semantic_v0.json"
        argv = [
            _py(),
            str(SCRIPTS / "run_vertical_slice_batch_v0.py"),
            "--fixture",
            "--llm",
            "--out",
            str(batch_out),
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            argv, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=600
        )
        semantic_go, sem_summary = extract_go(
            batch_out if batch_out.exists() else None, proc.returncode
        )
        checks.append(
            {
                "id": "semantic_batch_still_go",
                "ok": bool(semantic_go),
                "detail": sem_summary.get("go_no_go"),
            }
        )
    else:
        checks.append(
            {
                "id": "semantic_batch_skipped_no_llm",
                "ok": True,
                "detail": "dry-run: admissibility gate metrics only",
            }
        )

    go = all(c["ok"] for c in checks)
    payload = {
        "schema_version": "integration-admissible-batch-v0",
        "admissibility": adm_results,
        "admitted_entities": admitted_entities,
        "checks": checks,
        "go_no_go": {
            "go": go,
            "reasons": [c for c in checks if not c["ok"]] or ["integration gate checks met"],
        },
        "note": (
            "Filter-only integration: measures that marketing/destination are not ADMISSIBLE. "
            "Full harvest card-boundary improvement is separate from this gate."
        ),
    }
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written = str(out_path)
    except OSError:
        written = None
        try:
            alt = Path("/tmp") / out_path.name
            alt.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            written = str(alt)
        except OSError as e:
            return TestResult(
                id="integration_admissible_batch",
                suite="integration",
                go=False,
                exit_code=1,
                duration_s=round(time.monotonic() - t0, 2),
                out_path=None,
                error=str(e),
            )

    return TestResult(
        id="integration_admissible_batch",
        suite="integration",
        go=go,
        exit_code=0 if go else 1,
        duration_s=round(time.monotonic() - t0, 2),
        out_path=written,
        summary={"checks": checks, "admitted_n": len(admitted_entities)},
    )


def select_tests(
    specs: list[TestSpec], suite: str, only: list[str] | None
) -> list[TestSpec]:
    if only:
        ids = set(only)
        return [s for s in specs if s.id in ids]
    if suite == "all":
        order = ["offline", "semantic", "integration"]
        return [s for suite_name in order for s in specs if s.suite == suite_name]
    return [s for s in specs if s.suite == suite]


def print_report(results: list[TestResult], suite_filter: str) -> int:
    by_suite: dict[str, list[TestResult]] = {}
    for r in results:
        by_suite.setdefault(r.suite, []).append(r)

    print("=== Eval suite v0 ===")
    any_fail = False
    suite_status: dict[str, bool] = {}
    for suite_name in ("offline", "semantic", "integration"):
        if suite_name not in by_suite:
            continue
        rs = by_suite[suite_name]
        ok = all(r.go for r in rs)
        suite_status[suite_name] = ok
        if not ok:
            any_fail = True
        print(f"\n{suite_name.upper()}  [{'PASS' if ok else 'FAIL'}]")
        for r in rs:
            status = "PASS" if r.go else "FAIL"
            if r.go is None:
                status = "UNKNOWN"
            extra = ""
            if r.summary.get("counts"):
                extra = f" counts={r.summary['counts']}"
            if r.summary.get("checks_failed"):
                extra += f" failed_checks={r.summary['checks_failed']}"
            if r.error:
                extra += f" err={r.error}"
            print(f"  {status:7} {r.id:28} {r.duration_s:7.1f}s{extra}")
            if r.out_path:
                print(f"           → {r.out_path}")

    print("\n--- suite rollup (not averaged) ---")
    for k, v in suite_status.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print(f"overall_all_suites_pass: {not any_fail and bool(suite_status)}")
    return 1 if any_fail else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Multi-suite independent eval runner v0")
    ap.add_argument(
        "--suite",
        choices=["offline", "semantic", "integration", "all"],
        default="offline",
    )
    ap.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated test ids (overrides --suite filter)",
    )
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--model", default="qwen3.8:27b")
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--observations", type=Path, default=None)
    ap.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "evals" / "_suite_out",
    )
    ap.add_argument("--timeout", type=int, default=600, help="Per-test timeout seconds")
    ap.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write machine-readable suite report JSON",
    )
    args = ap.parse_args()

    specs = registry()
    if args.list:
        print(f"{'ID':28} {'SUITE':12} {'LLM':5} DESCRIPTION")
        for s in specs:
            print(
                f"{s.id:28} {s.suite:12} {'yes' if s.needs_llm else 'no':5} {s.description}"
            )
        return 0

    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    selected = select_tests(specs, args.suite, only)
    if not selected:
        print("no tests selected", file=sys.stderr)
        return 2

    ctx = _ctx(args)
    ctx["outdir"].mkdir(parents=True, exist_ok=True)

    results: list[TestResult] = []
    for spec in selected:
        if spec.needs_llm and not args.llm and not spec.allow_dry_run:
            results.append(
                TestResult(
                    id=spec.id,
                    suite=spec.suite,
                    go=None,
                    exit_code=0,
                    duration_s=0.0,
                    out_path=None,
                    error="skipped (needs --llm)",
                )
            )
            continue

        print(f"\n>> running {spec.id} ({spec.suite}) ...")
        if spec.script == "__integration_admissible_batch__":
            r = run_integration_admissible_batch(ctx)
        else:
            r = run_subprocess_test(spec, ctx, timeout=args.timeout)
        results.append(r)
        print(f"   go={r.go} exit={r.exit_code} {r.duration_s}s")

    report = {
        "schema_version": "eval-suite-v0",
        "suite_requested": args.suite,
        "llm": bool(args.llm),
        "results": [
            {
                "id": r.id,
                "suite": r.suite,
                "go": r.go,
                "exit_code": r.exit_code,
                "duration_s": r.duration_s,
                "out_path": r.out_path,
                "error": r.error,
                "summary": r.summary,
            }
            for r in results
        ],
    }
    report_path = args.report or (ctx["outdir"] / "suite_report.json")
    try:
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nwrote report {report_path}")
    except OSError:
        alt = Path("/tmp") / "suite_report.json"
        alt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote report {alt}")

    return print_report(results, args.suite)


if __name__ == "__main__":
    raise SystemExit(main())
