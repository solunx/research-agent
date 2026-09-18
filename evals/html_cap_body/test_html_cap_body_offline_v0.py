#!/usr/bin/env python3
"""
Offline tests: HTML snapshot cap ignores script/style/head.

Live citation (110505Z step 1): html_chars=699128; naive 400k cut was
still inside a stylesheet. Product cards lived in <body> / innerText.

No LLM, no GPU, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from browser import _HTML_SNAP_CAP, prepare_html_for_snapshot  # noqa: E402
from candidates import extract_candidates  # noqa: E402

sys.path.insert(0, str(ROOT / "evals" / "coolblue_list_detail"))
from reconstruct_110505Z import (  # noqa: E402
    ASUS_TITLE,
    NAIVE_CAP,
    VICTUS_A_TITLE,
    reconstruct_110505Z_search_html,
)

CASES_01_02 = [
    (
        "01",
        ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/step_000_page_text.txt",
        ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/step_000_affordances.json",
        ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/page.html",
        "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir/flamenco-beach-resort",
        "list_results",
    ),
    (
        "02",
        ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/step_000_page_text.txt",
        ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/step_000_affordances.json",
        ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/page.html",
        "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma/sbh-monica-beach",
        "live_detail",
    ),
]


def _fp(cands) -> str:
    from candidates import candidates_to_jsonable

    rows = []
    for c in candidates_to_jsonable(cands):
        pa = c.get("primary_action") or {}
        rows.append(
            (
                c.get("candidate_id"),
                tuple(c.get("identity_hints") or []),
                tuple(c.get("evidence") or []),
                pa.get("href"),
            )
        )
    return json.dumps(rows, ensure_ascii=False)


def test_naive_cap_drops_coolblue_body():
    raw = reconstruct_110505Z_search_html(huge_head=True)
    assert len(raw) > NAIVE_CAP, len(raw)
    naive = raw[:NAIVE_CAP]
    assert "<body" not in naive.lower() or VICTUS_A_TITLE not in naive
    assert VICTUS_A_TITLE not in naive
    assert ASUS_TITLE not in naive
    print(f"OK test_naive_cap_drops_coolblue_body raw={len(raw)} naive_has_victus=False")


def test_prepare_keeps_body_within_cap():
    """Mandatory negative vs the old cap: body product cards survive."""
    raw = reconstruct_110505Z_search_html(huge_head=True)
    prepared = prepare_html_for_snapshot(raw, cap=_HTML_SNAP_CAP)
    assert len(prepared) <= _HTML_SNAP_CAP, len(prepared)
    assert VICTUS_A_TITLE in prepared
    assert ASUS_TITLE in prepared
    assert "<style>" not in prepared.lower()
    assert "<script>" not in prepared.lower()
    print(
        f"OK test_prepare_keeps_body_within_cap prepared={len(prepared)} "
        f"victus=True asus=True"
    )


def test_regression_01_02_prepared_html_does_not_change_candidates():
    """Cap was never the 01/02 problem; prepare must be a no-op on small pages."""
    for label, text_p, aff_p, html_p, url, surface in CASES_01_02:
        text = text_p.read_text(encoding="utf-8")
        aff = json.loads(aff_p.read_text(encoding="utf-8"))
        html = html_p.read_text(encoding="utf-8")
        assert len(html) < _HTML_SNAP_CAP, (label, len(html))
        prepared = prepare_html_for_snapshot(html, cap=_HTML_SNAP_CAP)
        a = extract_candidates(
            text=text, affordances=aff, page_url=url, surface=surface,
            max_candidates=3, max_units=6, html=html,
        )
        b = extract_candidates(
            text=text, affordances=aff, page_url=url, surface=surface,
            max_candidates=3, max_units=6, html=prepared,
        )
        assert _fp(a) == _fp(b), label
        print(f"REGRESSION {label} n={len(a)} fingerprint unchanged after prepare")
    print("OK test_regression_01_02_prepared_html_does_not_change_candidates")


def test_regression_05_arxiv_cards_survive_prepare():
    """Cap was never the 05 problem; small repeating list must stay intact."""
    cards = "".join(
        f"<li class='result'><a href='https://arxiv.org/abs/2609.{n}'>"
        f"arXiv:2609.{n}</a><p>Paper {n}</p></li>"
        for n in ("18128", "13860", "17632")
    )
    html = (
        "<html><head><style>body{color:#000}</style></head>"
        f"<body><ol class='results'>{cards}</ol></body></html>"
    )
    prepared = prepare_html_for_snapshot(html, cap=_HTML_SNAP_CAP)
    assert "2609.18128" in prepared and "2609.13860" in prepared
    assert "<style>" not in prepared.lower()
    print("OK test_regression_05_arxiv_cards_survive_prepare", len(prepared))


def test_synthetic_list_and_06_text_unaffected():
    syn = ROOT / "evals/candidate_offline/fixtures_from_traces/synthetic_list/page.html"
    html = syn.read_text(encoding="utf-8")
    prepared = prepare_html_for_snapshot(html, cap=_HTML_SNAP_CAP)
    assert "article" in prepared.lower() or "card" in prepared.lower() or "<li" in prepared.lower()
    wiki = ROOT / "evals/long_line_units/fixture_06_wiki_page_text.txt"
    text = wiki.read_text(encoding="utf-8")[:200]
    # 06 has no page.html; prepare must not be required. Sanity: text still has Fuerteventura.
    assert "Fuerteventura" in wiki.read_text(encoding="utf-8")
    print("OK test_synthetic_list_and_06_text_unaffected", "syn_len", len(html), "prep", len(prepared))


def main():
    test_naive_cap_drops_coolblue_body()
    test_prepare_keeps_body_within_cap()
    test_regression_01_02_prepared_html_does_not_change_candidates()
    test_regression_05_arxiv_cards_survive_prepare()
    test_synthetic_list_and_06_text_unaffected()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
