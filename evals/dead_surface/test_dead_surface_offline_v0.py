#!/usr/bin/env python3
"""
Offline tests: H-dead-surface code terminal (Open #29).

Predicate is structural only: fetch_ok AND affordances==0 AND
candidate_units<=1 AND text_chars < DEAD_SURFACE_TEXT_CHARS_MAX
(provisional). No lexicon.

No network, no LLM, no GPU.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidate_units import package_candidate_units  # noqa: E402
from live_offer_state_slice import (  # noqa: E402
    DEAD_SURFACE_STOP_REASON,
    DEAD_SURFACE_TEXT_CHARS_MAX,
    is_dead_surface,
)

EVALS = ROOT / "evals" / "contract_driven"
FIX = ROOT / "evals" / "candidate_offline" / "fixtures_from_traces"
TUI_DIR = EVALS / "20260919T111126Z_tui_package_crete"
BOL_DIR = EVALS / "20260919T131049Z_bol_airpods_pro"

GOLDEN = {
    "01": {
        "result": EVALS
        / "20260916T065415Z_01_web_hotel_package_concrete"
        / "result_01_web_hotel_package_concrete_20260916T065415Z.json",
        "stop_reason": "MAX_ACQUISITION_STEPS",
        "contract_satisfied": False,
    },
    "02": {
        "result": EVALS
        / "20260916T062828Z_02_web_hotel_property_only"
        / "result_02_web_hotel_property_only_20260916T062828Z.json",
        "stop_reason": "CONTRACT_SATISFIED",
        "contract_satisfied": True,
    },
    "05": {
        "result": EVALS
        / "20260918T081459Z_05_web_literature_abstract"
        / "result_05_web_literature_abstract_20260918T081459Z.json",
        "stop_reason": "CONTRACT_SATISFIED",
        "contract_satisfied": True,
    },
    "06": {
        "result": EVALS
        / "20260916T064738Z_06_web_wiki_fact"
        / "result_06_web_wiki_fact_20260916T064738Z.json",
        "stop_reason": "CONTRACT_SATISFIED",
        "contract_satisfied": True,
    },
}


def _units(text: str, aff: list, url: str) -> list:
    return package_candidate_units(
        text=text,
        affordances=aff,
        page_url=url,
        max_units=6,
        max_lines_per_unit=8,
    )


def test_predicate_requires_all_four_clauses():
    assert is_dead_surface(
        fetch_ok=True,
        affordances_count=0,
        candidate_units_count=1,
        text_chars=190,
    )
    assert not is_dead_surface(
        fetch_ok=False,
        affordances_count=0,
        candidate_units_count=1,
        text_chars=190,
    ), "FETCH_FAILED owns empty fetch"
    assert not is_dead_surface(
        fetch_ok=True,
        affordances_count=1,
        candidate_units_count=1,
        text_chars=190,
    )
    assert not is_dead_surface(
        fetch_ok=True,
        affordances_count=0,
        candidate_units_count=0,
        text_chars=DEAD_SURFACE_TEXT_CHARS_MAX,
    ), "at-threshold text is not extremely short"
    assert DEAD_SURFACE_STOP_REASON == "DEAD_SURFACE_NO_CONTENT"
    print("OK test_predicate_requires_all_four_clauses")


def test_negative_sparse_but_real_two_or_three_units():
    """2–3 candidates / units = not dead, even with 0 aff and short text."""
    for n in (2, 3):
        assert not is_dead_surface(
            fetch_ok=True,
            affordances_count=0,
            candidate_units_count=n,
            text_chars=190,
        ), n
    # Task 06 wiki-fact: long text, many units, many aff
    loop = json.loads(
        (
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "loop_06_web_wiki_fact_20260916T064738Z.json"
        ).read_text(encoding="utf-8")
    )
    step0 = (loop.get("steps") or [])[0]
    assert not is_dead_surface(
        fetch_ok=True,
        affordances_count=int(step0.get("affordance_n") or 0),
        candidate_units_count=int(step0.get("candidate_units_n") or 0),
        text_chars=int(step0.get("text_chars") or 0),
    )
    assert int(step0["text_chars"]) > DEAD_SURFACE_TEXT_CHARS_MAX
    assert int(step0["candidate_units_n"]) >= 2
    print("OK test_negative_sparse_but_real_two_or_three_units")


def test_reconstruct_tui_is_dead_before_interpret():
    text = (TUI_DIR / "trace/artifacts/step_000_page_text.txt").read_text(
        encoding="utf-8"
    )
    aff = json.loads(
        (TUI_DIR / "trace/artifacts/step_000_affordances.json").read_text(
            encoding="utf-8"
        )
    )
    units = _units(text, aff, "https://www.tui.nl/")
    dead = is_dead_surface(
        fetch_ok=True,
        affordances_count=len(aff),
        candidate_units_count=len(units),
        text_chars=len(text),
    )
    assert len(aff) == 0, len(aff)
    assert len(units) <= 1, len(units)
    assert len(text) < DEAD_SURFACE_TEXT_CHARS_MAX, len(text)
    assert dead, (len(aff), len(units), len(text))
    print(
        "OK test_reconstruct_tui_is_dead_before_interpret",
        DEAD_SURFACE_STOP_REASON,
        len(text),
    )


def test_reconstruct_bol_does_not_match_stated_predicate():
    """Bol IP-block: 3 global links, 2 units, 1093 chars.

    Catching bol would require units<=2, which collides with the mandatory
    2–3 candidate negative. Cite, do not stretch the predicate.
    """
    text = (BOL_DIR / "trace/artifacts/step_000_page_text.txt").read_text(
        encoding="utf-8"
    )
    aff = json.loads(
        (BOL_DIR / "trace/artifacts/step_000_affordances.json").read_text(
            encoding="utf-8"
        )
    )
    units = _units(text, aff, "https://www.bol.com/")
    dead = is_dead_surface(
        fetch_ok=True,
        affordances_count=len(aff),
        candidate_units_count=len(units),
        text_chars=len(text),
    )
    assert len(aff) == 3, len(aff)
    assert len(units) == 2, len(units)
    assert len(text) == 1093, len(text)
    assert not dead
    print("OK test_reconstruct_bol_does_not_match_stated_predicate")


def test_regression_01_02_05_06_golden_results_and_not_dead():
    for task_id, spec in GOLDEN.items():
        raw = json.loads(spec["result"].read_text(encoding="utf-8"))
        assert raw["stop_reason"] == spec["stop_reason"], (
            task_id,
            raw["stop_reason"],
        )
        assert raw["contract_satisfied"] is spec["contract_satisfied"], task_id
        assert raw["stop_reason"] != DEAD_SURFACE_STOP_REASON
    # Fixtures: 01/02 page extract
    for label, folder, url in (
        (
            "01",
            FIX / "01_price_surface",
            "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir/flamenco-beach-resort",
        ),
        (
            "02",
            FIX / "02_detail",
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma/sbh-monica-beach",
        ),
    ):
        text = (folder / "step_000_page_text.txt").read_text(encoding="utf-8")
        aff = json.loads((folder / "step_000_affordances.json").read_text())
        units = _units(text, aff, url)
        assert not is_dead_surface(
            fetch_ok=True,
            affordances_count=len(aff),
            candidate_units_count=len(units),
            text_chars=len(text),
        ), (label, len(aff), len(units), len(text))
    # 05/06 from live loop step records (already-successful runs)
    for loop_path in (
        EVALS
        / "20260918T081459Z_05_web_literature_abstract"
        / "loop_05_web_literature_abstract_20260918T081459Z.json",
        EVALS
        / "20260916T064738Z_06_web_wiki_fact"
        / "loop_06_web_wiki_fact_20260916T064738Z.json",
    ):
        loop = json.loads(loop_path.read_text(encoding="utf-8"))
        for s in loop.get("steps") or []:
            assert not is_dead_surface(
                fetch_ok=True,
                affordances_count=int(s.get("affordance_n") or 0),
                candidate_units_count=int(s.get("candidate_units_n") or 0),
                text_chars=int(s.get("text_chars") or 0),
            ), (loop_path.name, s.get("step"))
    print("OK test_regression_01_02_05_06_golden_results_and_not_dead")


if __name__ == "__main__":
    test_predicate_requires_all_four_clauses()
    test_negative_sparse_but_real_two_or_three_units()
    test_reconstruct_tui_is_dead_before_interpret()
    test_reconstruct_bol_does_not_match_stated_predicate()
    test_regression_01_02_05_06_golden_results_and_not_dead()
    print("ALL OK dead_surface offline")
