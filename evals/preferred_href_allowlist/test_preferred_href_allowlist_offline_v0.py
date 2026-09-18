#!/usr/bin/env python3
"""
Offline tests: OPEN_URL allowlist includes shown-candidate primary_action hrefs.

Live citation (`20260917T171515Z` step 3):
  LLM OPEN_URL https://arxiv.org/abs/2609.13860
  code_reject href_not_in_affordances
  href is c0.primary_action, not in the capped 60-item affordance list.

No network, no LLM, no GPU. Mock chat_fn.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidates import extract_candidates  # noqa: E402
from evidence_acquisition import (  # noqa: E402
    acquisition_decide,
    filter_safe_affordances,
    observed_open_hrefs,
)

HERE = Path(__file__).resolve().parent
AFF_1715 = HERE / "fixture_171515Z_step_003_affordances.json"
CAND_1715 = HERE / "fixture_171515Z_step_003_candidates.json"
ABS_HREF = "https://arxiv.org/abs/2609.13860"
INVENTED = "https://example.test/invented/not-observed"
SEARCH_URL = (
    "https://arxiv.org/search/?query=tool-augmented+LLM+agents"
    "&searchtype=all&abstracts=show&order=-announced_date_first&size=50"
)
GAPS = [
    {
        "kind": "decision_gap",
        "decision_id": "claim_extracted",
        "required_entry": "claim_extracted = EXTRACTED",
        "observed": "NOT_VISIBLE",
        "allowed": ["EXTRACTED"],
        "result": "FAIL",
    }
]
LIVE_MAX_CANDIDATES = 3
LIVE_MAX_UNITS = 6

CASES_01_02_06 = [
    (
        "01_flamenco_price_surface",
        ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/step_000_page_text.txt",
        ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/step_000_affordances.json",
        "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir/flamenco-beach-resort",
        "list_results",
    ),
    (
        "02_monica_detail",
        ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/step_000_page_text.txt",
        ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/step_000_affordances.json",
        "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma/sbh-monica-beach",
        "live_detail",
    ),
    (
        "06_wiki_fuerteventura",
        ROOT / "evals/long_line_units/fixture_06_wiki_page_text.txt",
        ROOT / "evals/long_line_units/fixture_06_wiki_affordances.json",
        "https://en.wikipedia.org/wiki/Fuerteventura",
        "live_detail",
    ),
]


def _pref_from_candidates(cands_json: dict) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for c in cands_json.get("candidates") or []:
        pa = c.get("primary_action") or {}
        href = str(pa.get("href") or "")
        text = str(pa.get("text") or "")
        if href or text:
            out.append({"text": text[:120], "href": href[:400]})
    return out


def _decide(aff, pref, href, *, page_url=SEARCH_URL):
    def chat_fn(_messages):
        return json.dumps(
            {
                "action_class": "OPEN_URL",
                "target_text": "arXiv:2609.13860",
                "target_href": href,
                "for_decision_ids": ["claim_extracted"],
                "reason": "open observed candidate abs page",
            }
        )

    return acquisition_decide(
        gaps=GAPS,
        affordances=aff,
        page_url=page_url,
        page_title="Search",
        claim_preview=[],
        task_text="Find a recent paper on LLM agents.",
        chat_fn=chat_fn,
        step_index=3,
        max_steps=6,
        preferred_item_links=pref,
    )


def test_live_fixture_abs_missing_from_affordances():
    aff = json.loads(AFF_1715.read_text(encoding="utf-8"))
    cands = json.loads(CAND_1715.read_text(encoding="utf-8"))
    aff_hrefs = {str(a.get("href") or "") for a in aff}
    pref = _pref_from_candidates(cands)
    assert ABS_HREF not in aff_hrefs
    assert ABS_HREF in {p["href"] for p in pref}
    print("OK test_live_fixture_abs_missing_from_affordances")


def test_171515Z_open_candidate_abs_now_accepted():
    aff = json.loads(AFF_1715.read_text(encoding="utf-8"))
    cands = json.loads(CAND_1715.read_text(encoding="utf-8"))
    pref = _pref_from_candidates(cands)
    d = _decide(aff, pref, ABS_HREF)
    assert d.get("action_class") == "OPEN_URL", d
    assert d.get("target_href") == ABS_HREF, d
    assert d.get("source") == "llm", d
    print("OK test_171515Z_open_candidate_abs_now_accepted")


def test_negative_invented_url_still_rejected():
    """Mandatory negative: URL in neither affordances nor primary_action → STOP."""
    aff = json.loads(AFF_1715.read_text(encoding="utf-8"))
    cands = json.loads(CAND_1715.read_text(encoding="utf-8"))
    pref = _pref_from_candidates(cands)
    d = _decide(aff, pref, INVENTED)
    assert d.get("action_class") == "STOP", d
    assert d.get("reason") == "href_not_in_affordances", d
    assert d.get("source") == "code_reject", d
    # Without preferred links the live abs href must still fail (old rule).
    d_old = _decide(aff, [], ABS_HREF)
    assert d_old.get("action_class") == "STOP", d_old
    assert d_old.get("reason") == "href_not_in_affordances", d_old
    print("OK test_negative_invented_url_still_rejected")


def test_observed_open_hrefs_unions_sets():
    aff = [{"href": "https://example.test/a"}, {"href": ""}]
    pref = [{"text": "x", "href": "https://example.test/b"}]
    hrefs = observed_open_hrefs(aff, pref)
    assert hrefs == {"https://example.test/a", "https://example.test/b"}
    print("OK test_observed_open_hrefs_unions_sets")


def test_01_02_06_no_new_accepts_from_primary_action():
    """Regression: 01/02/06 candidate hrefs already sit in the affordance list."""
    for label, text_p, aff_p, url, surface in CASES_01_02_06:
        aff = json.loads(aff_p.read_text(encoding="utf-8"))
        text = text_p.read_text(encoding="utf-8")
        cands = extract_candidates(
            text=text,
            affordances=aff,
            page_url=url,
            surface=surface,
            max_candidates=LIVE_MAX_CANDIDATES,
            max_units=LIVE_MAX_UNITS,
        )
        aff_hrefs = {str(a.get("href") or "").strip() for a in aff if a.get("href")}
        safe = filter_safe_affordances(aff)
        safe_hrefs = {str(a.get("href") or "").strip() for a in safe if a.get("href")}
        extra = []
        extra_vs_safe = []
        for c in cands:
            href = str((c.primary_action or {}).get("href") or "").strip()
            if href and href not in aff_hrefs:
                extra.append((c.candidate_id, href))
            if href and href not in safe_hrefs:
                extra_vs_safe.append((c.candidate_id, href))
        assert extra == [], f"{label}: primary_action hrefs not already in affordances: {extra}"
        pref = [
            {
                "text": str((c.primary_action or {}).get("text") or ""),
                "href": str((c.primary_action or {}).get("href") or ""),
            }
            for c in cands
            if c.has_action()
        ]
        # OPEN a href that already survived filter_safe (same accept as before).
        in_safe = next((h for h in safe_hrefs if h), None)
        assert in_safe, label
        d_ok = _decide(aff, pref, in_safe, page_url=url)
        assert d_ok.get("action_class") == "OPEN_URL", (label, d_ok)
        d_bad = _decide(aff, pref, INVENTED, page_url=url)
        assert d_bad.get("action_class") == "STOP", (label, d_bad)
        assert d_bad.get("reason") == "href_not_in_affordances", (label, d_bad)
        print(
            f"REGRESSION {label} extra_vs_full_aff=0 extra_vs_safe={len(extra_vs_safe)} "
            f"invented_rejected=True"
        )
    print("OK test_01_02_06_no_new_accepts_from_primary_action")


def main():
    test_live_fixture_abs_missing_from_affordances()
    test_171515Z_open_candidate_abs_now_accepted()
    test_negative_invented_url_still_rejected()
    test_observed_open_hrefs_unions_sets()
    test_01_02_06_no_new_accepts_from_primary_action()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
