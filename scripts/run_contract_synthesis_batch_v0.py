#!/usr/bin/env python3
"""
Contract synthesis + FREEZE for a directory of task.md files (batch_v0).

Step 1 of the generic agent path:
  task.md → iterative LLM synthesis → gap-check → FREEZE

Does NOT run the retrieval agent. Produces one frozen (or max-pass) contract
per task so you can inspect claim content before wiring sufficiency.

Usage (repo root, host or container):

  # Heuristic only (no Ollama) — schema/loop smoke
  python scripts/run_contract_synthesis_batch_v0.py \\
      --tasks-dir tasks/batch_v0 \\
      --outdir ./evals/contract_synthesis

  # With LLM (same Ollama as agent)
  python scripts/run_contract_synthesis_batch_v0.py \\
      --tasks-dir tasks/batch_v0 \\
      --outdir ./evals/contract_synthesis \\
      --llm

  # Single task
  python scripts/run_contract_synthesis_batch_v0.py \\
      --task tasks/batch_v0/02_web_hotel_property_only.md \\
      --outdir ./evals/contract_synthesis --llm

Boundary: code owns meta-schema + freeze loop; LLM owns all claim content.
See docs/FRAMEWORK_BOUNDARY.md. No domain enums in the framework path.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_discovery import (  # noqa: E402
    synthesize_and_freeze_contract,
    synthesize_contract_from_task_path,
    validate_contract,
)


def _make_chat_fn():
    """Optional Ollama chat — same pattern as run_contract_discovery_v0 / mode runners."""
    try:
        from llm import OllamaClient
    except Exception as e:
        raise RuntimeError(
            "LLM requested but cannot import llm.OllamaClient"
        ) from e

    client = OllamaClient()

    def chat_fn(messages: list[dict]) -> dict:
        return client.chat(messages)

    return chat_fn



def main() -> int:
    ap = argparse.ArgumentParser(description="Contract synthesis + FREEZE batch")
    ap.add_argument("--tasks-dir", type=str, default="", help="Directory of *.md tasks")
    ap.add_argument("--task", type=str, default="", help="Single task.md path")
    ap.add_argument("--outdir", type=str, default="./evals/contract_synthesis")
    ap.add_argument("--llm", action="store_true", help="Use Ollama for synthesis + gap-check")
    ap.add_argument("--max-passes", type=int, default=3)
    ap.add_argument("--no-heuristic", action="store_true", help="Fail if LLM unavailable")
    args = ap.parse_args()

    tasks: list[Path] = []
    if args.task:
        tasks = [Path(args.task)]
    elif args.tasks_dir:
        d = Path(args.tasks_dir)
        tasks = sorted(d.glob("*.md"))
        tasks = [t for t in tasks if t.name.lower() != "readme.md"]
    else:
        default = ROOT / "tasks" / "batch_v0"
        tasks = sorted(default.glob("*.md"))
        tasks = [t for t in tasks if t.name.lower() != "readme.md"]

    if not tasks:
        print("No task.md files found", file=sys.stderr)
        return 2

    chat_fn = None
    if args.llm:
        chat_fn = _make_chat_fn()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root = Path(args.outdir) / f"{ts}_synthesis"
    out_root.mkdir(parents=True, exist_ok=True)

    results = []
    print(f"Campaign dir: {out_root}")
    print(f"Planned jobs: {len(tasks)} (llm={bool(chat_fn)})")

    for path in tasks:
        job_id = path.stem
        print(f">> {job_id}")
        try:
            result = synthesize_contract_from_task_path(
                path,
                chat_fn=chat_fn,
                max_passes=args.max_passes,
                use_heuristic_fallback=not args.no_heuristic,
            )
            status = "FROZEN" if result.get("frozen") else "UNFROZEN"
            val_ok = (result.get("validation") or {}).get("ok")
            print(
                f"   status={status} validation_ok={val_ok} "
                f"llm_calls={result.get('llm_calls')} "
                f"passes={len(result.get('passes') or [])}"
            )
            # Unique filenames: job_id + campaign ts
            out_file = out_root / f"contract_{job_id}_{ts}.json"
            out_file.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            results.append(
                {
                    "job_id": job_id,
                    "task_path": str(path),
                    "status": status,
                    "frozen": bool(result.get("frozen")),
                    "validation_ok": val_ok,
                    "llm_calls": result.get("llm_calls"),
                    "remaining_gaps": result.get("remaining_gaps") or [],
                    "contract_file": str(out_file.name),
                    "subject": ((result.get("contract") or {}).get("subject") or {}).get(
                        "name"
                    ),
                    "decision_ids": [
                        d.get("id")
                        for d in ((result.get("contract") or {}).get("decisions") or [])
                        if isinstance(d, dict)
                    ],
                }
            )
        except Exception as e:
            print(f"   ERROR: {type(e).__name__}: {e}")
            results.append(
                {
                    "job_id": job_id,
                    "task_path": str(path),
                    "status": "ERROR",
                    "frozen": False,
                    "error": f"{type(e).__name__}: {e}",
                }
            )

    report = {
        "schema": "contract-synthesis-batch-v0",
        "campaign_dir": str(out_root),
        "llm": bool(chat_fn),
        "max_passes": args.max_passes,
        "counts": {
            "total": len(results),
            "frozen": sum(1 for r in results if r.get("frozen")),
            "unfrozen": sum(
                1 for r in results if r.get("status") == "UNFROZEN"
            ),
            "error": sum(1 for r in results if r.get("status") == "ERROR"),
        },
        "results": results,
        "notes": [
            "frozen=true means LLM (or heuristic) gap-check said ready_to_freeze",
            "Inspect per-job contract_*.json for claim content — do not treat freeze as task success",
            "Next: wire sufficiency gate to frozen contract (step 2)",
            "See docs/FRAMEWORK_BOUNDARY.md",
        ],
    }
    report_path = out_root / f"campaign_report_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Also LATEST-style pointer without overwriting uniqueness
    (out_root / "campaign_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=== CONTRACT SYNTHESIS BATCH ===")
    print(f"counts: {report['counts']}")
    for r in results:
        print(f"  {r['job_id']}: status={r.get('status')} frozen={r.get('frozen')}")
    print(f"wrote {report_path}")
    return 0 if report["counts"]["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
