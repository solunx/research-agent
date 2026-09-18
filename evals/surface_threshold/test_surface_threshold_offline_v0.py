#!/usr/bin/env python3
"""
Offline Open #10: surface density recalibration.

Live citation (`20260918T062211Z` step 3 abs):
  _classify_surface used glyph∨D2c count >= 3 → list_results
  four D2c lines: arXiv-IDs 2609/18128, DOI 48550, file size 5,658 KB
  HTML-leaf then packed View PDF / HTML / TeX instead of the abstract.

Same class as Monica PRICE_LINE 7 vs glyph/digit 37: the old >=3 did not
transfer onto identifier-shaped digit runs.

No network, no LLM, no GPU.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidate_units import (  # noqa: E402
    count_price_like_lines,
    line_is_price_like,
)
from live_offer_state_slice import (  # noqa: E402
    _PRICE_LIKE_LIST_THRESHOLD,
    _classify_surface,
)

HERE = Path(__file__).resolve().parent
ABS_062 = HERE / "fixture_062211Z_step_003_abs_page_text.txt"
SEARCH_062 = HERE / "fixture_062211Z_step_002_search_page_text.txt"
ABS_102 = ROOT / "evals/long_line_units/fixture_05_102344Z_abs_page_text.txt"
MON = ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/step_000_page_text.txt"
FLA = ROOT / (
    "evals/candidate_offline/fixtures_from_traces/01_price_surface/step_000_page_text.txt"
)
WIKI = ROOT / "evals/long_line_units/fixture_06_wiki_page_text.txt"
SYN = ROOT / "evals/candidate_offline/fixtures_from_traces/synthetic_list/page_text.txt"

ARXIV_START = "https://arxiv.org/"
ABS_URL = "https://arxiv.org/abs/2609.18128"
SEARCH_URL = (
    "https://arxiv.org/search/?query=large+language+model+agents+tool+use"
    "&searchtype=all&abstracts=show&order=-announced_date_first&size=50"
)
MON_URL = (
    "https://www.corendon.be/spanje/canarische-eilanden/"
    "fuerteventura/costa-calma/sbh-monica-beach"
)
FLA_URL = (
    "https://www.corendon.be/egypte/rode-zee/marsa-alam/"
    "el-quseir/flamenco-beach-resort"
)
WIKI_URL = "https://en.wikipedia.org/wiki/Fuerteventura"

# Reconstruction of the four D2c lines that crossed T=3 on 062211Z abs
# *before* identifier/1-decimal tightening (measured, not guessed).
OLD_ABS_D2C_LINES = (
    "Cite as:\tarXiv:2609.18128 [cs.AI]",
    "(or arXiv:2609.18128v1 [cs.AI] for this version)",
    "https://doi.org/10.48550/arXiv.2609.18128",
    "[v1] Wed, 16 Sep 2026 05:05:35 UTC (5,658 KB)",
)


def test_reconstruct_062211Z_identifier_false_positives():
    """Cite the four lines; IDs/DOI no longer count; only file-size remains."""
    text = ABS_062.read_text(encoding="utf-8")
    for ln in OLD_ABS_D2C_LINES:
        assert ln in text, ln
    id_lines = OLD_ABS_D2C_LINES[:3]
    filesize = OLD_ABS_D2C_LINES[3]
    for ln in id_lines:
        assert not line_is_price_like(ln), ln
    assert line_is_price_like(filesize), filesize
    hits = count_price_like_lines(text)
    assert hits == 1, hits
    assert hits < _PRICE_LIKE_LIST_THRESHOLD
    print(
        f"OK reconstruct 062211Z old_d2c_lines=4 now_hits={hits} "
        f"T={_PRICE_LIKE_LIST_THRESHOLD} (IDs/DOI dropped; 5,658 KB remains)"
    )


def test_negative_abs_is_not_list_results():
    """Mandatory negative: arXiv abs must not classify as list_results."""
    text = ABS_062.read_text(encoding="utf-8")
    surf, same = _classify_surface(
        start_url=ARXIV_START, cur_url=ABS_URL, text=text, step=3
    )
    assert surf != "list_results", (surf, same)
    assert surf == "live_offer_state", (surf, same)
    assert same is True
    # Second abs family (102344Z abstract with percentages) also not a list.
    text_b = ABS_102.read_text(encoding="utf-8")
    surf_b, _ = _classify_surface(
        start_url=ARXIV_START,
        cur_url="https://arxiv.org/abs/2601.14696",
        text=text_b,
        step=3,
    )
    assert surf_b != "list_results", surf_b
    print(f"OK negative abs surface={surf} (not list_results); 102344Z={surf_b}")


def test_search_list_still_list_results():
    """ArXiv search must remain list_results so HTML-leaf still gates on."""
    text = SEARCH_062.read_text(encoding="utf-8")
    hits = count_price_like_lines(text)
    assert hits >= _PRICE_LIKE_LIST_THRESHOLD, hits
    surf, same = _classify_surface(
        start_url=ARXIV_START, cur_url=SEARCH_URL, text=text, step=2
    )
    assert surf == "list_results", (surf, same, hits)
    print(f"OK search still list_results hits={hits}")


def test_01_02_06_surfaces_unchanged():
    """Regression: canonical start-page step=0 stays live_detail."""
    cases = (
        ("01_flamenco", FLA, FLA_URL),
        ("02_monica", MON, MON_URL),
        ("06_wiki", WIKI, WIKI_URL),
    )
    for label, path, url in cases:
        text = path.read_text(encoding="utf-8")
        surf, same = _classify_surface(
            start_url=url, cur_url=url, text=text, step=0
        )
        assert surf == "live_detail", (label, surf, same)
        assert same is True
        print(f"REGRESSION {label} step=0 surface=live_detail")
    print("OK test_01_02_06_surfaces_unchanged")


def test_synthetic_list_still_dense():
    text = SYN.read_text(encoding="utf-8")
    hits = count_price_like_lines(text)
    assert hits == 3, hits
    surf, _ = _classify_surface(
        start_url="https://example.test/",
        cur_url="https://example.test/offers",
        text=text,
        step=1,
    )
    assert surf == "list_results", surf
    print(f"OK synthetic list hits={hits} surface={surf}")


def test_negative_identifier_and_review_score_not_price_like():
    """Bare arXiv-ID / DOI / 1-decimal score must not be D2c; 3-digit price must."""
    assert not line_is_price_like("Cite as:\tarXiv:2609.18128 [cs.AI]")
    assert not line_is_price_like("https://doi.org/10.48550/arXiv.2609.18128")
    assert not line_is_price_like("8,1")
    assert line_is_price_like("va 694 p.p.")
    assert line_is_price_like("va 499 p.p.")
    print("OK negative identifier/review-score; 3-digit prices still D2c")


def main():
    test_reconstruct_062211Z_identifier_false_positives()
    test_negative_abs_is_not_list_results()
    test_search_list_still_list_results()
    test_01_02_06_surfaces_unchanged()
    test_synthetic_list_still_dense()
    test_negative_identifier_and_review_score_not_price_like()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
