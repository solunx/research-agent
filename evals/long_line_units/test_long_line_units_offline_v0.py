#!/usr/bin/env python3
"""
Offline tests for Open #27 — long innerText lines must not be dropped.

No browser, no LLM, no GPU. Uses the REAL captured abs page from live run
`20260917T093236Z` (task 05, step 003, https://arxiv.org/abs/2609.19059).

Bug: `_skip_line_structural` treated len>240 as skip-and-split. The abstract
is one 1524-char line in flattened page_text, so it never entered a unit.
Interpret only saw chrome (Submit / view email / View PDF). Title survived
in the 8-line prefix chunk; claim_extracted stayed NOT_VISIBLE even though
the paragraph is in page_text.

Fix: wrap long lines into 240-char windows as their own block; keep them
without requiring digit-density or an item_link; append at most one long
unit/candidate after action-first rank so interpret sees the paragraph.

Negative: 01/02 known-good top-3 item_link hrefs must not change (same
assertion as Open #24a). A page with only short lines must not grow a
phantom long unit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidate_units import package_candidate_units, units_to_observations  # noqa: E402
from candidates import extract_candidates, candidates_to_observations  # noqa: E402

HERE = Path(__file__).resolve().parent
ABS_TEXT = (HERE / "fixture_05_arxiv_abs_page_text.txt").read_text(encoding="utf-8")
ABS_AFF = json.loads((HERE / "fixture_05_arxiv_abs_affordances.json").read_text(encoding="utf-8"))
ABS_URL = "https://arxiv.org/abs/2609.19059"
# Distinctive prefix of the dropped abstract (first 160 chars survive join).
ABSTRACT_PREFIX = "Multimodal large language model (MLLM) agents"


def _unit_blob(units: list[dict]) -> str:
    return " ".join(" ".join(u.get("texts") or []) for u in units)


def test_abs_page_text_contains_unwrapped_abstract():
    """Fixture sanity: the paragraph is in page_text as one huge line."""
    huge = [ln.strip() for ln in ABS_TEXT.splitlines() if len(ln.strip()) > 240]
    assert len(huge) == 1, huge
    assert ABSTRACT_PREFIX in huge[0]
    assert len(huge[0]) > 1000
    print("OK test_abs_page_text_contains_unwrapped_abstract")


def test_abstract_survives_packaging():
    units = package_candidate_units(
        text=ABS_TEXT,
        affordances=ABS_AFF,
        page_url=ABS_URL,
        max_units=6,
    )
    blob = _unit_blob(units)
    assert ABSTRACT_PREFIX in blob, blob[:400]
    print("OK test_abstract_survives_packaging n_units=%d" % len(units))


def test_abstract_reaches_extract_and_observations():
    cands = extract_candidates(
        text=ABS_TEXT,
        affordances=ABS_AFF,
        page_url=ABS_URL,
        surface="list_results",
        max_candidates=3,
        max_units=6,
    )
    ev = " ".join(" ".join(c.evidence) for c in cands)
    assert ABSTRACT_PREFIX in ev, ev[:500]
    obs = candidates_to_observations(cands, max_candidates=8)
    obs_text = " ".join(str(o.get("text") or "") for o in obs)
    assert ABSTRACT_PREFIX in obs_text, obs_text[:500]
    print(
        "OK test_abstract_reaches_extract_and_observations "
        "n_cands=%d n_obs=%d" % (len(cands), len(obs))
    )


def test_short_only_page_does_not_invent_long_unit():
    """Negative: short chrome lines stay short; no phantom paragraph unit."""
    text = "Search\nSubmit\nDonate\nLog in\n"
    units = package_candidate_units(
        text=text,
        affordances=[{"text": "Submit", "href": "https://arxiv.org/user/create", "scope": "local"}],
        page_url="https://arxiv.org/",
        max_units=6,
    )
    blob = _unit_blob(units)
    assert ABSTRACT_PREFIX not in blob
    assert all(_texts_ok(u) for u in units)
    print("OK test_short_only_page_does_not_invent_long_unit n=%d" % len(units))


def _texts_ok(u: dict) -> bool:
    return all(len(str(t)) <= 240 for t in (u.get("texts") or []))


def test_known_good_fixtures_top3_hrefs_unchanged():
    """Same 01/02/synthetic contract as Open #24a — wrapping must not reshuffle nav."""
    man = json.loads(
        (ROOT / "evals/candidate_offline/fixtures_from_traces/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "synthetic_multi_offer_list": [
            "/offers/alpha-resort",
            "/offers/beta-lodge",
            "/offers/gamma-inn",
        ],
        "02_monica_detail": [
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma",
            "https://www.corendon.be/vakanties/lastminutes",
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma",
        ],
        "01_flamenco_price_surface": [
            "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir",
            "https://www.corendon.be/vakanties/lastminutes",
            "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir",
        ],
    }
    for m in man:
        label = str(m.get("label") or "")
        if label not in expected:
            continue
        text = (ROOT / m["page_text"]).read_text(encoding="utf-8")
        aff = json.loads((ROOT / m["affordances"]).read_text(encoding="utf-8"))
        units = package_candidate_units(
            text=text, affordances=aff, page_url=m["url"], max_units=8
        )
        hrefs = [str((u.get("item_link") or {}).get("href") or "") for u in units[:3]]
        assert hrefs == expected[label], f"{label}: item_link hrefs changed: {hrefs}"
    print("OK test_known_good_fixtures_top3_hrefs_unchanged")


def test_units_to_observations_keeps_abstract_prefix():
    units = package_candidate_units(
        text=ABS_TEXT, affordances=ABS_AFF, page_url=ABS_URL, max_units=6
    )
    obs = units_to_observations(units, page_url=ABS_URL, surface="live_detail", max_units=8)
    blob = " ".join(str(o.get("text") or "") for o in obs)
    assert ABSTRACT_PREFIX in blob, blob[:500]
    print("OK test_units_to_observations_keeps_abstract_prefix")


def main():
    test_abs_page_text_contains_unwrapped_abstract()
    test_abstract_survives_packaging()
    test_abstract_reaches_extract_and_observations()
    test_short_only_page_does_not_invent_long_unit()
    test_known_good_fixtures_top3_hrefs_unchanged()
    test_units_to_observations_keeps_abstract_prefix()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
