#!/usr/bin/env python3
"""
Single Contract Discovery mode experiment (CD0 / CD1 / CD2).

Does NOT change the live retrieval pipeline.

Usage:
  # Offline heuristic (no Ollama)
  python scripts/run_contract_discovery_mode_v0.py --mode CD0 --task packages --out ./cd0.json

  # LLM
  python scripts/run_contract_discovery_mode_v0.py --mode CD2 --task packages --llm \\
    --out ./cd2_packages.json

  # Literature-style task (fixture surfaces)
  python scripts/run_contract_discovery_mode_v0.py --mode CD1 --task literature --llm \\
    --out ./cd1_lit.json

  # Real run dir surfaces
  python scripts/run_contract_discovery_mode_v0.py --mode CD2 --llm \\
    --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026 \\
    --out ./cd2_from_run.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_discovery import (  # noqa: E402
    CONTRACT_SCHEMA_VERSION,
    analyze_gaps,
    compare_contracts,
    discover_contract_mode,
    load_run_context,
    select_representative_surfaces,
    validate_contract,
)

TASK_PACKAGES = """Vind concrete all-inclusive (of volpension) pakket-deals (vlucht + hotel) voor 3 personen
in december 2026, vertrek bij voorkeur BRU of Charleroi, budget max €1000 p.p.

Harde criteria: pakket vlucht+hotel, all-inclusive/volpension, prijs zichtbaar, detail/boekingslink.
Primaire bronnen: nl.lastminute.com / lastminute.be, sunweb.be, optioneel corendon.be.
"""

TASK_LITERATURE = """Find primary outcome results from randomized controlled trials comparing
drug A versus standard care. Extract study design, primary endpoint result, and population size
when available. Prefer full-text or results sections over chrome/keywords/footers.
"""

FIXTURE_SURFACES_PACKAGES = [
    {
        "name": "Sercotel Playa Canteras",
        "source_url": "https://nl.lastminute.com/s/tsx?destination=CTY-1&meal=all-inclusive",
        "page_role": "list",
        "awareness_status": "partial",
        "member_count": 3,
        "sample_members": [
            {"entity": "Sercotel Playa Canteras", "value": "€2.275"},
            {"entity": "board", "value": "Enkel kamer"},
            {"entity": "flight", "value": "Heen- en terugvluchten vanaf Brussel"},
        ],
        "observed_raw": "Enkel kamer | Heen- en terugvluchten vanaf Brussel | € 2.275",
        "rankable": False,
        "match_status": "partial",
    },
    {
        "name": "Gran Canaria",
        "source_url": "https://nl.lastminute.com/s/tsx?destination=A&meal=all-inclusive",
        "page_role": "list",
        "awareness_status": "partial",
        "member_count": 1,
        "sample_members": [
            {"entity": "Gran Canaria", "value": "€2.328 pp, 30 nachten"},
        ],
        "observed_raw": "Spanje | Rechtstreekse vlucht inbegrepen | Hotel | € 2.328 | pp, 30 nachten",
        "rankable": False,
        "match_status": "partial",
    },
    {
        "name": "Vragen & Contact",
        "source_url": "https://nl.lastminute.com/",
        "page_role": "landing",
        "awareness_status": "partial",
        "member_count": 0,
        "sample_members": [],
        "observed_raw": "Vragen & Contact",
        "rankable": False,
    },
]

FIXTURE_SURFACES_LITERATURE = [
    {
        "name": "rct_paragraph",
        "source_url": "paper://example/rct",
        "page_role": "detail",
        "awareness_status": "adequate",
        "member_count": 2,
        "sample_members": [
            {
                "entity": "methods",
                "value": "We conducted a randomised, double-blind, placebo-controlled trial in 412 adults.",
            },
            {
                "entity": "outcome",
                "value": "Primary outcome: mean HbA1c reduction −1.2% (95% CI −1.5 to −0.9) versus control.",
            },
        ],
        "observed_raw": "randomised controlled trial; primary outcome HbA1c",
        "rankable": False,
    },
    {
        "name": "footer",
        "source_url": "paper://example/rct",
        "page_role": "detail",
        "awareness_status": "partial",
        "member_count": 0,
        "sample_members": [],
        "observed_raw": "Corresponding author: Jane Doe, Department of Medicine.",
        "rankable": False,
    },
]


def make_chat_fn():
    from llm import OllamaClient

    client = OllamaClient()
    def chat(messages):
        return client.chat(messages)
    return chat


def resolve_task_and_surfaces(args) -> tuple[str, list[dict[str, Any]], dict[str, Any], str]:
    meta: dict[str, Any] = {}
    task_id = args.task
    if args.run_dir:
        ctx = load_run_context(Path(args.run_dir))
        task_text = ctx["task_text"] or TASK_PACKAGES
        surfaces = select_representative_surfaces(ctx["shortlist"], max_surfaces=4)
        meta = ctx.get("metadata") or {}
        task_id = task_id or "from_run"
        return task_text, surfaces, meta, task_id

    if args.task == "literature":
        return TASK_LITERATURE, FIXTURE_SURFACES_LITERATURE, meta, "literature"
    # default packages
    return TASK_PACKAGES, FIXTURE_SURFACES_PACKAGES, meta, "packages"


def main() -> int:
    ap = argparse.ArgumentParser(description="Contract Discovery mode experiment CD0|CD1|CD2")
    ap.add_argument("--mode", required=True, choices=["CD0", "CD1", "CD2", "cd0", "cd1", "cd2"])
    ap.add_argument("--task", default="packages", choices=["packages", "literature"])
    ap.add_argument("--run-dir", default=None, help="Optional real run directory for surfaces")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-heuristic-fallback", action="store_true")
    ap.add_argument(
        "--strict-exit",
        action="store_true",
        help="Exit 1 when validation.ok is false (default: exit 0 if a contract was written)",
    )
    args = ap.parse_args()
    mode = args.mode.upper()

    task_text, surfaces, meta, task_id = resolve_task_and_surfaces(args)
    if mode == "CD0":
        surfaces_for_mode: list[dict[str, Any]] = []
    else:
        surfaces_for_mode = surfaces

    chat_fn = None
    chat_ok = False
    if args.llm:
        try:
            chat_fn = make_chat_fn()
            chat_ok = True
        except Exception as e:
            print(f"[cd-mode] --llm requested but chat_fn failed: {e}", file=sys.stderr)
            if args.no_heuristic_fallback:
                return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    error_msg: str | None = None
    result: dict[str, Any] | None = None
    try:
        result = discover_contract_mode(
            mode,
            task_text,
            surfaces_for_mode,
            chat_fn=chat_fn,
            meta=meta,
            use_heuristic_fallback=not args.no_heuristic_fallback,
        )
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"[cd-mode] discover_contract_mode failed: {error_msg}", file=sys.stderr)
        result = {
            "mode": mode,
            "contract": {
                "schema_version": CONTRACT_SCHEMA_VERSION,
                "subject": {"name": "error", "definition": error_msg},
                "observables": ["error"],
                "decisions": [
                    {
                        "id": "subject_instance",
                        "question": "error",
                        "outcomes": ["TARGET", "NOT_TARGET", "UNKNOWN"],
                    }
                ],
                "sufficiency": {"required": [], "blocking_unknowns": []},
                "missing_to_solve": [error_msg],
                "_source": "error",
            },
            "provisional": None,
            "llm_calls": 0,
            "surfaces_n": len(surfaces_for_mode),
        }

    dur = time.monotonic() - t0
    contract = result["contract"]
    validation = validate_contract(contract)
    try:
        gaps = analyze_gaps(contract, surfaces if surfaces else surfaces_for_mode, meta)
    except Exception as e:
        from contract_discovery import GapAnalysis

        gaps = GapAnalysis(
            decision_status={},
            observable_status={},
            why_zero_rankable=[f"analyze_gaps_error: {e}"],
            contract_explains_run=False,
            notes=[str(e)],
        )

    stability = None
    if result.get("provisional"):
        try:
            stability = compare_contracts(result["provisional"], contract)
        except Exception:
            stability = None

    # CD0 vs would-be CD1 stability if we also have surfaces (diagnostic only)
    cross = None
    if mode == "CD0" and surfaces:
        try:
            from contract_discovery import discover_contract

            other = discover_contract(
                task_text, surfaces, chat_fn=None, meta=meta, use_heuristic_fallback=True
            )
            cross = compare_contracts(contract, other)
        except Exception:
            cross = None

    has_decisions = bool(
        isinstance(contract.get("decisions"), list) and contract.get("decisions")
    )
    payload: dict[str, Any] = {
        "schema_version": "contract-discovery-mode-v0",
        "mode": mode,
        "task_id": task_id,
        "llm_enabled": bool(args.llm),
        "chat_fn_available": chat_ok,
        "duration_s": round(dur, 3),
        "llm_calls": result.get("llm_calls", 0),
        "surfaces_n": result.get("surfaces_n", 0),
        "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        "contract": contract,
        "provisional": result.get("provisional"),
        "validation": {
            "ok": validation.ok,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "gap_analysis": {
            "decision_status": gaps.decision_status,
            "why_zero_rankable": gaps.why_zero_rankable[:8],
            "contract_explains_run": gaps.contract_explains_run,
            "notes": gaps.notes,
        },
        "stability_provisional_to_final": stability,
        "stability_cd0_vs_heuristic_cd1": cross,
        "success_v0": bool(
            validation.ok and (gaps.contract_explains_run or mode == "CD0") and not error_msg
        ),
        "go_no_go": {
            "go": bool(validation.ok and not error_msg),
            "reasons": (
                ["validation.ok"]
                if validation.ok and not error_msg
                else (
                    [f"runtime_error: {error_msg}"]
                    if error_msg
                    else [f"validation errors: {validation.errors[:5]}"]
                )
            ),
        },
        "error": error_msg,
        "note": (
            "CD0=task-only provisional; CD1=task+samples one-shot; "
            "CD2=provisional then refine with samples. Pilot metrics; do not average domains. "
            "Exit 0 by default when a contract JSON was written (use --strict-exit for validation gate)."
        ),
    }

    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== Contract Discovery mode ===")
    print(
        f"mode={mode} task={task_id} source={contract.get('_source')} "
        f"llm_calls={payload['llm_calls']}"
    )
    print(
        f"validation.ok={validation.ok} explains_run={gaps.contract_explains_run} "
        f"duration={dur:.1f}s"
    )
    if validation.errors:
        print(f"validation.errors={validation.errors[:5]}")
    if validation.warnings:
        print(f"validation.warnings={validation.warnings[:5]}")
    subj = (contract.get("subject") or {}).get("name")
    decs = [d.get("id") for d in (contract.get("decisions") or []) if isinstance(d, dict)]
    print(f"subject={subj} decisions={decs}")
    if stability:
        print(f"stability jaccard_decisions={stability.get('jaccard_decisions')}")
    print(f"GO={payload['go_no_go']['go']}")
    print(f"wrote {out}")

    # Experiment-friendly exit: success if we produced a contract artifact.
    # Use --strict-exit to gate on validation.ok (old behaviour).
    if error_msg and not has_decisions:
        return 2
    if args.strict_exit and not payload["go_no_go"]["go"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
