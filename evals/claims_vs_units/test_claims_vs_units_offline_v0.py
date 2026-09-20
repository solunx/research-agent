#!/usr/bin/env python3
"""
Offline tests for Open #32 — HTML leaf replace dropping D2c text units.

Wiki 165815Z: step_003_candidate_units u0 already had
`198.674 (01/01/2026)`; selected candidates were html_structure
landmark cards (Atomium / Manneken / de Munt). Not a rank loss
(text rank keeps u0 first) and not Open #27 recap (claims n=4 =
title + 3 HTML). HTML exclusive replace is a second packager.

Detector: line_is_price_like (glyph ∨ D2c), not bare digit_run.
Mandatory negatives 01/02/03/05/06.

No LLM, no GPU, no beautifulsoup (uses recorded candidates JSON).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidate_units import (  # noqa: E402
    line_is_price_like,
    package_candidate_units,
)
from candidates import (  # noqa: E402
    Candidate,
    candidates_from_units,
    candidates_to_observations,
    extract_candidates,
    html_cards_have_price_like,
    rank_candidates,
    splice_unrepresented_price_like_text,
)

EVALS = ROOT / "evals" / "contract_driven"
FIX = ROOT / "evals" / "candidate_offline" / "fixtures_from_traces"
WIKI = EVALS / "20260919T165815Z_wiki_brussels_population" / "trace" / "artifacts"
FIGURE = "198.674"
LIVE_MAX_CANDIDATES = 3
LIVE_MAX_UNITS = 6


def _cands_from_json(path: Path) -> list[Candidate]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("candidates") if isinstance(raw, dict) else raw
    fields = set(Candidate.__dataclass_fields__)
    out: list[Candidate] = []
    for row in rows:
        kwargs = {k: v for k, v in row.items() if k in fields}
        out.append(Candidate(**kwargs))
    return out


def _blob(cands: list[Candidate]) -> str:
    return " ".join(
        " ".join(list(c.identity_hints or []) + list(c.evidence or []))
        for c in cands
    )


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


def _text_cands(text: str, aff: list, url: str, surface: str) -> list[Candidate]:
    units = package_candidate_units(
        text=text, affordances=aff, page_url=url, max_units=LIVE_MAX_UNITS
    )
    return candidates_from_units(
        units,
        source_url=url,
        surface=surface,
        max_candidates=LIVE_MAX_UNITS,
        page_text=text,
    )


def test_wiki_units_had_figure_html_candidates_did_not():
    """Recorded 165815Z: u0 has the figure; selected HTML cards do not."""
    units = json.loads((WIKI / "step_003_candidate_units.json").read_text())
    u0 = (units.get("units") or [None])[0]
    assert u0, units
    u0_blob = " ".join(u0.get("texts") or [])
    assert FIGURE in u0_blob, u0_blob[:400]
    html = _cands_from_json(WIKI / "step_003_candidates.json")
    assert html, "recorded HTML candidates missing"
    assert all((c.packager_source or "") == "html_structure" for c in html)
    assert FIGURE not in _blob(html), _blob(html)[:400]
    claims = json.loads((WIKI / "step_003_claims.json").read_text())
    preview = " ".join(claims.get("claim_preview") or [])
    assert FIGURE not in preview, preview
    assert "Atomium" in preview or "Manneken" in preview
    print("OK test_wiki_units_had_figure_html_candidates_did_not")


def test_not_rank_loss_text_arm_keeps_figure():
    """If HTML had not replaced, rank would have kept u0 (block_index=0)."""
    text = (WIKI / "step_003_page_text.txt").read_text(encoding="utf-8")
    aff = json.loads((WIKI / "step_003_affordances.json").read_text())
    url = "https://nl.wikipedia.org/wiki/Brussel_(stad)"
    raw = _text_cands(text, aff, url, "list_results")
    assert any(FIGURE in " ".join(c.evidence or []) for c in raw)
    ranked = rank_candidates(raw)
    top3 = ranked[:LIVE_MAX_CANDIDATES]
    assert any(FIGURE in " ".join(c.evidence or []) for c in top3), [
        (c.block_index, c.digit_run_count, (c.identity_hints or [""])[0][:40])
        for c in top3
    ]
    print("OK test_not_rank_loss_text_arm_keeps_figure")


def test_wiki_splice_puts_figure_in_observations():
    """#32 splice: D2c infobox reaches candidates_to_observations."""
    html = _cands_from_json(WIKI / "step_003_candidates.json")
    # Atomium card has D2c "165 miljard" — that must not block the infobox splice.
    text = (WIKI / "step_003_page_text.txt").read_text(encoding="utf-8")
    aff = json.loads((WIKI / "step_003_affordances.json").read_text())
    url = "https://nl.wikipedia.org/wiki/Brussel_(stad)"
    raw = _text_cands(text, aff, url, "list_results")
    spliced = splice_unrepresented_price_like_text(html, raw)
    assert len(spliced) == len(html) + 1, [c.packager_source for c in spliced]
    assert FIGURE in _blob(spliced), _blob(spliced)[:500]
    assert any((c.packager_source or "") == "html_structure" for c in spliced)
    obs = candidates_to_observations(spliced)
    obs_blob = " ".join(str(o.get("text") or "") for o in obs)
    assert FIGURE in obs_blob, obs_blob[:500]
    print(
        "OK test_wiki_splice_puts_figure_in_observations "
        f"n={len(spliced)} last={spliced[-1].packager_source}"
    )


def test_d2c_not_bare_digit_run():
    """Splice uses line_is_price_like; 1958 year / 1830 id are not D2c."""
    html = _cands_from_json(WIKI / "step_003_candidates.json")
    for c in html:
        for ln in list(c.evidence or []) + list(c.identity_hints or []):
            if "1830" in ln or "1958" in ln:
                assert not line_is_price_like(ln), ln
    infobox_line = "Bevolkingsdichtheid\t198.674 (01/01/2026)"
    assert line_is_price_like(infobox_line)
    print("OK test_d2c_not_bare_digit_run")


def test_negative_priced_html_does_not_splice():
    """Coolblue-like: HTML cards already have D2c → no extra text unit."""
    html = [
        Candidate(
            candidate_id="c0",
            identity_hints=["VICTUS 16"],
            evidence=["VICTUS 16", "1.499,-"],
            primary_action={"text": "VICTUS 16", "href": "https://example.test/a"},
            packager_source="html_structure",
            digit_run_count=2,
            currency_glyph_count=0,
        )
    ]
    text = [
        Candidate(
            candidate_id="u0",
            identity_hints=["VICTUS 16"],
            evidence=["VICTUS 16", "1.499,-", "1.649,-", "1.349,-"],
            packager_source="blank_block",
            digit_run_count=6,
        )
    ]
    out = splice_unrepresented_price_like_text(html, text)
    assert out is html or _fp(out) == _fp(html)
    assert len(out) == 1
    print("OK test_negative_priced_html_does_not_splice")


def test_negative_arxiv_pagination_below_threshold():
    """arXiv chrome 100/200 is two D2c lines — below T=3, no splice."""
    html = [
        Candidate(
            candidate_id="c0",
            identity_hints=["Paper title one"],
            evidence=["Paper title one", "arXiv:2609.18128"],
            primary_action={"text": "pdf", "href": "https://arxiv.org/abs/2609.18128"},
            packager_source="html_structure",
            digit_run_count=3,
            n_lines=2,
        )
    ]
    text = [
        Candidate(
            candidate_id="u0",
            identity_hints=["Showing results"],
            evidence=["Showing 1–50 of 1,934 results for all: agents"],
            packager_source="blank_block",
            digit_run_count=3,
        ),
        Candidate(
            candidate_id="u1",
            identity_hints=["results per page"],
            evidence=["100", "200"],
            packager_source="blank_block",
            digit_run_count=2,
        ),
    ]
    out = splice_unrepresented_price_like_text(html, text)
    assert len(out) == 1, [c.packager_source for c in out]
    assert out[0].packager_source == "html_structure"
    print("OK test_negative_arxiv_pagination_below_threshold")


def _regression_case(label: str, text_p: Path, aff_p: Path, url: str, surface: str):
    if not text_p.is_file():
        print(f"SKIP {label} missing {text_p}")
        return
    text = text_p.read_text(encoding="utf-8", errors="replace")
    aff = json.loads(aff_p.read_text()) if aff_p.is_file() else []
    # Text-only extract: splice is HTML-replace-only, so html="" is a
    # byte-identity regression of the non-replace arm.
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
    print(f"OK regression {label} text-arm n={len(a)}")


def test_regression_01_02_03_05_06_text_arm_unchanged():
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
    ]
    for label, text_p, aff_p, url, surface in cases:
        _regression_case(label, text_p, aff_p, url, surface)
    print("OK test_regression_01_02_03_05_06_text_arm_unchanged")


def test_negative_03_05_recorded_html_no_unwanted_splice():
    """Recorded HTML-replace steps: Coolblue has D2c; arXiv below T=3."""
    cases = [
        (
            "03",
            EVALS
            / "20260919T064948Z_03_web_product_gpu"
            / "trace/artifacts/step_003_candidates.json",
            EVALS
            / "20260919T064948Z_03_web_product_gpu"
            / "trace/artifacts/step_003_page_text.txt",
            EVALS
            / "20260919T064948Z_03_web_product_gpu"
            / "trace/artifacts/step_003_affordances.json",
            "https://www.coolblue.be/nl/zoeken",
            True,
        ),
        (
            "05",
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "trace/artifacts/step_002_candidates.json",
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "trace/artifacts/step_002_page_text.txt",
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "trace/artifacts/step_002_affordances.json",
            "https://arxiv.org/search/?query=large+language+model+agents+tool+use",
            False,
        ),
    ]
    for label, cand_p, text_p, aff_p, url, expect_html_d2c in cases:
        if not cand_p.is_file() or not text_p.is_file():
            print(f"SKIP {label} missing artifacts")
            continue
        html = _cands_from_json(cand_p)
        if not html:
            print(f"SKIP {label} no candidates")
            continue
        aff = json.loads(aff_p.read_text()) if aff_p.is_file() else []
        raw = _text_cands(text_p.read_text(encoding="utf-8"), aff, url, "list_results")
        before = _fp(html)
        has_d2c = html_cards_have_price_like(html)
        if expect_html_d2c:
            assert has_d2c, label
        out = splice_unrepresented_price_like_text(list(html), raw)
        assert len(out) == len(html), (
            label,
            len(out),
            [c.packager_source for c in out],
            _blob(out)[:300],
        )
        if has_d2c:
            assert _fp(out) == before, label
        print(
            f"OK negative recorded {label} html_d2c={has_d2c} n={len(out)}"
        )
    print("OK test_negative_03_05_recorded_html_no_unwanted_splice")


def main() -> None:
    test_wiki_units_had_figure_html_candidates_did_not()
    test_not_rank_loss_text_arm_keeps_figure()
    test_wiki_splice_puts_figure_in_observations()
    test_d2c_not_bare_digit_run()
    test_negative_priced_html_does_not_splice()
    test_negative_arxiv_pagination_below_threshold()
    test_regression_01_02_03_05_06_text_arm_unchanged()
    test_negative_03_05_recorded_html_no_unwanted_splice()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
