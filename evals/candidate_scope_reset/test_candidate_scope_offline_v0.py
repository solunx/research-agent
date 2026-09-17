#!/usr/bin/env python3
"""
Offline tests for Open #26 — candidate-scoped best_outcomes reset.

No browser, no LLM, no GPU. Pure apply_candidate_scope_after_action.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from live_offer_state_slice import apply_candidate_scope_after_action  # noqa: E402

DECISIONS_05 = [
    {"id": "subject_instance", "required_for_eligibility": ["RELEVANT"]},
    {"id": "title_extracted", "required_for_eligibility": ["EXTRACTED"]},
    {"id": "recency", "required_for_eligibility": ["IN_RANGE"]},
    {"id": "source_site", "required_for_eligibility": []},
]
DECISIONS_01 = [
    {"id": "subject_instance", "required_for_eligibility": ["CONFIRMED", "YES"]},
    {"id": "board_type", "required_for_eligibility": ["ALL_INCLUSIVE"]},
]
DECISIONS_02 = [
    {"id": "subject_instance", "required_for_eligibility": ["CONFIRMED"]},
    {"id": "board_type", "required_for_eligibility": ["ALL_INCLUSIVE"]},
    {"id": "detail_link", "required_for_eligibility": ["VALID_DETAIL_PAGE"]},
]


def test_unbind_after_reject_like_083112Z():
    """stap 3 abs NOT_RELEVANT, OPEN Search → post-bind weg, source_site blijft."""
    best = {
        "source_site": {"outcome": "ARXIV", "step": 2},
        "subject_instance": {"outcome": "NOT_RELEVANT", "step": 3},
        "recency": {"outcome": "IN_RANGE", "step": 3},
        "title_extracted": {"outcome": "EXTRACTED", "step": 3},
    }
    new_best, path, bound, event = apply_candidate_scope_after_action(
        best_outcomes=best,
        active_candidate_path="/abs/2609.19059",
        candidate_bound_step=3,
        action_class="OPEN_URL",
        target_href="https://arxiv.org/search",
        page_url_before="https://arxiv.org/abs/2609.19059",
        new_url="https://arxiv.org/search/",
        ok=True,
        surface_before="list_results",
        preferred_item_links=[
            {"text": "arXiv:2609.19059", "href": "https://arxiv.org/abs/2609.19059"}
        ],
        decisions=DECISIONS_05,
        next_step=4,
    )
    assert event == "unbind", event
    assert path is None and bound is None
    assert "source_site" in new_best and new_best["source_site"]["outcome"] == "ARXIV"
    assert "subject_instance" not in new_best
    assert "title_extracted" not in new_best
    assert "recency" not in new_best
    print("OK test_unbind_after_reject_like_083112Z")


def test_fill_unbinds_bound_candidate():
    best = {
        "source_site": {"outcome": "ARXIV", "step": 1},
        "subject_instance": {"outcome": "NOT_RELEVANT", "step": 3},
    }
    new_best, path, bound, event = apply_candidate_scope_after_action(
        best_outcomes=best,
        active_candidate_path="/abs/2609.19059",
        candidate_bound_step=3,
        action_class="FILL_AND_SUBMIT",
        target_href=None,
        page_url_before="https://arxiv.org/abs/2609.19059",
        new_url="https://arxiv.org/search/?query=tool-using+LLM+agents",
        ok=True,
        surface_before="list_results",
        preferred_item_links=[],
        decisions=DECISIONS_05,
        next_step=4,
    )
    assert event == "unbind", event
    assert path is None
    assert list(new_best) == ["source_site"]
    print("OK test_fill_unbinds_bound_candidate")


def test_task02_tab_does_not_reset():
    """Zelfde path + tab; geen list-bind → 02-baseline ongewijzigd."""
    monica = (
        "https://www.corendon.be/spanje/canarische-eilanden/"
        "fuerteventura/costa-calma/sbh-monica-beach"
    )
    tab = monica + "?tab=price-calculation-tab#acco-tabs-section"
    best = {
        "subject_instance": {"outcome": "CONFIRMED", "step": 0},
        "board_type": {"outcome": "ALL_INCLUSIVE", "step": 0},
        "detail_link": {"outcome": "VALID_DETAIL_PAGE", "step": 0},
    }
    new_best, path, bound, event = apply_candidate_scope_after_action(
        best_outcomes=best,
        active_candidate_path=None,
        candidate_bound_step=None,
        action_class="CLICK_TEXT",
        target_href=tab,
        page_url_before=monica,
        new_url=tab,
        ok=True,
        surface_before="live_detail",
        preferred_item_links=[{"text": "Prijzen & boeken", "href": tab}],
        decisions=DECISIONS_02,
        next_step=1,
    )
    assert event == "", event
    assert path is None
    assert new_best["board_type"]["outcome"] == "ALL_INCLUSIVE"
    assert new_best["subject_instance"]["outcome"] == "CONFIRMED"
    print("OK test_task02_tab_does_not_reset")


def test_task02_flygo_from_detail_does_not_bind():
    """Fly & Go is ander path maar vanaf live_detail zonder list-bind → geen reset."""
    monica = (
        "https://www.corendon.be/spanje/canarische-eilanden/"
        "fuerteventura/costa-calma/sbh-monica-beach"
    )
    fly = (
        "https://www.corendon.be/spanje/canarische-eilanden/"
        "fuerteventura/costa-calma/fly-go-sbh-monica-beach"
    )
    best = {
        "subject_instance": {"outcome": "CONFIRMED", "step": 0},
        "board_type": {"outcome": "ALL_INCLUSIVE", "step": 0},
    }
    new_best, path, bound, event = apply_candidate_scope_after_action(
        best_outcomes=best,
        active_candidate_path=None,
        candidate_bound_step=None,
        action_class="OPEN_URL",
        target_href=fly,
        page_url_before=monica,
        new_url=fly,
        ok=True,
        surface_before="live_detail",
        preferred_item_links=[{"text": "Bekijk deze Fly & Go vakantie", "href": fly}],
        decisions=DECISIONS_02,
        next_step=1,
    )
    assert event == "", event
    assert path is None
    assert new_best["board_type"]["outcome"] == "ALL_INCLUSIVE"
    print("OK test_task02_flygo_from_detail_does_not_bind")


def test_task01_list_to_detail_satisfying_no_reset():
    """list ALL_INCLUSIVE → OPEN detail: bind, #19-outcomes blijven."""
    list_url = "https://www.corendon.be/kerstvakantie"
    detail = "https://www.corendon.be/egypte/rode-zee/offers/grand-park-lara"
    best = {
        "board_type": {"outcome": "ALL_INCLUSIVE", "step": 0},
        "subject_instance": {"outcome": "CONFIRMED", "step": 0},
    }
    new_best, path, bound, event = apply_candidate_scope_after_action(
        best_outcomes=best,
        active_candidate_path=None,
        candidate_bound_step=None,
        action_class="OPEN_URL",
        target_href=detail,
        page_url_before=list_url,
        new_url=detail,
        ok=True,
        surface_before="list_results",
        preferred_item_links=[{"text": "Grand Park Lara", "href": detail}],
        decisions=DECISIONS_01,
        next_step=1,
    )
    assert event == "bind", event
    assert path == "/egypte/rode-zee/offers/grand-park-lara"
    assert bound == 1
    assert new_best["board_type"]["outcome"] == "ALL_INCLUSIVE"
    print("OK test_task01_list_to_detail_satisfying_no_reset")


def test_switch_rejected_item_to_other_preferred():
    """abs/A REJECT → OPEN abs/B (preferred): reset post-bind, bind B."""
    best = {
        "source_site": {"outcome": "ARXIV", "step": 1},
        "subject_instance": {"outcome": "NOT_RELEVANT", "step": 3},
        "title_extracted": {"outcome": "EXTRACTED", "step": 3},
    }
    href_b = "https://arxiv.org/abs/2601.14696"
    new_best, path, bound, event = apply_candidate_scope_after_action(
        best_outcomes=best,
        active_candidate_path="/abs/2609.19059",
        candidate_bound_step=3,
        action_class="OPEN_URL",
        target_href=href_b,
        page_url_before="https://arxiv.org/search/?q=x",
        new_url=href_b,
        ok=True,
        surface_before="list_results",
        preferred_item_links=[{"text": "arXiv:2601.14696", "href": href_b}],
        decisions=DECISIONS_05,
        next_step=4,
    )
    assert event == "switch", event
    assert path == "/abs/2601.14696"
    assert bound == 4
    assert "source_site" in new_best
    assert "subject_instance" not in new_best
    assert "title_extracted" not in new_best
    print("OK test_switch_rejected_item_to_other_preferred")


def test_html_deepening_same_record_no_unbind():
    best = {
        "subject_instance": {"outcome": "NOT_RELEVANT", "step": 3},
        "source_site": {"outcome": "ARXIV", "step": 1},
    }
    new_best, path, bound, event = apply_candidate_scope_after_action(
        best_outcomes=best,
        active_candidate_path="/abs/2609.19059",
        candidate_bound_step=3,
        action_class="OPEN_URL",
        target_href="https://arxiv.org/html/2609.19059v1",
        page_url_before="https://arxiv.org/abs/2609.19059",
        new_url="https://arxiv.org/html/2609.19059v1",
        ok=True,
        surface_before="list_results",
        preferred_item_links=[],
        decisions=DECISIONS_05,
        next_step=4,
    )
    assert event == "", event
    assert path == "/abs/2609.19059"
    assert new_best["subject_instance"]["outcome"] == "NOT_RELEVANT"
    print("OK test_html_deepening_same_record_no_unbind")


def main():
    test_unbind_after_reject_like_083112Z()
    test_fill_unbinds_bound_candidate()
    test_task02_tab_does_not_reset()
    test_task02_flygo_from_detail_does_not_bind()
    test_task01_list_to_detail_satisfying_no_reset()
    test_switch_rejected_item_to_other_preferred()
    test_html_deepening_same_record_no_unbind()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
