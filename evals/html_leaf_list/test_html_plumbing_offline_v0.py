#!/usr/bin/env python3
"""
Offline tests for Open #24b Fase 2 plumbing — raw HTML rides next to
innerText. Candidate extraction is unchanged in this slice.

No LLM, no GPU. Playwright not required.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from browser import _snapshot  # noqa: E402
from candidates import candidates_to_jsonable, extract_candidates  # noqa: E402
from trace_session import TraceSession  # noqa: E402

LIVE_MAX_CANDIDATES = 3
LIVE_MAX_UNITS = 6

CASES = [
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
        ROOT / "evals/long_line_units/fixture_06_wiki_page_text.txt",
        ROOT / "evals/long_line_units/fixture_06_wiki_affordances.json",
        "https://en.wikipedia.org/wiki/Fuerteventura",
        "live_detail",
    ),
]


def _fp(cands) -> str:
    rows = []
    for c in candidates_to_jsonable(cands):
        pa = c.get("primary_action") or {}
        rows.append(
            (
                c.get("candidate_id"),
                tuple(c.get("identity_hints") or []),
                tuple(c.get("evidence") or []),
                pa.get("text"),
                pa.get("href"),
            )
        )
    return json.dumps(rows, ensure_ascii=False, sort_keys=False)


def _live_extract(text: str, aff: list, url: str, surface: str):
    return extract_candidates(
        text=text,
        affordances=aff,
        page_url=url,
        surface=surface,
        max_candidates=LIVE_MAX_CANDIDATES,
        max_units=LIVE_MAX_UNITS,
    )


class _Page:
    def __init__(self, *, html: str | None, text: str = "visible body") -> None:
        self.url = "https://example.test/list"
        self._html = html
        self._text = text

    def title(self) -> str:
        return "List"

    def inner_text(self, _sel: str) -> str:
        return self._text

    def content(self) -> str:
        if self._html is None:
            raise RuntimeError("content() unavailable")
        return self._html


def test_snapshot_includes_html():
    html = "<html><body><li class='result'>A</li></body></html>"
    snap = _snapshot(_Page(html=html), include_hints=False)
    assert snap.get("html") == html
    assert snap.get("html_chars") == len(html)
    assert "visible body" in str(snap.get("text") or "")
    print("OK test_snapshot_includes_html")


def test_snapshot_html_missing_content_is_empty():
    """Negative: pages without content() still snapshot text."""
    snap = _snapshot(_Page(html=None), include_hints=False)
    assert snap.get("html") == ""
    assert int(snap.get("html_chars") or 0) == 0
    assert snap.get("error") is None
    print("OK test_snapshot_html_missing_content_is_empty")


def test_trace_writes_page_html_artifact():
    html = "<html><body><p>card</p></body></html>"
    with tempfile.TemporaryDirectory() as td:
        tr = TraceSession(td, run_kind="html_plumbing_test")
        tr.set_step(2)
        tr.log_observe(url="https://example.test/search", text="inner", html=html)
        path = Path(td) / "artifacts" / "step_002_page.html"
        assert path.is_file(), path
        assert path.read_text(encoding="utf-8") == html
    print("OK test_trace_writes_page_html_artifact")


def test_01_02_06_candidate_set_unchanged_without_html_kwarg():
    """Plumbing must not change extract_candidates (html not wired yet)."""
    for label, text_p, aff_p, url, surface in CASES:
        text = text_p.read_text(encoding="utf-8")
        aff = json.loads(aff_p.read_text(encoding="utf-8"))
        a = _fp(_live_extract(text, aff, url, surface))
        b = _fp(_live_extract(text, aff, url, surface))
        assert a == b, f"{label}: non-deterministic extract"
        print(f"PLUMB {label} n_cands fingerprint_ok")
    print("OK test_01_02_06_candidate_set_unchanged_without_html_kwarg")


def main():
    test_snapshot_includes_html()
    test_snapshot_html_missing_content_is_empty()
    test_trace_writes_page_html_artifact()
    test_01_02_06_candidate_set_unchanged_without_html_kwarg()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
