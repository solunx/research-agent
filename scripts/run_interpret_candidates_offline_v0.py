#!/usr/bin/env python3
"""
Offline interpretation over Candidates (no browser, optional LLM).

Scientific isolation
--------------------
Given:
  - candidates JSON (from run_candidate_extraction_offline_v0)
  - frozen contract JSON (from contract synthesis)
Produce:
  - outcomes per decision_id
  - sufficiency gaps vs contract

Does NOT run acquisition, planner, or STOP loops.
Purpose: answer "can interpret fill the contract from top-K candidates?"

Usage
-----
python scripts/run_interpret_candidates_offline_v0.py \\
  --candidates evals/candidate_offline/.../candidates_02_monica_detail_....json \\
  --contract evals/contract_synthesis/.../contract_02_....json \\
  --llm --outdir ./evals/interpret_candidates

# Batch: directory of candidates_*.json + contract-dir resolved by label stem
python scripts/run_interpret_candidates_offline_v0.py \\
  --candidates-dir evals/candidate_offline/20260828T144644Z_candidate_offline \\
  --contract-dir evals/contract_synthesis/20260827T195209Z_synthesis \\
  --llm --outdir ./evals/interpret_candidates
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from candidates import Candidate, candidates_to_observations  # noqa: E402
from pipeline_offline import eligibility_from_outcomes, run_interpretation  # noqa: E402
from sufficiency import evaluate_sufficiency  # noqa: E402


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _make_chat_fn():
    try:
        from llm import chat as llm_chat  # type: ignore

        return llm_chat
    except Exception:
        try:
            from llm import chat_ollama as llm_chat  # type: ignore

            return llm_chat
        except Exception as e:
            raise RuntimeError("LLM requested but llm.chat unavailable") from e


def _decisions_from_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    from live_offer_state_slice import _decisions_from_frozen_contract

    return _decisions_from_frozen_contract(contract)


def _candidates_from_payload(payload: dict[str, Any]) -> list[Candidate]:
    raw = payload.get("candidates") or []
    out: list[Candidate] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        out.append(
            Candidate(
                candidate_id=str(c.get("candidate_id") or f"c{len(out)}"),
                identity_hints=list(c.get("identity_hints") or []),
                evidence=list(c.get("evidence") or []),
                primary_action=c.get("primary_action"),
                source_url=str(c.get("source_url") or payload.get("url") or ""),
                surface=str(c.get("surface") or payload.get("surface") or ""),
                density_hits=int(c.get("density_hits") or 0),
                packager_source=str(c.get("packager_source") or ""),
                block_index=c.get("block_index"),
                is_chrome=bool(c.get("is_chrome") or False),
            )
        )
    return out


def _resolve_contract(contract_dir: Path, label: str) -> Path | None:
    """Match candidates_02_monica_detail_… → contract_02_…"""
    stem = label
    # strip common prefixes
    for prefix in ("candidates_",):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
    # drop trailing timestamp if present
    parts = stem.split("_")
    # try progressive matches
    cands = list(contract_dir.glob("contract_*.json"))
    for c in cands:
        name = c.name
        if stem in name or any(
            stem.startswith(x) for x in [name.replace("contract_", "").rsplit("_20", 1)[0]]
        ):
            # prefer label key in filename
            key = stem
            for token in ("monica", "property_only", "package_concrete", "flamenco", "synthetic"):
                if token in stem.lower() and token in name.lower():
                    return c
            if key.split("_")[0] in name:
                return c
    # explicit task id patterns
    mapping = {
        "02_monica_detail": "02_web_hotel_property_only",
        "01_flamenco_price_surface": "01_web_hotel_package_concrete",
        "synthetic_multi_offer_list": None,
    }
    for k, task_id in mapping.items():
        if k in label and task_id:
            hits = list(contract_dir.glob(f"contract_{task_id}*.json"))
            if hits:
                return sorted(hits)[-1]
    return None


def run_one(
    *,
    candidates_payload: dict[str, Any],
    contract: dict[str, Any],
    chat_fn,
    label: str,
) -> dict[str, Any]:
    cands = _candidates_from_payload(candidates_payload)
    obs = candidates_to_observations(cands, max_candidates=6)
    # page title not available offline; identity is in candidates
    decisions = _decisions_from_contract(contract)
    interp = run_interpretation(
        observations=obs, decisions=decisions, chat_fn=chat_fn
    )
    outcomes = interp.get("outcomes") or {}
    elig = interp.get("eligibility") or eligibility_from_outcomes(outcomes, decisions)
    suf = evaluate_sufficiency(contract, outcomes)
    return {
        "label": label,
        "url": candidates_payload.get("url"),
        "candidate_n": len(cands),
        "obs_n": len(obs),
        "decision_ids": [d.get("id") for d in decisions],
        "outcomes": outcomes,
        "eligible": elig.get("eligible") if isinstance(elig, dict) else elig,
        "sufficiency": {
            "satisfied": suf.get("satisfied"),
            "gaps": suf.get("gaps"),
            "stop_reason": suf.get("stop_reason"),
        },
        "llm_calls": interp.get("llm_calls"),
        "provenance_blocked_n": interp.get("provenance_blocked_n"),
        "interpreted": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", default="", help="Single candidates_*.json")
    ap.add_argument("--candidates-dir", default="", help="Dir with candidates_*.json")
    ap.add_argument("--contract", default="", help="Single frozen contract JSON")
    ap.add_argument("--contract-dir", default="", help="Dir of contract_*.json")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--outdir", default="./evals/interpret_candidates")
    args = ap.parse_args()

    chat_fn = _make_chat_fn() if args.llm else None

    jobs: list[tuple[str, Path, Path]] = []
    if args.candidates:
        cp = Path(args.candidates)
        if args.contract:
            jobs.append((cp.stem, cp, Path(args.contract)))
        elif args.contract_dir:
            contr = _resolve_contract(Path(args.contract_dir), cp.stem)
            if not contr:
                print(f"No contract match for {cp.name}")
                return 2
            jobs.append((cp.stem, cp, contr))
        else:
            print("Need --contract or --contract-dir")
            return 2
    elif args.candidates_dir:
        cdir = Path(args.candidates_dir)
        for cp in sorted(cdir.glob("candidates_*.json")):
            if "synthetic" in cp.name:
                print(f"skip synthetic (no contract): {cp.name}")
                continue
            if args.contract:
                jobs.append((cp.stem, cp, Path(args.contract)))
            else:
                contr = _resolve_contract(Path(args.contract_dir), cp.stem)
                if not contr:
                    print(f"skip no contract: {cp.name}")
                    continue
                jobs.append((cp.stem, cp, contr))
    else:
        ap.print_help()
        return 2

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.outdir) / f"{ts}_interpret_candidates"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Campaign dir: {out_dir}")
    print(f"Planned jobs: {len(jobs)} (llm={bool(chat_fn)})")

    results = []
    for label, cpath, contr_path in jobs:
        payload = _load(cpath)
        contract = _load(contr_path)
        # unwrap if synthesis wrapper
        if "contract" in contract and isinstance(contract["contract"], dict):
            contract = contract["contract"]
        print(f">> {label}")
        print(f"   contract={contr_path.name}")
        try:
            r = run_one(
                candidates_payload=payload,
                contract=contract,
                chat_fn=chat_fn,
                label=label,
            )
            r["contract_path"] = str(contr_path)
            r["ok"] = True
        except Exception as e:
            r = {"label": label, "error": str(e), "ok": False}
            print(f"   ERROR {e}")
        results.append(r)
        if r.get("ok"):
            print(
                f"   outcomes={r.get('outcomes')} "
                f"satisfied={r.get('sufficiency', {}).get('satisfied')} "
                f"llm_calls={r.get('llm_calls')}"
            )
        (out_dir / f"result_{label}_{ts}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    report = {
        "schema": "interpret-candidates-offline-v0",
        "created_at": ts,
        "results": [
            {
                "label": r.get("label"),
                "ok": r.get("ok"),
                "satisfied": (r.get("sufficiency") or {}).get("satisfied"),
                "outcomes": r.get("outcomes"),
                "error": r.get("error"),
            }
            for r in results
        ],
    }
    rp = out_dir / f"campaign_report_{ts}.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {rp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
