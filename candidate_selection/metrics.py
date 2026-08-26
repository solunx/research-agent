"""Metrics for candidate selection (no blended suite score)."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .contract import CandidateDecision, oracle_to_decision


def score_predictions(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    rows: each has oracle (RELEVANT|IRRELEVANT|AMBIGUOUS) and prediction (decision).
    RELEVANT ↔ ADMISSIBLE, IRRELEVANT ↔ NOT_ADMISSIBLE, AMBIGUOUS ↔ UNKNOWN for match.
    """
    tp = fp = fn = tn = 0
    amb_correct = amb_total = 0
    confusion: dict[str, Counter] = {}
    n = 0
    for r in rows:
        oracle = str(r.get("oracle") or "AMBIGUOUS").upper()
        pred = str(r.get("prediction") or r.get("decision") or "UNKNOWN").upper()
        n += 1
        confusion.setdefault(oracle, Counter())[pred] += 1
        expected = oracle_to_decision(oracle).value
        if oracle == "AMBIGUOUS":
            amb_total += 1
            if pred == CandidateDecision.UNKNOWN.value:
                amb_correct += 1
            continue
        # Binary relevance metrics on RELEVANT vs IRRELEVANT
        if oracle == "RELEVANT" and pred == "ADMISSIBLE":
            tp += 1
        elif oracle == "RELEVANT" and pred != "ADMISSIBLE":
            fn += 1
        elif oracle == "IRRELEVANT" and pred == "ADMISSIBLE":
            fp += 1
        elif oracle == "IRRELEVANT" and pred != "ADMISSIBLE":
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    fnr = fn / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0

    return {
        "n": n,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_negative_rate": fnr,
        "false_positive_rate": fpr,
        "ambiguous_unknown_rate": (amb_correct / amb_total) if amb_total else None,
        "n_ambiguous": amb_total,
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }
