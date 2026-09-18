#!/usr/bin/env python3
"""
Offline tests: CLICK_TEXT → related input_field fallback.

Diagnosis (task 03, run 20260916T110052Z + live reconfirm 2026-09-18):
  LLM chose CLICK_TEXT target_text=Zoeken. Playwright text=Zoeken timed out
  (icon submit has aria-label only, empty innerText). Agent then browsed
  Computers & tablets (wrong GPU category).

  input_field capacity did NOT self-solve the click timeout: the search
  field is listed, but CLICK_TEXT still uses the text= engine.

Fallback relation is token-boundary match of click text into the input's
accessible name (_label_matches_text). No "Zoeken"/"search" lexicon.
Exactly one match required.

No network, no LLM, no GPU for the pure-Python cases. Playwright execute
uses this folder's local HTML fixture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evidence_acquisition import (  # noqa: E402
    click_text_accessible_name_selectors,
    click_text_selectors,
    execute_acquisition_action,
    related_input_field,
    related_input_locator,
)

HERE = Path(__file__).resolve().parent
FIXTURE_HTML = HERE / "icon_search_page.html"
EVALS = ROOT / "evals" / "contract_driven"
CAND_FIX = ROOT / "evals" / "candidate_offline" / "fixtures_from_traces"

SEARCH_INPUT = {
    "kind": "input_field",
    "text": "Zoeken naar producten",
    "href": "",
    "scope": "local",
    "tag": "input",
    "type": "search",
    "name": "query",
    "id": "search",
    "placeholder": "Zoeken naar...",
    "aria_label": "Zoeken naar producten",
}
NEWSLETTER = {
    "kind": "input_field",
    "text": "E-mailadres",
    "href": "",
    "scope": "local",
    "tag": "input",
    "type": "email",
    "name": "email",
    "id": "email",
    "placeholder": "E-mailadres",
    "aria_label": "Nieuwsbrief",
}
BUTTON_ZOEKEN = {"kind": "button", "text": "Zoeken", "href": "", "scope": "local"}
BUTTON_CAT = {
    "kind": "button",
    "text": "Computers & tablets",
    "href": "",
    "scope": "local",
}
COOLBLUE_AFFS = [
    BUTTON_ZOEKEN,
    BUTTON_CAT,
    {"kind": "button", "text": "Account", "href": "", "scope": "local"},
    SEARCH_INPUT,
    NEWSLETTER,
]


def test_selectors_still_start_with_text_engine():
    sels = click_text_selectors("Zoeken")
    assert sels[0] == "text=Zoeken", sels
    assert any(s.startswith("button:has-text(") for s in sels), sels
    acc = click_text_accessible_name_selectors("Zoeken")
    assert "[aria-label='Zoeken']" in acc, acc
    print("OK test_selectors_still_start_with_text_engine")


def test_related_matches_shared_accessible_name_token():
    """Positive: click text is a token in the unique input's accessible name."""
    hit = related_input_field("Zoeken", COOLBLUE_AFFS)
    assert hit is not None, "expected unique related input"
    assert hit.get("id") == "search", hit
    loc = related_input_locator(hit)
    assert loc == "#search", loc
    print(f"OK test_related_matches_shared_accessible_name_token loc={loc}")


def test_negative_unrelated_click_does_not_pick_input():
    """Mandatory negative: failed category click must not grab the search field."""
    hit = related_input_field("Computers & tablets", COOLBLUE_AFFS)
    assert hit is None, f"unrelated click must not bind an input: {hit}"
    hit2 = related_input_field("Account", COOLBLUE_AFFS)
    assert hit2 is None, f"Account must not bind search/newsletter: {hit2}"
    hit3 = related_input_field("NietBestaand", COOLBLUE_AFFS)
    assert hit3 is None, hit3
    print("OK test_negative_unrelated_click_does_not_pick_input")


def test_negative_ambiguous_two_matching_inputs():
    """Two inputs sharing the click token → None (do not pick at random)."""
    other = dict(SEARCH_INPUT)
    other["id"] = "search-nav"
    other["name"] = "q2"
    hit = related_input_field("Zoeken", [SEARCH_INPUT, other, NEWSLETTER])
    assert hit is None, f"ambiguous match must be None: {hit}"
    print("OK test_negative_ambiguous_two_matching_inputs")


def test_negative_type_only_input_has_no_locator():
    """No id/name/accessible name → no locator (never first-visible-input)."""
    bare = {"kind": "input_field", "type": "search"}
    assert related_input_locator(bare) is None
    assert related_input_locator(None) is None
    print("OK test_negative_type_only_input_has_no_locator")


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_regression_01_02_06_clicks_do_not_bind_inputs():
    """Tasks where the Coolblue click-timeout scenario does not occur."""
    cases = [
        (
            "01",
            EVALS
            / "20260916T065415Z_01_web_hotel_package_concrete"
            / "trace"
            / "artifacts"
            / "step_000_affordances.json",
            ["VERTREKPERIODE", "Kerstvakantie 2026", "Wijzig Reisgezelschap", "VLIEGEN VANAF"],
        ),
        (
            "02",
            CAND_FIX / "02_detail" / "step_000_affordances.json",
            ["Prijzen & boeken", "Ligging", "Foto's & Video's", "ALL INCLUSIVE"],
        ),
        (
            "06",
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "trace"
            / "artifacts"
            / "step_000_affordances.json",
            ["Toggle Demographics subsection", "Toggle History subsection"],
        ),
    ]
    for label, path, clicks in cases:
        assert path.is_file(), f"missing fixture {path}"
        affs = _load_json(path)
        for text in clicks:
            hit = related_input_field(text, affs)
            assert hit is None, f"{label} CLICK_TEXT {text!r} bound input {hit}"
        print(f"OK regression {label} n_aff={len(affs)} clicks={clicks}")
    print("OK test_regression_01_02_06_clicks_do_not_bind_inputs")


def test_regression_05_unrelated_clicks_do_not_bind_search():
    """arXiv: Related Papers / View PDF must not bind the search input.
    'Search' token-matches the field — that is the same structural class as
    Coolblue Zoeken, and only runs after a click timeout (execute path).
    """
    path = (
        EVALS
        / "20260918T081459Z_05_web_literature_abstract"
        / "trace"
        / "artifacts"
        / "step_001_affordances.json"
    )
    assert path.is_file(), path
    affs = _load_json(path)
    for text in ("Related Papers", "View PDF", "Back to Abstract", "Computer Science"):
        hit = related_input_field(text, affs)
        assert hit is None, f"05 {text!r} bound {hit}"
    search_hit = related_input_field("Search", affs)
    assert search_hit is not None
    assert search_hit.get("id") == "arxiv-search-input", search_hit
    print("OK test_regression_05_unrelated_clicks_do_not_bind_search")


def _active_id():
    from browser import _ensure_browser

    page = _ensure_browser()
    return page.evaluate(
        "() => (document.activeElement && document.activeElement.id) || ''"
    )


def test_execute_zoeken_falls_back_to_related_input():
    if not FIXTURE_HTML.is_file():
        print("SKIP test_execute_zoeken_falls_back_to_related_input (fixture missing)")
        return
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP test_execute_zoeken_falls_back_to_related_input (no playwright)")
        return
    from browser import browser_open, browser_list_affordances

    url = FIXTURE_HTML.as_uri()
    snap = browser_open(url, wait_seconds=0.4, max_chars=4000)
    if snap.get("error") and "playwright" in str(snap.get("error")).lower():
        print(f"SKIP test_execute_zoeken_falls_back_to_related_input ({snap.get('error')})")
        return
    aff = browser_list_affordances(max_items=30)
    kinds = [a.get("kind") for a in (aff.get("affordances") or [])]
    assert "input_field" in kinds, aff
    result = execute_acquisition_action(
        {"action_class": "CLICK_TEXT", "target_text": "Zoeken"},
        max_chars=4000,
    )
    assert result.get("ok"), result
    assert result.get("click_fallback") == "related_input_field", result
    assert result.get("clicked_selector") == "#search", result
    assert _active_id() == "search", f"expected #search focused, got {_active_id()!r}"
    print(
        "OK test_execute_zoeken_falls_back_to_related_input "
        f"fallback={result.get('click_fallback')} sel={result.get('clicked_selector')}"
    )


def test_execute_negative_failed_click_does_not_focus_search():
    if not FIXTURE_HTML.is_file():
        print("SKIP test_execute_negative_failed_click_does_not_focus_search")
        return
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP test_execute_negative_failed_click_does_not_focus_search (no playwright)")
        return
    from browser import browser_open

    url = FIXTURE_HTML.as_uri()
    snap = browser_open(url, wait_seconds=0.4, max_chars=4000)
    if snap.get("error") and "playwright" in str(snap.get("error")).lower():
        print(f"SKIP ({snap.get('error')})")
        return
    result = execute_acquisition_action(
        {"action_class": "CLICK_TEXT", "target_text": "NietBestaand"},
        max_chars=4000,
    )
    assert not result.get("ok"), result
    assert result.get("click_fallback") != "related_input_field", result
    assert _active_id() != "search", f"search must not be focused after unrelated miss, got {_active_id()!r}"
    print(
        "OK test_execute_negative_failed_click_does_not_focus_search "
        f"ok={result.get('ok')} err={result.get('error')}"
    )


def test_execute_visible_text_click_skips_fallback():
    """Computers & tablets has innerText — existing locator path, no related-input."""
    if not FIXTURE_HTML.is_file():
        print("SKIP test_execute_visible_text_click_skips_fallback")
        return
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP test_execute_visible_text_click_skips_fallback (no playwright)")
        return
    from browser import browser_open

    url = FIXTURE_HTML.as_uri()
    snap = browser_open(url, wait_seconds=0.4, max_chars=4000)
    if snap.get("error") and "playwright" in str(snap.get("error")).lower():
        print(f"SKIP ({snap.get('error')})")
        return
    result = execute_acquisition_action(
        {"action_class": "CLICK_TEXT", "target_text": "Computers & tablets"},
        max_chars=4000,
    )
    assert result.get("ok"), result
    assert not result.get("click_fallback"), result
    assert _active_id() != "search", f"category click must not focus search, got {_active_id()!r}"
    print(
        "OK test_execute_visible_text_click_skips_fallback "
        f"sel={result.get('clicked_selector')} active={_active_id()!r}"
    )


def main():
    test_selectors_still_start_with_text_engine()
    test_related_matches_shared_accessible_name_token()
    test_negative_unrelated_click_does_not_pick_input()
    test_negative_ambiguous_two_matching_inputs()
    test_negative_type_only_input_has_no_locator()
    test_regression_01_02_06_clicks_do_not_bind_inputs()
    test_regression_05_unrelated_clicks_do_not_bind_search()
    test_execute_zoeken_falls_back_to_related_input()
    test_execute_negative_failed_click_does_not_focus_search()
    test_execute_visible_text_click_skips_fallback()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
