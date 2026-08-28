"""
Live detail slice v0 — real B/C (open URL → observations) → frozen D–F pipeline.

Controlled test (not free agent browse):
  OPEN detail_url
    → literal line observations (no semantic outcomes)
    → CANDIDATE_UNIT → INTERPRETATION → CODE eligibility
    → A–F stages with B/C = LIVE (not SIMULATED)

Stop before book. No domain board heuristics in extractors.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from pipeline_offline import (
    PACKAGES_DECISIONS,
    PACKAGES_TASK_TEXT,
    eligibility_from_outcomes,
    run_candidate_unit,
    run_interpretation,
)
from run_ledger import RunLedger

ChatFnStr = Callable[[list[dict[str, str]]], str]

# Structural line filters only (length / noise shape — not hotel/board meaning)
_CHROME_LINE = re.compile(
    r"^(cookie|privacy|login|registreer|newsletter|instagram|facebook|twitter|"
    r"copyright|©|\d{1,2}:\d{2}|menu|zoeken|search)$",
    re.I,
)
_BOARDISH = re.compile(
    r"(all[-\s]?inclusive|volpension|ultra\s+all|half.?pension|full\s+board|"
    r"enkel\s+kamer|room\s+only|ontbijt|breakfast)",
    re.I,
)
_FLIGHTISH = re.compile(
    r"(vlucht|flight|heen-?\s*en\s*terug|retour|vanaf\s+brussel|bru\b)",
    re.I,
)


def load_oracle(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def oracle_by_entity(oracle_path: Path) -> dict[str, dict[str, Any]]:
    return {str(r.get("entity") or "").strip(): r for r in load_oracle(oracle_path) if r.get("entity")}


def fetch_page(url: str, *, backend: str = "playwright", wait_seconds: float = 3.0) -> dict[str, Any]:
    """
    backend: playwright | fetch
    Returns {url, title, text, error, backend, ...}
    """
    backend = (backend or "playwright").lower().strip()
    if backend == "fetch":
        try:
            from web import web_fetch

            r = web_fetch(url, max_chars=20000, timeout=25)
            text = str(r.get("text") or r.get("content") or "")
            return {
                "url": r.get("url") or url,
                "title": r.get("title") or "",
                "text": text,
                "error": r.get("error"),
                "backend": "fetch",
                "status_code": r.get("status_code"),
                "prefer_browser": r.get("prefer_browser"),
            }
        except Exception as e:
            return {"url": url, "title": "", "text": "", "error": str(e), "backend": "fetch"}

    # default playwright
    try:
        from browser import browser_open

        snap = browser_open(url, wait_seconds=wait_seconds, headless=True, max_chars=20000)
        snap["backend"] = "playwright"
        return snap
    except Exception as e:
        return {"url": url, "title": "", "text": "", "error": str(e), "backend": "playwright"}


def _meal_params(url: str) -> list[str]:
    out = []
    try:
        q = parse_qs(urlparse(url).query)
        for k, vals in q.items():
            if k.lower() in ("meal", "mealplan", "board", "catering"):
                for v in vals:
                    out.append(f"{k}={v}")
    except Exception:
        pass
    return out


_PRICEISH = re.compile(
    r"(€|eur|p\.?\s*p\.?|per\s+persoon|va\s+\d|vanaf\s+\d|\d[\d.\s]{2,}\s*€)",
    re.I,
)


def page_text_to_observations(
    *,
    candidate_id: str,
    url: str,
    title: str,
    text: str,
    max_claim_lines: int = 24,
) -> list[dict[str, Any]]:
    """
    Literal observations only. Lines → candidate_claim; URL meal params → search_context.
    No outcome fields.

    Prioritizes board/flight/price-shaped lines so live pages do not explode into
    hundreds of LLM interpretation calls. Cap is hard (default 24).
    """
    obs: list[dict[str, Any]] = []
    oid = 0

    def add(channel: str, t: str, scope: str, origin: str) -> None:
        nonlocal oid
        t = (t or "").strip()
        if not t:
            return
        obs.append(
            {
                "observation_id": f"live-{oid}",
                "candidate_id": candidate_id,
                "text": t[:500],
                "channel": channel,
                "scope": scope,
                "provenance": {
                    "origin": origin,
                    "source_url": url,
                    "surface": "live_detail",
                },
            }
        )
        oid += 1

    add("candidate_claim", candidate_id, "identity", "entity")
    if title:
        add("candidate_claim", title, "page_title", "browser_title")

    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    candidates: list[str] = []
    seen: set[str] = set()
    for ln in lines:
        if len(ln) < 3 or len(ln) > 240:
            continue
        if _CHROME_LINE.match(ln):
            continue
        if ln.lower() in ("home", "back", "sluiten", "close", "meer info"):
            continue
        key = ln.lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(ln)

    def rank(ln: str) -> tuple[int, int]:
        if _BOARDISH.search(ln):
            return (0, -len(ln))
        if _FLIGHTISH.search(ln):
            return (1, -len(ln))
        if _PRICEISH.search(ln):
            return (2, -len(ln))
        return (3, -min(len(ln), 80))

    candidates.sort(key=rank)
    for ln in candidates[: max(0, int(max_claim_lines))]:
        add("candidate_claim", ln, "page_body", "browser_inner_text")

    for m in _meal_params(url):
        add("search_context", m, "url_query", "url_query")
    if url:
        add("navigation", url[:300], "url", "browser_url")

    return obs


def observations_to_pipeline_row(
    candidate_id: str,
    obs: list[dict[str, Any]],
    *,
    source_url: str,
    expected_eligible: bool | None = None,
    expected_role: str | None = None,
) -> dict[str, Any]:
    claims = [o["text"] for o in obs if o.get("channel") == "candidate_claim"]
    # Dedup consecutive duplicates
    deduped: list[str] = []
    for c in claims:
        if not deduped or deduped[-1] != c:
            deduped.append(c)
    raw = " | ".join(deduped[:40])
    row: dict[str, Any] = {
        "entity": candidate_id,
        "source_url": source_url,
        "raw_evidence": raw,
        "value": next((c for c in deduped if "€" in c or "va " in c.lower() or "p.p" in c.lower()), ""),
        "evidence_kind": "live_detail",
    }
    if expected_eligible is not None:
        row["expected_eligible"] = expected_eligible
    if expected_role:
        row["expected_role"] = expected_role
    return row


def stage_d_from_obs(obs: list[dict[str, Any]]) -> dict[str, Any]:
    claims = [str(o.get("text") or "") for o in obs if o.get("channel") == "candidate_claim"]
    boardish = [c for c in claims if _BOARDISH.search(c)]
    flightish = [c for c in claims if _FLIGHTISH.search(c)]
    return {
        "status": "PRESENT" if claims else "ABSENT",
        "candidate_claim_n": len(claims),
        "boardish_literal_present": bool(boardish),
        "boardish_samples": boardish[:8],
        "flightish_literal_present": bool(flightish),
        "flightish_samples": flightish[:8],
        "claim_preview": claims[:15],
    }


def run_live_detail_one(
    *,
    entity: str,
    detail_url: str,
    chat_fn: ChatFnStr | None,
    backend: str = "playwright",
    wait_seconds: float = 3.5,
    expected_eligible: bool | None = True,
    expected_role: str | None = "live_detail_ai",
    task_text: str = PACKAGES_TASK_TEXT,
    ledger: RunLedger | None = None,
    max_claim_lines: int = 24,
) -> dict[str, Any]:
    ledger = ledger or RunLedger(task_text=task_text, run_kind="live_detail_slice", meta={"entity": entity})

    print(f"[live_detail] OPEN {entity} via {backend}: {detail_url[:100]}...", flush=True)
    ledger.log_action("OPEN_URL", payload={"url": detail_url, "backend": backend})
    page = fetch_page(detail_url, backend=backend, wait_seconds=wait_seconds)
    err = page.get("error")
    text = str(page.get("text") or "")
    final_url = str(page.get("url") or detail_url)
    title = str(page.get("title") or "")

    ledger.log_action(
        "OBSERVE_PAGE",
        payload={"url": final_url},
        result_summary={
            "title": title[:120],
            "text_chars": len(text),
            "error": err,
            "backend": page.get("backend"),
            "policy_stop": page.get("policy_stop"),
            "blocked": page.get("blocked"),
        },
        ok=not bool(err) and len(text) > 50,
        error=str(err) if err else None,
    )

    if page.get("policy_stop") or page.get("blocked"):
        ledger.set_stop("BOT_WALL_OR_POLICY")
        return {
            "entity": entity,
            "ok": False,
            "stop_reason": "BOT_WALL_OR_POLICY",
            "page": {k: page.get(k) for k in ("url", "title", "error", "backend", "policy_stop")},
            "ledger": ledger.to_dict(),
        }

    if err or len(text) < 40:
        ledger.set_stop("FETCH_FAILED_OR_EMPTY")
        return {
            "entity": entity,
            "ok": False,
            "stop_reason": "FETCH_FAILED_OR_EMPTY",
            "page": {k: page.get(k) for k in ("url", "title", "error", "backend", "text")},
            "text_preview": text[:500],
            "ledger": ledger.to_dict(),
        }

    obs = page_text_to_observations(
        candidate_id=entity,
        url=final_url,
        title=title,
        text=text,
        max_claim_lines=max_claim_lines,
    )
    ledger.log_observations(obs)
    stage_d = stage_d_from_obs(obs)
    print(
        f"[live_detail] {entity}: text_chars={len(text)} claims={stage_d.get('candidate_claim_n')} "
        f"boardish={stage_d.get('boardish_literal_present')} flightish={stage_d.get('flightish_literal_present')}",
        flush=True,
    )

    row = observations_to_pipeline_row(
        entity,
        obs,
        source_url=final_url,
        expected_eligible=expected_eligible,
        expected_role=expected_role,
    )

    # Prefer running CU/interp on rich observations via pipeline helpers
    cu = run_candidate_unit(
        candidate_id=entity, observations=obs, task_text=task_text, chat_fn=chat_fn
    )
    ledger.log_decision(
        "candidate_unit",
        outcome=str(cu.get("decision")),
        raw=cu,
    )

    interp = None
    eligible = False
    outcomes: dict[str, str] = {}
    if cu.get("admitted"):
        interp = run_interpretation(
            observations=obs, decisions=PACKAGES_DECISIONS, chat_fn=chat_fn
        )
        outcomes = interp.get("outcomes") or {}
        elig = interp.get("eligibility") or eligibility_from_outcomes(outcomes, PACKAGES_DECISIONS)
        eligible = bool(elig.get("eligible"))
        for did, outc in outcomes.items():
            ledger.log_decision(
                "interpretation",
                decision_id=did,
                outcome=str(outc),
                evidence_refs=[
                    o.get("observation_id", "")
                    for o in obs
                    if o.get("channel") == "candidate_claim"
                ][:12],
                raw={"aggregated": outc},
            )
        ledger.log_decision(
            "eligibility",
            outcome="ELIGIBLE" if eligible else "NOT_ELIGIBLE",
            raw=elig if isinstance(elig, dict) else {"eligible": eligible},
        )
    else:
        ledger.log_decision(
            "eligibility",
            outcome="NOT_ELIGIBLE",
            raw={"reason": "candidate_not_admitted", "cu": cu.get("decision")},
        )

    # Safety: board must not come only from search_context
    search_leak = False
    if interp:
        board_trace = (interp.get("decision_traces") or {}).get("board_type") or {}
        per = board_trace.get("per_text") or []
        active = [
            t
            for t in per
            if not t.get("skipped") and t.get("outcome") not in (None, "UNKNOWN")
        ]
        if active and all(t.get("channel") == "search_context" for t in active):
            search_leak = True

    if search_leak:
        stop = "SEARCH_CONTEXT_BOARD_LEAK"
    elif expected_eligible is True and eligible:
        stop = "ALL_REQUIRED_OUTCOMES_PROVEN"
    elif expected_eligible is True and not eligible:
        if not stage_d.get("boardish_literal_present"):
            stop = "EVIDENCE_UNAVAILABLE_BOARD"
        elif outcomes.get("board_type") == "UNKNOWN":
            stop = "BOARD_UNKNOWN_AFTER_INTERP"
        else:
            stop = "NOT_ELIGIBLE_AFTER_INTERP"
    else:
        stop = "COMPLETED"

    ledger.set_stop(stop)

    stages = {
        "A_site": {
            "status": "PRESENT",
            "detail_url": detail_url,
            "note": "oracle or caller-provided URL",
        },
        "B_retrieval": {
            "status": "LIVE_OPENED" if not err else "FAILED",
            "requested_url": detail_url,
            "final_url": final_url,
            "backend": page.get("backend"),
        },
        "C_page_or_state": {
            "status": "LIVE_FETCHED" if len(text) > 40 else "EMPTY",
            "title": title[:160],
            "text_chars": len(text),
        },
        "D_observation": stage_d,
        "E_candidate_interpretation": {
            "candidate_unit": cu.get("decision"),
            "admitted": cu.get("admitted"),
            "outcomes": outcomes,
        },
        "F_eligibility": {
            "eligible": eligible,
            "expected_eligible": expected_eligible,
            "match": (
                None
                if expected_eligible is None
                else bool(eligible) == bool(expected_eligible)
            ),
        },
    }

    # Fault localization (same spirit as positive_evidence_trace)
    fault = "none"
    if expected_eligible is True:
        if stages["B_retrieval"]["status"] != "LIVE_OPENED":
            fault = "B_retrieval"
        elif stages["C_page_or_state"]["status"] != "LIVE_FETCHED":
            fault = "C_page_empty"
        elif not stage_d.get("boardish_literal_present"):
            fault = "D_missing_board_literal"
        elif not cu.get("admitted"):
            fault = f"E_candidate_{cu.get('decision')}"
        elif outcomes.get("board_type") not in ("ALL_INCLUSIVE",):
            fault = f"E_board_{outcomes.get('board_type', 'MISSING')}"
        elif outcomes.get("package_includes_flight") not in ("FLIGHT_INCLUDED",):
            fault = f"E_flight_{outcomes.get('package_includes_flight', 'MISSING')}"
        elif not eligible:
            fault = "F_eligibility_false"
        elif search_leak:
            fault = "F_search_context_leak"

    ledger.trace_stages = stages
    ledger.pipeline_summary = {
        "entity": entity,
        "eligible": eligible,
        "outcomes": outcomes,
        "candidate_unit": cu.get("decision"),
        "fault_localization": fault,
        "stop_reason": stop,
        "search_context_board_leak": search_leak,
    }
    ledger.metrics = {
        "text_chars": len(text),
        "observation_n": len(obs),
        "claim_n": stage_d.get("candidate_claim_n"),
        "boardish": stage_d.get("boardish_literal_present"),
        "flightish": stage_d.get("flightish_literal_present"),
        "eligible": eligible,
        "fault": fault,
        "llm_enabled": chat_fn is not None,
    }

    return {
        "entity": entity,
        "ok": True,
        "stop_reason": stop,
        "fault_localization": fault,
        "stages": stages,
        "eligible": eligible,
        "expected_eligible": expected_eligible,
        "match": stages["F_eligibility"]["match"],
        "outcomes": outcomes,
        "candidate_unit": cu,
        "interpretation": interp,
        "observation_n": len(obs),
        "page": {
            "url": final_url,
            "title": title,
            "text_chars": len(text),
            "backend": page.get("backend"),
            "cookies_dismissed": page.get("cookies_dismissed"),
        },
        "text_preview": text[:800],
        "pipeline_row": row,
        "ledger": ledger.to_dict(),
    }


def run_live_detail_batch(
    targets: list[dict[str, Any]],
    *,
    chat_fn: ChatFnStr | None,
    backend: str = "playwright",
    wait_seconds: float = 3.5,
    task_text: str = PACKAGES_TASK_TEXT,
    max_claim_lines: int = 24,
) -> dict[str, Any]:
    """
    targets: [{entity, detail_url, expected_eligible?, expected_role?}, ...]
    Each target gets its own ledger (isolation).
    """
    results = []
    for t in targets:
        entity = str(t.get("entity") or "unknown")
        url = str(t.get("detail_url") or t.get("url") or "")
        ledger = RunLedger(
            task_text=task_text,
            run_kind="live_detail_slice",
            meta={"entity": entity, "backend": backend},
        )
        r = run_live_detail_one(
            entity=entity,
            detail_url=url,
            chat_fn=chat_fn,
            backend=backend,
            wait_seconds=wait_seconds,
            expected_eligible=t.get("expected_eligible", True),
            expected_role=t.get("expected_role") or "live_detail_ai",
            task_text=task_text,
            ledger=ledger,
            max_claim_lines=max_claim_lines,
        )
        results.append(r)
        print(
            f"[live_detail] done {entity}: ok={r.get('ok')} eligible={r.get('eligible')} "
            f"fault={r.get('fault_localization')} stop={r.get('stop_reason')}",
            flush=True,
        )

    n = len(results)
    with_exp = [r for r in results if r.get("expected_eligible") is not None and r.get("ok")]
    matches = sum(1 for r in with_exp if r.get("match") is True)
    pos = [r for r in with_exp if r.get("expected_eligible") is True]
    pos_ok = sum(1 for r in pos if r.get("eligible"))
    faults: dict[str, int] = {}
    for r in results:
        f = str(r.get("fault_localization") or "n/a")
        faults[f] = faults.get(f, 0) + 1

    go = True
    reasons = []
    if chat_fn is None:
        reasons.append("no LLM — structural live fetch only")
        go = all(r.get("ok") and r.get("stages", {}).get("C_page_or_state", {}).get("status") == "LIVE_FETCHED" for r in results) if results else False
        if not go:
            reasons.append("one or more pages failed to fetch usable text")
    else:
        if not pos:
            go = False
            reasons.append("no positive targets")
        elif pos_ok < len(pos):
            go = False
            reasons.append(f"positives eligible {pos_ok}/{len(pos)}")
        else:
            reasons.append("all expected positives eligible from live pages")
        if any(r.get("ledger", {}).get("pipeline_summary", {}).get("search_context_board_leak") for r in results):
            go = False
            reasons.append("search_context board leak")

    return {
        "schema": "live-detail-slice-v0",
        "backend": backend,
        "n": n,
        "metrics": {
            "n": n,
            "n_ok_fetch": sum(1 for r in results if r.get("ok")),
            "n_with_expected": len(with_exp),
            "eligibility_match": matches,
            "eligibility_match_rate": (matches / len(with_exp)) if with_exp else None,
            "positive_n": len(pos),
            "positive_eligible_ok": pos_ok,
        },
        "fault_counts": faults,
        "go_no_go": {"go": go, "reasons": reasons},
        "results": results,
        "task_text": task_text,
    }
