#!/usr/bin/env python3
"""
Contract Discovery v0 — offline / optional-LLM experiment.

Does NOT change the retrieval pipeline.

Usage (from repo root, inside container or host):

  # Heuristic only (no Ollama) — always works for schema + gap analysis
  python scripts/run_contract_discovery_v0.py \\
      --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026

  # With Ollama (typed contract from LLM)
  python scripts/run_contract_discovery_v0.py \\
      --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026 \\
      --llm

  # Write result JSON (recommended when runs/ is root-owned by Docker)
  python scripts/run_contract_discovery_v0.py --run-dir PATH --out ./contract_discovery_v0.json

  # Optional LLM fill (needs Ollama reachable, same as agent)
  python scripts/run_contract_discovery_v0.py --run-dir PATH --llm --out ./contract_discovery_v0.json

If --run-dir is omitted, uses built-in fixture synthesized from the known
2026-08-24 packages run (destination noise + hotel list + rankable=0).

This script is intentionally OUTSIDE the docker agent loop: it reads completed
run artifacts and produces a Research Contract + gap analysis. It does not
call browser tools or modify harvest/eligibility.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_discovery import (  # noqa: E402
    CONTRACT_SCHEMA_VERSION,
    analyze_gaps,
    discover_contract,
    select_representative_surfaces,
    validate_contract,
    run_discovery_on_run_dir,
    compact_page_surface,
)


def fixture_run_dir(tmp: Path) -> Path:
    """Build a minimal run dir from known failure modes of the packages task."""
    tmp.mkdir(parents=True, exist_ok=True)
    task = (ROOT / "tasks" / "compare_packages_dec2026.md")
    if task.exists():
        (tmp / "task.md").write_text(task.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        (tmp / "task.md").write_text(
            "Vind all-inclusive pakketten 3 pax december 2026 BRU max €1000 pp.\n",
            encoding="utf-8",
        )

    shortlist = [
        {
            "name": "Gran Canaria",
            "source_url": "https://nl.lastminute.com/s/tsx?destination=A&pageType=searchDestinations",
            "price": "€2.328",
            "match_status": "observed_only",
            "eligibility": "ineligible",
            "rankable": False,
            "evidence": {
                "observed": {
                    "entity": "Gran Canaria",
                    "value": "€2.328",
                    "raw_evidence": "Spanje | Rechtstreekse vlucht inbegrepen | Hotel | € 2.328 | pp, 30 nachten",
                }
            },
            "page_state": {
                "observed_url": "https://nl.lastminute.com/s/tsx?destination=A&pageType=searchDestinations",
                "page_role": "list",
                "usable_for_task": True,
                "awareness": {"status": "partial", "gaps": ["subject_identity"]},
                "structure": {
                    "member_count": 0,
                    "members": [],
                    "rejected_members": [
                        {
                            "entity": "Gran Canaria",
                            "value": "€2.328",
                            "reject_reason": "reject_geo_nav",
                            "role": "NAVIGATION",
                        },
                        {
                            "entity": "Personaliseer je pakket",
                            "value": "€4.557",
                            "reject_reason": "reject_cta",
                            "role": "ACTION",
                        },
                    ],
                    "admissibility_stats": {"accept": 0, "reject_geo_nav": 1, "reject_cta": 1},
                    "member_role_stats": {"NAVIGATION": 1, "ACTION": 1},
                },
            },
        },
        {
            "name": "Sercotel Playa Canteras",
            "source_url": "https://nl.lastminute.com/s/tsx?destination=TOR-2800&pageType=search&dateFrom=2026-12-05&dateTo=2026-12-12",
            "price": "€705",
            "match_status": "observed_only",
            "eligibility": "ineligible",
            "rankable": False,
            "evidence": {
                "observed": {
                    "entity": "Sercotel Playa Canteras",
                    "value": "€705",
                    "raw_evidence": "Enkel kamer | Heen- en terugvluchten vanaf Brussel | 3 kleine tassen | € 705 | pp",
                }
            },
            "page_state": {
                "observed_url": "https://nl.lastminute.com/s/tsx?destination=TOR-2800&pageType=search",
                "page_role": "list",
                "usable_for_task": True,
                "awareness": {
                    "status": "adequate",
                    "gaps": [],
                    "have": ["page_usable", "subject_identity", "primary_values", "entity_value_link"],
                },
                "structure": {
                    "member_count": 2,
                    "members": [
                        {
                            "entity": "Sercotel Playa Canteras",
                            "value": "€705",
                            "admissibility": {"role": "TARGET", "admissible": True},
                        },
                        {
                            "entity": "Apartamentos Cordial Mogán Valle",
                            "value": "€656",
                            "admissibility": {"role": "TARGET", "admissible": True},
                        },
                    ],
                    "rejected_members": [
                        {
                            "entity": "Pakket bekijken",
                            "value": "€848",
                            "reject_reason": "reject_cta",
                            "role": "ACTION",
                        }
                    ],
                    "admissibility_stats": {"accept": 2, "reject_cta": 1},
                    "member_role_stats": {"TARGET": 2, "ACTION": 1},
                },
            },
        },
        {
            "name": "sunweb_surface",
            "source_url": "https://www.sunweb.be/nl/vakantie/all-inclusive?Mealplan[0]=all-inclusive",
            "price": None,
            "match_status": "observed_only",
            "eligibility": "ineligible",
            "rankable": False,
            "evidence": {"observed": {}},
            "page_state": {
                "observed_url": "https://www.sunweb.be/nl/vakantie/all-inclusive",
                "page_role": "list",
                "usable_for_task": True,
                "awareness": {"status": "partial", "gaps": ["subject_identity", "entity_value_link"]},
                "structure": {
                    "member_count": 0,
                    "members": [],
                    "rejected_members": [],
                    "admissibility_stats": {},
                    "member_role_stats": {},
                },
            },
        },
        {
            "name": "corendon_surface",
            "source_url": "https://www.corendon.be/vakanties?adults=3&meal=all-inclusive",
            "price": None,
            "match_status": "observed_only",
            "eligibility": "ineligible",
            "rankable": False,
            "evidence": {"observed": {}},
            "page_state": {
                "observed_url": "https://www.corendon.be/vakanties",
                "page_role": "list",
                "usable_for_task": True,
                "awareness": {"status": "partial", "gaps": ["subject_identity"]},
                "structure": {
                    "member_count": 0,
                    "members": [],
                    "rejected_members": [],
                    "admissibility_stats": {},
                    "member_role_stats": {},
                },
            },
        },
    ]
    (tmp / "shortlist.json").write_text(json.dumps(shortlist, ensure_ascii=False, indent=2), encoding="utf-8")
    (tmp / "metadata.json").write_text(
        json.dumps(
            {
                "status": "RUN_FAILED_LLM+forced_report",
                "shortlist_count": 11,
                "rankable_count": 0,
                "candidate_precision": 0.0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return tmp


def main() -> int:
    ap = argparse.ArgumentParser(description="Contract Discovery v0")
    ap.add_argument("--run-dir", type=Path, default=None, help="Path to a completed run directory")
    ap.add_argument("--llm", action="store_true", help="Call Ollama to fill contract content")
    ap.add_argument("--out", type=Path, default=None, help="Write full result JSON here")
    ap.add_argument("--fixture", action="store_true", help="Force built-in fixture (ignore --run-dir)")
    args = ap.parse_args()

    chat_fn = None
    if args.llm:
        from llm import OllamaClient

        client = OllamaClient()

        def chat_fn(messages):  # type: ignore[misc]
            return client.chat(messages)

    if args.fixture or args.run_dir is None:
        fix = ROOT / "evals" / "_fixture_contract_discovery_run"
        run_dir = fixture_run_dir(fix)
        print(f"[contract_discovery] using fixture run_dir={run_dir}")
    else:
        run_dir = args.run_dir
        if not run_dir.exists():
            print(f"run-dir not found: {run_dir}", file=sys.stderr)
            return 2

    result = run_discovery_on_run_dir(
        run_dir,
        chat_fn=chat_fn,
        use_heuristic_fallback=True,
        max_surfaces=4,
    )

    # Pretty console summary
    print("=== Contract Discovery v0 ===")
    print(f"schema_version: {CONTRACT_SCHEMA_VERSION}")
    print(f"source: {result['contract'].get('_source')}")
    print(f"validation.ok: {result['validation']['ok']}")
    if result["validation"]["errors"]:
        print("validation.errors:", result["validation"]["errors"])
    if result["validation"]["warnings"]:
        print("validation.warnings:", result["validation"]["warnings"])
    print(f"success_v0 (explains 0-rankable): {result['success_v0']}")
    print("--- subject ---")
    print(json.dumps(result["contract"].get("subject"), ensure_ascii=False, indent=2))
    print("--- decisions ---")
    for d in result["contract"].get("decisions") or []:
        print(f"  {d.get('id')}: outcomes={d.get('outcomes')}")
    print("--- gap decision_status ---")
    for k, v in (result["gap_analysis"]["decision_status"] or {}).items():
        print(f"  {k}: {v}")
    print("--- why_zero_rankable (first 5) ---")
    for line in (result["gap_analysis"]["why_zero_rankable"] or [])[:5]:
        print(f"  - {line}")

    out = args.out
    if out is None:
        # Docker-created runs/ dirs are often root-owned → not writable from host user.
        candidates = [
            Path(result["run_dir"]) / "contract_discovery_v0.json",
            Path.cwd() / "contract_discovery_v0.json",
            Path("/tmp") / f"contract_discovery_v0_{Path(result['run_dir']).name}.json",
        ]
        out = None
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        last_err: Exception | None = None
        for cand in candidates:
            try:
                cand.parent.mkdir(parents=True, exist_ok=True)
                cand.write_text(payload, encoding="utf-8")
                out = cand
                break
            except OSError as e:
                last_err = e
                continue
        if out is None:
            print(f"ERROR: could not write result JSON ({last_err})", file=sys.stderr)
            print("Pass an explicit writable path: --out ./contract_discovery_v0.json", file=sys.stderr)
            return 2
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0 if result["success_v0"] and result["validation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
