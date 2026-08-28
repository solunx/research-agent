#!/usr/bin/env python3
"""
Single-job or small batch: gap-driven live acquisition loop.

Examples
--------
# Lab: force click labels (NOT product hardcoding — experiment only)
python scripts/run_live_offer_state_slice_v0.py --preset monica_lab --llm \\
  --out ./evals/live_offer/monica_lab.json

# Pure LLM acquisition (no force list) from oracle detail URL
python scripts/run_live_offer_state_slice_v0.py --preset costa_llm --llm \\
  --out ./evals/live_offer/costa_llm.json

# Smoke: open + affordances only (no LLM)
python scripts/run_live_offer_state_slice_v0.py --preset monica_lab --out ./evals/live_offer/smoke.json
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

from live_offer_state_slice import run_acquisition_batch  # noqa: E402
from pipeline_offline import PACKAGES_TASK_TEXT  # noqa: E402

EVALS = ROOT / "evals"
ORACLE = EVALS / "positive_evidence_trace_oracle_v0.jsonl"

# Lab force texts are *experiment parameters*, not core policy.
# They must match visible UI labels on the page under test.
LAB_PRICE_CLICKS = [
    "Prijzen & boeken",
    "Prijzen en boeken",
    "Bekijk beschikbaarheid",
    "Prijsberekening",
]


def load_oracle_entity(name: str) -> dict[str, Any] | None:
    if not ORACLE.is_file():
        return None
    for line in ORACLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("entity") == name:
            return row
    return None


def make_chat_fn(*, keep_alive: str | int | None = "0"):
    try:
        from llm import OllamaClient
        import requests
    except Exception as e:
        print(f"[offer_state] Ollama unavailable: {e}", file=sys.stderr)
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
        print(f"[offer_state] flush soft-fail: {e}", file=sys.stderr)


def targets_for_preset(preset: str) -> list[dict[str, Any]]:
    preset = (preset or "").strip().lower()
    if preset == "monica_lab":
        row = load_oracle_entity("SBH Monica Beach") or {}
        url = row.get("detail_url") or (
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/"
            "costa-calma/sbh-monica-beach"
        )
        return [
            {
                "entity": "SBH Monica Beach",
                "detail_url": url,
                "expected_eligible": True,
                "force_click_texts": list(LAB_PRICE_CLICKS),
                "max_acquisition_steps": 4,
            }
        ]
    if preset == "costa_lab":
        row = load_oracle_entity("SBH Costa Calma Beach Resort") or {}
        url = row.get("detail_url") or (
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/"
            "costa-calma/sbh-costa-calma-beach-resort"
        )
        return [
            {
                "entity": "SBH Costa Calma Beach Resort",
                "detail_url": url,
                "expected_eligible": True,
                "force_click_texts": list(LAB_PRICE_CLICKS),
                "max_acquisition_steps": 4,
            }
        ]
    if preset == "costa_llm":
        row = load_oracle_entity("SBH Costa Calma Beach Resort") or {}
        return [
            {
                "entity": "SBH Costa Calma Beach Resort",
                "detail_url": row.get("detail_url"),
                "expected_eligible": True,
                "force_click_texts": None,  # pure acquisition LLM
                "max_acquisition_steps": 3,
            }
        ]
    if preset == "monica_llm":
        row = load_oracle_entity("SBH Monica Beach") or {}
        return [
            {
                "entity": "SBH Monica Beach",
                "detail_url": row.get("detail_url"),
                "expected_eligible": True,
                "force_click_texts": None,
                "max_acquisition_steps": 3,
            }
        ]
    if preset == "both_lab":
        return targets_for_preset("monica_lab") + targets_for_preset("costa_lab")
    raise SystemExit(f"unknown preset: {preset}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Live offer-state / acquisition slice v0")
    ap.add_argument("--preset", default="monica_lab")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("./evals/live_offer/slice_out.json"))
    ap.add_argument("--flush", action="store_true")
    ap.add_argument(
        "--trace",
        action="store_true",
        default=True,
        help="Write TraceSession (events.jsonl + audit.md) under <out>_traces/ (default on)",
    )
    ap.add_argument(
        "--no-trace",
        action="store_true",
        help="Disable TraceSession",
    )
    args = ap.parse_args()

    targets = targets_for_preset(args.preset)
    chat_fn = make_chat_fn() if args.llm else None
    if args.llm and chat_fn is None:
        print("[offer_state] --llm requested but chat_fn unavailable", file=sys.stderr)

    args.out = Path(args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    enable_trace = bool(args.trace) and not bool(args.no_trace)
    trace_root = str(args.out.parent / f"{args.out.stem}_traces") if enable_trace else None

    result = run_acquisition_batch(
        targets,
        chat_fn=chat_fn,
        task_text=PACKAGES_TASK_TEXT,
        trace_root=trace_root,
    )

    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in result.get("results") or []:
        ent = str(r.get("entity") or "x").replace(" ", "_")[:40]
        led = r.get("ledger")
        if led:
            lp = args.out.with_name(f"{args.out.stem}_ledger_{ent}.json")
            lp.write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"wrote ledger {lp}")
        if r.get("trace_dir"):
            print(f"wrote trace {r.get('trace_dir')}")

    print(f"wrote {args.out}")
    print(
        f"=== Offer-state slice === go={result.get('go_no_go')} "
        f"metrics={result.get('metrics')} faults={result.get('fault_counts')}"
    )
    if trace_root:
        print(f"trace_root={trace_root}")

    if args.flush:
        flush_ollama_model()

    go = (result.get("go_no_go") or {}).get("go")
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
