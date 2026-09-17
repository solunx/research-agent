#!/usr/bin/env python3
"""
Offline tests for Open #27 — long innerText lines must not be dropped,
and the observation mapping must not recap independently of extract.

No browser, no LLM, no GPU.

Live budget (Open #6, live_offer_state_slice extract_candidates):
  max_candidates=3, max_units=6.
Open #27 may splice one extra long-text candidate after that rank, so
len(selected) can be 4. Live observations must use that selected list
without a second hardcoded cap (20260917T102344Z dropped c3).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidate_units import package_candidate_units, units_to_observations  # noqa: E402
from candidates import (  # noqa: E402
    Candidate,
    extract_candidates,
    candidates_to_observations,
)

HERE = Path(__file__).resolve().parent
ABS_TEXT = (HERE / "fixture_05_arxiv_abs_page_text.txt").read_text(encoding="utf-8")
ABS_AFF = json.loads((HERE / "fixture_05_arxiv_abs_affordances.json").read_text(encoding="utf-8"))
ABS_URL = "https://arxiv.org/abs/2609.19059"
# Distinctive prefix of the dropped abstract (first 160 chars survive join).
ABSTRACT_PREFIX = "Multimodal large language model (MLLM) agents"

# Frozen 102344Z abs page (AdaTIR) — exact live selected list + page capture.
ADA_TEXT = (HERE / "fixture_05_102344Z_abs_page_text.txt").read_text(encoding="utf-8")
ADA_AFF = json.loads((HERE / "fixture_05_102344Z_abs_affordances.json").read_text(encoding="utf-8"))
ADA_URL = "https://arxiv.org/abs/2601.14696"
ADA_ABSTRACT_PREFIX = "Tool-Integrated Reasoning (TIR) has significantly enhanced"

# Must match live_offer_state_slice.py extract_candidates kwargs (Open #6).
LIVE_MAX_CANDIDATES = 3
LIVE_MAX_UNITS = 6


def _unit_blob(units: list[dict]) -> str:
    return " ".join(" ".join(u.get("texts") or []) for u in units)


def _obs_blob(obs: list[dict]) -> str:
    return " ".join(str(o.get("text") or "") for o in obs)


def _live_extract(text: str, aff: list, url: str, surface: str) -> list[Candidate]:
    return extract_candidates(
        text=text,
        affordances=aff,
        page_url=url,
        surface=surface,
        max_candidates=LIVE_MAX_CANDIDATES,
        max_units=LIVE_MAX_UNITS,
    )


def _live_observations(cands: list[Candidate]) -> list[dict]:
    """Same call as live_offer_state_slice after the cap-sync fix: no recap."""
    return candidates_to_observations(cands)


def _claim_texts(obs: list[dict]) -> list[str]:
    return [str(o.get("text") or "") for o in obs if o.get("channel") == "candidate_claim"]


def _cands_from_json(path: Path) -> list[Candidate]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("candidates") if isinstance(raw, dict) else raw
    fields = set(Candidate.__dataclass_fields__)
    out: list[Candidate] = []
    for row in rows:
        kwargs = {k: v for k, v in row.items() if k in fields}
        out.append(Candidate(**kwargs))
    return out


def test_abs_page_text_contains_unwrapped_abstract():
    """Fixture sanity: the paragraph is in page_text as one huge line."""
    huge = [ln.strip() for ln in ABS_TEXT.splitlines() if len(ln.strip()) > 240]
    assert len(huge) == 1, huge
    assert ABSTRACT_PREFIX in huge[0]
    assert len(huge[0]) > 1000
    print("OK test_abs_page_text_contains_unwrapped_abstract")


def test_abstract_survives_packaging():
    units = package_candidate_units(
        text=ABS_TEXT,
        affordances=ABS_AFF,
        page_url=ABS_URL,
        max_units=LIVE_MAX_UNITS,
    )
    blob = _unit_blob(units)
    assert ABSTRACT_PREFIX in blob, blob[:400]
    print("OK test_abstract_survives_packaging n_units=%d" % len(units))


def test_abstract_reaches_extract_and_observations_live_budget():
    """Live-realistic: extract 3/6, observations over full selected (no recap)."""
    cands = _live_extract(ABS_TEXT, ABS_AFF, ABS_URL, "list_results")
    ev = " ".join(" ".join(c.evidence) for c in cands)
    assert ABSTRACT_PREFIX in ev, ev[:500]
    obs = _live_observations(cands)
    obs_text = _obs_blob(obs)
    assert ABSTRACT_PREFIX in obs_text, obs_text[:500]
    print(
        "OK test_abstract_reaches_extract_and_observations_live_budget "
        "n_cands=%d n_obs=%d" % (len(cands), len(obs))
    )


def test_wide_budget_still_keeps_abstract():
    """Separate wide-budget scenario (historical offline default 8) — still green."""
    cands = extract_candidates(
        text=ABS_TEXT,
        affordances=ABS_AFF,
        page_url=ABS_URL,
        surface="list_results",
        max_candidates=8,
        max_units=8,
    )
    obs = candidates_to_observations(cands, max_candidates=8)
    assert ABSTRACT_PREFIX in _obs_blob(obs)
    print(
        "OK test_wide_budget_still_keeps_abstract n_cands=%d n_obs=%d"
        % (len(cands), len(obs))
    )


def test_independent_obs_cap_3_drops_spliced_c3():
    """Negative: the old live recap (max_candidates=3) hides the spliced abstract."""
    cands = _cands_from_json(HERE / "fixture_05_102344Z_abs_candidates.json")
    assert [c.candidate_id for c in cands] == ["c0", "c1", "c2", "c3"]
    assert ADA_ABSTRACT_PREFIX in " ".join(cands[3].evidence)
    dropped = candidates_to_observations(cands, max_candidates=3)
    blob = _obs_blob(dropped)
    assert ADA_ABSTRACT_PREFIX not in blob, blob[:400]
    ids = {o.get("candidate_id") for o in dropped}
    assert "c3" not in ids
    print(
        "OK test_independent_obs_cap_3_drops_spliced_c3 "
        "n_obs=%d ids=%s" % (len(dropped), sorted(ids))
    )


def test_102344Z_c3_reaches_synced_observations():
    """Reconstruct 102344Z: 4 selected candidates, abstract on c3, synced cap keeps it."""
    frozen = _cands_from_json(HERE / "fixture_05_102344Z_abs_candidates.json")
    assert len(frozen) == 4
    assert frozen[3].candidate_id == "c3"
    assert ADA_ABSTRACT_PREFIX in " ".join(frozen[3].evidence)

    obs = _live_observations(frozen)
    blob = _obs_blob(obs)
    assert ADA_ABSTRACT_PREFIX in blob, blob[:500]
    c3_obs = [o for o in obs if o.get("candidate_id") == "c3"]
    assert c3_obs, [o.get("candidate_id") for o in obs]
    assert any(ADA_ABSTRACT_PREFIX in str(o.get("text") or "") for o in c3_obs)

    # Same reconstruction via extract on the captured page (live 3/6 + splice).
    extracted = _live_extract(ADA_TEXT, ADA_AFF, ADA_URL, "list_results")
    assert len(extracted) == 4, [c.candidate_id for c in extracted]
    assert extracted[3].candidate_id == "c3"
    obs2 = _live_observations(extracted)
    assert ADA_ABSTRACT_PREFIX in _obs_blob(obs2)
    print(
        "OK test_102344Z_c3_reaches_synced_observations "
        "frozen_n_obs=%d extract_n_obs=%d c3_text=%r"
        % (len(obs), len(obs2), str(c3_obs[0].get("text") or "")[:80])
    )


def test_short_only_page_does_not_invent_long_unit():
    """Negative: short chrome lines stay short; no phantom paragraph unit."""
    text = "Search\nSubmit\nDonate\nLog in\n"
    units = package_candidate_units(
        text=text,
        affordances=[{"text": "Submit", "href": "https://arxiv.org/user/create", "scope": "local"}],
        page_url="https://arxiv.org/",
        max_units=LIVE_MAX_UNITS,
    )
    blob = _unit_blob(units)
    assert ABSTRACT_PREFIX not in blob
    assert all(_texts_ok(u) for u in units)
    print("OK test_short_only_page_does_not_invent_long_unit n=%d" % len(units))


def _texts_ok(u: dict) -> bool:
    return all(len(str(t)) <= 240 for t in (u.get("texts") or []))


def test_known_good_fixtures_top3_hrefs_unchanged():
    """Same 01/02/synthetic contract as Open #24a — wrapping must not reshuffle nav."""
    man = json.loads(
        (ROOT / "evals/candidate_offline/fixtures_from_traces/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "synthetic_multi_offer_list": [
            "/offers/alpha-resort",
            "/offers/beta-lodge",
            "/offers/gamma-inn",
        ],
        "02_monica_detail": [
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma",
            "https://www.corendon.be/vakanties/lastminutes",
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma",
        ],
        "01_flamenco_price_surface": [
            "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir",
            "https://www.corendon.be/vakanties/lastminutes",
            "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir",
        ],
    }
    for m in man:
        label = str(m.get("label") or "")
        if label not in expected:
            continue
        text = (ROOT / m["page_text"]).read_text(encoding="utf-8")
        aff = json.loads((ROOT / m["affordances"]).read_text(encoding="utf-8"))
        units = package_candidate_units(
            text=text, affordances=aff, page_url=m["url"], max_units=8
        )
        hrefs = [str((u.get("item_link") or {}).get("href") or "") for u in units[:3]]
        assert hrefs == expected[label], f"{label}: item_link hrefs changed: {hrefs}"
    print("OK test_known_good_fixtures_top3_hrefs_unchanged")


def test_units_to_observations_keeps_abstract_prefix():
    units = package_candidate_units(
        text=ABS_TEXT, affordances=ABS_AFF, page_url=ABS_URL, max_units=LIVE_MAX_UNITS
    )
    obs = units_to_observations(
        units, page_url=ABS_URL, surface="live_detail", max_units=len(units)
    )
    blob = _obs_blob(obs)
    assert ABSTRACT_PREFIX in blob, blob[:500]
    print("OK test_units_to_observations_keeps_abstract_prefix")


def test_01_02_06_first3_observation_claims_unchanged():
    """Regression: first-3 claim texts identical under old recap vs synced cap.

    01/02/06 now also splice a 4th long-text candidate (#27). That extra
    observation is new (same class as 05 c3). The original three claims that
    previously reached interpret must not reshuffle.
    """
    cases = [
        (
            "01_flamenco_price_surface",
            ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/step_000_page_text.txt",
            ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/step_000_affordances.json",
            "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir/flamenco-beach-resort",
            "list_results",
        ),
        (
            "02_monica_detail",
            ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/step_000_page_text.txt",
            ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/step_000_affordances.json",
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma/sbh-monica-beach",
            "live_detail",
        ),
        (
            "06_wiki_fuerteventura",
            HERE / "fixture_06_wiki_page_text.txt",
            HERE / "fixture_06_wiki_affordances.json",
            "https://en.wikipedia.org/wiki/Fuerteventura",
            "live_detail",
        ),
    ]
    for label, text_p, aff_p, url, surface in cases:
        text = text_p.read_text(encoding="utf-8")
        aff = json.loads(aff_p.read_text(encoding="utf-8"))
        cands = _live_extract(text, aff, url, surface)
        before = _claim_texts(candidates_to_observations(cands, max_candidates=3))
        after = _claim_texts(_live_observations(cands))
        assert before[:3] == after[:3], f"{label}: first-3 claims changed"
        extra_n = max(0, len(after) - len(before))
        print(
            "REGRESSION %s n_cands=%d before_claims=%d after_claims=%d "
            "first3_equal=True extra=%d ids=%s"
            % (
                label,
                len(cands),
                len(before),
                len(after),
                extra_n,
                [c.candidate_id for c in cands],
            )
        )
        for i, t in enumerate(before[:3]):
            print("  [%s] before/after claim[%d] prefix=%r" % (label, i, t[:80]))
    print("OK test_01_02_06_first3_observation_claims_unchanged")


def main():
    test_abs_page_text_contains_unwrapped_abstract()
    test_abstract_survives_packaging()
    test_abstract_reaches_extract_and_observations_live_budget()
    test_wide_budget_still_keeps_abstract()
    test_independent_obs_cap_3_drops_spliced_c3()
    test_102344Z_c3_reaches_synced_observations()
    test_short_only_page_does_not_invent_long_unit()
    test_known_good_fixtures_top3_hrefs_unchanged()
    test_units_to_observations_keeps_abstract_prefix()
    test_01_02_06_first3_observation_claims_unchanged()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
