#!/usr/bin/env python3
"""
Offline pipeline on a REAL run-dir (harvest observations) — no new semantics.

  python scripts/run_pipeline_from_run_v0.py \
    --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026 \
    --llm --max-candidates 15 \
    --out ./evals/pipeline_offline/from_run_v0.json

Optional oracle overlay (JSONL with entity + expected_eligible):
  --oracle evals/run_slice_oracle_v0.jsonl --require-oracle

No admissibility.py. Same chain:
  observations → CANDIDATE_UNIT → INTERPRETATION → CODE eligibility
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observation_builder import build_from_run_dir_rich  # noqa: E402
from pipeline_offline import (  # noqa: E402
    PACKAGES_TASK_TEXT,
    go_no_go,
    run_pipeline_one,
    score_pipeline_batch,
)


def make_chat_fn(*, keep_alive: str | int | None = "0"):
    try:
        from llm import OllamaClient
        import requests
    except Exception as e:
        print(f"[from_run] Ollama unavailable: {e}", file=sys.stderr)
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
        print(f"[from_run] flush soft-fail: {e}", file=sys.stderr)


def load_oracle(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        key = str(row.get("entity") or row.get("candidate_id") or "").strip()
        if key:
            out[key] = row
    return out


def observations_to_rows(
    obs: list[dict[str, Any]],
    oracle: dict[str, dict[str, Any]],
    *,
    max_candidates: int,
) -> list[dict[str, Any]]:
    """
    Group observation contract rows by candidate_id into pipeline fixture-like rows.
    Reconstructs raw_evidence from candidate_claim texts (literal only).
    """
    by_cid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in obs:
        cid = str(o.get("candidate_id") or "").strip()
        if not cid:
            continue
        by_cid[cid].append(o)

    # Prefer candidates that have at least one candidate_claim
    ranked = sorted(
        by_cid.items(),
        key=lambda kv: (
            -sum(1 for x in kv[1] if x.get("channel") == "candidate_claim"),
            -len(kv[1]),
            kv[0],
        ),
    )
    rows: list[dict[str, Any]] = []
    for cid, items in ranked[:max_candidates]:
        claims = [
            str(x.get("text") or "")
            for x in items
            if x.get("channel") == "candidate_claim" and x.get("text")
        ]
        # de-dup preserve order
        seen = set()
        claim_u = []
        for c in claims:
            if c not in seen:
                seen.add(c)
                claim_u.append(c)
        urls = [
            str(x.get("source_url") or x.get("text") or "")
            for x in items
            if x.get("channel") in ("navigation", "search_context")
        ]
        source_url = ""
        for u in urls:
            if u.startswith("http"):
                source_url = u
                break
        if not source_url:
            for x in items:
                su = str(x.get("source_url") or "")
                if su.startswith("http"):
                    source_url = su
                    break

        row: dict[str, Any] = {
            "entity": cid,
            "raw_evidence": " | ".join(claim_u[1:] if claim_u and claim_u[0] == cid else claim_u),
            "value": next(
                (
                    str(x.get("text"))
                    for x in items
                    if x.get("channel") == "candidate_claim"
                    and str(x.get("text") or "").startswith("€")
                ),
                "",
            ),
            "source_url": source_url,
            "page_url": source_url,
            # attach full observation list so pipeline can prefer it later if needed
            "_observations": items,
        }
        if cid in oracle:
            orow = oracle[cid]
            if "expected_eligible" in orow:
                row["expected_eligible"] = orow["expected_eligible"]
            if "expected_role" in orow:
                row["expected_role"] = orow["expected_role"]
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--oracle", type=Path, default=None)
    ap.add_argument("--require-oracle", action="store_true")
    ap.add_argument("--max-candidates", type=int, default=15)
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flush-model", action="store_true")
    ap.add_argument("--skip-candidate-gate", action="store_true")
    ap.add_argument("--min-entity-score", type=float, default=0.5)
    args = ap.parse_args()

    run_dir = args.run_dir
    if not run_dir.exists():
        print(f"run-dir not found: {run_dir}", file=sys.stderr)
        return 2

    obs = build_from_run_dir_rich(
        run_dir,
        include_notes=False,
        include_shortlist=True,
        min_entity_score=args.min_entity_score,
    )
    oracle = load_oracle(args.oracle)
    rows = observations_to_rows(obs, oracle, max_candidates=args.max_candidates)

    print(
        f"[from_run] obs_rows={len(obs)} candidates={len(rows)} "
        f"oracle_keys={len(oracle)} run_dir={run_dir}",
        flush=True,
    )

    chat_fn = make_chat_fn(keep_alive="0") if args.llm else None
    if args.llm and chat_fn is None:
        print("[WARN] --llm but no chat_fn → fail-closed", flush=True)

    t0 = time.monotonic()
    results = []
    for row in rows:
        pr = run_pipeline_one(
            row,
            chat_fn=chat_fn,
            task_text=PACKAGES_TASK_TEXT,
            require_candidate_admit=not args.skip_candidate_gate,
        )
        results.append(pr)
        elig = pr.eligible
        exp = pr.expected_eligible
        match = "" if exp is None else ("OK" if bool(elig) == bool(exp) else "MISMATCH")
        print(
            f"  [{pr.candidate_id[:42]:42s}] CU={pr.candidate_stage.get('decision')} "
            f"eligible={elig} expected={exp} {match}",
            flush=True,
        )

    dur = time.monotonic() - t0
    metrics = score_pipeline_batch(results)
    # Extra staged diagnostics (no domain knowledge)
    admitted = sum(1 for r in results if r.candidate_stage.get("admitted"))
    skipped = sum(1 for r in results if r.skipped_interpretation)
    eligible_n = sum(1 for r in results if r.eligible)
    metrics["candidate_admitted_n"] = admitted
    metrics["candidate_admitted_rate"] = (admitted / len(results)) if results else 0.0
    metrics["skipped_interpretation_n"] = skipped
    metrics["eligible_n"] = eligible_n
    metrics["observation_input_n"] = len(obs)

    go = go_no_go(
        metrics,
        llm_enabled=bool(args.llm and chat_fn),
        require_oracle=bool(args.require_oracle),
        n_candidates=len(results),
    )
    # Real-run without full oracle: still GO only if safety holds; label as diagnostic
    if not args.require_oracle and metrics.get("n_with_expected", 0) == 0:
        go["reasons"].append(
            "diagnostic run without oracle — eligibility match not scored"
        )

    payload = {
        "schema_version": "pipeline-from-run-v0",
        "run_dir": str(run_dir),
        "oracle_path": str(args.oracle) if args.oracle else None,
        "llm_enabled": bool(args.llm),
        "chat_fn_available": chat_fn is not None,
        "max_candidates": args.max_candidates,
        "duration_s": round(dur, 3),
        "metrics": metrics,
        "go_no_go": go,
        "results": [r.to_dict() for r in results],
        "isolation": {
            "fresh_messages_per_call": True,
            "keep_alive": "0",
            "flush_model": bool(args.flush_model),
            "notes_included": False,
        },
        "hypothesis": (
            "Same offline chain on real harvest observations: no domain heuristics; "
            "measure candidate admit rate, eligibility, search_context leaks, UNKNOWN rate."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.flush_model:
        flush_ollama_model()

    print("=== Pipeline from run v0 ===")
    print(
        f"n={metrics['n']} admitted={admitted} eligible={eligible_n} "
        f"leaks={metrics.get('search_context_board_leaks')} "
        f"match_rate={metrics.get('eligibility_match_rate')} "
        f"llm_calls={metrics.get('llm_calls_total')} duration={dur:.1f}s"
    )
    print(f"GO={go['go']} reasons={go['reasons']}")
    print(f"wrote {args.out}")
    # Exit 0 if safety GO; with --require-oracle respect go fully
    if args.require_oracle:
        return 0 if go["go"] else 1
    return 0 if metrics.get("search_context_board_leaks", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
