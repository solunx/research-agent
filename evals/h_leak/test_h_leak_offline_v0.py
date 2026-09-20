#!/usr/bin/env python3
"""
H-leak diagnosis (campaign 1 TUI `20260919T111126Z`).

Where `"one concrete bookable"` enters interpretation: not the contract
question, but task.md first `**bold**` → extract_entity_hint → entity →
page_text_to_observations origin=entity claim (fixed: that add() is removed).

No network, no LLM, no GPU.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from interpretation import build_user_prompt, interpret_observation  # noqa: E402
from live_detail_slice import page_text_to_observations  # noqa: E402

_cd_path = ROOT / "scripts" / "run_contract_driven_task_v0.py"
_cd_spec = importlib.util.spec_from_file_location("run_contract_driven_task_v0", _cd_path)
assert _cd_spec and _cd_spec.loader
_cd = importlib.util.module_from_spec(_cd_spec)
_cd_spec.loader.exec_module(_cd)
extract_entity_hint = _cd.extract_entity_hint
load_frozen_contract = _cd.load_frozen_contract

TASK = ROOT / "tasks/campaign1_generaliteit/tui_package_crete.md"
CONTRACT = (
    ROOT
    / "evals/contract_synthesis/20260919T110338Z_synthesis"
    / "contract_tui_package_crete_20260919T110338Z.json"
)
PAGE = (
    ROOT
    / "evals/contract_driven/20260919T111126Z_tui_package_crete"
    / "trace/artifacts/step_000_page_text.txt"
)
PHRASE = "one concrete bookable"
ACCESS_DENIED = (
    "Access Denied\n"
    'You don\'t have permission to access "http://www.tui.nl/" on this server.'
)


def test_phrase_comes_from_task_bold_not_decision_question():
    task = TASK.read_text(encoding="utf-8")
    assert f"**{PHRASE}**" in task
    entity = extract_entity_hint(task, "tui_package_crete")
    assert entity == PHRASE

    contract = load_frozen_contract(CONTRACT)
    si = next(d for d in contract["decisions"] if d["id"] == "subject_instance")
    assert PHRASE not in str(si.get("question") or "")
    assert "bookable package" in str(si.get("question") or "").lower()
    subj = json.dumps(contract.get("subject") or {}).lower()
    assert PHRASE in subj
    print("OK test_phrase_comes_from_task_bold_not_decision_question", entity)


def test_build_user_prompt_does_not_inject_phrase_from_decision():
    contract = load_frozen_contract(CONTRACT)
    si = next(d for d in contract["decisions"] if d["id"] == "subject_instance")
    empty = build_user_prompt(si, "")
    denied = build_user_prompt(si, ACCESS_DENIED)
    entity = build_user_prompt(si, PHRASE)
    assert PHRASE not in empty
    assert PHRASE not in denied
    assert PHRASE in entity
    payload = json.loads(denied)
    assert payload["decision"]["question"].startswith("Is the page a specific bookable package")
    assert payload["observation"]["source_text"] == ACCESS_DENIED
    print("OK test_build_user_prompt_does_not_inject_phrase_from_decision")


def test_page_text_to_observations_does_not_inject_entity_as_claim():
    page = PAGE.read_text(encoding="utf-8")
    obs = page_text_to_observations(
        candidate_id=PHRASE,
        url="https://www.tui.nl/",
        title="Access Denied",
        text=page,
    )
    identity = [
        o
        for o in obs
        if (o.get("provenance") or {}).get("origin") == "entity"
        or o.get("text") == PHRASE
    ]
    assert not identity, [o.get("text") for o in obs]
    assert all(o.get("candidate_id") == PHRASE for o in obs)
    print("OK test_page_text_to_observations_does_not_inject_entity_as_claim", len(obs))


def test_interpret_without_llm_is_unknown():
    contract = load_frozen_contract(CONTRACT)
    si = next(d for d in contract["decisions"] if d["id"] == "subject_instance")
    for src in ("", ACCESS_DENIED, PHRASE):
        ir = interpret_observation(src, contract_decision=si, chat_fn=None)
        assert ir.outcome == "UNKNOWN"
        assert ir.source == "heuristic_stub"
    print("OK test_interpret_without_llm_is_unknown")


if __name__ == "__main__":
    test_phrase_comes_from_task_bold_not_decision_question()
    test_build_user_prompt_does_not_inject_phrase_from_decision()
    test_page_text_to_observations_does_not_inject_entity_as_claim()
    test_interpret_without_llm_is_unknown()
    print("ALL OK h_leak offline")
