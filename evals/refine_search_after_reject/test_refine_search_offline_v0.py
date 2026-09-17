#!/usr/bin/env python3
"""
Offline tests: refine-search hint after current-page object rejection.

Diagnosis (run 20260917T072448Z, raw loop): after subject_instance=NOT_RELEVANT
on https://arxiv.org/abs/2609.19059 the planner chose Related Papers / HTML /
Back to Abstract — never FILL_AND_SUBMIT with a new query.

No network, no LLM, no GPU. Mock chat_fn + capture of the planner payload.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evidence_acquisition import (  # noqa: E402
    action_fingerprint,
    acquisition_decide,
    object_rejected_on_current_page,
    should_hint_refine_search,
)

ABS_URL = "https://arxiv.org/abs/2609.19059"
SEARCH_URL = "https://arxiv.org/search/"

INPUT_AFF = {
    "kind": "input_field",
    "text": "Search papers...",
    "href": "",
    "scope": "local",
    "tag": "input",
    "type": "search",
    "name": "query",
    "id": "query",
    "placeholder": "Search papers...",
}
RELATED_AFF = {
    "kind": "link",
    "text": "Related Papers",
    "href": "https://arxiv.org/abs/2609.19059#related",
    "scope": "local",
    "role": "link",
}

GAPS_FAIL = [
    {
        "decision_id": "subject_instance",
        "result": "FAIL",
        "observed": "NOT_RELEVANT",
        "allowed": ["RELEVANT"],
    }
]
PAGE_REJECT = {"subject_instance": "NOT_RELEVANT", "claim_extracted": "NOT_VISIBLE"}


def _payload_from_messages(messages):
    for m in messages:
        if m.get("role") == "user":
            return json.loads(m["content"])
    raise AssertionError("no user message")


def test_reject_helper_not_absence():
    assert object_rejected_on_current_page(PAGE_REJECT, GAPS_FAIL) == {
        "decision_id": "subject_instance",
        "observed": "NOT_RELEVANT",
    }
    # Absence FAIL must not count as object rejection
    gaps_abs = [
        {
            "decision_id": "claim_extracted",
            "result": "FAIL",
            "observed": "NOT_VISIBLE",
            "allowed": ["EXTRACTED"],
        }
    ]
    page_abs = {"claim_extracted": "NOT_VISIBLE", "subject_instance": "UNKNOWN"}
    assert object_rejected_on_current_page(page_abs, gaps_abs) is None
    print("OK test_reject_helper_not_absence")


def test_hint_requires_list_results_history():
    assert (
        should_hint_refine_search(
            current_page_outcomes=PAGE_REJECT,
            gaps=GAPS_FAIL,
            surfaces_seen=["live_detail"],
        )
        is None
    )
    assert should_hint_refine_search(
        current_page_outcomes=PAGE_REJECT,
        gaps=GAPS_FAIL,
        surfaces_seen=["live_detail", "list_results"],
    ) == {"decision_id": "subject_instance", "observed": "NOT_RELEVANT"}
    print("OK test_hint_requires_list_results_history")


def test_decide_payload_and_refined_fill_allowed():
    """Citaat-equivalent van stap 3 run 20260917T072448Z: NOT_RELEVANT + prior list."""
    captured = {}

    def chat_fn(messages):
        captured["user"] = _payload_from_messages(messages)
        captured["system"] = messages[0]["content"]
        return json.dumps(
            {
                "action_class": "FILL_AND_SUBMIT",
                "target_text": "Search papers...",
                "query_text": "LLM tool-using agents 2024",
                "for_decision_ids": ["subject_instance"],
                "reason": "this paper is NOT_RELEVANT; refine search",
            }
        )

    prior_fill = action_fingerprint(
        {
            "action_class": "FILL_AND_SUBMIT",
            "target_text": "Search papers...",
            "target_id": "query",
            "query_text": "large language model agents tool use",
        },
        page_url=ABS_URL,
    )
    decision = acquisition_decide(
        gaps=GAPS_FAIL,
        affordances=[INPUT_AFF, RELATED_AFF],
        page_url=ABS_URL,
        page_title="MIRAGE",
        claim_preview=[],
        task_text="Find a recent paper on LLM agents / tool use.",
        chat_fn=chat_fn,
        step_index=3,
        max_steps=6,
        blocked_action_keys=[prior_fill],
        preferred_item_links=[{"text": "Related Papers", "href": RELATED_AFF["href"]}],
        current_page_outcomes=PAGE_REJECT,
        surfaces_seen=["live_detail", "list_results"],
    )
    user = captured["user"]
    assert user["refine_search_after_reject"] is True, user
    assert user["page_object_rejected"]["observed"] == "NOT_RELEVANT", user
    assert "rejected" in captured["system"].lower() or "NOT_RELEVANT" in captured["system"]
    assert "do not keep clicking" in captured["system"].lower() or "Do NOT keep clicking" in captured["system"]
    assert decision.get("action_class") == "FILL_AND_SUBMIT", decision
    assert decision.get("query_text") == "LLM tool-using agents 2024", decision
    print("OK test_decide_payload_and_refined_fill_allowed")


def test_identical_query_still_blocked():
    """Negatieve test:zelfde query_text + zelfde veld blijft no_progress_repeat_blocked."""
    blocked_fp = action_fingerprint(
        {
            "action_class": "FILL_AND_SUBMIT",
            "target_text": "Search papers...",
            "target_id": "query",
            "query_text": "large language model agents tool use",
        },
        page_url=ABS_URL,
    )

    def chat_fn(messages):
        return json.dumps(
            {
                "action_class": "FILL_AND_SUBMIT",
                "target_text": "Search papers...",
                "query_text": "large language model agents tool use",
                "for_decision_ids": ["subject_instance"],
                "reason": "retry same query",
            }
        )

    decision = acquisition_decide(
        gaps=GAPS_FAIL,
        affordances=[INPUT_AFF],
        page_url=ABS_URL,
        page_title="MIRAGE",
        claim_preview=[],
        task_text="Find LLM agent papers",
        chat_fn=chat_fn,
        step_index=3,
        max_steps=6,
        blocked_action_keys=[blocked_fp],
        current_page_outcomes=PAGE_REJECT,
        surfaces_seen=["list_results"],
    )
    assert decision.get("action_class") == "STOP", decision
    assert decision.get("reason") == "no_progress_repeat_blocked", decision
    print("OK test_identical_query_still_blocked")


def test_no_hint_without_reject_keeps_stay_on_entity():
    """Zonder reject geen refine-flag — bestaande stay-on-entity voorkeur blijft."""
    captured = {}

    def chat_fn(messages):
        captured["user"] = _payload_from_messages(messages)
        captured["system"] = messages[0]["content"]
        return json.dumps(
            {
                "action_class": "CLICK_TEXT",
                "target_text": "Related Papers",
                "for_decision_ids": ["claim_extracted"],
                "reason": "deepen",
            }
        )

    gaps = [
        {
            "decision_id": "claim_extracted",
            "result": "FAIL",
            "observed": "NOT_VISIBLE",
            "allowed": ["EXTRACTED"],
        }
    ]
    decision = acquisition_decide(
        gaps=gaps,
        affordances=[INPUT_AFF, RELATED_AFF],
        page_url=ABS_URL,
        page_title="MIRAGE",
        claim_preview=[],
        task_text="Find LLM agent papers",
        chat_fn=chat_fn,
        step_index=3,
        max_steps=6,
        current_page_outcomes={
            "subject_instance": "UNKNOWN",
            "claim_extracted": "NOT_VISIBLE",
        },
        surfaces_seen=["list_results"],
    )
    user = captured["user"]
    assert user["refine_search_after_reject"] is False, user
    assert "stay on the current entity" in captured["system"]
    assert decision.get("action_class") == "CLICK_TEXT", decision
    print("OK test_no_hint_without_reject_keeps_stay_on_entity")


def main():
    test_reject_helper_not_absence()
    test_hint_requires_list_results_history()
    test_decide_payload_and_refined_fill_allowed()
    test_identical_query_still_blocked()
    test_no_hint_without_reject_keeps_stay_on_entity()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
