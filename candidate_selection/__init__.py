"""Candidate selection experiment package (structural vs LLM vs hybrid)."""

from .contract import (
    CandidateDecision,
    CandidateUnit,
    SelectionResult,
    TaskContext,
)
from .metrics import score_predictions

__all__ = [
    "CandidateDecision",
    "CandidateUnit",
    "SelectionResult",
    "TaskContext",
    "score_predictions",
]
