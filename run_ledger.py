"""
Run Evidence Ledger v0 — observe the pipeline; do not steer it.

Side-branch telemetry for scientific post-mortems:
  actions, observations, LLM decision records, stop_reason, costs.

No automatic prompt/model updates from this layer.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class LedgerAction:
    action_type: str
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    error: str | None = None


@dataclass
class LedgerDecision:
    stage: str  # candidate_unit | interpretation | eligibility | other
    timestamp: str
    decision_id: str | None = None
    outcome: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class RunLedger:
    """Append-only run record. Write JSON at end (and optionally incrementally)."""

    def __init__(
        self,
        *,
        task_text: str = "",
        run_kind: str = "live_detail_slice",
        run_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        self.created_at = _utc_iso()
        self.task_text = task_text
        self.run_kind = run_kind
        self.meta = meta or {}
        self.actions: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.stop_reason: str | None = None
        self.pipeline_summary: dict[str, Any] = {}
        self.trace_stages: dict[str, Any] = {}
        self.metrics: dict[str, Any] = {}
        self._t0 = time.monotonic()

    def log_action(
        self,
        action_type: str,
        *,
        payload: dict[str, Any] | None = None,
        result_summary: dict[str, Any] | None = None,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        self.actions.append(
            {
                "action_type": action_type,
                "timestamp": _utc_iso(),
                "payload": payload or {},
                "result_summary": result_summary or {},
                "ok": ok,
                "error": error,
            }
        )

    def log_observations(self, obs: list[dict[str, Any]]) -> None:
        for o in obs:
            self.observations.append(dict(o))

    def log_decision(
        self,
        stage: str,
        *,
        decision_id: str | None = None,
        outcome: str | None = None,
        evidence_refs: list[str] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.decisions.append(
            {
                "stage": stage,
                "timestamp": _utc_iso(),
                "decision_id": decision_id,
                "outcome": outcome,
                "evidence_refs": evidence_refs or [],
                "raw": raw or {},
            }
        )

    def log_event(self, name: str, data: dict[str, Any] | None = None) -> None:
        self.events.append({"name": name, "timestamp": _utc_iso(), "data": data or {}})

    def set_stop(self, reason: str) -> None:
        self.stop_reason = reason
        self.log_event("stop", {"reason": reason})

    def duration_s(self) -> float:
        return round(time.monotonic() - self._t0, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "run-evidence-ledger-v0",
            "run_id": self.run_id,
            "created_at": self.created_at,
            "run_kind": self.run_kind,
            "task_text": self.task_text,
            "meta": self.meta,
            "stop_reason": self.stop_reason,
            "duration_s": self.duration_s(),
            "actions": self.actions,
            "observations": self.observations,
            "decisions": self.decisions,
            "events": self.events,
            "pipeline_summary": self.pipeline_summary,
            "trace_stages": self.trace_stages,
            "metrics": self.metrics,
            "counts": {
                "actions": len(self.actions),
                "observations": len(self.observations),
                "decisions": len(self.decisions),
            },
        }

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path
