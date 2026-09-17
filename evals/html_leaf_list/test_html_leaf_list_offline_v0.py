#!/usr/bin/env python3
"""
Offline tests for Open #24b Fase 2.2 — leaf `extract_candidates_via_html`
additive on surface=list_results only.

Not html_b2 (no heading+price NCA). Repeating leaf containers only.

Mandatory negatives: task 01/02 candidate fingerprints byte-identical
with vs without HTML (01 sketch is list_results but not a ≥3-sibling
result list; 02 is live_detail so html is ignored).

No LLM, no GPU.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidates import (  # noqa: E402
    candidates_to_jsonable,
    candidates_to_observations,
    extract_candidates,
)
from structural_observer import extract_candidates_via_html  # noqa: E402

LIVE_MAX_CANDIDATES = 3
LIVE_MAX_UNITS = 6
CARD_RE = re.compile(r"arXiv:(\d{4}\.\d+)\s*\[([^\]]+)\]", re.I)
PAPER_ID_RE = re.compile(r"\d{4}\.\d+")

SEARCH_TEXT = (
    ROOT / "evals/affordance_identity/fixture_05_111714Z_step_002_page_text.txt"
)
SEARCH_AFF = (
    ROOT / "evals/affordance_identity/fixture_05_111714Z_step_002_affordances.json"
)
SEARCH_URL = (
    "https://arxiv.org/search/?query=large+language+model+agents+tool+use"
    "&searchtype=all&abstracts=show&order=-announced_date_first&size=50"
)

CASES_01_02 = [
    (
        "01_flamenco_price_surface",
        ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/step_000_page_text.txt",
        ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/step_000_affordances.json",
        ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/page.html",
        "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir/flamenco-beach-resort",
        "list_results",
    ),
    (
        "02_monica_detail",
        ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/step_000_page_text.txt",
        ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/step_000_affordances.json",
        ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/page.html",
        "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma/sbh-monica-beach",
        "live_detail",
    ),
]


def _fp(cands) -> str:
    rows = []
    for c in candidates_to_jsonable(cands):
        pa = c.get("primary_action") or {}
        rows.append(
            {
                "id": c.get("candidate_id"),
                "hints": c.get("identity_hints") or [],
                "evidence": c.get("evidence") or [],
                "text": pa.get("text"),
                "href": pa.get("href"),
                "src": c.get("packager_source"),
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def _obs_fp(cands) -> str:
    obs = candidates_to_observations(cands)
    rows = [
        (o.get("observation_id"), o.get("text"), o.get("channel"))
        for o in obs
    ]
    return json.dumps(rows, ensure_ascii=False)


def _live_extract(text: str, aff: list, url: str, surface: str, html: str = ""):
    return extract_candidates(
        text=text,
        affordances=aff,
        page_url=url,
        surface=surface,
        max_candidates=LIVE_MAX_CANDIDATES,
        max_units=LIVE_MAX_UNITS,
        html=html,
    )


def reconstruct_repeating_list_html(page_text: str) -> str:
    """Turn captured `arXiv:ID [pdf, …]` lines into repeating leaf <li> cards.

    Generic list markup (`ol.results > li.result`); tokens in the bracket
    become distinct hrefs. No site lexicon in extraction code.
    """
    lines = page_text.splitlines()
    cards: list[str] = []
    for i, ln in enumerate(lines):
        m = CARD_RE.search(ln)
        if not m:
            continue
        pid = m.group(1)
        rest = [x.strip() for x in lines[i + 1 : i + 4] if x.strip()]
        title = rest[1] if len(rest) > 1 else (rest[0] if rest else pid)
        bits = [f'<a href="https://arxiv.org/abs/{pid}">arXiv:{pid}</a>']
        for tok in (t.strip() for t in m.group(2).split(",")):
            if tok:
                bits.append(f'<a href="https://arxiv.org/{html_lib.escape(tok)}/{pid}">{html_lib.escape(tok)}</a>')
        cards.append(
            "<li class=\"result\"><p>"
            + " ".join(bits)
            + f"</p><p>{html_lib.escape(title)}</p></li>"
        )
    return (
        "<!DOCTYPE html><html><body><ol class=\"results\">"
        + "".join(cards)
        + "</ol></body></html>"
    )


def _paper_ids(cands) -> list[str]:
    blob = " ".join(
        " ".join(list(c.identity_hints or []) + list(c.evidence or []))
        for c in cands
    )
    return list(dict.fromkeys(PAPER_ID_RE.findall(blob)))


def test_01_02_candidate_set_byte_identical_with_html():
    """Mandatory negative: 01/02 unchanged when HTML is supplied."""
    for label, text_p, aff_p, html_p, url, surface in CASES_01_02:
        text = text_p.read_text(encoding="utf-8")
        aff = json.loads(aff_p.read_text(encoding="utf-8"))
        html = html_p.read_text(encoding="utf-8")
        without = _live_extract(text, aff, url, surface, html="")
        with_html = _live_extract(text, aff, url, surface, html=html)
        assert _fp(without) == _fp(with_html), f"{label}: candidate-set changed"
        assert _obs_fp(without) == _obs_fp(with_html), f"{label}: observations changed"
        print(f"NEG {label} n={len(without)} candidates+obs identical with html")
    print("OK test_01_02_candidate_set_byte_identical_with_html")


def test_repeating_leaf_html_keeps_distinct_paper_cards():
    text = SEARCH_TEXT.read_text(encoding="utf-8")
    html = reconstruct_repeating_list_html(text)
    ids = [m[0] for m in CARD_RE.findall(text)]
    assert len(ids) >= 19, len(ids)
    html_cands = extract_candidates_via_html(
        html=html,
        page_url=SEARCH_URL,
        surface="list_results",
        max_candidates=12,
        apply_quality=False,
        drop_parents=True,
        repeating_only=True,
        min_repeating_siblings=3,
    )
    hrefs = [
        str((c.primary_action or {}).get("href") or "")
        for c in html_cands
        if (c.primary_action or {}).get("href")
    ]
    assert len(html_cands) >= 8, [c.identity_hints[:1] for c in html_cands]
    assert len(set(hrefs)) >= 8, hrefs
    for h in hrefs[:8]:
        assert any(pid in h for pid in ids)
    print(
        f"HTML leaf n={len(html_cands)} unique_hrefs={len(set(hrefs))} "
        f"first={hrefs[:3]}"
    )
    print("OK test_repeating_leaf_html_keeps_distinct_paper_cards")


def test_list_results_extract_uses_html_cards_not_straddling_chunk():
    text = SEARCH_TEXT.read_text(encoding="utf-8")
    aff = json.loads(SEARCH_AFF.read_text(encoding="utf-8"))
    html = reconstruct_repeating_list_html(text)
    old = _live_extract(text, aff, SEARCH_URL, "list_results", html="")
    new = _live_extract(text, aff, SEARCH_URL, "list_results", html=html)
    old_ids = _paper_ids(old)
    new_ids = _paper_ids(new)
    old_hrefs = [str((c.primary_action or {}).get("href") or "") for c in old]
    new_hrefs = [str((c.primary_action or {}).get("href") or "") for c in new]
    # Old text path bound ClinAgent 2609.13860 to first-card pdf 2609.19059.
    mismatched = [
        c
        for c in old
        if "2609.13860" in " ".join(c.identity_hints + c.evidence)
        and "2609.19059" in str((c.primary_action or {}).get("href") or "")
    ]
    assert mismatched, "precondition: text path still has the #24b mismatch"
    new_mismatch = [
        c
        for c in new
        if "2609.13860" in " ".join(c.identity_hints + c.evidence)
        and "2609.19059" in str((c.primary_action or {}).get("href") or "")
    ]
    assert not new_mismatch, [(c.identity_hints, c.primary_action) for c in new]
    assert len(new_ids) >= 2, f"new paper ids={new_ids}"
    assert all(c.packager_source == "html_structure" for c in new)
    print(
        f"EXTRACT old_ids={old_ids} old_hrefs={old_hrefs} "
        f"new_ids={new_ids} new_hrefs={new_hrefs}"
    )
    print("OK test_list_results_extract_uses_html_cards_not_straddling_chunk")


def test_negative_live_detail_ignores_list_html():
    """Same repeating HTML on live_detail must not change the text candidate set."""
    text = SEARCH_TEXT.read_text(encoding="utf-8")
    aff = json.loads(SEARCH_AFF.read_text(encoding="utf-8"))
    html = reconstruct_repeating_list_html(text)
    without = _live_extract(text, aff, SEARCH_URL, "live_detail", html="")
    with_html = _live_extract(text, aff, SEARCH_URL, "live_detail", html=html)
    assert _fp(without) == _fp(with_html)
    print("OK test_negative_live_detail_ignores_list_html")


def test_synthetic_list_html_recovers_three_offer_cards():
    html = (
        ROOT / "evals/candidate_offline/fixtures_from_traces/synthetic_list/page.html"
    ).read_text(encoding="utf-8")
    text = (
        ROOT / "evals/candidate_offline/fixtures_from_traces/synthetic_list/page_text.txt"
    ).read_text(encoding="utf-8")
    aff = json.loads(
        (
            ROOT / "evals/candidate_offline/fixtures_from_traces/synthetic_list/affordances.json"
        ).read_text(encoding="utf-8")
    )
    cands = _live_extract(text, aff, "https://example.test/offers", "list_results", html=html)
    hrefs = [str((c.primary_action or {}).get("href") or "") for c in cands]
    assert any("alpha-resort" in h for h in hrefs), hrefs
    assert any("beta-lodge" in h for h in hrefs), hrefs
    print(f"SYNTH n={len(cands)} hrefs={hrefs}")
    print("OK test_synthetic_list_html_recovers_three_offer_cards")


def main():
    test_01_02_candidate_set_byte_identical_with_html()
    test_repeating_leaf_html_keeps_distinct_paper_cards()
    test_list_results_extract_uses_html_cards_not_straddling_chunk()
    test_negative_live_detail_ignores_list_html()
    test_synthetic_list_html_recovers_three_offer_cards()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
