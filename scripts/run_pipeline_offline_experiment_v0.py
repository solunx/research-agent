#!/usr/bin/env python3
"""
Offline pipeline experiment v0 — one fixture file through the full chain.

  python scripts/run_pipeline_offline_experiment_v0.py \
    --fixture evals/vertical_slice_batch_fixture_v0.jsonl --llm \
    --out ./evals/pipeline_offline/batch_v0.json

Without --llm: fail-closed (CU UNKNOWN → skip interp → not eligible); safety checks still run.
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

from pipeline_offline import (  # noqa: E402
    go_no_go,
    load_packages_fixture,
    run_pipeline_one,
    score_pipeline_batch,
)


def make_chat_fn(*, keep_alive: str | int | None = "0"):
    try:
        from llm import OllamaClient
        import requests
    except Exception as e:
        print(f"[pipeline] OllamaClient unavailable: {e}", file=sys.stderr)
        return None

    client = OllamaClient()
    base = client.base_url
    model = client.model

    def _fn(messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": getattr(client, "temperature", 0.2)},
        }
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        resp = requests.post(
            f"{base}/api/chat",
            json=payload,
            timeout=getattr(client, "timeout", 480),
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", data)
        if isinstance(msg, dict):
            return str(msg.get("content") or "")
        return str(msg)

    return _fn


def flush_ollama_model() -> None:
    try:
        from llm import OllamaClient
        import requests

        client = OllamaClient()
        requests.post(
            f"{client.base_url}/api/generate",
            json={"model": client.model, "prompt": "", "keep_alive": 0},
            timeout=30,
        )
        time.sleep(0.5)
    except Exception as e:
        print(f"[pipeline] flush soft-fail: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "evals" / "vertical_slice_batch_fixture_v0.jsonl",
    )
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flush-model", action="store_true")
    ap.add_argument(
        "--skip-candidate-gate",
        action="store_true",
        help="Always run interpretation (CU still recorded; useful ablation)",
    )
    ap.add_argument(
        "--require-oracle",
        action="store_true",
        help="Fail GO if fixture has candidates but zero expected_eligible labels",
    )
    args = ap.parse_args()

    rows = load_packages_fixture(args.fixture)
    chat_fn = make_chat_fn(keep_alive="0") if args.llm else None
    if args.llm and chat_fn is None:
        print("[WARN] --llm but chat_fn unavailable → fail-closed", flush=True)

    t0 = time.monotonic()
    results = []
    for row in rows:
        pr = run_pipeline_one(
            row,
            chat_fn=chat_fn,
            require_candidate_admit=not args.skip_candidate_gate,
        )
        results.append(pr)
        elig = pr.eligible
        exp = pr.expected_eligible
        match = "" if exp is None else ("OK" if bool(elig) == bool(exp) else "MISMATCH")
        print(
            f"  [{pr.candidate_id[:40]:40s}] CU={pr.candidate_stage.get('decision')} "
            f"eligible={elig} expected={exp} {match}",
            flush=True,
        )

    dur = time.monotonic() - t0
    metrics = score_pipeline_batch(results)
    go = go_no_go(metrics, llm_enabled=bool(args.llm and chat_fn), require_oracle=bool(args.require_oracle), n_candidates=metrics.get('n', 0))

    payload = {
        "schema_version": "pipeline-offline-exp-v0",
        "fixture": str(args.fixture),
        "llm_enabled": bool(args.llm),
        "chat_fn_available": chat_fn is not None,
        "require_candidate_admit": not args.skip_candidate_gate,
        "duration_s": round(dur, 3),
        "metrics": metrics,
        "go_no_go": go,
        "results": [r.to_dict() for r in results],
        "isolation": {
            "fresh_messages_per_call": True,
            "keep_alive": "0",
            "flush_model": bool(args.flush_model),
        },
        "hypothesis": (
            "observation → CANDIDATE_UNIT → interpretation → code eligibility "
            "matches expected eligible on package fixtures; search_context never boards AI."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.flush_model:
        flush_ollama_model()

    print("=== Pipeline offline v0 ===")
    print(
        f"n={metrics['n']} match_rate={metrics.get('eligibility_match_rate')} "
        f"pos_ok={metrics.get('positive_eligible_ok')}/{metrics.get('positive_n')} "
        f"neg_ok={metrics.get('negative_not_eligible_ok')}/{metrics.get('negative_n')} "
        f"search_leaks={metrics.get('search_context_board_leaks')} "
        f"llm_calls={metrics.get('llm_calls_total')} duration={dur:.1f}s"
    )
    print(f"GO={go['go']} reasons={go['reasons']}")
    print(f"wrote {args.out}")
    return 0 if go["go"] or not args.llm else 1


if __name__ == "__main__":
    raise SystemExit(main())
