"""
Pilot datasets + oracles for candidate selection campaign.

Oracle labels: RELEVANT | IRRELEVANT | AMBIGUOUS
No implementation-derived labels.
"""
from __future__ import annotations

from typing import Any

from .contract import CandidateUnit, TaskContext


def pilot_web_travel() -> dict[str, Any]:
    task = TaskContext(
        task_id="web_packages_ai_flight",
        task_text=(
            "Find all-inclusive flight+hotel packages for 3 adults from Brussels "
            "in December 2026 with visible price and board type on the offer card."
        ),
        domain="web",
    )
    units_oracle: list[tuple[CandidateUnit, str]] = [
        (
            CandidateUnit(
                unit_id="w1",
                text="Grand Park Lara All Inclusive Resort",
                element_type="card_title",
                neighbors=["All-inclusive", "Heen- en terugvluchten vanaf Brussel", "€ 849"],
                raw_evidence="All-inclusive | Heen- en terugvluchten vanaf Brussel | € 849",
                entity_score=0.85,
                source_url="https://example.com/s/tsx?meal=all-inclusive",
            ),
            "RELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="w2",
                text="Sercotel Playa Canteras",
                element_type="card_title",
                neighbors=["Enkel kamer", "Heen- en terugvluchten vanaf Brussel", "€ 2.275"],
                raw_evidence="Enkel kamer | Heen- en terugvluchten vanaf Brussel | € 2.275",
                entity_score=0.85,
            ),
            "RELEVANT",  # real offer card (even if board fails later)
        ),
        (
            CandidateUnit(
                unit_id="w3",
                text="Gran Canaria",
                element_type="entity",
                neighbors=["Spanje", "Rechtstreekse vlucht inbegrepen", "€ 2.328"],
                raw_evidence="Spanje | Rechtstreekse vlucht inbegrepen | Hotel | € 2.328",
                entity_score=0.75,
            ),
            "AMBIGUOUS",  # destination aggregate
        ),
        (
            CandidateUnit(
                unit_id="w4",
                text="Vragen & Contact",
                element_type="nav",
                neighbors=["Geen brandstoftoeslag"],
                entity_score=0.2,
            ),
            "IRRELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="w5",
                text="Smullen geblazen door de Ultra All Inclusive formule",
                element_type="chrome",
                neighbors=["va 560 p.p."],
                entity_score=0.25,
            ),
            "IRRELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="w6",
                text="Pakket bekijken",
                element_type="cta",
                neighbors=[],
            ),
            "IRRELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="w7",
                text="Lopesan Costa Meloneras Resort & Spa",
                element_type="card_title",
                neighbors=["Enkel kamer", "Heen- en terugvluchten vanaf Brussel", "€ 698"],
                raw_evidence="Enkel kamer | Heen- en terugvluchten vanaf Brussel | € 698",
                entity_score=0.85,
            ),
            "RELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="w8",
                text="Blue Bay AI Resort",
                element_type="offer_card",
                neighbors=["All inclusive", "Flight included from Brussels", "€ 910"],
                raw_evidence="All inclusive | Flight included from Brussels | € 910",
                entity_score=0.9,
            ),
            "RELEVANT",
        ),
    ]
    return {"task": task, "items": units_oracle, "dataset_id": "pilot_web_travel"}


def pilot_literature() -> dict[str, Any]:
    task = TaskContext(
        task_id="lit_rct_results",
        task_text=(
            "Find randomized controlled trials comparing drug A versus standard care "
            "and extract the primary outcome results."
        ),
        domain="literature",
    )
    units_oracle: list[tuple[CandidateUnit, str]] = [
        (
            CandidateUnit(
                unit_id="l1",
                text="We conducted a randomised, double-blind, placebo-controlled trial in 412 adults.",
                element_type="paragraph",
                path="paper/methods",
                neighbors=["Primary endpoint was 12-week remission."],
            ),
            "RELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="l2",
                text="Corresponding author: Jane Doe, Department of Medicine.",
                element_type="footer",
                path="paper/footer",
            ),
            "IRRELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="l3",
                text="Keywords: diabetes, insulin, HbA1c",
                element_type="ui_label",
            ),
            "IRRELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="l4",
                text="Primary outcome: mean HbA1c reduction −1.2% (95% CI −1.5 to −0.9) versus control.",
                element_type="paragraph",
                path="paper/results",
                neighbors=["Table 2"],
            ),
            "RELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="l5",
                text="Narrative review of recent advances in the field.",
                element_type="paragraph",
                path="paper/intro",
            ),
            "IRRELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="l6",
                text="Systematic review and meta-analysis of 28 trials on treatment X.",
                element_type="title",
                path="paper/title",
            ),
            "AMBIGUOUS",  # review, not RCT of drug A
        ),
    ]
    return {"task": task, "items": units_oracle, "dataset_id": "pilot_literature"}


def pilot_code() -> dict[str, Any]:
    task = TaskContext(
        task_id="code_auth_handlers",
        task_text=(
            "Identify functions that implement authentication or session validation "
            "in this codebase snippet set."
        ),
        domain="code",
    )
    units_oracle: list[tuple[CandidateUnit, str]] = [
        (
            CandidateUnit(
                unit_id="c1",
                text="def verify_session_token(token: str) -> User:\n    ...",
                element_type="function_def",
                path="auth/session.py",
                neighbors=["raise AuthError"],
            ),
            "RELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="c2",
                text="def format_price(cents: int) -> str:\n    return f'€{cents/100:.2f}'",
                element_type="function_def",
                path="pricing/format.py",
            ),
            "IRRELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="c3",
                text="# TODO: clean up logging",
                element_type="comment",
                path="utils/log.py",
            ),
            "IRRELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="c4",
                text="class LoginHandler(BaseHandler):\n    def post(self):\n        check_password(...)",
                element_type="function_def",
                path="http/login.py",
                neighbors=["check_password"],
            ),
            "RELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="c5",
                text="AUTH_COOKIE_NAME = 'sid'",
                element_type="list_item",
                path="auth/constants.py",
            ),
            "AMBIGUOUS",
        ),
    ]
    return {"task": task, "items": units_oracle, "dataset_id": "pilot_code"}


def pilot_documents() -> dict[str, Any]:
    task = TaskContext(
        task_id="doc_findings_claim",
        task_text=(
            "Extract findings that support the claim that remote work increased "
            "productivity in the studied cohort."
        ),
        domain="documents",
    )
    units_oracle: list[tuple[CandidateUnit, str]] = [
        (
            CandidateUnit(
                unit_id="d1",
                text="Table 3: Productivity rose 12% (p<0.01) among remote workers versus office baseline.",
                element_type="table_row",
                path="report.docx/table3",
                neighbors=["n=1,204"],
            ),
            "RELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="d2",
                text="Agenda — Q3 planning workshop",
                element_type="heading",
                path="slides.pptx/slide1",
            ),
            "IRRELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="d3",
                text="We observed higher output per hour in the remote arm after controlling for tenure.",
                element_type="paragraph",
                path="report.docx/discussion",
            ),
            "RELEVANT",
        ),
        (
            CandidateUnit(
                unit_id="d4",
                text="Page 1 of 48 — Confidential",
                element_type="footer",
            ),
            "IRRELEVANT",
        ),
    ]
    return {"task": task, "items": units_oracle, "dataset_id": "pilot_documents"}


ALL_PILOTS = {
    "pilot_web_travel": pilot_web_travel,
    "pilot_literature": pilot_literature,
    "pilot_code": pilot_code,
    "pilot_documents": pilot_documents,
}
