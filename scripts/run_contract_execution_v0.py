#!/usr/bin/env python3
"""
Contract Execution v0.1 — offline generic decision executor.

Reads a Research Contract (from discovery) + shortlist items, runs every
decision through decision_executor (no decision_id branches), scores vs oracle.

Usage:
  # Fixture: heuristic contract + fixture shortlist
  python scripts/run_contract_execution_v0.py --fixture

  # Real run artifacts + optional precomputed contract JSON
  python scripts/run_contract_execution_v0.py \\
    --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026 \\
    --contract ./contract_discovery_v0_llm.json \\
    --out ./contract_execution_v0.json

  # Discover heuristic contract from run if --contract omitted
  python scripts/run_contract_execution_v0.py --run-dir PATH --out ./exec.json

Does NOT wire into agent.py / harvest / eligibility.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_discovery import (  # noqa: E402
    discover_contract,
    load_run_context,
    select_representative_surfaces,
    validate_contract,
)
from decision_executor import (  # noqa: E402
    execute_contract_on_items,
    go_no_go,
    load_oracle,
    score_against_oracle,
)


def write_json(path: Path, obj: dict) -> Path:
    candidates = [path]
    if not path.is_absolute():
        candidates.append(Path.cwd() / path.name)
        candidates.append(Path("/tmp") / path.name)
    payload = json.dumps(obj, ensure_ascii=False, indent=2)
    last_err = None
    for cand in candidates:
        try:
            cand.parent.mkdir(parents=True, exist_ok=True)
            cand.write_text(payload, encoding="utf-8")
            return cand
        except OSError as e:
            last_err = e
    raise SystemExit(f"could not write {path}: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Contract Execution v0.1")
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--contract", type=Path, default=None, help="contract_discovery JSON")
    ap.add_argument("--oracle", type=Path, default=ROOT / "evals" / "decision_oracle_packages_v0.jsonl")
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("contract_execution_v0.json"))
    ap.add_argument("--llm-unknown", action="store_true", help="LLM only when deterministic UNKNOWN")
    ap.add_argument(
        "--decisions",
        type=str,
        default="",
        help="comma-separated decision ids (default: all in contract)",
    )
    args = ap.parse_args()

    # --- load items + contract ---
    if args.fixture or args.run_dir is None:
        # Import fixture helper without requiring scripts to be a package
        import importlib.util

        disc_path = ROOT / "scripts" / "run_contract_discovery_v0.py"
        spec = importlib.util.spec_from_file_location("run_contract_discovery_v0", disc_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        run_dir = mod.fixture_run_dir(ROOT / "evals" / "_fixture_contract_discovery_run")
        print(f"[execution] fixture run_dir={run_dir}")
    else:
        run_dir = args.run_dir
        if not run_dir.exists():
            print(f"run-dir not found: {run_dir}", file=sys.stderr)
            return 2

    ctx = load_run_context(run_dir)
    items = ctx["shortlist"]
    if not items:
        print("no shortlist items", file=sys.stderr)
        return 2

    if args.contract and args.contract.exists():
        blob = json.loads(args.contract.read_text(encoding="utf-8"))
        # accept either full discovery result or bare contract
        contract = blob.get("contract") if isinstance(blob.get("contract"), dict) else blob
        print(f"[execution] loaded contract from {args.contract} source={contract.get('_source')}")
    else:
        surfaces = select_representative_surfaces(items, max_surfaces=4)
        contract = discover_contract(
            ctx["task_text"],
            surfaces,
            meta=ctx["metadata"],
            use_heuristic_fallback=True,
        )
        print(f"[execution] discovered contract source={contract.get('_source')}")

    v = validate_contract(contract)
    print(f"[execution] contract validation.ok={v.ok} warnings={v.warnings}")
    if not v.ok:
        print("validation.errors:", v.errors, file=sys.stderr)
        return 2

    decision_ids = [x.strip() for x in args.decisions.split(",") if x.strip()] or None

    chat_fn = None
    if args.llm_unknown:
        from llm import OllamaClient

        client = OllamaClient()

        def chat_fn(messages):  # type: ignore[misc]
            return client.chat(messages)

    results = execute_contract_on_items(
        contract,
        items,
        decision_ids=decision_ids,
        chat_fn=chat_fn,
        llm_on_unknown=bool(args.llm_unknown),
    )

    oracle = []
    if args.oracle.exists():
        oracle = load_oracle(args.oracle)
        print(f"[execution] oracle rows={len(oracle)} from {args.oracle}")
    else:
        print(f"[execution] no oracle at {args.oracle}")

    metrics = score_against_oracle(results, oracle) if oracle else {
        "oracle_n": 0,
        "result_counts": {},
        "false_pass": 0,
        "false_pass_rate": 0.0,
        "spec_gap_rate": sum(1 for r in results if r.result == "SPEC_GAP") / (len(results) or 1),
        "unknown_rate": sum(1 for r in results if r.result == "UNKNOWN") / (len(results) or 1),
    }
    if not oracle:
        from collections import Counter

        c = Counter(r.result for r in results)
        metrics["result_counts"] = dict(c)

    gate = go_no_go(metrics)

    print("=== Contract Execution v0.1 ===")
    print(f"items={len(items)} results={len(results)}")
    print(f"result_counts={metrics.get('result_counts')}")
    print(f"unknown_rate={metrics.get('unknown_rate')}")
    print(f"spec_gap_rate={metrics.get('spec_gap_rate')}")
    print(f"oracle_accuracy={metrics.get('oracle_accuracy')} false_pass={metrics.get('false_pass')}")
    print(f"blocker_recall={metrics.get('blocker_recall')}")
    print(f"GO={gate['go']} reasons={gate['reasons']}")

    # sample matrix
    print("--- sample results (first 12) ---")
    for r in results[:12]:
        print(f"  {r.decision_id:20} {r.result:8} {r.outcome!s:20} | {r.item_key[:50]}")

    out_obj = {
        "run_dir": str(run_dir),
        "contract_source": contract.get("_source"),
        "contract_schema_version": contract.get("schema_version"),
        "decision_ids": [d.get("id") for d in (contract.get("decisions") or [])],
        "results": [r.to_dict() for r in results],
        "metrics": {k: v for k, v in metrics.items() if k != "details"},
        "oracle_details": metrics.get("details"),
        "go_no_go": gate,
    }
    written = write_json(args.out, out_obj)
    print(f"wrote {written}")
    return 0 if gate["go"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
