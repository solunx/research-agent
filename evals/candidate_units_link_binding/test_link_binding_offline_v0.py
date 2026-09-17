#!/usr/bin/env python3
"""
Offline regression test for a `candidate_units.package_candidate_units`
item_link mis-binding bug, found 2026-09-17 while diagnosing
FRAMEWORK_BOUNDARY Open #24 ("list_results item hrefs not in affordances")
against the real trace of run `20260916T170647Z` (task 05, arXiv search
results, step 002).

No network, no LLM, no browser. Uses the REAL captured trace artifacts
(`fixture_05_arxiv_list_page_text.txt` / `fixture_05_arxiv_list_affordances.json`)
per testdiscipline: reproduce with real data before changing code.

--- Bug (fixed here) --------------------------------------------------
`_link_for_block` / the link-anchor pass in `package_candidate_units` matched
a link's label against block text with raw substring containment
(`lab in text` / `text in lab`). A short link label that is a literal prefix
of an unrelated word elsewhere on the page produced a false match, e.g.:

    "submit" in "submitted 24 march, 2026; originally announced march 2026."

This silently bound the page's global "Submit" nav link (-> /user/create,
an account-creation page with no relation to the block) to arXiv result
cards purely because every card contains a "Submitted <date>" line. Fix:
`_label_matches_text` requires a non-alphanumeric boundary (or string edge)
on both sides — a structural/token check, not language or domain content
(FRAMEWORK_BOUNDARY: no word lists, no site-specific rules).

--- Known, NOT fixed here (documented, out of scope for this patch) ---
A second, deeper issue surfaced while diagnosing this: on this same page,
the *entire* 50-result list renders as ONE blank-line block (no blank line
separates result cards in the flattened page text), which
`package_candidate_units` then slices into fixed 8-line chunks that straddle
paper boundaries. Combined with `browser_list_affordances`'s de-dupe-by-
visible-text (only the first occurrence of a repeated label like "pdf" is
ever captured), later chunks whose own paper link was never captured fall
back to matching the generic word "pdf" and bind to a DIFFERENT paper's pdf
link. An attempted fix (disambiguate via href path-tail identifier presence)
was tried, measured against the known-good 01/02 regression fixtures below,
and reverted: it broke real cases where a legitimate link (e.g. "Prijzen &
boeken") competed with an unrelated but literally-duplicated breadcrumb link
("Costa Calma") in the same block, dropping the correct action link on task
02. This is a representation/chunking-boundary problem (the same class the
project's own `structural_observer.py` HTML arm was built for — see
`CANDIDATE_LAYER.md` §12), not a matching-algorithm problem. Logged in
LEARNING_LOG.md / FRAMEWORK_BOUNDARY.md Open #24 as a distinct, still-open
follow-on. Do NOT attempt to "fix" this with more text heuristics here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidate_units import _label_matches_text, package_candidate_units  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent
PAGE_TEXT = FIXTURE_DIR / "fixture_05_arxiv_list_page_text.txt"
AFFORDANCES = FIXTURE_DIR / "fixture_05_arxiv_list_affordances.json"
PAGE_URL = (
    "https://arxiv.org/search/?query=large+language+model+agents+tool+use"
    "+2024&searchtype=all&source=header"
)


def _load_units():
    text = PAGE_TEXT.read_text(encoding="utf-8")
    affordances = json.loads(AFFORDANCES.read_text(encoding="utf-8"))
    return package_candidate_units(
        text=text,
        affordances=affordances,
        page_url=PAGE_URL,
        max_units=8,
        max_lines_per_unit=8,
    )


def _find_unit_with(units, needle: str):
    for u in units:
        if any(needle in t for t in (u.get("texts") or [])):
            return u
    return None


def test_label_matches_text_unit_boundary():
    """Direct unit test of the fixed matcher (isolated from packaging noise)."""
    # The original false positive: must NOT match.
    assert not _label_matches_text("submit", "submitted 24 march, 2026")
    # Reverse-direction false positive must also be rejected.
    assert not _label_matches_text("submitted 24 march, 2026", "submit")
    # Legitimate exact-word match must still work.
    assert _label_matches_text("submit", "search submit donate log in")
    # Legitimate multi-word phrase match must still work.
    assert _label_matches_text("advanced search", "show abstracts advanced search 25 50")
    # Legitimate containment of a longer id-bearing label must still work.
    assert _label_matches_text("arxiv:2608.06909", "arxiv:2608.06909 [pdf, ps, other]")
    print("OK test_label_matches_text_unit_boundary")


def test_paper_card_no_longer_binds_to_unrelated_submit_link():
    """
    Regression (real fixture): a unit whose text includes a "Submitted
    <date>" line (true of nearly every arXiv result card) must not bind to
    the unrelated global "Submit" (-> /user/create) link anymore.
    """
    units = _load_units()
    offenders = [
        u.get("unit_id")
        for u in units
        if "user/create" in str((u.get("item_link") or {}).get("href") or "")
        and any("arXiv:" in t for t in (u.get("texts") or []))
    ]
    assert not offenders, f"paper-result units wrongly bound to Submit/user-create: {offenders}"
    print("OK test_paper_card_no_longer_binds_to_unrelated_submit_link")


def test_chrome_block_keeps_legitimate_submit_binding():
    """
    Non-regression / positive control: the literal top-nav chrome block
    ("Search Submit Donate Log in ...") DOES contain the standalone word
    "Submit" and must keep that correct, exact-word structural match — the
    fix must not become overly strict and reject true matches.
    """
    units = _load_units()
    u = _find_unit_with(units, "Donate")
    assert u is not None, "fixture must still contain the top-nav chrome block"
    link = u.get("item_link") or {}
    assert "user/create" in str(link.get("href") or ""), (
        f"expected chrome block to keep its legitimate Submit binding, got: {link}"
    )
    print(f"OK test_chrome_block_keeps_legitimate_submit_binding (item_link={link})")


def test_real_item_link_still_binds_when_present():
    """
    Sanity / non-regression: a unit whose real paper link IS present in the
    (truncated) affordances list must still bind correctly. arXiv:2608.06909
    is present both in page text and in the affordances fixture.
    """
    units = _load_units()
    u = _find_unit_with(units, "arXiv:2608.06909")
    assert u is not None, "fixture must contain the 2608.06909 unit"
    link = u.get("item_link")
    assert link is not None, "expected a bound item_link for a unit with a real matching affordance"
    assert "2608.06909" in str(link.get("href") or ""), link
    print(f"OK test_real_item_link_still_binds_when_present (item_link={link})")


def test_known_good_fixtures_unchanged():
    """
    Non-regression against the project's own accepted-good manifest
    (`evals/candidate_offline/fixtures_from_traces/manifest.json`): the
    word-boundary fix must not change item_link bindings on the fixtures
    task 01/02 stability was measured against (9/9 SUCCESS, 2026-09-15).
    """
    manifest_path = ROOT / "evals/candidate_offline/fixtures_from_traces/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    }
    for m in manifest:
        label = m["label"]
        if label not in expected:
            continue
        text = (ROOT / m["page_text"]).read_text(encoding="utf-8")
        aff = json.loads((ROOT / m["affordances"]).read_text(encoding="utf-8"))
        units = package_candidate_units(
            text=text, affordances=aff, page_url=m["url"], max_units=8, max_lines_per_unit=8
        )
        hrefs = [str((u.get("item_link") or {}).get("href") or "") for u in units[:3]]
        assert hrefs == expected[label], f"{label}: item_link hrefs changed: {hrefs}"
    print("OK test_known_good_fixtures_unchanged")


def main():
    test_label_matches_text_unit_boundary()
    test_paper_card_no_longer_binds_to_unrelated_submit_link()
    test_chrome_block_keeps_legitimate_submit_binding()
    test_real_item_link_still_binds_when_present()
    test_known_good_fixtures_unchanged()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
