#!/usr/bin/env python3
"""
Offline tests for Open #26 — candidate-scoped best_outcomes reset.

No browser, no LLM, no GPU. Path 1 (`apply_candidate_scope_after_action`)
and path 2 (`apply_fill_query_round_reset`), including the composed
#25 sequence (bound abs NOT_RELEVANT → FILL) against 083112Z artifacts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from live_offer_state_slice import (  # noqa: E402
    _merge_outcomes,
    apply_candidate_scope_after_action,
    apply_fill_query_round_reset,
)

RESULT_083112Z = (
    ROOT
    / "evals/contract_driven/20260917T083112Z_05_web_literature_abstract"
    / "result_05_web_literature_abstract_20260917T083112Z.json"
)
ABS_083112Z = "https://arxiv.org/abs/2609.19059"
SEARCH_083112Z = (
    "https://arxiv.org/search/?query=large+language+model+agents+tool+use"
)
Q1_083112Z = "large language model agents tool use"
Q2_083112Z = "LLM agents tool use"

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
DECISIONS_06 = [
    {"id": "subject_instance", "required_for_eligibility": ["CONFIRMED"]},
    {"id": "fact_extracted", "required_for_eligibility": ["EXTRACTED"]},
]


def _fp(best: dict) -> str:
    rows = {k: {"outcome": v.get("outcome"), "step": v.get("step")} for k, v in sorted(best.items())}
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


def _step_outcomes_083112Z() -> dict[int, dict[str, str]]:
    raw = json.loads(RESULT_083112Z.read_text(encoding="utf-8"))
    out: dict[int, dict[str, str]] = {}
    for rec in raw["steps_contract_flags"]:
        out[int(rec["step"])] = dict(rec["outcomes"])
    return out


def _bind_abs(*, best: dict, next_step: int):
    """Current-code bind: abs href in preferred_item_links (post-#24b)."""
    return apply_candidate_scope_after_action(
        best_outcomes=best,
        active_candidate_path=None,
        candidate_bound_step=None,
        action_class="OPEN_URL",
        target_href=ABS_083112Z,
        page_url_before=SEARCH_083112Z,
        new_url=ABS_083112Z,
        ok=True,
        surface_before="list_results",
        preferred_item_links=[{"text": "arXiv:2609.19059", "href": ABS_083112Z}],
        decisions=DECISIONS_05,
        next_step=next_step,
    )


def _loop_fill_after_bound(*, best, path, bound_step, next_step: int):
    """Same order as live_offer_state_slice: path 1 then path 2."""
    scoped, new_path, new_bound, ev1 = apply_candidate_scope_after_action(
        best_outcomes=best,
        active_candidate_path=path,
        candidate_bound_step=bound_step,
        action_class="FILL_AND_SUBMIT",
        target_href=None,
        page_url_before=ABS_083112Z,
        new_url="https://arxiv.org/search/?query=LLM+agents+tool+use",
        ok=True,
        surface_before="list_results",
        preferred_item_links=[],
        decisions=DECISIONS_05,
        next_step=next_step,
    )
    final, last_q, last_st, ev2 = apply_fill_query_round_reset(
        best_outcomes=scoped,
        action_class="FILL_AND_SUBMIT",
        query_text=Q2_083112Z,
        last_fill_query_text=Q1_083112Z,
        last_fill_result_step=2,
        next_step=next_step,
        ok=True,
    )
    return scoped, ev1, final, ev2, new_path, last_q, last_st


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


def test_01_02_06_fill_round_trigger_dead_byte_identical():
    """Mandatory negative: 01/02/06 never fire a second FILL — best unchanged."""
    cases = [
        (
            "01",
            {
                "subject_instance": {"outcome": "CONFIRMED", "step": 0},
                "board_type": {"outcome": "ALL_INCLUSIVE", "step": 0},
            },
            "CLICK_TEXT",
            DECISIONS_01,
            "https://www.corendon.be/kerstvakantie",
        ),
        (
            "02",
            {
                "subject_instance": {"outcome": "CONFIRMED", "step": 0},
                "board_type": {"outcome": "ALL_INCLUSIVE", "step": 0},
                "detail_link": {"outcome": "VALID_DETAIL_PAGE", "step": 0},
            },
            "CLICK_TEXT",
            DECISIONS_02,
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma/sbh-monica-beach",
        ),
        (
            "06",
            {
                "subject_instance": {"outcome": "CONFIRMED", "step": 0},
                "fact_extracted": {"outcome": "EXTRACTED", "step": 0},
            },
            "OPEN_URL",
            DECISIONS_06,
            "https://en.wikipedia.org/wiki/Fuerteventura",
        ),
    ]
    for label, best, action, decisions, url in cases:
        before = _fp(best)
        scoped, path, bound, ev = apply_candidate_scope_after_action(
            best_outcomes=best,
            active_candidate_path=None,
            candidate_bound_step=None,
            action_class=action,
            target_href=url,
            page_url_before=url,
            new_url=url,
            ok=True,
            surface_before="live_detail",
            preferred_item_links=[],
            decisions=decisions,
            next_step=1,
        )
        after_scope, last_q, last_st, qev = apply_fill_query_round_reset(
            best_outcomes=scoped,
            action_class=action,
            query_text=None,
            last_fill_query_text=None,
            last_fill_result_step=None,
            next_step=1,
            ok=True,
        )
        assert ev == "", (label, ev)
        assert qev == "", (label, qev)
        assert path is None and bound is None, label
        assert last_q is None and last_st is None, label
        assert _fp(after_scope) == before, (
            f"{label}: best_outcomes changed without a second FILL\n"
            f" before={before}\n after={_fp(after_scope)}"
        )
        print(f"NEG {label} trigger_dead fingerprint_unchanged n_keys={len(after_scope)}")
    print("OK test_01_02_06_fill_round_trigger_dead_byte_identical")


def test_05_fill2_not_relevant_cleared():
    """083112Z: second FILL (different query) must not keep abs NOT_RELEVANT."""
    best = {
        "source_site": {"outcome": "ARXIV", "step": 0},
        "access_status": {"outcome": "OPEN_ACCESS", "step": 2},
        "subject_instance": {"outcome": "NOT_RELEVANT", "step": 3},
        "claim_extracted": {"outcome": "NOT_VISIBLE", "step": 3},
        "title_extracted": {"outcome": "NOT_VISIBLE", "step": 2},
    }
    before = dict(best)
    new_best, last_q, last_st, event = apply_fill_query_round_reset(
        best_outcomes=best,
        action_class="FILL_AND_SUBMIT",
        query_text="LLM agents tool use",
        last_fill_query_text="large language model agents tool use",
        last_fill_result_step=2,
        next_step=5,
        ok=True,
    )
    assert event == "search_round_reset", event
    assert last_q == "llm agents tool use"
    assert last_st == 5
    assert new_best["source_site"]["outcome"] == "ARXIV"
    assert new_best["source_site"]["step"] == 0
    assert "subject_instance" in new_best
    assert new_best["subject_instance"]["outcome"] == "UNKNOWN", new_best["subject_instance"]
    assert new_best["claim_extracted"]["outcome"] == "UNKNOWN"
    assert new_best["title_extracted"]["outcome"] == "UNKNOWN"
    assert new_best["access_status"]["outcome"] == "UNKNOWN"
    assert before["subject_instance"]["outcome"] == "NOT_RELEVANT"
    print(
        "OK test_05_fill2_not_relevant_cleared "
        f"subject={new_best['subject_instance']['outcome']} "
        f"source_site={new_best['source_site']['outcome']}"
    )


def test_05_fill1_only_does_not_wipe():
    """First FILL in a run has no previous query — do not weaken homepage/list labels."""
    best = {
        "source_site": {"outcome": "ARXIV", "step": 0},
        "subject_instance": {"outcome": "NOT_RELEVANT", "step": 0},
    }
    new_best, last_q, last_st, event = apply_fill_query_round_reset(
        best_outcomes=best,
        action_class="FILL_AND_SUBMIT",
        query_text="large language model agents tool use",
        last_fill_query_text=None,
        last_fill_result_step=None,
        next_step=2,
        ok=True,
    )
    assert event == "", event
    assert last_q == "large language model agents tool use"
    assert last_st == 2
    assert _fp(new_best) == _fp(best)
    assert new_best["subject_instance"]["outcome"] == "NOT_RELEVANT"
    print(
        "OK test_05_fill1_only_does_not_wipe "
        f"event={event!r} subject={new_best['subject_instance']['outcome']}"
    )


def test_coolblue_refine_drops_list_pool_keeps_step0():
    """183956Z: FILL q=videokaart after q=rtx 4070 — laptop pool labels weaken."""
    best = {
        "price_scope": {"outcome": "PRICE_INCL_VAT", "step": 0},
        "study_design": {"outcome": "BE_SHOP", "step": 0},
        "availability": {"outcome": "IN_STOCK", "step": 0},
        "vram_amount": {"outcome": "VRAM_NOT_STATED", "step": 0},
        "subject_instance": {"outcome": "OTHER_GPU", "step": 1},
        "detail_link": {"outcome": "CONCRETE_PRODUCT_PAGE", "step": 1},
        "board_type": {"outcome": "UNKNOWN", "step": 0},
    }
    new_best, last_q, last_st, event = apply_fill_query_round_reset(
        best_outcomes=best,
        action_class="FILL_AND_SUBMIT",
        query_text="RTX 4070 videokaart",
        last_fill_query_text="RTX 4070",
        last_fill_result_step=1,
        next_step=2,
        ok=True,
    )
    assert event == "search_round_reset", event
    assert new_best["detail_link"]["outcome"] == "UNKNOWN", new_best["detail_link"]
    assert new_best["subject_instance"]["outcome"] == "UNKNOWN", new_best["subject_instance"]
    assert new_best["price_scope"]["outcome"] == "PRICE_INCL_VAT"
    assert new_best["study_design"]["outcome"] == "BE_SHOP"
    assert new_best["availability"]["outcome"] == "IN_STOCK"
    assert last_q == "rtx 4070 videokaart"
    print(
        "OK test_coolblue_refine_drops_list_pool_keeps_step0 "
        f"detail_link={new_best['detail_link']['outcome']} "
        f"subject={new_best['subject_instance']['outcome']} "
        f"price_scope={new_best['price_scope']['outcome']} "
        f"study_design={new_best['study_design']['outcome']}"
    )


def test_reset_keeps_decision_keys_as_unknown_on_empty_pool():
    """Fifth: chrome-only refine must leave detail_link present as UNKNOWN, not deleted."""
    best = {
        "price_scope": {"outcome": "PRICE_INCL_VAT", "step": 0},
        "detail_link": {"outcome": "CONCRETE_PRODUCT_PAGE", "step": 1},
        "subject_instance": {"outcome": "OTHER_GPU", "step": 1},
    }
    new_best, _, _, event = apply_fill_query_round_reset(
        best_outcomes=best,
        action_class="FILL_AND_SUBMIT",
        query_text="RTX 4070 Super",
        last_fill_query_text="RTX 4070 videokaart",
        last_fill_result_step=1,
        next_step=3,
        ok=True,
    )
    assert event == "search_round_reset", event
    assert "detail_link" in new_best, list(new_best)
    assert "subject_instance" in new_best, list(new_best)
    assert new_best["detail_link"]["outcome"] == "UNKNOWN"
    assert new_best["subject_instance"]["outcome"] == "UNKNOWN"
    assert set(new_best) == set(best)
    # Empty/chrome interpret writes UNKNOWN → merge must still see a gap key.
    from live_offer_state_slice import _merge_outcomes

    merged = _merge_outcomes(
        new_best,
        {"detail_link": "UNKNOWN", "subject_instance": "UNKNOWN"},
        3,
    )
    assert merged["detail_link"]["outcome"] == "UNKNOWN"
    assert "detail_link" in merged
    print(
        "OK test_reset_keeps_decision_keys_as_unknown_on_empty_pool "
        f"keys={sorted(new_best)} detail_link={merged['detail_link']['outcome']}"
    )


def test_083112Z_canonical_bound_reject_then_fill_path1_then_path2():
    """#25 under path 2: abs NOT_RELEVANT recorded at bind-step, then new FILL.

    Homepage labels left UNKNOWN so merge writes the abs reject at step 3
    (the existing unbind tests). Loop order = path 1 then path 2.
    """
    steps = _step_outcomes_083112Z()
    best: dict = {}
    for st in (0, 1, 2):
        oc = dict(steps[st])
        if st == 0:
            oc["subject_instance"] = "UNKNOWN"
            oc["title_extracted"] = "UNKNOWN"
            oc["claim_extracted"] = "UNKNOWN"
            oc["url_extracted"] = "UNKNOWN"
        best = _merge_outcomes(best, oc, st)
    best, path, bound, bev = _bind_abs(best=best, next_step=3)
    assert bev == "bind" and path == "/abs/2609.19059" and bound == 3
    best = _merge_outcomes(best, steps[3], 3)
    assert best["subject_instance"] == {"outcome": "NOT_RELEVANT", "step": 3}
    assert best["access_status"]["outcome"] == "OPEN_ACCESS"
    assert best["recency"]["outcome"] == "IN_RANGE"
    assert best["year_venue_extracted"]["outcome"] == "EXTRACTED"
    assert best["source_site"] == {"outcome": "ARXIV", "step": 2}

    after1, ev1, after2, ev2, new_path, last_q, last_st = _loop_fill_after_bound(
        best=best, path=path, bound_step=bound, next_step=4
    )
    assert ev1 == "unbind", ev1
    assert new_path is None
    assert "subject_instance" not in after1
    assert "access_status" not in after1
    assert "recency" not in after1
    assert "year_venue_extracted" not in after1
    assert after1["source_site"] == {"outcome": "ARXIV", "step": 2}

    assert ev2 == "search_round_reset", ev2
    assert last_q == "llm agents tool use" and last_st == 4
    assert "subject_instance" not in after2
    assert "access_status" not in after2
    assert after2["source_site"]["outcome"] == "UNKNOWN"
    print(
        "OK test_083112Z_canonical_bound_reject_then_fill_path1_then_path2 "
        f"path1={ev1} path2={ev2} subject_absent={('subject_instance' not in after2)} "
        f"source_site={after2['source_site']['outcome']}"
    )


def test_083112Z_exact_merge_homepage_not_relevant_survives_unbind():
    """Measurement, not a pass-criterion for #25.

    Raw 083112Z steps: homepage subject_instance=NOT_RELEVANT (step 0) and
    abs the same label. _merge_outcomes does not bump step on equal concrete
    strings, so unbind (drop step>=3) and path 2 (weaken step>=2) leave it.
    Path 2 did not cause this; do not patch _merge_outcomes here.
    """
    steps = _step_outcomes_083112Z()
    assert steps[0]["subject_instance"] == "NOT_RELEVANT"
    assert steps[3]["subject_instance"] == "NOT_RELEVANT"
    best: dict = {}
    for st in (0, 1, 2):
        best = _merge_outcomes(best, steps[st], st)
    best, path, bound, bev = _bind_abs(best=best, next_step=3)
    assert bev == "bind"
    best = _merge_outcomes(best, steps[3], 3)
    assert best["subject_instance"] == {"outcome": "NOT_RELEVANT", "step": 0}, best[
        "subject_instance"
    ]
    after1, ev1, after2, ev2, _, _, _ = _loop_fill_after_bound(
        best=best, path=path, bound_step=bound, next_step=4
    )
    assert ev1 == "unbind"
    assert ev2 == "search_round_reset"
    assert after1["subject_instance"] == {"outcome": "NOT_RELEVANT", "step": 0}
    assert after2["subject_instance"] == {"outcome": "NOT_RELEVANT", "step": 0}
    assert "access_status" not in after1 and "recency" not in after1
    assert after1["source_site"]["outcome"] == "ARXIV"
    assert after2["source_site"]["outcome"] == "UNKNOWN"
    print(
        "OK test_083112Z_exact_merge_homepage_not_relevant_survives_unbind "
        f"subject_step={after2['subject_instance']['step']} "
        f"path1_dropped_abs_labels={('access_status' not in after1)}"
    )


SNAPSHOT_083112Z_AFTER_PATH1_PATH2 = (
    '{"authors_extracted": {"outcome": "UNKNOWN", "step": 4}, '
    '"claim_extracted": {"outcome": "NOT_VISIBLE", "step": 0}, '
    '"source_site": {"outcome": "UNKNOWN", "step": 4}, '
    '"subject_instance": {"outcome": "NOT_RELEVANT", "step": 0}, '
    '"title_extracted": {"outcome": "NOT_VISIBLE", "step": 0}, '
    '"url_extracted": {"outcome": "NOT_VISIBLE", "step": 0}}'
)


def test_known_current_behavior_not_correctness_083112Z_merge_step_stamp():
    """known-current-behavior test, niet een correctness-test.

    Pins the 083112Z merge+unbind+path-2 result as a baseline snapshot.
    Homepage subject_instance=NOT_RELEVANT at step=0, abs the same string
    at step=3, bind, unbind, then path-2 weaken. Current _merge_outcomes
    does not bump step on a repeated concrete label, so step=0 survives
    both resets. A future merge-step fix MUST fail this test on purpose
    (snapshot diff), not silently. Do not treat a green run as "the
    discrepancy is gone" unless the snapshot was deliberately rewritten.
    """
    steps = _step_outcomes_083112Z()
    assert steps[0]["subject_instance"] == "NOT_RELEVANT"
    assert steps[3]["subject_instance"] == "NOT_RELEVANT"
    best: dict = {}
    for st in (0, 1, 2):
        best = _merge_outcomes(best, steps[st], st)
    best, path, bound, bev = _bind_abs(best=best, next_step=3)
    assert bev == "bind"
    best = _merge_outcomes(best, steps[3], 3)
    after1, ev1, after2, ev2, _, _, _ = _loop_fill_after_bound(
        best=best, path=path, bound_step=bound, next_step=4
    )
    assert ev1 == "unbind" and ev2 == "search_round_reset"
    got = _fp(after2)
    assert got == SNAPSHOT_083112Z_AFTER_PATH1_PATH2, (
        "known-current-behavior snapshot changed — if this is an intentional "
        "merge/reset fix, rewrite SNAPSHOT_083112Z_AFTER_PATH1_PATH2; "
        f"got={got}"
    )
    print(
        "OK test_known_current_behavior_not_correctness_083112Z_merge_step_stamp "
        f"snapshot={got}"
    )


def test_083112Z_step0_site_label_survives_composed_fill():
    """(b) Path 2 must not wipe a pre-search-round confirming label."""
    best = {
        "source_site": {"outcome": "ARXIV", "step": 0},
        "subject_instance": {"outcome": "NOT_RELEVANT", "step": 3},
        "access_status": {"outcome": "OPEN_ACCESS", "step": 3},
        "title_extracted": {"outcome": "NOT_VISIBLE", "step": 2},
    }
    after1, ev1, after2, ev2, new_path, _, _ = _loop_fill_after_bound(
        best=best,
        path="/abs/2609.19059",
        bound_step=3,
        next_step=4,
    )
    assert ev1 == "unbind" and ev2 == "search_round_reset"
    assert new_path is None
    assert "subject_instance" not in after1
    assert "subject_instance" not in after2
    assert after1["source_site"] == {"outcome": "ARXIV", "step": 0}
    assert after2["source_site"] == {"outcome": "ARXIV", "step": 0}
    assert after2["title_extracted"]["outcome"] == "UNKNOWN"
    print(
        "OK test_083112Z_step0_site_label_survives_composed_fill "
        f"source_site={after2['source_site']['outcome']} "
        f"title={after2['title_extracted']['outcome']}"
    )


def main():
    test_unbind_after_reject_like_083112Z()
    test_fill_unbinds_bound_candidate()
    test_task02_tab_does_not_reset()
    test_task02_flygo_from_detail_does_not_bind()
    test_task01_list_to_detail_satisfying_no_reset()
    test_switch_rejected_item_to_other_preferred()
    test_html_deepening_same_record_no_unbind()
    test_01_02_06_fill_round_trigger_dead_byte_identical()
    test_05_fill2_not_relevant_cleared()
    test_05_fill1_only_does_not_wipe()
    test_coolblue_refine_drops_list_pool_keeps_step0()
    test_reset_keeps_decision_keys_as_unknown_on_empty_pool()
    test_083112Z_canonical_bound_reject_then_fill_path1_then_path2()
    test_083112Z_exact_merge_homepage_not_relevant_survives_unbind()
    test_known_current_behavior_not_correctness_083112Z_merge_step_stamp()
    test_083112Z_step0_site_label_survives_composed_fill()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
