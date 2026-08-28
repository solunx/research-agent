#!/usr/bin/env python3
"""
Live detail slice v0 — open real oracle detail URLs → observations → frozen pipeline.

  # fetch only (no LLM) — proves B/C text extraction
  python scripts/run_live_detail_slice_v0.py --entities "SBH Costa Calma Beach Resort" \
    --backend playwright --out ./evals/live_detail/costa_fetch.json

  # full D–F with LLM
  python scripts/run_live_detail_slice_v0.py --preset costa_monica --llm \
    --backend playwright --out ./evals/live_detail/costa_monica_llm.json

  # all primary detail positives from oracle (exclude offer-dependent cases)
  python scripts/run_live_detail_slice_v0.py --preset primary_detail --llm \
    --out ./evals/live_detail/primary_llm.json

Ledger JSON is written next to --out as <stem>_ledger_<entity>.json (per entity)
and a combined report at --out.
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

from live_detail_slice import (  # noqa: E402
    oracle_by_entity,
    run_live_detail_batch,
)
from pipeline_offline import PACKAGES_TASK_TEXT  # noqa: E402

EVALS = ROOT / "evals"
ORACLE = EVALS / "positive_evidence_trace_oracle_v0.jsonl"

# Primary detail cases (direct AI on page) — not Playa Park offer-dependent / JS-heavy AX
PRIMARY_DETAIL = [
    "SBH Costa Calma Beach Resort",
    "SBH Monica Beach",
]
COSTA_MONICA = list(PRIMARY_DETAIL)
IVI = ["The IVI Mare - adults only"]


def make_chat_fn(*, keep_alive: str | int | None = "0"):
    try:
        from llm import OllamaClient
        import requests
    except Exception as e:
        print(f"[live_detail] Ollama unavailable: {e}", file=sys.stderr)
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
        print(f"[live_detail] flush soft-fail: {e}", file=sys.stderr)


def resolve_targets(
    *,
    preset: str | None,
    entities: list[str],
    oracle_path: Path,
) -> list[dict[str, Any]]:
    by = oracle_by_entity(oracle_path)
    names: list[str] = []
    if preset == "costa_monica":
        names = COSTA_MONICA
    elif preset == "primary_detail":
        names = PRIMARY_DETAIL + IVI
    elif preset == "ivi":
        names = IVI
    elif entities:
        names = entities
    else:
        names = COSTA_MONICA

    targets = []
    for name in names:
        rec = by.get(name)
        if not rec:
            print(f"[live_detail] WARN: entity not in oracle: {name}", file=sys.stderr)
            continue
        targets.append(
            {
                "entity": name,
                "detail_url": rec.get("detail_url"),
                "expected_eligible": bool(rec.get("expected_eligible", True)),
                "expected_role": rec.get("expected_role") or "live_detail_ai",
            }
        )
    return targets


def main() -> int:
    ap = argparse.ArgumentParser(description="Live detail slice v0")
    ap.add_argument("--oracle", type=Path, default=ORACLE)
    ap.add_argument(
        "--preset",
        choices=["costa_monica", "primary_detail", "ivi"],
        default=None,
    )
    ap.add_argument(
        "--entities",
        nargs="*",
        default=[],
        help="Oracle entity names (quote multi-word names)",
    )
    ap.add_argument("--backend", choices=["playwright", "fetch"], default="playwright")
    ap.add_argument("--wait-seconds", type=float, default=3.5)
    ap.add_argument(
        "--max-claim-lines",
        type=int,
        default=24,
        help="Max page body lines as candidate_claim (caps LLM calls on live pages)",
    )
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--flush-model", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    targets = resolve_targets(
        preset=args.preset, entities=list(args.entities or []), oracle_path=args.oracle
    )
    if not targets:
        print("[live_detail] no targets resolved", file=sys.stderr)
        return 2

    if args.flush_model:
        flush_ollama_model()

    chat_fn = make_chat_fn(keep_alive="0") if args.llm else None
    if args.llm and chat_fn is None:
        print("[live_detail] --llm requested but chat unavailable", file=sys.stderr)
        return 2

    print(f"[live_detail] targets={len(targets)} backend={args.backend} llm={args.llm}")
    for t in targets:
        print(f"  - {t['entity']}: {t['detail_url'][:90]}...")

    t0 = time.monotonic()
    report = run_live_detail_batch(
        targets,
        chat_fn=chat_fn,
        backend=args.backend,
        wait_seconds=args.wait_seconds,
        task_text=PACKAGES_TASK_TEXT,
        max_claim_lines=args.max_claim_lines,
    )
    report["duration_s"] = round(time.monotonic() - t0, 2)
    report["llm_enabled"] = bool(args.llm)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Write per-entity ledgers
    for r in report.get("results") or []:
        ent = str(r.get("entity") or "unknown").replace(" ", "_")[:40]
        led_path = args.out.parent / f"{args.out.stem}_ledger_{ent}.json"
        led = r.get("ledger")
        if led:
            led_path.write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")
            r["ledger_path"] = str(led_path)
        # shrink embedded ledger in main report to summary to keep file smaller
        if "ledger" in r and isinstance(r["ledger"], dict):
            r["ledger_summary"] = {
                "run_id": r["ledger"].get("run_id"),
                "stop_reason": r["ledger"].get("stop_reason"),
                "counts": r["ledger"].get("counts"),
                "pipeline_summary": r["ledger"].get("pipeline_summary"),
            }
            # keep full ledger only in side file
            del r["ledger"]

    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    g = report.get("go_no_go") or {}
    m = report.get("metrics") or {}
    print("=== Live detail slice v0 ===")
    print(
        f"n={report.get('n')} fetch_ok={m.get('n_ok_fetch')} "
        f"pos={m.get('positive_eligible_ok')}/{m.get('positive_n')} "
        f"match_rate={m.get('eligibility_match_rate')} "
        f"faults={report.get('fault_counts')} duration={report.get('duration_s')}s"
    )
    print(f"GO={g.get('go')} reasons={g.get('reasons')}")
    for r in report.get("results") or []:
        st = r.get("stages") or {}
        d = st.get("D_observation") or {}
        print(
            f"  [{str(r.get('entity'))[:42]:42}] "
            f"ok={r.get('ok')} eligible={r.get('eligible')} "
            f"boardish={d.get('boardish_literal_present')} "
            f"fault={r.get('fault_localization')} stop={r.get('stop_reason')}"
        )
    print(f"wrote {args.out}")
    return 0 if g.get("go") else 1


if __name__ == "__main__":
    raise SystemExit(main())
