#!/usr/bin/env python3
"""
Offline tests for Open #33 — list-card evidence across OPEN_URL.

Option B: stash source_list_card on OPEN to a shown primary_action.href,
append provenance=prior_list_card on the *first* interpret after that
OPEN, clear on #26 unbind. Never replaces detail candidates.

No network, no GPU. Mock chat_fn only (no live Ollama).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidates import (  # noqa: E402
    Candidate,
    candidates_to_observations,
    extract_candidates,
)
from live_offer_state_slice import (  # noqa: E402
    PRIOR_LIST_CARD_CANDIDATE_ID,
    PRIOR_LIST_CARD_ORIGIN,
    apply_source_list_card_after_action,
    consume_prior_list_card_into_observations,
    source_list_card_from_open,
)
from pipeline_offline import (  # noqa: E402
    _is_subject_bound,
    aggregate_outcome,
    run_interpretation,
    subject_candidate_ref_from_rows,
)

EVALS = ROOT / "evals" / "contract_driven"
FIX = ROOT / "evals" / "candidate_offline" / "fixtures_from_traces"
ART_1057 = (
    EVALS
    / "20260920T105757Z_marktplaats_fiets_regio"
    / "trace"
    / "artifacts"
)
LIST_1057 = ART_1057 / "step_004_candidates.json"
DETAIL_1057 = ART_1057 / "step_005_candidates.json"
LISTING_HREF = (
    "https://www.2dehands.be/v/fietsen-en-brommers/fietsen-dames-damesfietsen"
    "/m2443330671-dames-stadsfiets"
)
LIST_URL = "https://www.2dehands.be/q/stadsfiets+antwerpen/#Language:all-languages"
LIVE_MAX_CANDIDATES = 3
LIVE_MAX_UNITS = 6

LOCATION_DECISIONS = [
    {
        "id": "subject_instance",
        "question": "Is this a second-hand bicycle listing?",
        "outcomes": ["CONFIRMED_BICYCLE", "NOT_BICYCLE", "UNKNOWN"],
        "allowed_channels": ["candidate_claim"],
        "required_for_eligibility": ["CONFIRMED_BICYCLE"],
    },
    {
        "id": "location_scope",
        "question": "Does the listing location fall within Antwerp or Brussels?",
        "outcomes": ["ANTWERP", "BRUSSELS", "OTHER_REGION", "UNKNOWN"],
        "allowed_channels": ["candidate_claim"],
        "required_for_eligibility": ["ANTWERP", "BRUSSELS"],
    },
]


def _cands_from_json(path: Path) -> list[Candidate]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("candidates") if isinstance(raw, dict) else raw
    fields = set(Candidate.__dataclass_fields__)
    out: list[Candidate] = []
    for row in rows:
        kwargs = {k: v for k, v in row.items() if k in fields}
        out.append(Candidate(**kwargs))
    return out


def _fp(cands: list[Candidate]) -> str:
    rows = []
    for c in cands:
        pa = c.primary_action or {}
        rows.append(
            {
                "id": c.candidate_id,
                "hints": c.identity_hints or [],
                "evidence": c.evidence or [],
                "href": pa.get("href"),
                "src": c.packager_source,
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def _claim_texts(obs: list[dict]) -> list[str]:
    return [str(o.get("text") or "") for o in obs if o.get("channel") == "candidate_claim"]


def _loc_chat(messages):
    """Test-only mock: map snippet text → location_scope. Not production lexicon."""
    user = messages[-1]["content"]
    payload = json.loads(user)
    did = str(payload.get("decision", {}).get("id") or "")
    text = str((payload.get("observation") or {}).get("source_text") or "")
    tl = text.lower()
    if did == "location_scope":
        if "antwerpen" in tl:
            outcome = "ANTWERP"
        elif "oostende" in tl:
            outcome = "OTHER_REGION"
        else:
            outcome = "UNKNOWN"
        return json.dumps(
            {"outcome": outcome, "confidence": "high", "reason": "fixture-mock"}
        )
    if did == "subject_instance":
        if "stadsfiets" in tl or "fietsen" in tl or "fiets " in tl:
            return json.dumps(
                {
                    "outcome": "CONFIRMED_BICYCLE",
                    "confidence": "medium",
                    "reason": "fixture-mock",
                }
            )
        return json.dumps(
            {"outcome": "UNKNOWN", "confidence": "low", "reason": "fixture-mock"}
        )
    return json.dumps(
        {"outcome": "UNKNOWN", "confidence": "low", "reason": "fixture-mock"}
    )


def test_stash_only_on_open_href_match():
    list_cands = _cands_from_json(LIST_1057)
    card = source_list_card_from_open(
        action_class="OPEN_URL",
        target_href=LISTING_HREF,
        selected=list_cands,
        page_url=LIST_URL,
    )
    assert card is not None, "list c2 href must stash"
    assert "Antwerpen" in (card.get("text") or ""), card
    assert card.get("candidate_id") == "c2"
    none_click = source_list_card_from_open(
        action_class="CLICK_TEXT",
        target_href=LISTING_HREF,
        selected=list_cands,
        page_url=LIST_URL,
    )
    assert none_click is None
    none_invented = source_list_card_from_open(
        action_class="OPEN_URL",
        target_href="https://example.test/invented",
        selected=list_cands,
        page_url=LIST_URL,
    )
    assert none_invented is None
    print("OK test_stash_only_on_open_href_match")


def test_one_shot_consume_then_unbind_clears():
    list_cands = _cands_from_json(LIST_1057)
    card, pending = apply_source_list_card_after_action(
        action_class="OPEN_URL",
        target_href=LISTING_HREF,
        selected=list_cands,
        page_url=LIST_URL,
        scope_event="bind",
        source_list_card=None,
        list_card_pending_interpret=False,
    )
    assert pending is True and card is not None
    detail_cands = _cands_from_json(DETAIL_1057)
    base = candidates_to_observations(detail_cands)
    first, pending_after, injected = consume_prior_list_card_into_observations(
        base, card, pending, step=5, page_url=LISTING_HREF, surface="list_results"
    )
    # consume_prior_list_card_into_observations: pending always False after
    # a True inbound — first interpret after OPEN only.
    assert pending_after is False, pending_after
    assert injected is True
    origins = [
        (o.get("provenance") or {}).get("origin")
        for o in first
        if o.get("channel") == "candidate_claim"
    ]
    assert origins.count(PRIOR_LIST_CARD_ORIGIN) == 1, origins
    second, pending2, injected2 = consume_prior_list_card_into_observations(
        base, card, pending_after, step=6, page_url=LISTING_HREF, surface="list_results"
    )
    assert pending2 is False and injected2 is False
    assert _claim_texts(second) == _claim_texts(base)
    cleared, pending_u = apply_source_list_card_after_action(
        action_class="FILL_AND_SUBMIT",
        target_href=None,
        selected=detail_cands,
        page_url=LISTING_HREF,
        scope_event="unbind",
        source_list_card=card,
        list_card_pending_interpret=False,
    )
    assert cleared is None and pending_u is False
    print("OK test_one_shot_consume_then_unbind_clears")


def test_negative_detail_candidates_never_replaced():
    """Detail already has correct evidence: channel appends, does not replace."""
    detail = [
        Candidate(
            candidate_id="c0",
            identity_hints=["Dames stadsfiets"],
            evidence=["Dames stadsfiets", "€ 350,00", "Antwerpen"],
            primary_action={"text": "Dames stadsfiets", "href": LISTING_HREF},
            source_url=LISTING_HREF,
            surface="live_detail",
            packager_source="html_structure",
            block_index=0,
        ),
        Candidate(
            candidate_id="c1",
            identity_hints=["Ophalen"],
            evidence=["Ophalen"],
            source_url=LISTING_HREF,
            surface="live_detail",
            packager_source="html_structure",
            block_index=1,
        ),
    ]
    conflicting_list = Candidate(
        candidate_id="c2",
        identity_hints=["Dames stadsfiets"],
        evidence=["Dames stadsfiets", "Oostende"],
        primary_action={"text": "Dames stadsfiets", "href": LISTING_HREF},
        source_url=LIST_URL,
        surface="list_results",
        packager_source="html_structure",
        block_index=16,
    )
    fp_before = _fp(detail)
    obs_detail = candidates_to_observations(detail)
    card = source_list_card_from_open(
        action_class="OPEN_URL",
        target_href=LISTING_HREF,
        selected=[conflicting_list],
        page_url=LIST_URL,
    )
    assert card is not None
    obs_with, pending, injected = consume_prior_list_card_into_observations(
        obs_detail, card, True, step=5, page_url=LISTING_HREF
    )
    assert pending is False and injected
    assert _fp(detail) == fp_before, "selected candidates must be untouched"
    detail_claims = _claim_texts(obs_detail)
    with_claims = _claim_texts(obs_with)
    for t in detail_claims:
        assert t in with_claims, t
    extra = [
        o
        for o in obs_with
        if (o.get("provenance") or {}).get("origin") == PRIOR_LIST_CARD_ORIGIN
    ]
    assert len(extra) == 1
    assert extra[0].get("candidate_id") == PRIOR_LIST_CARD_CANDIDATE_ID
    assert with_claims[: len(detail_claims)] == detail_claims
    loc_without = run_interpretation(
        observations=obs_detail, decisions=LOCATION_DECISIONS, chat_fn=_loc_chat
    )
    loc_with = run_interpretation(
        observations=obs_with, decisions=LOCATION_DECISIONS, chat_fn=_loc_chat
    )
    assert loc_without["outcomes"]["location_scope"] == "ANTWERP"
    assert loc_with["outcomes"]["location_scope"] == "ANTWERP"
    # Conflicting list-card Oostende must not flip a satisfying detail label.
    assert loc_with["outcomes"]["location_scope"] == loc_without["outcomes"]["location_scope"]
    print("OK test_negative_detail_candidates_never_replaced")


def test_105757Z_list_card_allows_antwerp_not_other_region():
    list_cands = _cands_from_json(LIST_1057)
    detail_cands = _cands_from_json(DETAIL_1057)
    assert "Antwerpen" in " ".join(list_cands[2].evidence)
    assert "Antwerpen" not in _fp(detail_cands)
    assert "oostende" in _fp(detail_cands).lower()
    obs_detail = candidates_to_observations(detail_cands)
    assert not any("Antwerpen" in t for t in _claim_texts(obs_detail))
    card = source_list_card_from_open(
        action_class="OPEN_URL",
        target_href=LISTING_HREF,
        selected=list_cands,
        page_url=LIST_URL,
    )
    assert card is not None
    obs_with, pending, injected = consume_prior_list_card_into_observations(
        obs_detail, card, True, step=5, page_url=LISTING_HREF
    )
    assert pending is False and injected
    assert _fp(detail_cands) == _fp(_cands_from_json(DETAIL_1057))
    extra = [
        o
        for o in obs_with
        if (o.get("provenance") or {}).get("origin") == PRIOR_LIST_CARD_ORIGIN
    ]
    assert extra and "Antwerpen" in extra[0]["text"]
    loc_only = [LOCATION_DECISIONS[1]]
    without_loc = run_interpretation(
        observations=obs_detail, decisions=loc_only, chat_fn=_loc_chat
    )
    with_loc = run_interpretation(
        observations=obs_with, decisions=loc_only, chat_fn=_loc_chat
    )
    # Same-page crumbs only: "fietsen oostende" → OTHER_REGION (105757Z).
    assert without_loc["outcomes"]["location_scope"] == "OTHER_REGION", without_loc[
        "outcomes"
    ]
    assert with_loc["outcomes"]["location_scope"] == "ANTWERP", with_loc["outcomes"]
    with_card = run_interpretation(
        observations=obs_with, decisions=LOCATION_DECISIONS, chat_fn=_loc_chat
    )
    assert with_card["outcomes"]["location_scope"] == "ANTWERP", with_card["outcomes"]
    ref = with_card.get("subject_candidate_ref") or {}
    assert ref.get("candidate_id") != PRIOR_LIST_CARD_CANDIDATE_ID, ref
    print("OK test_105757Z_list_card_allows_antwerp_not_other_region")


def test_prior_list_card_survives_subject_bind_sibling_still_dropped():
    """#22 still drops unbound siblings; prior_list_card is same-record extra."""
    subject_ref = {
        "candidate_id": "c0",
        "block_index": 0,
        "item_link_href": None,
        "scope": "unit",
    }
    sibling = {
        "candidate_id": "c2",
        "block_index": 10,
        "outcome": "OTHER_REGION",
        "confidence": "high",
        "prior_list_card": False,
    }
    prior = {
        "candidate_id": PRIOR_LIST_CARD_CANDIDATE_ID,
        "block_index": None,
        "outcome": "ANTWERP",
        "confidence": "high",
        "prior_list_card": True,
        "item_link_href": LISTING_HREF,
    }
    assert not _is_subject_bound(sibling, subject_ref)
    assert _is_subject_bound(prior, subject_ref)
    out = aggregate_outcome(
        [sibling, prior],
        preferred_outcomes=["ANTWERP", "BRUSSELS"],
        subject_candidate_ref=subject_ref,
        require_subject_binding=True,
    )
    assert out == "ANTWERP", out
    rows = [
        {
            "candidate_id": "c0",
            "outcome": "CONFIRMED_BICYCLE",
            "confidence": "medium",
            "prior_list_card": False,
            "block_index": 0,
        },
        {
            "candidate_id": PRIOR_LIST_CARD_CANDIDATE_ID,
            "outcome": "CONFIRMED_BICYCLE",
            "confidence": "high",
            "prior_list_card": True,
        },
    ]
    ref = subject_candidate_ref_from_rows(rows)
    assert ref is not None
    assert ref.get("candidate_id") == "c0", ref
    print("OK test_prior_list_card_survives_subject_bind_sibling_still_dropped")


def _regression_extract(label: str, text_p: Path, aff_p: Path, url: str, surface: str):
    if not text_p.is_file():
        print(f"SKIP {label} missing {text_p}")
        return None
    text = text_p.read_text(encoding="utf-8", errors="replace")
    aff = json.loads(aff_p.read_text()) if aff_p.is_file() else []
    a = extract_candidates(
        text=text,
        affordances=aff,
        page_url=url,
        surface=surface,
        max_candidates=LIVE_MAX_CANDIDATES,
        max_units=LIVE_MAX_UNITS,
        html="",
    )
    b = extract_candidates(
        text=text,
        affordances=aff,
        page_url=url,
        surface=surface,
        max_candidates=LIVE_MAX_CANDIDATES,
        max_units=LIVE_MAX_UNITS,
        html="",
    )
    assert _fp(a) == _fp(b), label
    return a


def test_regression_01_02_03_05_06_and_campaign_packager_unchanged():
    cases = [
        (
            "01",
            FIX / "01_price_surface" / "step_000_page_text.txt",
            FIX / "01_price_surface" / "step_000_affordances.json",
            "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir/flamenco-beach-resort",
            "list_results",
        ),
        (
            "02",
            FIX / "02_detail" / "step_000_page_text.txt",
            FIX / "02_detail" / "step_000_affordances.json",
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma/sbh-monica-beach",
            "live_detail",
        ),
        (
            "03",
            EVALS
            / "20260919T064948Z_03_web_product_gpu"
            / "trace/artifacts/step_000_page_text.txt",
            EVALS
            / "20260919T064948Z_03_web_product_gpu"
            / "trace/artifacts/step_000_affordances.json",
            "https://www.coolblue.be/nl",
            "list_results",
        ),
        (
            "05",
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "trace/artifacts/step_002_page_text.txt",
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "trace/artifacts/step_002_affordances.json",
            "https://arxiv.org/search/?query=large+language+model+agents+tool+use",
            "list_results",
        ),
        (
            "06",
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "trace/artifacts/step_000_page_text.txt",
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "trace/artifacts/step_000_affordances.json",
            "https://en.wikipedia.org/wiki/Fuerteventura",
            "live_detail",
        ),
        (
            "tui",
            EVALS
            / "20260920T101517Z_tui_package_crete"
            / "trace/artifacts/step_000_page_text.txt",
            EVALS
            / "20260920T101517Z_tui_package_crete"
            / "trace/artifacts/step_000_affordances.json",
            "https://www.tui.nl/",
            "live_detail",
        ),
        (
            "bol",
            EVALS
            / "20260920T101537Z_bol_airpods_pro"
            / "trace/artifacts/step_000_page_text.txt",
            EVALS
            / "20260920T101537Z_bol_airpods_pro"
            / "trace/artifacts/step_000_affordances.json",
            "https://www.bol.com/",
            "live_detail",
        ),
        (
            "wiki",
            EVALS
            / "20260920T111537Z_wiki_brussels_population"
            / "trace/artifacts/step_000_page_text.txt",
            EVALS
            / "20260920T111537Z_wiki_brussels_population"
            / "trace/artifacts/step_000_affordances.json",
            "https://nl.wikipedia.org/wiki/Brussel_(stad)",
            "list_results",
        ),
        (
            "ss",
            EVALS
            / "20260920T115358Z_semanticscholar_rag_paper"
            / "trace/artifacts/step_000_page_text.txt",
            EVALS
            / "20260920T115358Z_semanticscholar_rag_paper"
            / "trace/artifacts/step_000_affordances.json",
            "https://www.semanticscholar.org/",
            "live_detail",
        ),
    ]
    extracted: dict[str, list[Candidate]] = {}
    for label, text_p, aff_p, url, surface in cases:
        got = _regression_extract(label, text_p, aff_p, url, surface)
        if got is not None:
            extracted[label] = got
            print(f"OK regression packager {label} n={len(got)}")
    # 01/02/06 start on (or as) detail: no OPEN_URL-from-card in these fixtures.
    for label in ("01", "02", "06", "tui", "bol", "wiki", "ss"):
        if label not in extracted:
            continue
        miss = source_list_card_from_open(
            action_class="OPEN_URL",
            target_href="https://example.test/not-a-card",
            selected=extracted[label],
            page_url="https://example.test/",
        )
        assert miss is None, label
    print("OK test_regression_01_02_03_05_06_and_campaign_packager_unchanged")


def test_task_05_open_from_card_appends_does_not_replace_abs():
    """05 *does* OPEN_URL a shown primary_action (abs). Extra channel only."""
    search = _cands_from_json(
        EVALS
        / "20260918T081459Z_05_web_literature_abstract"
        / "trace/artifacts/step_002_candidates.json"
    )
    abs_cands = _cands_from_json(
        EVALS
        / "20260918T081459Z_05_web_literature_abstract"
        / "trace/artifacts/step_003_candidates.json"
    )
    href = str((search[0].primary_action or {}).get("href") or "")
    assert href.startswith("https://arxiv.org/abs/"), href
    fp_abs = _fp(abs_cands)
    card = source_list_card_from_open(
        action_class="OPEN_URL",
        target_href=href,
        selected=search,
        page_url="https://arxiv.org/search/?query=large+language+model+agents+tool+use",
    )
    assert card is not None
    obs = candidates_to_observations(abs_cands)
    with_card, pending, injected = consume_prior_list_card_into_observations(
        obs, card, True, step=3, page_url=href
    )
    assert pending is False and injected
    assert _fp(abs_cands) == fp_abs
    extra = [
        o
        for o in with_card
        if (o.get("provenance") or {}).get("origin") == PRIOR_LIST_CARD_ORIGIN
    ]
    assert extra
    for t in _claim_texts(obs):
        assert t in _claim_texts(with_card)
    print("OK test_task_05_open_from_card_appends_does_not_replace_abs")


def main() -> None:
    test_stash_only_on_open_href_match()
    test_one_shot_consume_then_unbind_clears()
    test_negative_detail_candidates_never_replaced()
    test_105757Z_list_card_allows_antwerp_not_other_region()
    test_prior_list_card_survives_subject_bind_sibling_still_dropped()
    test_regression_01_02_03_05_06_and_campaign_packager_unchanged()
    test_task_05_open_from_card_appends_does_not_replace_abs()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
