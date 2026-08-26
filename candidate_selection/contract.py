"""
Generic candidate-selection contract.

Selectors emit ADMISSIBLE | NOT_ADMISSIBLE | UNKNOWN only.
They must NOT emit domain outcomes (ROOM_ONLY, RCT, etc.).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CandidateDecision(str, Enum):
    ADMISSIBLE = "ADMISSIBLE"
    NOT_ADMISSIBLE = "NOT_ADMISSIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class TaskContext:
    """User task shared with every selector (no domain ontology)."""

    task_id: str
    task_text: str
    domain: str  # web | literature | documents | code — for reporting only
    notes: str = ""


@dataclass
class CandidateUnit:
    """
    One selectable unit from a source surface.

    Structural fields are optional; methods that need them degrade to UNKNOWN
    when absent (fail-closed), they must not invent semantics.
    """

    unit_id: str
    text: str
    # Structural grounding (optional)
    element_type: str | None = None  # e.g. heading, card_title, paragraph, function, table_cell
    parent_id: str | None = None
    source_url: str | None = None
    path: str | None = None  # file path / DOM path
    neighbors: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    # Optional scores from harvest (not semantic labels)
    entity_score: float | None = None
    raw_evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelectionResult:
    unit_id: str
    decision: CandidateDecision
    reason: str
    confidence: str = "medium"  # low | medium | high
    evidence_refs: list[str] = field(default_factory=list)
    method_id: str = ""
    latency_ms: float = 0.0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d


# Oracle labels use the same vocabulary as decisions for scoring alignment.
ORACLE_LABELS = ("RELEVANT", "IRRELEVANT", "AMBIGUOUS")


def oracle_to_decision(oracle: str) -> CandidateDecision:
    """Map annotation labels to decision space for metrics."""
    o = (oracle or "").upper()
    if o == "RELEVANT":
        return CandidateDecision.ADMISSIBLE
    if o == "IRRELEVANT":
        return CandidateDecision.NOT_ADMISSIBLE
    return CandidateDecision.UNKNOWN
