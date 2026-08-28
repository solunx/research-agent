#!/usr/bin/env python3
"""
Positive Evidence Trace v0 — one fixture through A→F localization.

  # dry-run (no LLM)
  python scripts/run_positive_evidence_trace_v0.py \
    --fixture evals/detail_evidence_fixture_v0.jsonl \
    --out ./evals/evidence_trace/detail_dry.json

  # with LLM
  python scripts/run_positive_evidence_trace_v0.py \
    --fixture evals/detail_evidence_fixture_v0.jsonl --llm \
    --oracle evals/positive_evidence_trace_oracle_v0.jsonl \
    --out ./evals/evidence_trace/detail_llm.json

Presets:
  --preset detail | offer_state | all_fixtures
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

from positive_evidence_trace import (  # noqa: E402
    load_jsonl,
    load_oracle,
    run_trace_batch,
)

EVALS = ROOT / "evals"
PRESETS = {
    "detail": EVALS / "detail_evidence_fixture_v0.jsonl",
    "offer_state": EVALS / "offer_state_fixture_v0.jsonl",
}


def make_chat_fn(*, keep_alive: str | int | None = "0"):
    try:
        from llm import OllamaClient
        import requests
    except Exception as e:
        print(f"[trace] Ollama unavailable: {e}", file=sys.stderr)
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
        print(f"[trace] flush soft-fail: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Positive evidence trace A→F v0")
    ap.add_argument("--fixture", type=Path, default=None)
    ap.add_argument("--preset", choices=list(PRESETS.keys()) + ["all_fixtures"], default=None)
    ap.add_argument("--oracle", type=Path, default=EVALS / "positive_evidence_trace_oracle_v0.jsonl")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--flush-model", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    paths: list[Path] = []
    if args.preset == "all_fixtures":
        paths = list(PRESETS.values())
    elif args.preset:
        paths = [PRESETS[args.preset]]
    elif args.fixture:
        paths = [args.fixture]
    else:
        paths = [PRESETS["detail"]]

    rows: list[dict[str, Any]] = []
    for p in paths:
        if not p.exists():
            print(f"[trace] missing fixture {p}", file=sys.stderr)
            return 2
        rows.extend(load_jsonl(p))

    if args.flush_model:
        flush_ollama_model()

    chat_fn = make_chat_fn(keep_alive="0") if args.llm else None
    if args.llm and chat_fn is None:
        print("[trace] --llm requested but chat_fn unavailable", file=sys.stderr)
        return 2

    oracle = load_oracle(args.oracle) if args.oracle else {}
    t0 = time.monotonic()
    result = run_trace_batch(
        rows,
        chat_fn=chat_fn,
        oracle=oracle,
        mode="fixture_simulated_harvest",
    )
    result["duration_s"] = round(time.monotonic() - t0, 2)
    result["llm_enabled"] = bool(args.llm)
    result["fixture_paths"] = [str(p) for p in paths]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    g = result.get("go_no_go") or {}
    m = result.get("metrics") or {}
    print("=== Positive evidence trace v0 ===")
    print(
        f"n={result.get('n')} match_rate={m.get('eligibility_match_rate')} "
        f"pos={m.get('positive_eligible_ok')}/{m.get('positive_n')} "
        f"neg={m.get('negative_not_eligible_ok')}/{m.get('negative_n')} "
        f"leaks={m.get('search_context_board_leaks')} "
        f"llm_calls={m.get('llm_calls_total')} duration={result['duration_s']}s"
    )
    print(f"fault_counts={result.get('fault_counts')}")
    print(f"GO={g.get('go')} reasons={g.get('reasons')}")
    for t in result.get("traces") or []:
        f = t.get("fault_localization")
        el = t["stages"]["F_eligibility"]
        print(
            f"  [{t['entity'][:40]:40}] "
            f"kind={t.get('evidence_kind')} "
            f"eligible={el.get('eligible')} exp={el.get('expected_eligible')} "
            f"fault={f}"
        )
    print(f"wrote {args.out}")
    return 0 if g.get("go") else 1


if __name__ == "__main__":
    raise SystemExit(main())
