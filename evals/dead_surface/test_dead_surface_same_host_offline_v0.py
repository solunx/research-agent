#!/usr/bin/env python3
"""
Offline tests: Open #30 second-order dead surface (2a, same-host http).

NOT 2b (HTTP status tokens). No lexicon. No network, no LLM, no GPU.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from candidate_units import package_candidate_units  # noqa: E402
from live_offer_state_slice import (  # noqa: E402
    DEAD_SURFACE_NO_SAME_HOST_STOP_REASON,
    DEAD_SURFACE_STOP_REASON,
    is_dead_surface,
    is_dead_surface_no_same_host,
    same_host_http_affordance_count,
)

EVALS = ROOT / "evals" / "contract_driven"
FIX = ROOT / "evals" / "candidate_offline" / "fixtures_from_traces"
BOL_DIR = EVALS / "20260919T131049Z_bol_airpods_pro"
TUI_DIR = EVALS / "20260919T111126Z_tui_package_crete"

CONTACT_MAILTO_ONLY = [
    {
        "kind": "link",
        "text": "write us",
        "href": "mailto:desk@example.org",
        "scope": "global",
    },
    {
        "kind": "link",
        "text": "call",
        "href": "tel:+3200000000",
        "scope": "global",
    },
]


def _units(text: str, aff: list, url: str) -> list:
    return package_candidate_units(
        text=text,
        affordances=aff,
        page_url=url,
        max_units=6,
        max_lines_per_unit=8,
    )


def _dead2(*, url: str, aff: list, units_n: int, fetch_ok: bool = True, text_chars: int = 500):
    d1 = is_dead_surface(
        fetch_ok=fetch_ok,
        affordances_count=len(aff),
        candidate_units_count=units_n,
        text_chars=text_chars,
    )
    return d1, is_dead_surface_no_same_host(
        fetch_ok=fetch_ok,
        page_url=url,
        affordances=aff,
        candidate_units_count=units_n,
        first_order_dead=d1,
    )


def test_stop_reason_distinct_from_fix1():
    assert DEAD_SURFACE_NO_SAME_HOST_STOP_REASON == "DEAD_SURFACE_NO_SAME_HOST_CONTENT"
    assert DEAD_SURFACE_NO_SAME_HOST_STOP_REASON != DEAD_SURFACE_STOP_REASON
    print("OK test_stop_reason_distinct_from_fix1")


def test_mailto_and_other_host_do_not_count():
    url = "https://www.bol.com/"
    aff = [
        {"href": "mailto:customerservice@bol.com"},
        {"href": "https://whatismyip.akamai.com/"},
        {"href": "https://developers.bol.com/"},
    ]
    assert same_host_http_affordance_count(page_url=url, affordances=aff) == 0
    relative = [{"href": "/nl/p/x"}]
    assert same_host_http_affordance_count(page_url=url, affordances=relative) == 1
    print("OK test_mailto_and_other_host_do_not_count")


def test_reconstruct_bol_131049Z_triggers_2a_not_fix1():
    text = (BOL_DIR / "trace/artifacts/step_000_page_text.txt").read_text(
        encoding="utf-8"
    )
    aff = json.loads(
        (BOL_DIR / "trace/artifacts/step_000_affordances.json").read_text(
            encoding="utf-8"
        )
    )
    url = "https://www.bol.com/"
    units = _units(text, aff, url)
    d1, d2 = _dead2(url=url, aff=aff, units_n=len(units), text_chars=len(text))
    assert len(aff) == 3, len(aff)
    assert len(units) == 2, len(units)
    assert same_host_http_affordance_count(page_url=url, affordances=aff) == 0
    assert not d1, "FIX 1 must stay false on bol"
    assert d2, (len(aff), len(units), len(text))
    print(
        "OK test_reconstruct_bol_131049Z_triggers_2a_not_fix1",
        DEAD_SURFACE_NO_SAME_HOST_STOP_REASON,
    )


def test_negative_06_wiki_same_host_does_not_trigger():
    """06 Fuerteventura: many en.wikipedia.org hrefs. Must not be 2a-dead."""
    loop = json.loads(
        (
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "loop_06_web_wiki_fact_20260916T064738Z.json"
        ).read_text(encoding="utf-8")
    )
    step0 = (loop.get("steps") or [])[0]
    aff = json.loads(
        (
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "trace/artifacts/step_000_affordances.json"
        ).read_text(encoding="utf-8")
    )
    url = str(step0.get("url") or "https://en.wikipedia.org/wiki/Fuerteventura")
    n_same = same_host_http_affordance_count(page_url=url, affordances=aff)
    assert n_same >= 1, n_same
    d1, d2 = _dead2(
        url=url,
        aff=aff,
        units_n=int(step0.get("candidate_units_n") or 0),
        text_chars=int(step0.get("text_chars") or 0),
    )
    assert not d1
    assert not d2, n_same
    print(
        "OK test_negative_06_wiki_same_host_does_not_trigger",
        f"aff={len(aff)} same_host_http={n_same}",
    )


def test_contact_page_mailto_only_is_accepted_dead_for_this_loop():
    """Task A boundary: 2 units, 0 same-host http, only mailto/tel.

    This IS 2a-dead. The acquisition loop navigates via same-host http(s)
    OPEN_URL. mailto is not that. False-positive class: a sparse page whose
    two units already hold the answer (e.g. the email itself) never reaches
    interpret. Escape: 3+ units, or one same-host http link, keeps interpret.
    Accepted for this agent — documented, not stretched.
    """
    url = "https://www.example.org/contact"
    aff = CONTACT_MAILTO_ONLY
    text = "Office hours Monday–Friday.\nWrite the desk for a paper copy."
    # Predicate input is the loop's candidate_units_count. Two units = Task A case.
    units_n = 2
    d1, d2 = _dead2(url=url, aff=aff, units_n=units_n, text_chars=len(text))
    assert not d1, "mailto means aff>0 so FIX 1 is false"
    assert d2, "0 same-host http + sparse units = 2a dead"
    # One same-host http link must keep the page alive.
    aff_nav = aff + [{"kind": "link", "text": "home", "href": "https://www.example.org/"}]
    d1b, d2b = _dead2(url=url, aff=aff_nav, units_n=units_n, text_chars=len(text))
    assert not d1b and not d2b
    # Three units escape even with 0 same-host http.
    d1c, d2c = _dead2(url=url, aff=aff, units_n=3, text_chars=len(text))
    assert not d1c and not d2c
    print(
        "OK test_contact_page_mailto_only_is_accepted_dead_for_this_loop "
        "(accepted 2a-dead at units=2; +same-host http or units=3 survives)"
    )


def test_tui_stays_fix1_not_2a():
    """#29 owns TUI; 2a must not steal the stop_reason."""
    text = (TUI_DIR / "trace/artifacts/step_000_page_text.txt").read_text(
        encoding="utf-8"
    )
    aff = json.loads(
        (TUI_DIR / "trace/artifacts/step_000_affordances.json").read_text(
            encoding="utf-8"
        )
    )
    url = "https://www.tui.nl/"
    units = _units(text, aff, url)
    d1, d2 = _dead2(url=url, aff=aff, units_n=len(units), text_chars=len(text))
    assert d1
    assert not d2
    print("OK test_tui_stays_fix1_not_2a")


def test_regression_01_02_03_05_06_and_campaign_not_2a():
    cases = [
        (
            "01",
            FIX / "01_price_surface" / "step_000_affordances.json",
            FIX / "01_price_surface" / "step_000_page_text.txt",
            "https://www.corendon.be/egypte/rode-zee/marsa-alam/el-quseir/flamenco-beach-resort",
        ),
        (
            "02",
            FIX / "02_detail" / "step_000_affordances.json",
            FIX / "02_detail" / "step_000_page_text.txt",
            "https://www.corendon.be/spanje/canarische-eilanden/fuerteventura/costa-calma/sbh-monica-beach",
        ),
        (
            "03",
            EVALS
            / "20260919T064948Z_03_web_product_gpu"
            / "trace/artifacts/step_000_affordances.json",
            EVALS
            / "20260919T064948Z_03_web_product_gpu"
            / "trace/artifacts/step_000_page_text.txt",
            "https://www.coolblue.be/nl",
        ),
        (
            "05",
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "trace/artifacts/step_002_affordances.json",
            EVALS
            / "20260918T081459Z_05_web_literature_abstract"
            / "trace/artifacts/step_002_page_text.txt",
            "https://arxiv.org/search/?query=large+language+model+agents+tool+use",
        ),
        (
            "06",
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "trace/artifacts/step_000_affordances.json",
            EVALS
            / "20260916T064738Z_06_web_wiki_fact"
            / "trace/artifacts/step_000_page_text.txt",
            "https://en.wikipedia.org/wiki/Fuerteventura",
        ),
        (
            "marktplaats",
            EVALS
            / "20260919T140350Z_marktplaats_fiets_regio"
            / "trace/artifacts/step_000_affordances.json",
            EVALS
            / "20260919T140350Z_marktplaats_fiets_regio"
            / "trace/artifacts/step_000_page_text.txt",
            "https://www.2dehands.be/",
        ),
        (
            "ss",
            EVALS
            / "20260919T145809Z_semanticscholar_rag_paper"
            / "trace/artifacts/step_001_affordances.json",
            EVALS
            / "20260919T145809Z_semanticscholar_rag_paper"
            / "trace/artifacts/step_001_page_text.txt",
            "https://www.semanticscholar.org/",
        ),
        (
            "wiki_bxl",
            EVALS
            / "20260919T165815Z_wiki_brussels_population"
            / "trace/artifacts/step_000_affordances.json",
            EVALS
            / "20260919T165815Z_wiki_brussels_population"
            / "trace/artifacts/step_000_page_text.txt",
            "https://nl.wikipedia.org/wiki/Brussel_(stad)",
        ),
    ]
    for label, aff_path, text_path, url in cases:
        assert aff_path.is_file(), aff_path
        aff = json.loads(aff_path.read_text(encoding="utf-8"))
        text = text_path.read_text(encoding="utf-8") if text_path.is_file() else "x" * 500
        units = _units(text, aff, url)
        d1, d2 = _dead2(url=url, aff=aff, units_n=len(units), text_chars=len(text))
        n_same = same_host_http_affordance_count(page_url=url, affordances=aff)
        assert not d2, (label, n_same, len(units), len(aff))
        print(f"OK regression {label} same_host_http={n_same} units={len(units)} 2a=False")
    print("OK test_regression_01_02_03_05_06_and_campaign_not_2a")


if __name__ == "__main__":
    test_stop_reason_distinct_from_fix1()
    test_mailto_and_other_host_do_not_count()
    test_reconstruct_bol_131049Z_triggers_2a_not_fix1()
    test_negative_06_wiki_same_host_does_not_trigger()
    test_contact_page_mailto_only_is_accepted_dead_for_this_loop()
    test_tui_stays_fix1_not_2a()
    test_regression_01_02_03_05_06_and_campaign_not_2a()
    print("ALL OK dead_surface same-host 2a offline")
