#!/usr/bin/env python3
"""
Offline unit tests for FILL_AND_SUBMIT + input_field affordance path.

No live network. Uses:
  - pure Python checks for fingerprint / decide validation
  - local HTML fixture + Playwright for execute path
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evidence_acquisition import (
    ACTION_CLASSES,
    action_fingerprint,
    acquisition_decide,
    execute_acquisition_action,
    filter_safe_affordances,
)


FIXTURE_HTML = Path(__file__).resolve().parent / "search_page.html"


def test_action_classes_contains_fill():
    assert "FILL_AND_SUBMIT" in ACTION_CLASSES
    print("OK test_action_classes_contains_fill")


def test_fingerprint_includes_query():
    d1 = {
        "action_class": "FILL_AND_SUBMIT",
        "target_text": "Search papers...",
        "target_id": "query",
        "query_text": "LLM agent",
    }
    d2 = {
        "action_class": "FILL_AND_SUBMIT",
        "target_text": "Search papers...",
        "target_id": "query",
        "query_text": "LLM agent",
    }
    d3 = {
        "action_class": "FILL_AND_SUBMIT",
        "target_text": "Search papers...",
        "target_id": "query",
        "query_text": "transformer agents",  # different query
    }
    fp1 = action_fingerprint(d1, page_url="https://arxiv.org/")
    fp2 = action_fingerprint(d2, page_url="https://arxiv.org/")
    fp3 = action_fingerprint(d3, page_url="https://arxiv.org/")
    assert fp1 == fp2, f"same query must fingerprint equal: {fp1!r} vs {fp2!r}"
    assert fp1 != fp3, f"different query must fingerprint differ: {fp1!r} vs {fp3!r}"
    assert "q=llm agent" in fp1
    assert "query" in fp1  # target_id included
    print(f"OK test_fingerprint_includes_query fp1={fp1} fp3={fp3}")


def test_decide_fill_with_mock_llm():
    """Mock chat_fn returns FILL_AND_SUBMIT; code must accept and keep query_text."""
    mock_affs = [
        {
            "kind": "input_field",
            "text": "Search papers...",
            "href": "",
            "role": "search",
            "scope": "local",
            "tag": "input",
            "type": "search",
            "name": "query",
            "id": "query",
            "placeholder": "Search papers...",
            "aria_label": "Search papers",
        },
        {
            "kind": "button",
            "text": "Search",
            "href": "",
            "role": "button",
            "scope": "local",
        },
    ]
    gaps = [{"decision_id": "subject_instance", "result": "UNKNOWN"}]

    def chat_fn(messages):
        return json.dumps(
            {
                "action_class": "FILL_AND_SUBMIT",
                "target_text": "Search papers...",
                "query_text": "LLM agent architecture",
                "for_decision_ids": ["subject_instance"],
                "reason": "need search results for subject",
            }
        )

    decision = acquisition_decide(
        gaps=gaps,
        affordances=mock_affs,
        page_url="https://arxiv.org/",
        page_title="arXiv",
        claim_preview=[],
        task_text="Find LLM agent papers on arXiv",
        chat_fn=chat_fn,
        step_index=0,
        max_steps=4,
        blocked_action_keys=[],
    )
    assert decision.get("action_class") == "FILL_AND_SUBMIT", decision
    assert decision.get("query_text") == "LLM agent architecture", decision
    assert decision.get("target_id") == "query", decision
    assert decision.get("target_name") == "query", decision
    assert "action_key" in decision
    print(f"OK test_decide_fill_with_mock_llm decision={json.dumps(decision, ensure_ascii=False)[:300]}")


def test_decide_blocks_same_query_repeat():
    mock_affs = [
        {
            "kind": "input_field",
            "text": "Search papers...",
            "scope": "local",
            "tag": "input",
            "type": "search",
            "name": "query",
            "id": "query",
            "placeholder": "Search papers...",
        },
    ]
    gaps = [{"decision_id": "subject_instance", "result": "UNKNOWN"}]
    blocked_fp = action_fingerprint(
        {
            "action_class": "FILL_AND_SUBMIT",
            "target_text": "Search papers...",
            "target_id": "query",
            "query_text": "LLM agent",
        },
        page_url="https://arxiv.org/",
    )

    def chat_fn(messages):
        return json.dumps(
            {
                "action_class": "FILL_AND_SUBMIT",
                "target_text": "Search papers...",
                "query_text": "LLM agent",
                "for_decision_ids": ["subject_instance"],
                "reason": "retry same",
            }
        )

    decision = acquisition_decide(
        gaps=gaps,
        affordances=mock_affs,
        page_url="https://arxiv.org/",
        page_title="arXiv",
        claim_preview=[],
        task_text="Find LLM agent papers",
        chat_fn=chat_fn,
        step_index=1,
        max_steps=4,
        blocked_action_keys=[blocked_fp],
    )
    assert decision.get("action_class") == "STOP", decision
    assert decision.get("reason") == "no_progress_repeat_blocked", decision
    print("OK test_decide_blocks_same_query_repeat")


def test_decide_allows_different_query():
    mock_affs = [
        {
            "kind": "input_field",
            "text": "Search papers...",
            "scope": "local",
            "tag": "input",
            "type": "search",
            "name": "query",
            "id": "query",
            "placeholder": "Search papers...",
        },
    ]
    gaps = [{"decision_id": "subject_instance", "result": "UNKNOWN"}]
    blocked_fp = action_fingerprint(
        {
            "action_class": "FILL_AND_SUBMIT",
            "target_text": "Search papers...",
            "target_id": "query",
            "query_text": "LLM agent",
        },
        page_url="https://arxiv.org/",
    )

    def chat_fn(messages):
        return json.dumps(
            {
                "action_class": "FILL_AND_SUBMIT",
                "target_text": "Search papers...",
                "query_text": "multi-agent LLM systems",  # refined
                "for_decision_ids": ["subject_instance"],
                "reason": "refine query",
            }
        )

    decision = acquisition_decide(
        gaps=gaps,
        affordances=mock_affs,
        page_url="https://arxiv.org/",
        page_title="arXiv",
        claim_preview=[],
        task_text="Find LLM agent papers",
        chat_fn=chat_fn,
        step_index=1,
        max_steps=4,
        blocked_action_keys=[blocked_fp],
    )
    assert decision.get("action_class") == "FILL_AND_SUBMIT", decision
    assert decision.get("query_text") == "multi-agent LLM systems", decision
    print("OK test_decide_allows_different_query")


def test_decide_rejects_missing_query_text():
    mock_affs = [
        {
            "kind": "input_field",
            "text": "Search papers...",
            "scope": "local",
            "id": "query",
            "type": "search",
        },
    ]
    gaps = [{"decision_id": "x", "result": "UNKNOWN"}]

    def chat_fn(messages):
        return json.dumps(
            {
                "action_class": "FILL_AND_SUBMIT",
                "target_text": "Search papers...",
                # no query_text
                "reason": "oops",
            }
        )

    decision = acquisition_decide(
        gaps=gaps,
        affordances=mock_affs,
        page_url="https://arxiv.org/",
        page_title="arXiv",
        claim_preview=[],
        task_text="task",
        chat_fn=chat_fn,
        step_index=0,
        max_steps=4,
    )
    assert decision.get("action_class") == "STOP", decision
    assert decision.get("reason") == "fill_missing_query_text", decision
    print("OK test_decide_rejects_missing_query_text")


def test_filter_passes_input_metadata():
    affs = [
        {
            "kind": "input_field",
            "text": "Search...",
            "href": "",
            "scope": "local",
            "tag": "input",
            "type": "search",
            "name": "q",
            "id": "search-box",
            "placeholder": "Search...",
        }
    ]
    safe = filter_safe_affordances(affs)
    assert len(safe) == 1
    assert safe[0]["kind"] == "input_field"
    assert safe[0]["id"] == "search-box"
    assert safe[0]["name"] == "q"
    assert safe[0]["type"] == "search"
    print("OK test_filter_passes_input_metadata")


def test_execute_fill_on_local_html():
    """Open local HTML fixture, FILL_AND_SUBMIT, assert results text appears."""
    if not FIXTURE_HTML.is_file():
        print("SKIP test_execute_fill_on_local_html (fixture missing)")
        return
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP test_execute_fill_on_local_html (playwright not installed in this env)")
        return
    from browser import browser_open, browser_list_affordances

    url = FIXTURE_HTML.as_uri()
    snap = browser_open(url, wait_seconds=0.5, max_chars=4000)
    if snap.get("error") and "playwright" in str(snap.get("error")).lower():
        print(f"SKIP test_execute_fill_on_local_html ({snap.get('error')})")
        return
    assert snap.get("ok") or "Literature Search" in str(snap.get("text") or ""), snap

    aff = browser_list_affordances(max_items=20)
    assert aff.get("ok"), aff
    inputs = [a for a in aff.get("affordances") or [] if a.get("kind") == "input_field"]
    assert inputs, f"expected input_field in affordances, got: {aff.get('affordances')}"
    print(f"  input_field affordances: {json.dumps(inputs, ensure_ascii=False)}")

    decision = {
        "action_class": "FILL_AND_SUBMIT",
        "target_text": inputs[0].get("text") or "Search papers...",
        "target_id": inputs[0].get("id") or "query",
        "target_name": inputs[0].get("name") or "query",
        "target_type": inputs[0].get("type") or "search",
        "query_text": "LLM agent",
    }
    result = execute_acquisition_action(decision, max_chars=4000)
    print(f"  execute result ok={result.get('ok')} query={result.get('query_text')} sel={result.get('filled_selector')}")
    text = str(result.get("text") or "")
    assert result.get("ok"), result
    assert "RESULTS_FOR:LLM agent" in text or "LLM agent" in text, text[:500]
    print("OK test_execute_fill_on_local_html")


def main():
    test_action_classes_contains_fill()
    test_fingerprint_includes_query()
    test_filter_passes_input_metadata()
    test_decide_fill_with_mock_llm()
    test_decide_blocks_same_query_repeat()
    test_decide_allows_different_query()
    test_decide_rejects_missing_query_text()
    test_execute_fill_on_local_html()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
