#!/usr/bin/env python3
"""
Fase D STAP 1 — board_type with vs without Abora carousel claim.

Offline only. Real LLM. No live browser.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Repo root on path (same as run_fase_b_ab_offline_v0.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from interpretation import interpret_observation  # noqa: E402

PAGE_CTX = {
    "page_url": (
        "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/"
        "costa-calma/sbh-monica-beach"
    ),
    "surface": "live_detail",
    "same_entity_path": True,
}

# Fixed texts from successful run 20260915T070819Z
CLAIMS = {
    "title": (
        "SBH Monica Beach op Fuerteventura. Voordelig op vakantie naar Fuerteventura."
    ),
    "c0_flygo": (
        "TIP: boek deze vakantie als Fly & Go | Gemak voorop: pakketreis met vlucht + "
        "deze accommodatie + huurauto | De verzekering voor je auto is geregeld | "
        "Vrijheid en avontuur: ontdek in je eigen tempo je vakantiebestemming | "
        "Bekijk deze Fly & Go vakantie | Periode 1/04/2026 - 31/10/2026 | "
        "Periode 1/11/2026 - 30/04/2027 | Wanneer je tussen 01-04-2026 en 31-10-2026 "
        "in deze accommodatie verblijft, is onderstaande informatie van toepassing."
    ),
    "c1_reviews": (
        "26 maart 2026 | Over Costa Calma: | Leuk langgerekt dorp, met een lange "
        "bosstrook mrt wandelpaden. Wildlife dierentuin is een aanrader. | "
        "Over SBH Monica Beach: | Leuk hotel, je merkt niet dat het groot is. "
        "Voldoende ligstoelen overal. 2 zwembaden, leuke animatie | "
        "Algemene indruk | 10 | Ligging"
    ),
    "c2_abora": (
        "Spanje / Gran Canaria | Abora Continental by Lopesan Hotels 3+* | "
        "All Inclusive | 10-01-2027 | 5 dagen (4 nachten) | vanaf Brussel | "
        "va | 704 | p.p."
    ),
}

VARIANTS = {
    "1a_all": ["title", "c0_flygo", "c1_reviews", "c2_abora"],
    "1b_no_abora": ["title", "c0_flygo", "c1_reviews"],
    "1c_abora_only": ["c2_abora"],
}


def _make_chat_fn(temperature: float):
    try:
        from llm import OllamaClient
    except ImportError as e:
        raise RuntimeError(
            "Cannot import llm.OllamaClient. Run from repo root or Docker image "
            "with WORKDIR=/app and code mounted."
        ) from e

    client = OllamaClient(temperature=temperature)

    def chat_fn(messages: list[dict[str, Any]]) -> dict[str, Any]:
        msg = client.chat(messages)
        return msg if isinstance(msg, dict) else {"content": str(msg)}

    return chat_fn, client.model, client.base_url


def load_board_decision(contract_path: Path) -> dict[str, Any]:
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    c = raw.get("contract") or raw
    for d in c.get("decisions") or []:
        if d.get("id") == "board_type":
            return d
    raise SystemExit(f"board_type decision not found in {contract_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Fase D binding A/B (offline)")
    ap.add_argument(
        "--contract",
        required=True,
        help="Path to frozen contract_02 JSON",
    )
    ap.add_argument("--temperature", type=float, default=0.1)
    ap.add_argument("--outdir", default="./evals/fase_d_binding")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    decision = load_board_decision(Path(args.contract))
    chat_fn, model, base_url = _make_chat_fn(args.temperature)

    print(f"model       = {model}")
    print(f"base_url    = {base_url}")
    print(f"temperature = {args.temperature}")
    print(f"board outcomes = {decision.get('outcomes')}")
    print(f"question    = {(decision.get('question') or '')[:120]}")

    results: dict[str, Any] = {
        "schema": "fase-d-binding-ab-v0",
        "temperature": args.temperature,
        "model": model,
        "variants": {},
    }

    for name, keys in VARIANTS.items():
        print(f"\n=== {name}  keys={keys} ===")
        per_claim: list[dict[str, Any]] = []
        for k in keys:
            text = CLAIMS[k]
            t0 = time.monotonic()
            ir = interpret_observation(
                text,
                contract_decision=decision,
                chat_fn=chat_fn,
                page_context=PAGE_CTX,
            )
            dt = round(time.monotonic() - t0, 2)
            row = {
                "claim_key": k,
                "outcome": ir.outcome,
                "confidence": ir.confidence,
                "reason": (ir.reason or "")[:300],
                "seconds": dt,
            }
            per_claim.append(row)
            print(f"  [{k}] {ir.outcome}/{ir.confidence} ({dt}s)")
            print(f"         {(ir.reason or '')[:180]}")

        # Aggregate like a simple last-non-UNKNOWN sweep (diagnostic, not production)
        final = "UNKNOWN"
        for row in per_claim:
            o = str(row["outcome"] or "UNKNOWN").upper()
            if o and o not in ("UNKNOWN",):
                final = o
        results["variants"][name] = {
            "per_claim": per_claim,
            "aggregate_last_non_unknown": final,
        }
        print(f"  AGGREGATE (last non-UNKNOWN) -> {final}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outp = outdir / f"fase_d_binding_{stamp}.json"
    outp.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {outp}")
    print("\n============================================================")
    print("SUMMARY (copy back into chat)")
    print("============================================================")
    for name, v in results["variants"].items():
        print(f"  {name}: {v['aggregate_last_non_unknown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
