#!/usr/bin/env python3
"""
Run one candidate-selection experiment (one method × one dataset).

  python scripts/run_candidate_selection_experiment_v0.py \
    --method S0_structural --dataset pilot_web_travel \
    --out ./evals/candidate_campaign/exp_web_s0.json

  python scripts/run_candidate_selection_experiment_v0.py \
    --method S3_llm_grounded --dataset pilot_literature --llm \
    --out ./exp.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from candidate_selection.datasets import ALL_PILOTS  # noqa: E402
from candidate_selection.methods import METHODS  # noqa: E402
from candidate_selection.metrics import score_predictions  # noqa: E402


def make_chat_fn():
    """Wire to project OllamaClient (same path agent.py uses)."""
    client = None
    try:
        from llm import OllamaClient  # type: ignore

        client = OllamaClient()
    except Exception:
        try:
            from local_research_agent.llm import OllamaClient  # type: ignore

            client = OllamaClient()
        except Exception:
            return None

    def _fn(messages: list[dict[str, str]]) -> str:
        msg = client.chat(messages=messages)
        if isinstance(msg, dict):
            content = msg.get("content")
            if content is None and "message" in msg:
                content = (msg.get("message") or {}).get("content")
            return str(content or msg)
        return str(msg)

    return _fn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", required=True, choices=sorted(METHODS.keys()))
    ap.add_argument("--dataset", required=True, choices=sorted(ALL_PILOTS.keys()))
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("candidate_selection_exp_v0.json"))
    ap.add_argument("--repeats", type=int, default=1)
    args = ap.parse_args()

    ds = ALL_PILOTS[args.dataset]()
    task = ds["task"]
    items = ds["items"]
    method_fn = METHODS[args.method]
    needs_llm = args.method.startswith("S2") or args.method.startswith("S3") or args.method.startswith("S5")
    chat_fn = make_chat_fn() if (args.llm and needs_llm) else None
    if args.llm and needs_llm and chat_fn is None:
        print(
            "[WARN] --llm set but OllamaClient chat_fn unavailable → fail-closed UNKNOWN "
            "(not a valid LLM experiment)",
            flush=True,
        )

    rows: list[dict[str, Any]] = []
    t0 = time.monotonic()
    for rep in range(max(1, args.repeats)):
        for unit, oracle in items:
            if needs_llm:
                res = method_fn(task, unit, chat_fn=chat_fn)
            else:
                res = method_fn(task, unit)
            rows.append(
                {
                    "repeat": rep,
                    "unit_id": unit.unit_id,
                    "text": unit.text[:200],
                    "element_type": unit.element_type,
                    "oracle": oracle,
                    "prediction": res.decision.value,
                    "reason": res.reason,
                    "confidence": res.confidence,
                    "latency_ms": res.latency_ms,
                    "llm_calls": res.llm_calls,
                    "input_tokens": res.input_tokens,
                    "output_tokens": res.output_tokens,
                    "error": res.error,
                    "method_id": res.method_id,
                }
            )
    dur = time.monotonic() - t0
    metrics = score_predictions(rows)
    total_llm = sum(r["llm_calls"] for r in rows)
    total_in = sum(r["input_tokens"] for r in rows)
    total_out = sum(r["output_tokens"] for r in rows)

    # Structural: complete without errors. LLM methods: require chat_fn + actual llm_calls.
    no_hard_errors = all(r.get("error") is None for r in rows)
    if needs_llm and args.llm:
        go = bool(chat_fn is not None and total_llm > 0 and no_hard_errors)
        go_reasons = (
            ["LLM calls executed"]
            if go
            else [
                "LLM experiment invalid: chat_fn missing or zero llm_calls "
                "(fail-closed UNKNOWN is not an LLM result)"
            ]
        )
    else:
        go = no_hard_errors
        go_reasons = ["completed without hard errors"] if go else ["some unit errors"]
    out = {
        "schema_version": "candidate-selection-experiment-v0",
        "method": args.method,
        "dataset_id": ds["dataset_id"],
        "domain": task.domain,
        "task_id": task.task_id,
        "llm_enabled": bool(args.llm and needs_llm),
        "chat_fn_available": chat_fn is not None,
        "n_units": len(items),
        "repeats": args.repeats,
        "duration_s": round(dur, 3),
        "cost": {
            "llm_calls": total_llm,
            "input_tokens_est": total_in,
            "output_tokens_est": total_out,
        },
        "metrics": metrics,
        "rows": rows,
        "go_no_go": {
            "go": go,
            "reasons": go_reasons,
        },
        "note": (
            "Pilot experiment. Metrics are domain-scoped; do not average across domains. "
            "ADMISSIBLE↔RELEVANT, NOT↔IRRELEVANT, UNKNOWN↔AMBIGUOUS for scoring."
        ),
    }

    written = None
    for cand in (args.out, Path("/tmp") / args.out.name):
        try:
            cand.parent.mkdir(parents=True, exist_ok=True)
            cand.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            written = cand
            break
        except OSError:
            continue

    m = metrics
    print(f"=== Candidate selection exp ===")
    print(f"method={args.method} dataset={ds['dataset_id']} domain={task.domain}")
    print(
        f"n={m['n']} precision={m['precision']:.3f} recall={m['recall']:.3f} "
        f"F1={m['f1']:.3f} FNR={m['false_negative_rate']:.3f} FPR={m['false_positive_rate']:.3f}"
    )
    print(f"llm_calls={total_llm} duration={dur:.2f}s GO={go}")
    print(f"wrote {written}")
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
