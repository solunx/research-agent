#!/usr/bin/env python3
"""
Offline tests for Open #24b Fase 1 — affordance identity is (text, href),
not text alone.

Live citation (`20260917T111714Z` / `20260917T153607Z` search step 002):
  page_text has 19 paper-ids of the form `arXiv:NNNN  [pdf, ps, other]`
  (two cards are `[pdf]` only). `step_002_affordances.json` has exactly
  one `"text": "pdf"` → `https://arxiv.org/pdf/2609.19059`.

Cause (JS `push()` before this patch):
  const key = (kind + '|' + text.lower() + '|' + name + '|' + id)  // no href
  const textKey = 'T|' + text.lower();  // collapses later "pdf" links

No network, no LLM, no GPU. Reconstructs the search DOM from captured
page_text (visible labels + distinct hrefs), then runs the Python mirror
of `push()`. Does not invent a "pdf" lexicon: bracket tokens in the
captured text are the visible link labels; hrefs are `/{token}/{id}`.
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from browser import (  # noqa: E402
    affordance_identity_accepts,
    filter_affordances_by_identity,
)

HERE = Path(__file__).resolve().parent
# 111714Z and 153607Z step_002 page_text + affordances are byte-identical.
FIXTURE_TEXT = HERE / "fixture_05_111714Z_step_002_page_text.txt"
FIXTURE_AFF = HERE / "fixture_05_111714Z_step_002_affordances.json"
TRACE_LABELS = ("111714Z", "153607Z")

# Captured flattened list-card line (111714Z step_002_page_text.txt L50):
#   arXiv:2609.19059  [pdf, ps, other]
CARD_RE = re.compile(r"arXiv:(\d{4}\.\d+)\s*\[([^\]]+)\]", re.I)


def _legacy_text_only_filter(raw: list[dict]) -> list[dict]:
    """Pre-Fase-1 JS push() identity: key omits href; textKey is text-only."""
    seen: set[str] = set()
    out: list[dict] = []
    for item in raw:
        kind = str(item.get("kind") or "link")
        text_n = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        extra_name = str(item.get("name") or "")
        extra_id = str(item.get("id") or "")
        is_input = kind == "input_field"
        if not is_input and (not text_n or len(text_n) < 2 or len(text_n) > 100):
            continue
        key = f"{kind}|{text_n.lower()}|{extra_name}|{extra_id}"
        text_key = f"T|{text_n.lower()}"
        if key in seen:
            continue
        if not is_input and text_n and text_key in seen and kind != "tab":
            continue
        seen.add(key)
        if text_n:
            seen.add(text_key)
        out.append(item)
    return out


def reconstruct_search_links_from_page_text(page_text: str) -> list[dict]:
    """Turn captured `arXiv:ID [label, …]` lines into one link per (label, id).

    Structural only: the bracket tokens are the visible texts on the page;
    each token+id pair gets its own href so identity can see they differ.
    """
    raw: list[dict] = []
    for m in CARD_RE.finditer(page_text):
        paper_id = m.group(1)
        raw.append(
            {
                "kind": "link",
                "text": f"arXiv:{paper_id}",
                "href": f"https://arxiv.org/abs/{paper_id}",
            }
        )
        for token in (t.strip() for t in m.group(2).split(",")):
            if not token:
                continue
            raw.append(
                {
                    "kind": "link",
                    "text": token,
                    "href": f"https://arxiv.org/{token}/{paper_id}",
                }
            )
    return raw


def _pdf_items(items: list[dict]) -> list[dict]:
    return [
        it
        for it in items
        if re.sub(r"\s+", " ", str(it.get("text") or "")).strip().lower() == "pdf"
    ]


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        d = {k: (v or "") for k, v in attrs}
        self._href = d.get("href", "")
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        text = re.sub(r"\s+", " ", "".join(self._parts)).strip()
        self.items.append({"kind": "link", "text": text, "href": self._href})
        self._href = None


def _anchors_from_html(path: Path) -> list[dict]:
    parser = _AnchorCollector()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.items


def test_live_search_affordances_had_one_pdf():
    """Quote the live capture: text-only de-dupe left a single pdf href."""
    aff = json.loads(FIXTURE_AFF.read_text(encoding="utf-8"))
    pdfs = _pdf_items(aff)
    hrefs = sorted({str(it.get("href") or "") for it in pdfs})
    assert len(pdfs) == 1, f"live pdf count={len(pdfs)}"
    assert hrefs == ["https://arxiv.org/pdf/2609.19059"], hrefs
    for label in TRACE_LABELS:
        print(f"LIVE {label} step_002_affordances pdf_n=1 href={hrefs[0]}")
    print("OK test_live_search_affordances_had_one_pdf")


def test_reconstructed_search_keeps_distinct_pdf_hrefs():
    """Mandatory negative vs old rule: 19 unique pdf hrefs survive (text, href)."""
    text = FIXTURE_TEXT.read_text(encoding="utf-8")
    ids = CARD_RE.findall(text)
    paper_ids = [m[0] for m in ids]
    assert len(paper_ids) >= 19, f"paper_ids={len(paper_ids)}"
    assert len(set(paper_ids)) == len(paper_ids)
    raw = reconstruct_search_links_from_page_text(text)
    old = _legacy_text_only_filter(raw)
    new = filter_affordances_by_identity(raw)
    old_pdf = _pdf_items(old)
    new_pdf = _pdf_items(new)
    new_hrefs = [str(it.get("href") or "") for it in new_pdf]
    assert len(old_pdf) == 1, f"legacy pdf_n={len(old_pdf)}"
    assert old_pdf[0]["href"].endswith("/pdf/2609.19059")
    assert len(new_pdf) == len(paper_ids), (
        f"new pdf_n={len(new_pdf)} paper_ids={len(paper_ids)}"
    )
    assert len(set(new_hrefs)) == len(new_hrefs)
    assert len(set(new_hrefs)) > 1
    for pid in paper_ids:
        assert f"https://arxiv.org/pdf/{pid}" in new_hrefs
    for label in TRACE_LABELS:
        print(
            f"RECON {label} paper_ids={len(paper_ids)} "
            f"legacy_pdf={len(old_pdf)} new_pdf={len(new_pdf)} "
            f"unique_hrefs={len(set(new_hrefs))}"
        )
    print("OK test_reconstructed_search_keeps_distinct_pdf_hrefs")


def test_same_text_href_still_collapses():
    """Negative: exact (text, href) duplicates still de-dupe to one."""
    raw = [
        {"kind": "link", "text": "pdf", "href": "https://arxiv.org/pdf/2609.19059"},
        {"kind": "link", "text": "pdf", "href": "https://arxiv.org/pdf/2609.19059"},
        {"kind": "link", "text": "pdf", "href": "https://arxiv.org/pdf/2609.18736"},
    ]
    out = filter_affordances_by_identity(raw)
    hrefs = [it["href"] for it in out]
    assert hrefs == [
        "https://arxiv.org/pdf/2609.19059",
        "https://arxiv.org/pdf/2609.18736",
    ]
    seen: set[str] = set()
    assert affordance_identity_accepts(
        seen, kind="link", text="pdf", href="https://arxiv.org/pdf/1"
    )
    assert not affordance_identity_accepts(
        seen, kind="link", text="pdf", href="https://arxiv.org/pdf/1"
    )
    print("OK test_same_text_href_still_collapses")


def test_01_02_06_affordance_counts_unchanged():
    """Regression: 01/02/06 have unique (text) labels, so counts must match."""
    cases = [
        (
            "01_flamenco_price_surface",
            ROOT
            / "evals/candidate_offline/fixtures_from_traces/01_price_surface"
            / "step_000_affordances.json",
        ),
        (
            "02_monica_detail",
            ROOT
            / "evals/candidate_offline/fixtures_from_traces/02_detail"
            / "step_000_affordances.json",
        ),
        (
            "06_wiki_fuerteventura",
            ROOT / "evals/long_line_units/fixture_06_wiki_affordances.json",
        ),
    ]
    for label, path in cases:
        saved = json.loads(path.read_text(encoding="utf-8"))
        old = _legacy_text_only_filter(saved)
        new = filter_affordances_by_identity(saved)
        old_keys = [(it.get("text"), it.get("href")) for it in old]
        new_keys = [(it.get("text"), it.get("href")) for it in new]
        assert len(old) == len(saved), f"{label}: legacy dropped saved items"
        assert len(new) == len(saved), f"{label}: new dropped saved items"
        assert old_keys == new_keys, f"{label}: (text,href) set changed"
        print(f"REGRESSION saved {label} n={len(saved)} old=new")

    html_cases = [
        (
            "01_flamenco_price_surface_html",
            ROOT / "evals/candidate_offline/fixtures_from_traces/01_price_surface/page.html",
        ),
        (
            "02_monica_detail_html",
            ROOT / "evals/candidate_offline/fixtures_from_traces/02_detail/page.html",
        ),
    ]
    for label, path in html_cases:
        raw = _anchors_from_html(path)
        old = _legacy_text_only_filter(raw)
        new = filter_affordances_by_identity(raw)
        assert len(old) == len(new), (
            f"{label}: html identity count old={len(old)} new={len(new)}"
        )
        old_keys = [(it.get("text"), it.get("href")) for it in old]
        new_keys = [(it.get("text"), it.get("href")) for it in new]
        assert old_keys == new_keys, f"{label}: html (text,href) order/set changed"
        print(f"REGRESSION html {label} n={len(new)} old=new")
    print("OK test_01_02_06_affordance_counts_unchanged")


def main():
    test_live_search_affordances_had_one_pdf()
    test_reconstructed_search_keeps_distinct_pdf_hrefs()
    test_same_text_href_still_collapses()
    test_01_02_06_affordance_counts_unchanged()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
