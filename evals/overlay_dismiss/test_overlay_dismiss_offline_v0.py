#!/usr/bin/env python3
"""
Open #31 overlay dismiss — offline.

Chosen dismiss: first button in DOM order inside role=dialog / aria-modal
(not shortest text). 2dehands Sourcepoint: dialog+iframe, no same-origin
button → hide_blocking_dialog.

No network, no LLM, no GPU for the HTML/gate tests. Playwright optional.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from overlay_dismiss import (  # noqa: E402
    overlay_dismiss_should_run,
    overlays_from_html,
    pick_overlay_dismiss,
)
from evidence_acquisition import (  # noqa: E402
    action_fingerprint,
    reset_overlay_timeout_memory,
)

HERE = Path(__file__).resolve().parent
FIXTURE_2DEHANDS = HERE / "fixture_2dehands_sp_dialog.html"
FIXTURE_TWO_BTN = HERE / "fixture_dialog_two_buttons.html"
ICON_SEARCH = ROOT / "evals" / "click_related_input" / "icon_search_page.html"
EVALS = ROOT / "evals" / "contract_driven"
FIX = ROOT / "evals" / "candidate_offline" / "fixtures_from_traces"


def test_first_button_not_shortest_text():
    html = FIXTURE_TWO_BTN.read_text(encoding="utf-8")
    ovs = overlays_from_html(html)
    assert len(ovs) == 1, ovs
    assert len(ovs[0]["buttons"]) == 2, ovs[0]["buttons"]
    plan = pick_overlay_dismiss(ovs)
    assert plan is not None
    assert plan["method"] == "first_button"
    assert "Lees het cookiebeleid" in plan["first_button_text"]
    assert plan["first_button_text"] != "OK"
    print(
        "OK test_first_button_not_shortest_text",
        repr(plan["first_button_text"]),
    )


def test_2dehands_fixture_recognizes_dialog_and_picks_dismiss():
    html = FIXTURE_2DEHANDS.read_text(encoding="utf-8")
    ovs = overlays_from_html(html)
    assert ovs, "dialog must be found"
    ov = ovs[0]
    assert ov.get("role") == "dialog"
    assert ov.get("aria_modal") == "true"
    assert ov.get("id") == "sp_message_container_1494622"
    assert int(ov.get("n_iframes") or 0) >= 1
    plan = pick_overlay_dismiss(ovs)
    assert plan is not None
    assert plan["method"] == "hide_blocking_dialog", plan
    assert plan["overlay_id"] == "sp_message_container_1494622"
    assert plan["click_selector"]
    print(
        "OK test_2dehands_fixture_recognizes_dialog_and_picks_dismiss",
        plan["method"],
        plan["overlay_id"],
    )


def test_gate_requires_second_different_fingerprint():
    reset_overlay_timeout_memory()
    fp_fill = action_fingerprint(
        {
            "action_class": "FILL_AND_SUBMIT",
            "target_text": "Dropdown zoekbalk",
            "query_text": "fiets",
        },
        page_url="https://www.2dehands.be/",
    )
    fp_fill2 = action_fingerprint(
        {
            "action_class": "FILL_AND_SUBMIT",
            "target_text": "postcode",
            "query_text": "2000",
        },
        page_url="https://www.2dehands.be/",
    )
    assert not overlay_dismiss_should_run(prior_timeout_fps=[], current_fp=fp_fill)
    assert not overlay_dismiss_should_run(
        prior_timeout_fps=[fp_fill], current_fp=fp_fill
    ), "same fingerprint is not a second target"
    assert overlay_dismiss_should_run(
        prior_timeout_fps=[fp_fill], current_fp=fp_fill2
    )
    print("OK test_gate_requires_second_different_fingerprint")


def test_negative_no_dialog_html_has_no_dismiss_plan():
    html = ICON_SEARCH.read_text(encoding="utf-8")
    ovs = overlays_from_html(html)
    assert ovs == [] or pick_overlay_dismiss(ovs) is None
    plan = pick_overlay_dismiss(ovs)
    assert plan is None
    print("OK test_negative_no_dialog_html_has_no_dismiss_plan")


def test_negative_01_02_03_05_06_page_html_no_sp_dialog():
    """Legitimate click-timeouts (Coolblue Zoeken) are not overlay-gated.

    First timeout never dismisses. Pages without role=dialog / aria-modal
    yield no plan even if the gate were true.
    """
    paths = [
        (
            "01",
            FIX / "01_price_surface" / "page.html",
        ),
        (
            "02",
            FIX / "02_detail" / "page.html",
        ),
        (
            "03",
            ICON_SEARCH,
        ),
        (
            "05",
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "trace/artifacts/step_002_page.html",
        ),
        (
            "06",
            EVALS
            / "20260919T165815Z_wiki_brussels_population"
            / "trace/artifacts/step_000_page.html",
        ),
    ]
    for label, path in paths:
        if not path.is_file():
            print(f"SKIP {label} no page.html at {path}")
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        ovs = overlays_from_html(html)
        sp = [o for o in ovs if "sp_message" in str(o.get("id") or "")]
        assert not sp, (label, sp)
        # Cookie CMPs on 01/02 may still be role=dialog. The execute gate
        # still requires two timeouts; a single Zoeken timeout must not fire.
        fp_a = action_fingerprint(
            {"action_class": "CLICK_TEXT", "target_text": "Zoeken"},
            page_url="https://www.coolblue.be/nl",
        )
        assert not overlay_dismiss_should_run(prior_timeout_fps=[], current_fp=fp_a)
        print(f"OK negative {label} overlays={len(ovs)} first_timeout_gate=False")
    print("OK test_negative_01_02_03_05_06_page_html_no_sp_dialog")


def test_playwright_2dehands_fixture_optional():
    if not FIXTURE_2DEHANDS.is_file():
        print("SKIP test_playwright_2dehands_fixture_optional")
        return
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP test_playwright_2dehands_fixture_optional (no playwright)")
        return
    from browser import (
        browser_dismiss_blocking_overlay,
        browser_list_blocking_overlays,
        browser_open,
    )

    snap = browser_open(FIXTURE_2DEHANDS.as_uri(), wait_seconds=0.3, max_chars=2000)
    if snap.get("error") and "playwright" in str(snap.get("error") or "").lower():
        print("SKIP playwright", snap.get("error"))
        return
    listed = browser_list_blocking_overlays()
    assert listed, listed
    assert listed[0].get("aria_modal") == "true" or listed[0].get("role") == "dialog"
    dismissed = browser_dismiss_blocking_overlay()
    assert dismissed.get("attempted"), dismissed
    assert dismissed.get("method") in ("first_button", "hide_blocking_dialog")
    print(
        "OK test_playwright_2dehands_fixture_optional",
        dismissed.get("method"),
        dismissed.get("overlay_id"),
    )


if __name__ == "__main__":
    test_first_button_not_shortest_text()
    test_2dehands_fixture_recognizes_dialog_and_picks_dismiss()
    test_gate_requires_second_different_fingerprint()
    test_negative_no_dialog_html_has_no_dismiss_plan()
    test_negative_01_02_03_05_06_page_html_no_sp_dialog()
    test_playwright_2dehands_fixture_optional()
    print("ALL OK overlay_dismiss offline")
