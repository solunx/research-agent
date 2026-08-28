#!/usr/bin/env python3
"""
End-to-end: task.md → frozen contract → acquisition loop → sufficiency STOP.

Closes the wiring gap (no domain hardcoding):

  task.md
    → load or synthesize frozen contract
    → run_acquisition_loop(frozen_contract=...)
    → evidence → interpret → outcomes
    → sufficiency_stop (CODE)
    → STOP / CONTINUE

Usage
-----
# Single task with pre-synthesized contract
python scripts/run_contract_driven_task_v0.py \\
  --task tasks/batch_v0/02_web_hotel_property_only.md \\
  --contract evals/contract_synthesis/.../contract_02_....json \\
  --llm --outdir ./evals/contract_driven

# Resolve contract by task stem from a synthesis campaign dir
python scripts/run_contract_driven_task_v0.py \\
  --task tasks/batch_v0/01_web_hotel_package_concrete.md \\
  --contract-dir evals/contract_synthesis/20260827T140732Z_synthesis \\
  --llm --outdir ./evals/contract_driven

# Mini batch 01+02 only
python scripts/run_contract_driven_task_v0.py \\
  --tasks 01_web_hotel_package_concrete,02_web_hotel_property_only \\
  --tasks-dir tasks/batch_v0 \\
  --contract-dir evals/contract_synthesis/20260827T140732Z_synthesis \\
  --llm --outdir ./evals/contract_driven
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live_offer_state_slice import run_acquisition_loop  # noqa: E402
from run_ledger import RunLedger  # noqa: E402
from trace_session import TraceSession  # noqa: E402


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_task_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_start_url(task_text: str) -> str | None:
    """First http(s) URL in task (Suggested start / body)."""
    m = re.search(r"https?://[^\s\)\]\>\"']+", task_text)
    return m.group(0).rstrip(".,;") if m else None


def extract_entity_hint(task_text: str, task_id: str) -> str:
    # Prefer quoted/bold names; fallback to task_id
    m = re.search(r"\*\*([^*]{3,60})\*\*", task_text)
    if m:
        return m.group(1).strip()
    return task_id


def load_frozen_contract(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw.get("contract"), dict):
        c = dict(raw["contract"])
        # Ensure frozen flag propagates from wrapper
        if raw.get("frozen") is True:
            c["frozen"] = True
        return c
    return raw


def find_contract_for_task(contract_dir: Path, task_id: str) -> Path | None:
    """Match contract_*{task_id}*.json (prefer newest by name)."""
    if not contract_dir.is_dir():
        return None
    hits = sorted(contract_dir.glob(f"contract_*{task_id}*.json"))
    if not hits:
        hits = sorted(contract_dir.glob(f"*{task_id}*.json"))
    return hits[-1] if hits else None


def make_chat_fn():
    from llm import OllamaClient

    client = OllamaClient()

    def chat_fn(messages: list[dict[str, str]]) -> str:
        import requests

        payload = {
            "model": client.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": client.temperature},
        }
        resp = requests.post(
            f"{client.base_url}/api/chat",
            json=payload,
            timeout=getattr(client, "timeout", 480),
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", data)
        if isinstance(msg, dict):
            return str(msg.get("content") or "")
        return str(msg)

    return chat_fn


def run_one(
    *,
    task_path: Path,
    contract_path: Path,
    outdir: Path,
    use_llm: bool,
    start_url_override: str | None,
    max_steps: int,
) -> dict[str, Any]:
    task_id = task_path.stem
    task_text = load_task_text(task_path)
    contract = load_frozen_contract(contract_path)
    start_url = start_url_override or extract_start_url(task_text)
    entity = extract_entity_hint(task_text, task_id)

    stamp = utc_stamp()
    job_dir = outdir / f"{stamp}_{task_id}"
    job_dir.mkdir(parents=True, exist_ok=True)

    # --- logging: which contract ---
    contract_meta = {
        "task_id": task_id,
        "task_path": str(task_path),
        "contract_path": str(contract_path),
        "contract_frozen": bool(contract.get("frozen")),
        "contract_source": contract.get("_source"),
        "decision_ids": [
            d.get("id") for d in (contract.get("decisions") or []) if isinstance(d, dict)
        ],
        "sufficiency_required": (contract.get("sufficiency") or {}).get("required"),
        "start_url": start_url,
        "entity": entity,
    }
    (job_dir / f"contract_meta_{task_id}_{stamp}.json").write_text(
        json.dumps(contract_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[contract_driven] task={task_id}\n"
        f"  contract={contract_path.name}\n"
        f"  frozen={contract_meta['contract_frozen']}\n"
        f"  decisions={contract_meta['decision_ids']}\n"
        f"  required={contract_meta['sufficiency_required']}\n"
        f"  start_url={start_url}",
        flush=True,
    )

    if not start_url:
        result = {
            "ok": False,
            "task_id": task_id,
            "error": "no_start_url_in_task_or_args",
            "contract_meta": contract_meta,
            "stop_reason": "NO_START_URL",
        }
        (job_dir / f"result_{task_id}_{stamp}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    if not contract.get("frozen"):
        print(
            "[contract_driven] WARNING: contract.frozen is not true — "
            "sufficiency gate will refuse STOP",
            file=sys.stderr,
        )

    chat_fn = make_chat_fn() if use_llm else None
    ledger = RunLedger(
        task_text=task_text,
        run_kind="contract_driven_task",
        meta=contract_meta,
    )
    trace = TraceSession(
        job_dir / "trace",
        task_text=task_text,
        run_kind="contract_driven_task",
        meta=contract_meta,
    )

    t0 = time.monotonic()
    loop_result = run_acquisition_loop(
        entity=entity,
        start_url=start_url,
        chat_fn=chat_fn,
        max_acquisition_steps=max_steps,
        task_text=task_text,
        frozen_contract=contract,
        expected_eligible=True,
        force_click_texts=None,
        ledger=ledger,
        trace=trace,
    )
    duration = round(time.monotonic() - t0, 2)

    stop_reason = loop_result.get("stop_reason")
    contract_satisfied = loop_result.get("contract_satisfied")
    sufficiency = loop_result.get("sufficiency")

    summary = {
        "schema": "contract-driven-task-v0",
        "task_id": task_id,
        "ok": bool(loop_result.get("ok")),
        "duration_s": duration,
        "contract_path": str(contract_path),
        "contract_frozen": bool(contract.get("frozen")),
        "has_frozen_contract": True,
        "stop_reason": stop_reason,
        "contract_satisfied": contract_satisfied,
        "sufficiency": sufficiency,
        "outcomes": loop_result.get("outcomes"),
        "acquisition_steps": loop_result.get("acquisition_steps"),
        "final_url": loop_result.get("final_url"),
        "fault_localization": loop_result.get("fault_localization"),
        "steps_contract_flags": [
            {
                "step": s.get("step"),
                "contract_satisfied": s.get("contract_satisfied"),
                "gaps_n": len(s.get("gaps") or []),
                "outcomes": s.get("outcomes"),
            }
            for s in (loop_result.get("steps") or [])
        ],
        "trace_dir": loop_result.get("trace_dir"),
        "contract_meta": contract_meta,
    }

    out_name = f"result_{task_id}_{stamp}.json"
    (job_dir / out_name).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Full loop payload (larger)
    (job_dir / f"loop_{task_id}_{stamp}.json").write_text(
        json.dumps(loop_result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(
        f"[contract_driven] DONE {task_id}\n"
        f"  stop_reason={stop_reason}\n"
        f"  contract_satisfied={contract_satisfied}\n"
        f"  steps={loop_result.get('acquisition_steps')}\n"
        f"  outcomes={loop_result.get('outcomes')}\n"
        f"  duration_s={duration}\n"
        f"  wrote {job_dir / out_name}",
        flush=True,
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(
        description="task.md + frozen contract → acquisition → sufficiency STOP"
    )
    ap.add_argument("--task", type=str, default="", help="Single task.md path")
    ap.add_argument(
        "--tasks",
        type=str,
        default="",
        help="Comma list of task stems (with --tasks-dir)",
    )
    ap.add_argument("--tasks-dir", type=Path, default=ROOT / "tasks" / "batch_v0")
    ap.add_argument("--contract", type=str, default="", help="Path to one contract JSON")
    ap.add_argument(
        "--contract-dir",
        type=Path,
        default=None,
        help="Dir of contract_*.json from synthesis campaign",
    )
    ap.add_argument("--start-url", type=str, default="", help="Override start URL")
    ap.add_argument("--outdir", type=Path, default=ROOT / "evals" / "contract_driven")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--max-steps", type=int, default=3)
    args = ap.parse_args()

    outdir = args.outdir
    if not outdir.is_absolute():
        outdir = ROOT / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[Path, Path]] = []

    if args.task:
        task_path = Path(args.task)
        if not task_path.is_absolute():
            task_path = ROOT / task_path
        if args.contract:
            cpath = Path(args.contract)
            if not cpath.is_absolute():
                cpath = ROOT / cpath
        elif args.contract_dir:
            cdir = args.contract_dir if args.contract_dir.is_absolute() else ROOT / args.contract_dir
            cpath = find_contract_for_task(cdir, task_path.stem)
            if cpath is None:
                print(f"No contract for {task_path.stem} in {cdir}", file=sys.stderr)
                return 2
        else:
            print("Need --contract or --contract-dir", file=sys.stderr)
            return 2
        jobs.append((task_path, cpath))
    elif args.tasks:
        tasks_dir = args.tasks_dir if args.tasks_dir.is_absolute() else ROOT / args.tasks_dir
        cdir = args.contract_dir
        if cdir is None:
            print("--tasks requires --contract-dir", file=sys.stderr)
            return 2
        if not cdir.is_absolute():
            cdir = ROOT / cdir
        for stem in [s.strip() for s in args.tasks.split(",") if s.strip()]:
            task_path = tasks_dir / f"{stem}.md"
            if not task_path.is_file():
                # allow stem without numeric prefix match
                matches = list(tasks_dir.glob(f"*{stem}*.md"))
                if not matches:
                    print(f"Missing task {task_path}", file=sys.stderr)
                    return 2
                task_path = matches[0]
            cpath = find_contract_for_task(cdir, task_path.stem)
            if cpath is None:
                print(f"No contract for {task_path.stem} in {cdir}", file=sys.stderr)
                return 2
            jobs.append((task_path, cpath))
    else:
        print("Provide --task or --tasks", file=sys.stderr)
        return 2

    campaign = {
        "schema": "contract-driven-campaign-v0",
        "created_at": utc_stamp(),
        "llm": bool(args.llm),
        "results": [],
    }
    rc = 0
    for task_path, cpath in jobs:
        try:
            summary = run_one(
                task_path=task_path,
                contract_path=cpath,
                outdir=outdir,
                use_llm=bool(args.llm),
                start_url_override=args.start_url or None,
                max_steps=args.max_steps,
            )
            campaign["results"].append(
                {
                    "task_id": summary.get("task_id"),
                    "stop_reason": summary.get("stop_reason"),
                    "contract_satisfied": summary.get("contract_satisfied"),
                    "ok": summary.get("ok"),
                    "duration_s": summary.get("duration_s"),
                    "contract_path": summary.get("contract_path"),
                }
            )
            if not summary.get("ok"):
                rc = 1
            # For end-to-end test we care about contract path being used;
            # exit 0 if wiring ok even when contract not yet satisfied
        except Exception as e:
            print(f"[contract_driven] ERROR {task_path}: {e}", file=sys.stderr)
            campaign["results"].append(
                {"task_id": task_path.stem, "error": str(e), "ok": False}
            )
            rc = 1

    stamp = campaign["created_at"]
    report_path = outdir / f"campaign_report_{stamp}.json"
    report_path.write_text(json.dumps(campaign, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {report_path}")
    print("=== CONTRACT-DRIVEN ===")
    for r in campaign["results"]:
        print(
            f"  {r.get('task_id')}: satisfied={r.get('contract_satisfied')} "
            f"stop={r.get('stop_reason')} ok={r.get('ok')}"
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
