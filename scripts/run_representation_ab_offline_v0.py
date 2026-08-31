#!/usr/bin/env python3
"""
Representation A/B offline experiment (F1 Structural Observer).

Hypothesis
----------
Candidate binding may be a *representation* problem (solve at F1 with DOM
structure) rather than a downstream *classification* problem (more heuristics
on flattened text).

Arms
----
  text     — blank-line / link clustering (current default via candidates.py)
  html     — DOM leaf structural containers (article / listitem / card-ish)
  html_b2  — mixed-signal nearest-common-ancestor (identity heading + nearby
             price-shaped text bound at the tightest shared ancestor)
  ax       — accessibility tree (optional fixture; skipped if absent)

Why html_b2 exists
------------------
First A/B (leaf html) improved name+board co-location but not name+price.
Possible confound: we grouped on leaf tags, not the card container that holds
both signals. html_b2 isolates that confound without new fixtures.

No browser required when fixtures include page.html.
No LLM. No domain offer enums in the HTML arms.

Success criteria (scientific)
-----------------------------
On synthetic_multi_offer_list:
  - html / html_b2 recover ~3 distinct offer cards with primary_action each
  - parent-duplicate (list wrapper + children) suppressed
  - identity + price co-located when structure is present

On real-ish fixtures (monica / flamenco HTML sketches):
  - report metrics side-by-side; do NOT claim generic victory from n=3 alone
  - language: "directional signal (n=X)" unless held-out grows
  - if html_b2 still does not co-locate sibling identity/price cards, that is
    evidence that binding is NOT solved by tighter container selection → next
    hypothesis is interpret neighbor-window, not more DOM heuristics

Usage
-----
python scripts/run_representation_ab_offline_v0.py \\
  --manifest evals/candidate_offline/fixtures_from_traces/manifest.json \\
  --arms text,html,html_b2 \\
  --outdir ./evals/representation_ab

# Single fixture
python scripts/run_representation_ab_offline_v0.py \\
  --page-text path/to/page_text.txt \\
  --html path/to/page.html \\
  --label synthetic \\
  --arms text,html,html_b2
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from candidates import candidates_preview, candidates_to_jsonable  # noqa: E402
from structural_observer import (  # noqa: E402
    candidate_metrics,
    extract_for_arm,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _resolve(path_str: str, base: Path) -> Path:
    p = Path(path_str)
    if p.is_file():
        return p
    cand = base / path_str
    if cand.is_file():
        return cand
    cand2 = _ROOT / path_str
    if cand2.is_file():
        return cand2
    raise FileNotFoundError(path_str)


def _run_job(
    *,
    label: str,
    page_text: str,
    html: str,
    ax_tree: Any,
    affordances: list[dict],
    url: str,
    surface: str,
    arms: list[str],
    max_candidates: int,
) -> dict[str, Any]:
    arm_results: dict[str, Any] = {}
    for arm in arms:
        try:
            cands = extract_for_arm(
                arm,
                page_text=page_text,
                html=html,
                ax_tree=ax_tree,
                affordances=affordances,
                page_url=url,
                surface=surface,
                max_candidates=max_candidates,
            )
            metrics = candidate_metrics(cands)
            arm_results[arm] = {
                "ok": True,
                "metrics": metrics,
                "preview": candidates_preview(cands),
                "candidates": candidates_to_jsonable(cands),
            }
        except Exception as e:
            arm_results[arm] = {
                "ok": False,
                "error": str(e),
                "metrics": {},
                "preview": [],
                "candidates": [],
            }
    return {
        "label": label,
        "url": url,
        "surface": surface,
        "arms": arm_results,
        "has_html": bool(html and html.strip()),
        "has_ax": ax_tree is not None,
        "page_text_chars": len(page_text or ""),
        "html_chars": len(html or ""),
    }


def _print_job(job: dict[str, Any]) -> None:
    print(f">> {job['label']}  html={job['has_html']} ax={job['has_ax']}")
    for arm, res in (job.get("arms") or {}).items():
        if not res.get("ok"):
            print(f"   [{arm}] ERROR {res.get('error')}")
            continue
        m = res.get("metrics") or {}
        print(
            f"   [{arm}] n={m.get('candidate_n')} "
            f"action={m.get('with_primary_action')} "
            f"id={m.get('with_identity')} "
            f"coloc={m.get('identity_price_colocated')} "
            f"dens={m.get('with_density')}"
        )
        for line in (res.get("preview") or [])[:4]:
            print(f"      {line}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--manifest", default="", help="JSON list of fixture jobs")
    ap.add_argument("--page-text", default="")
    ap.add_argument("--html", default="")
    ap.add_argument("--ax", default="", help="Optional accessibility snapshot JSON")
    ap.add_argument("--affordances", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--surface", default="")
    ap.add_argument("--label", default="single")
    ap.add_argument(
        "--arms",
        default="text,html,html_b2",
        help="Comma list: text,html,html_b2,ax",
    )
    ap.add_argument("--max-candidates", type=int, default=8)
    ap.add_argument("--outdir", default="./evals/representation_ab")
    args = ap.parse_args()

    arms = [a.strip().lower() for a in args.arms.split(",") if a.strip()]
    jobs_spec: list[dict[str, Any]] = []
    base = Path.cwd()

    if args.manifest:
        manifest_path = _resolve(args.manifest, base)
        raw = _load_json(manifest_path)
        if not isinstance(raw, list):
            print("manifest must be a JSON list")
            return 2
        jobs_spec = raw
        base = manifest_path.parent
    elif args.page_text or args.html:
        jobs_spec = [
            {
                "label": args.label,
                "page_text": args.page_text,
                "html": args.html,
                "ax": args.ax,
                "affordances": args.affordances,
                "url": args.url,
                "surface": args.surface or "unknown",
            }
        ]
    else:
        ap.print_help()
        return 2

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.outdir) / f"{ts}_representation_ab"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Campaign dir: {out_dir}")
    print(f"Arms: {arms}")
    print(f"Planned jobs: {len(jobs_spec)}")

    all_results: list[dict[str, Any]] = []
    for spec in jobs_spec:
        label = str(spec.get("label") or "job")
        page_text = ""
        html = ""
        ax_tree = None
        affordances: list[dict] = []

        if spec.get("page_text"):
            page_text = _load_text(_resolve(str(spec["page_text"]), base))
        if spec.get("html"):
            try:
                html = _load_text(_resolve(str(spec["html"]), base))
            except FileNotFoundError:
                html = ""
        # auto-discover page.html next to page_text
        if not html and spec.get("page_text"):
            pt = Path(str(spec["page_text"]))
            for guess in (
                pt.with_name("page.html"),
                pt.parent / "page.html",
            ):
                for root in (base, _ROOT, Path.cwd()):
                    g = guess if guess.is_absolute() else root / guess
                    if g.is_file():
                        html = _load_text(g)
                        break
                if html:
                    break

        if spec.get("ax"):
            try:
                ax_tree = _load_json(_resolve(str(spec["ax"]), base))
            except FileNotFoundError:
                ax_tree = None
        if spec.get("affordances"):
            try:
                affordances = _load_json(_resolve(str(spec["affordances"]), base))
            except FileNotFoundError:
                affordances = []

        job = _run_job(
            label=label,
            page_text=page_text,
            html=html,
            ax_tree=ax_tree,
            affordances=affordances if isinstance(affordances, list) else [],
            url=str(spec.get("url") or ""),
            surface=str(spec.get("surface") or ""),
            arms=arms,
            max_candidates=args.max_candidates,
        )
        _print_job(job)
        all_results.append(job)
        (out_dir / f"result_{label}_{ts}.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # comparison table
    comparison = []
    for job in all_results:
        row: dict[str, Any] = {"label": job["label"], "has_html": job["has_html"]}
        for arm, res in (job.get("arms") or {}).items():
            m = res.get("metrics") or {}
            row[f"{arm}_n"] = m.get("candidate_n")
            row[f"{arm}_action"] = m.get("with_primary_action")
            row[f"{arm}_id"] = m.get("with_identity")
            row[f"{arm}_coloc"] = m.get("identity_price_colocated")
            row[f"{arm}_ok"] = res.get("ok")
        comparison.append(row)

    report = {
        "schema": "representation-ab-offline-v0",
        "created_at": ts,
        "arms": arms,
        "hypothesis": (
            "DOM structural grouping yields cleaner candidate boundaries than "
            "blank-line text clustering. html_b2 (mixed-signal NCA) tests whether "
            "leaf-level grouping was the confound for missing name+price "
            "co-location; parent-duplicate filter is generic nesting cleanup."
        ),
        "n_jobs": len(all_results),
        "comparison": comparison,
        "note": (
            "n is small (fixture set). Treat as directional signal, not validation. "
            "Synthetic list is the controlled primary test; HTML for real pages is "
            "structural sketch unless replaced with live-captured HTML. "
            "Chrome presence is out of scope for pure extraction (filter is in "
            "select_top_candidates). identity_price_colocated is a coarse proxy."
        ),
        "results": [
            {
                "label": j["label"],
                "has_html": j["has_html"],
                "arms": {
                    a: {
                        "ok": r.get("ok"),
                        "metrics": r.get("metrics"),
                        "preview": r.get("preview"),
                        "error": r.get("error"),
                    }
                    for a, r in (j.get("arms") or {}).items()
                },
            }
            for j in all_results
        ],
    }
    rp = out_dir / f"campaign_report_{ts}.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {rp}")
    print("--- comparison ---")
    for row in comparison:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
