#!/usr/bin/env python3
"""
Interpretation v0 — offline semantic interpretation experiment.

Maps raw observation strings → contract outcomes via LLM, then runs a
domain-agnostic gate (required outcome vs normalized outcome).

Usage:

  # Dry-run gate only (no Ollama): all interpretations UNKNOWN
  python scripts/run_interpretation_v0.py --out ./interpretation_v0.json

  # Full test (needs Ollama, same as agent)
  python scripts/run_interpretation_v0.py --llm --out ./interpretation_v0.json

Does NOT touch agent.py, harvest, or eligibility.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interpretation import (  # noqa: E402
    BOARD_TYPE_CONTRACT,
    execute_normalized,
    go_no_go,
    interpret_observation,
    load_golden,
    score_interpretations,
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
    ap = argparse.ArgumentParser(description="Interpretation v0")
    ap.add_argument(
        "--golden",
        type=Path,
        default=ROOT / "evals" / "interpretation_board_type_golden.jsonl",
    )
    ap.add_argument("--llm", action="store_true", help="Call Ollama for interpretation")
    ap.add_argument("--out", type=Path, default=Path("interpretation_v0.json"))
    ap.add_argument(
        "--required",
        type=str,
        default="ALL_INCLUSIVE",
        help="Comma-separated required outcomes for gate demo (default ALL_INCLUSIVE)",
    )
    args = ap.parse_args()

    if not args.golden.exists():
        print(f"golden not found: {args.golden}", file=sys.stderr)
        return 2

    golden = load_golden(args.golden)
    decision = BOARD_TYPE_CONTRACT["decision"]
    required = [x.strip() for x in args.required.split(",") if x.strip()]

    chat_fn = None
    if args.llm:
        from llm import OllamaClient

        client = OllamaClient()

        def chat_fn(messages):  # type: ignore[misc]
            return client.chat(messages)

        print(f"[interpretation] LLM model={client.model} base={client.base_url}")
    else:
        print("[interpretation] no --llm → fail-closed UNKNOWN for all rows (gate dry-run)")

    results = []
    for row in golden:
        text = str(row.get("source_text") or "")
        r = interpret_observation(text, contract_decision=decision, chat_fn=chat_fn)
        results.append(r)
        print(f"  {text!r:45} → {r.outcome:15} ({r.confidence}) {r.reason[:60]}")

    metrics = score_interpretations(results, golden)
    gate = go_no_go(metrics) if args.llm else {
        "go": False,
        "reasons": ["--llm not set; metrics not meaningful for GO"],
    }

    # Demo: hard criterion ALL_INCLUSIVE on each normalized row
    print("--- gate requires", required, "---")
    for r in results:
        g = execute_normalized(r.outcome, required=required)
        print(f"  {r.source_text!r:40} norm={r.outcome:15} → {g.result}")

    print("=== Interpretation v0 ===")
    print(f"n={metrics['n']} accuracy={metrics['accuracy']:.3f}")
    print(
        f"critical={metrics['critical_n']} critical_accuracy={metrics['critical_accuracy']}"
    )
    print(f"confusions={len(metrics['confusions'])}")
    for c in metrics["confusions"]:
        print(f"  ! {c['source_text']!r}: expected {c['expected']} got {c['actual']}")
    print(f"GO={gate['go']} reasons={gate['reasons']}")

    out_obj = {
        "contract": BOARD_TYPE_CONTRACT,
        "required_for_gate": required,
        "results": [r.to_dict() for r in results],
        "metrics": {k: v for k, v in metrics.items() if k != "details"},
        "details": metrics.get("details"),
        "go_no_go": gate,
        "mode": "llm" if args.llm else "stub",
    }
    written = write_json(args.out, out_obj)
    print(f"wrote {written}")
    if not args.llm:
        return 0
    return 0 if gate["go"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
