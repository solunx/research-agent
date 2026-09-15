#!/usr/bin/env python3
"""
Fase B offline A/B — single-decision vs multi-decision on ONE claim text.

Purpose
-------
Diagnose when board_type (or any decision) loses accuracy under multi-decision
batch prompts on the local model. Domain-free: works for any claim + any
decision definitions you pass.

Usage (on node-01, with Ollama reachable):
  # 1) Default Monica-like claim + built-in decision defs
  python scripts/run_fase_b_ab_offline_v0.py --llm --temperature 0.1

  # 2) Claim text from a real failed run (recommended)
  python scripts/run_fase_b_ab_offline_v0.py --llm --temperature 0.1 \\
    --claim-file path/to/claim.txt

  # 3) Docker (same as other scripts)
  docker compose run --rm research-agent \\
    python scripts/run_fase_b_ab_offline_v0.py --llm --temperature 0.1 \\
    --claim-file /app/evals/.../claim.txt \\
    --outdir ./evals/fase_b_ab

What it prints
--------------
1a  single: board only, subject only
1b  multi 2: board-first vs subject-first
1c  multi 3: live order vs board-first
optional carousel claim (negative control)

No live browser. No default change to batch_decisions.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running from repo root or /app
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from interpretation import interpret_observation, interpret_observation_multi  # noqa: E402


# ---------------------------------------------------------------------------
# Default claim (Monica-like). Prefer --claim-file from a real run when possible.
# ---------------------------------------------------------------------------
DEFAULT_CLAIM_C1 = (
    "SBH Monica Beach op Fuerteventura. Voordelig op vakantie naar Fuerteventura. "
    "All Inclusive - Aparthotel. "
    "TIP: boek deze vakantie als Fly & Go | Gemak voorop: pakketreis met vlucht + "
    "deze accommodatie + huurauto | Bekijk deze Fly & Go vakantie | "
    "Periode 1/04/2026 - 31/10/2026 | Periode 1/11/2026 - 30/04/2027"
)

DEFAULT_CLAIM_CAROUSEL = (
    "Spanje / Gran Canaria | Abora Continental by Lopesan Hotels 3+* | "
    "All Inclusive | 10-01-2027 | 5 dagen (4 nachten) | vanaf Brussel | va | 704 | p.p."
)

DEFAULT_PAGE_CTX = {
    "page_url": (
        "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/"
        "costa-calma/sbh-monica-beach"
    ),
    "surface": "live_detail",
    "same_entity_path": True,
}

# Decision shapes (generic structure; labels match contract_02 style)
D_SUBJECT = {
    "id": "subject_instance",
    "question": (
        "Is this observation from the public detail page for the hotel property "
        "SBH Monica Beach (Fuerteventura)? Choose one outcome."
    ),
    "outcomes": ["CONFIRMED", "NOT_FOUND", "PARTIAL", "UNKNOWN"],
    "definitions": {
        "CONFIRMED": "Text clearly identifies SBH Monica Beach as the page subject.",
        "NOT_FOUND": "Text is about a different property or unrelated page.",
        "PARTIAL": "Related to the property but identity not fully confirmed.",
        "UNKNOWN": "Insufficient evidence.",
    },
    "notes": [
        "Do not invent identity from nearby hotels in a recommendation carousel."
    ],
}

D_BOARD = {
    "id": "board_type",
    "question": (
        "What board/meal plan is advertised for SBH Monica Beach on this page? "
        "Choose exactly one outcome from the allowed list."
    ),
    "outcomes": [
        "ALL_INCLUSIVE",
        "HALF_BOARD",
        "FULL_BOARD",
        "BED_AND_BREAKFAST",
        "ROOM_ONLY",
        "NOT_STATED",
        "UNKNOWN",
    ],
    "definitions": {
        "ALL_INCLUSIVE": "Meals and typically drinks included for this property.",
        "HALF_BOARD": "Breakfast and dinner included.",
        "FULL_BOARD": "Breakfast, lunch and dinner included.",
        "BED_AND_BREAKFAST": "Only breakfast included.",
        "ROOM_ONLY": "Accommodation without meals included.",
        "NOT_STATED": "No board/meal plan is stated for this property.",
        "UNKNOWN": "Ambiguous or insufficient evidence.",
    },
    "notes": [
        "Attribute board type only to SBH Monica Beach, not to other hotels "
        "in a list/carousel.",
        "Prefer NOT_STATED over guessing when All Inclusive appears only on "
        "a different hotel name.",
    ],
}

D_DETAIL = {
    "id": "detail_link",
    "question": (
        "Is the observed URL a valid hotel property detail page "
        "(not only a search/list)?"
    ),
    "outcomes": ["VALID_DETAIL_PAGE", "NOT_DETAIL_PAGE", "UNKNOWN"],
    "definitions": {
        "VALID_DETAIL_PAGE": "URL/path is a specific accommodation detail page.",
        "NOT_DETAIL_PAGE": "Search, list, booking chrome, or unrelated.",
        "UNKNOWN": "Cannot tell.",
    },
    "notes": [],
}


def _make_chat_fn(temperature: float):
    """Build chat_fn using llm.OllamaClient with explicit temperature."""
    try:
        from llm import OllamaClient
    except ImportError as e:
        raise RuntimeError(
            "Cannot import llm.OllamaClient. Run from repo root or Docker image."
        ) from e

    client = OllamaClient(temperature=temperature)

    def chat_fn(messages: list[dict[str, Any]]) -> dict[str, Any]:
        msg = client.chat(messages)
        return msg if isinstance(msg, dict) else {"content": str(msg)}

    return chat_fn, client.model, client.base_url


def _run_single(
    decision: dict,
    text: str,
    page_ctx: dict,
    chat_fn,
    label: str,
) -> dict[str, Any]:
    t0 = time.monotonic()
    ir = interpret_observation(
        text,
        contract_decision=decision,
        chat_fn=chat_fn,
        page_context=page_ctx,
    )
    dt = round(time.monotonic() - t0, 2)
    row = {
        "label": label,
        "mode": "single",
        "decision_id": decision["id"],
        "outcome": ir.outcome,
        "confidence": ir.confidence,
        "reason": ir.reason,
        "duration_s": dt,
    }
    print(
        f"  [{label}] SINGLE {decision['id']} -> {ir.outcome}/{ir.confidence} "
        f"({dt}s)"
    )
    print(f"         reason: {ir.reason[:160]!r}")
    return row


def _run_multi(
    decisions: list[dict],
    text: str,
    page_ctx: dict,
    chat_fn,
    label: str,
) -> dict[str, Any]:
    t0 = time.monotonic()
    res = interpret_observation_multi(
        text,
        decisions=decisions,
        chat_fn=chat_fn,
        page_context=page_ctx,
    )
    dt = round(time.monotonic() - t0, 2)
    outcomes = {}
    for k, v in res.items():
        outcomes[k] = {
            "outcome": v.outcome,
            "confidence": v.confidence,
            "reason": v.reason,
        }
        print(
            f"  [{label}] MULTI  {k} -> {v.outcome}/{v.confidence}"
        )
        print(f"         reason: {v.reason[:160]!r}")
    print(f"  [{label}] total_s={dt}")
    return {
        "label": label,
        "mode": "multi",
        "decision_ids": [d["id"] for d in decisions],
        "outcomes": outcomes,
        "duration_s": dt,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fase B offline A/B: single vs multi-decision interpretation"
    )
    ap.add_argument(
        "--llm",
        action="store_true",
        help="Call real Ollama (required for this experiment)",
    )
    ap.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Ollama temperature (default 0.1 for more deterministic answers)",
    )
    ap.add_argument(
        "--claim-file",
        type=str,
        default=None,
        help="Path to a text file with the claim to interpret (UTF-8). "
        "If omitted, uses built-in DEFAULT_CLAIM_C1.",
    )
    ap.add_argument(
        "--claim-text",
        type=str,
        default=None,
        help="Claim text directly on the command line (alternative to --claim-file)",
    )
    ap.add_argument(
        "--skip-carousel",
        action="store_true",
        help="Skip the negative-control carousel claim",
    )
    ap.add_argument(
        "--outdir",
        type=str,
        default="./evals/fase_b_ab",
        help="Where to write the JSON result",
    )
    args = ap.parse_args()

    if not args.llm:
        print("ERROR: this experiment needs --llm (real Ollama).")
        print("Example: python scripts/run_fase_b_ab_offline_v0.py --llm --temperature 0.1")
        return 2

    # --- load claim ---
    if args.claim_text:
        claim = args.claim_text.strip()
        claim_src = "cli"
    elif args.claim_file:
        p = Path(args.claim_file)
        if not p.is_file():
            print(f"ERROR: claim file not found: {p}")
            return 2
        claim = p.read_text(encoding="utf-8").strip()
        claim_src = str(p)
    else:
        claim = DEFAULT_CLAIM_C1
        claim_src = "DEFAULT_CLAIM_C1"
        print(
            "NOTE: using built-in DEFAULT_CLAIM_C1. "
            "For a stronger test, pass --claim-file from step_000_candidates.json text."
        )

    if not claim:
        print("ERROR: empty claim text")
        return 2

    print("=" * 60)
    print("Fase B offline A/B")
    print(f"  temperature = {args.temperature}")
    print(f"  claim_src   = {claim_src}")
    print(f"  claim[:120] = {claim[:120]!r}...")
    print("=" * 60)

    try:
        chat_fn, model, base_url = _make_chat_fn(args.temperature)
    except Exception as e:
        print(f"ERROR: could not create LLM client: {e}")
        return 1

    print(f"  model    = {model}")
    print(f"  base_url = {base_url}")
    print()

    page_ctx = dict(DEFAULT_PAGE_CTX)
    results: dict[str, Any] = {
        "schema": "fase-b-ab-offline-v0",
        "created_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "temperature": args.temperature,
        "model": model,
        "claim_src": claim_src,
        "claim_preview": claim[:400],
        "runs": {},
    }

    # ----- 1a single -----
    print("--- 1a  single: board_type only ---")
    results["runs"]["1a_board"] = _run_single(
        D_BOARD, claim, page_ctx, chat_fn, "1a"
    )
    print()
    print("--- 1a  single: subject_instance only ---")
    results["runs"]["1a_subject"] = _run_single(
        D_SUBJECT, claim, page_ctx, chat_fn, "1a"
    )
    print()

    # ----- 1b multi 2 -----
    print("--- 1b  multi2: board first, then subject ---")
    results["runs"]["1b_board_first"] = _run_multi(
        [D_BOARD, D_SUBJECT], claim, page_ctx, chat_fn, "1b-bf"
    )
    print()
    print("--- 1b  multi2: subject first, then board ---")
    results["runs"]["1b_subject_first"] = _run_multi(
        [D_SUBJECT, D_BOARD], claim, page_ctx, chat_fn, "1b-sf"
    )
    print()

    # ----- 1c multi 3 -----
    print("--- 1c  multi3: live-like order (subject, detail, board) ---")
    results["runs"]["1c_live_order"] = _run_multi(
        [D_SUBJECT, D_DETAIL, D_BOARD], claim, page_ctx, chat_fn, "1c-live"
    )
    print()
    print("--- 1c  multi3: board first ---")
    results["runs"]["1c_board_first"] = _run_multi(
        [D_BOARD, D_SUBJECT, D_DETAIL], claim, page_ctx, chat_fn, "1c-bf"
    )
    print()

    # ----- negative control -----
    if not args.skip_carousel:
        print("--- carousel negative control (other hotel + All Inclusive) ---")
        print("--- single board on carousel claim ---")
        results["runs"]["carousel_single_board"] = _run_single(
            D_BOARD, DEFAULT_CLAIM_CAROUSEL, page_ctx, chat_fn, "car"
        )
        print()
        print("--- multi2 on carousel claim ---")
        results["runs"]["carousel_multi2"] = _run_multi(
            [D_SUBJECT, D_BOARD],
            DEFAULT_CLAIM_CAROUSEL,
            page_ctx,
            chat_fn,
            "car-m2",
        )
        print()

    # ----- summary table -----
    print("=" * 60)
    print("SUMMARY (copy this back into the chat)")
    print("=" * 60)

    def _board_from(run_key: str) -> str:
        r = results["runs"].get(run_key) or {}
        if r.get("mode") == "single":
            return f"{r.get('outcome')}/{r.get('confidence')}"
        outs = r.get("outcomes") or {}
        b = outs.get("board_type") or {}
        return f"{b.get('outcome')}/{b.get('confidence')}"

    def _subj_from(run_key: str) -> str:
        r = results["runs"].get(run_key) or {}
        if r.get("mode") == "single" and r.get("decision_id") == "subject_instance":
            return f"{r.get('outcome')}/{r.get('confidence')}"
        outs = r.get("outcomes") or {}
        s = outs.get("subject_instance") or {}
        return f"{s.get('outcome')}/{s.get('confidence')}"

    rows = [
        ("1a single board", _board_from("1a_board")),
        ("1a single subject", _subj_from("1a_subject")),
        ("1b multi2 board-first → board", _board_from("1b_board_first")),
        ("1b multi2 board-first → subject", _subj_from("1b_board_first")),
        ("1b multi2 subject-first → board", _board_from("1b_subject_first")),
        ("1b multi2 subject-first → subject", _subj_from("1b_subject_first")),
        ("1c multi3 live-order → board", _board_from("1c_live_order")),
        ("1c multi3 board-first → board", _board_from("1c_board_first")),
    ]
    if not args.skip_carousel:
        rows.append(
            ("carousel single board", _board_from("carousel_single_board"))
        )
        rows.append(
            ("carousel multi2 → board", _board_from("carousel_multi2"))
        )

    for name, val in rows:
        print(f"  {name:40s} {val}")

    # write output
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = results["created_at"]
    out_path = outdir / f"fase_b_ab_{stamp}.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
