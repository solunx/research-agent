#!/usr/bin/env python3
"""
Offline tests for optional --trace-interpret (infra, not an Open item).

Default OFF: run_interpretation return dict is byte-identical; no
step_NNN_interpret_trace.json; events.jsonl unchanged.

Flag ON: reconstruct wiki 165815Z claims → readable per-call rows.

No LLM, no GPU, no live.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidates import Candidate, candidates_to_observations  # noqa: E402
from live_offer_state_slice import save_interpret_trace_artifact  # noqa: E402
from pipeline_offline import run_interpretation  # noqa: E402
from trace_session import TraceSession  # noqa: E402

WIKI = (
    ROOT
    / "evals"
    / "contract_driven"
    / "20260919T165815Z_wiki_brussels_population"
    / "trace"
    / "artifacts"
)

DECISIONS = [
    {
        "id": "population_figure",
        "question": "Is a population figure visible?",
        "outcomes": ["FIGURE_FOUND", "UNKNOWN"],
        "allowed_channels": ["candidate_claim"],
        "required_for_eligibility": ["FIGURE_FOUND"],
    },
    {
        "id": "subject_instance",
        "question": "Is this the subject article?",
        "outcomes": ["NL_ARTICLE", "UNKNOWN"],
        "allowed_channels": ["candidate_claim"],
        "required_for_eligibility": ["NL_ARTICLE"],
    },
]


def _cands_from_json(path: Path) -> list[Candidate]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("candidates") if isinstance(raw, dict) else raw
    fields = set(Candidate.__dataclass_fields__)
    return [Candidate(**{k: v for k, v in row.items() if k in fields}) for row in rows]


def _dump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def test_flag_off_return_dict_unchanged():
    html = _cands_from_json(WIKI / "step_003_candidates.json")
    obs = candidates_to_observations(html)
    a = run_interpretation(observations=obs, decisions=DECISIONS, chat_fn=None)
    b = run_interpretation(
        observations=obs,
        decisions=DECISIONS,
        chat_fn=None,
        interpret_call_trace=None,
    )
    assert _dump(a) == _dump(b)
    sink: list[dict] = []
    c = run_interpretation(
        observations=obs,
        decisions=DECISIONS,
        chat_fn=None,
        interpret_call_trace=sink,
    )
    assert _dump(a) == _dump(c), "side-channel must not change return dict"
    assert sink, "flag-on collector should record calls"
    print(
        "OK test_flag_off_return_dict_unchanged "
        f"calls={len(sink)} keys={sorted(a.keys())}"
    )


def test_save_artifact_off_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        trace = TraceSession(Path(td) / "trace", task_text="t", run_kind="test")
        events_before = (Path(td) / "trace" / "events.jsonl").read_text(encoding="utf-8")
        rel = save_interpret_trace_artifact(
            trace,
            enabled=False,
            step=3,
            url="https://example.test/",
            surface="list_results",
            batch_decisions=False,
            calls=[{"decision_id": "x"}],
        )
        assert rel is None
        art = Path(td) / "trace" / "artifacts" / "step_003_interpret_trace.json"
        assert not art.is_file(), art
        events_after = (Path(td) / "trace" / "events.jsonl").read_text(encoding="utf-8")
        assert events_before == events_after
    print("OK test_save_artifact_off_writes_nothing")


def test_flag_on_wiki_fixture_readable_calls():
    html = _cands_from_json(WIKI / "step_003_candidates.json")
    obs = candidates_to_observations(html)
    # Title row as live loop does.
    obs.insert(
        0,
        {
            "observation_id": "live-title",
            "candidate_id": "Wikipedia",
            "text": "Brussel (stad) - Wikipedia",
            "channel": "candidate_claim",
            "scope": "page_title",
        },
    )
    sink: list[dict] = []
    run_interpretation(
        observations=obs,
        decisions=DECISIONS,
        chat_fn=None,
        interpret_call_trace=sink,
    )
    assert sink, sink
    for row in sink:
        assert "candidate_id" in row
        assert row.get("decision_id") in {"population_figure", "subject_instance"}
        assert "source_text" in row
        assert "source_text_sha256_16" in row
        assert len(row["source_text_sha256_16"]) == 16
        assert row.get("outcome") == "UNKNOWN"  # no chat_fn
        assert row.get("confidence") == "low"
    texts = " ".join(str(r.get("source_text") or "") for r in sink)
    assert "Atomium" in texts or "Manneken" in texts or "Munt" in texts, texts[:400]
    with tempfile.TemporaryDirectory() as td:
        trace = TraceSession(Path(td) / "trace", task_text="wiki", run_kind="test")
        events_before = (Path(td) / "trace" / "events.jsonl").read_text(encoding="utf-8")
        n_events = events_before.count("\n")
        rel = save_interpret_trace_artifact(
            trace,
            enabled=True,
            step=3,
            url="https://nl.wikipedia.org/wiki/Brussel_(stad)",
            surface="list_results",
            batch_decisions=False,
            calls=sink,
        )
        assert rel
        art = Path(td) / "trace" / "artifacts" / "step_003_interpret_trace.json"
        payload = json.loads(art.read_text(encoding="utf-8"))
        assert payload.get("schema") == "interpret-trace-v0"
        assert payload.get("calls")
        assert payload["calls"][0]["decision_id"]
        events_after = (Path(td) / "trace" / "events.jsonl").read_text(encoding="utf-8")
        assert events_after.count("\n") == n_events, "must not append events.jsonl"
    print(
        "OK test_flag_on_wiki_fixture_readable_calls "
        f"n={len(sink)} sample={sink[0]['decision_id']}/{sink[0]['candidate_id']}"
    )


def test_long_source_text_is_truncated_and_hashed():
    long = "x" * 900
    obs = [
        {
            "candidate_id": "c0",
            "text": long,
            "channel": "candidate_claim",
        }
    ]
    sink: list[dict] = []
    run_interpretation(
        observations=obs,
        decisions=DECISIONS[:1],
        chat_fn=None,
        interpret_call_trace=sink,
    )
    assert len(sink) == 1, sink
    row = sink[0]
    assert row["source_text_chars"] == 900
    assert row["source_text"].startswith("x" * 400)
    assert "[+500 chars]" in row["source_text"]
    assert len(row["source_text_sha256_16"]) == 16
    print("OK test_long_source_text_is_truncated_and_hashed")


def main() -> None:
    test_flag_off_return_dict_unchanged()
    test_save_artifact_off_writes_nothing()
    test_flag_on_wiki_fixture_readable_calls()
    test_long_source_text_is_truncated_and_hashed()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
