#!/usr/bin/env python3
"""
FIX 2: task entity hint must not become candidate_claim source_text.

Negative: a thin but real page (2–3 short evidence lines, not dead-surface)
plus a task-like entity string that looks like a confirming label.
That string must never enter interpret source_text, even via the sparse
page_text_to_observations safety net.

Entity remains as candidate_id / result.entity for logging.

No network, no LLM, no GPU.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from live_detail_slice import page_text_to_observations  # noqa: E402
from pipeline_offline import channel_allowed  # noqa: E402

EVALS = ROOT / "evals" / "contract_driven"
FIX = ROOT / "evals" / "candidate_offline" / "fixtures_from_traces"

ENTITY = "one concrete bookable"
THIN_TITLE = "Fuerteventura"
THIN_TEXT = """Fuerteventura

Fuerteventura is an island in the Canary Islands.

Population 119,732 (2019).
"""

PACKAGES_DECISION = {
    "id": "subject_instance",
    "allowed_channels": ["candidate_claim"],
}


def _interpret_texts(obs: list[dict]) -> list[str]:
    return [
        str(o.get("text") or "")
        for o in obs
        if o.get("channel") == "candidate_claim"
        and channel_allowed(PACKAGES_DECISION, str(o.get("channel") or ""))
    ]


def test_negative_thin_real_page_entity_never_source_text():
    obs = page_text_to_observations(
        candidate_id=ENTITY,
        url="https://en.wikipedia.org/wiki/Fuerteventura",
        title=THIN_TITLE,
        text=THIN_TEXT,
    )
    assert obs, "thin page still yields page claims"
    assert all(o.get("candidate_id") == ENTITY for o in obs)
    texts = _interpret_texts(obs)
    assert texts, texts
    assert ENTITY not in texts, texts
    assert not any(
        (o.get("provenance") or {}).get("origin") == "entity" for o in obs
    )
    assert THIN_TITLE in texts
    print("OK test_negative_thin_real_page_entity_never_source_text", texts)


def test_regression_01_02_05_06_entity_field_still_in_results():
    """Logging/provenance entity on golden results is unchanged (not this add())."""
    cases = [
        (
            EVALS
            / "20260916T065415Z_01_web_hotel_package_concrete"
            / "result_01_web_hotel_package_concrete_20260916T065415Z.json",
            EVALS
            / "20260916T065415Z_01_web_hotel_package_concrete"
            / "contract_meta_01_web_hotel_package_concrete_20260916T065415Z.json",
        ),
        (
            EVALS
            / "20260916T062828Z_02_web_hotel_property_only"
            / "result_02_web_hotel_property_only_20260916T062828Z.json",
            EVALS
            / "20260916T062828Z_02_web_hotel_property_only"
            / "contract_meta_02_web_hotel_property_only_20260916T062828Z.json",
        ),
        (
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "result_05_web_literature_abstract_20260918T081459Z.json",
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "contract_meta_05_web_literature_abstract_20260918T081459Z.json",
        ),
        (
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "result_06_web_wiki_fact_20260916T064738Z.json",
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "contract_meta_06_web_wiki_fact_20260916T064738Z.json",
        ),
    ]
    for result_path, meta_path in cases:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta.get("entity"), meta_path.name
        # result files store entity on contract_meta / loop, not always top-level
        assert result.get("stop_reason")
        print("  entity still logged", meta_path.name, repr(meta["entity"]))
    # 01/02 fixtures: page claims are page text, origin is never entity
    for folder, url in (
        (
            FIX / "01_price_surface",
            "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir/flamenco-beach-resort",
        ),
        (
            FIX / "02_detail",
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma/sbh-monica-beach",
        ),
    ):
        text = (folder / "step_000_page_text.txt").read_text(encoding="utf-8")
        obs = page_text_to_observations(
            candidate_id="one concrete bookable",
            url=url,
            title="Hotel page",
            text=text[:2000],
        )
        assert not any(
            (o.get("provenance") or {}).get("origin") == "entity" for o in obs
        )
        assert "one concrete bookable" not in _interpret_texts(obs)
    print("OK test_regression_01_02_05_06_entity_field_still_in_results")


if __name__ == "__main__":
    test_negative_thin_real_page_entity_never_source_text()
    test_regression_01_02_05_06_entity_field_still_in_results()
    print("ALL OK entity_not_claim offline")
