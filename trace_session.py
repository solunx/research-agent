"""
Trace / observability layer v0 — forensic observer of the agent.

Does NOT steer the agent. Append-only events + optional human audit.

Layout per run:
  <trace_dir>/
    meta.json
    events.jsonl          # one JSON object per line, ordered
    artifacts/
      step_NNN_affordances.json
      step_NNN_claims.json
      llm_NNN_io.json     # truncated prompts + structured output
    audit.md
    audit.json
    summary.json

Event phases (string enum, extensible):
  task_start | contract | observe | affordances | gaps |
  llm_call | code_policy | action | interpret | eligibility |
  acquisition | control | stop | error | flush
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _truncate(s: str, n: int = 4000) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[:n] + f"…[+{len(s) - n} chars]"


def _hash_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


class TraceSession:
    """Append-only forensic log for one task/entity run."""

    def __init__(
        self,
        root: Path | str,
        *,
        task_text: str = "",
        run_kind: str = "traced_run",
        meta: dict[str, Any] | None = None,
        max_text_artifact: int = 8000,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)
        self.task_text = task_text
        self.run_kind = run_kind
        self.meta = meta or {}
        self.run_id = self.meta.get("run_id") or (
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        )
        self.meta["run_id"] = self.run_id
        self.max_text_artifact = max_text_artifact
        self._t0 = time.monotonic()
        self._seq = 0
        self._step = 0
        self.events_path = self.root / "events.jsonl"
        # truncate previous if reusing dir
        if not self.events_path.exists():
            self.events_path.write_text("", encoding="utf-8")
        self._write_meta()
        self.emit(
            "task_start",
            {
                "task_text": _truncate(task_text, 2000),
                "run_kind": run_kind,
                "meta": self.meta,
            },
        )

    def _write_meta(self) -> None:
        payload = {
            "schema": "trace-session-meta-v0",
            "run_id": self.run_id,
            "created_at": _utc_iso(),
            "run_kind": self.run_kind,
            "task_text": self.task_text,
            "meta": self.meta,
        }
        (self.root / "meta.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def set_step(self, step: int) -> None:
        self._step = int(step)

    def emit(self, phase: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self._seq += 1
        ev = {
            "seq": self._seq,
            "step": self._step,
            "phase": phase,
            "t": _utc_iso(),
            "t_rel_s": round(time.monotonic() - self._t0, 3),
            "data": data or {},
        }
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def save_artifact(self, name: str, obj: Any) -> str:
        """Write JSON artifact under artifacts/; return relative path."""
        safe = name.replace("/", "_").replace(" ", "_")[:120]
        path = self.root / "artifacts" / safe
        if not path.suffix:
            path = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(obj, (dict, list)):
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            path.write_text(str(obj), encoding="utf-8")
        return str(path.relative_to(self.root))

    def log_observe(
        self,
        *,
        url: str,
        title: str = "",
        text: str = "",
        text_chars: int | None = None,
        error: str | None = None,
        backend: str | None = None,
    ) -> None:
        n = text_chars if text_chars is not None else len(text or "")
        art = None
        if text:
            art = self.save_artifact(
                f"step_{self._step:03d}_page_text.txt",
                _truncate(text, self.max_text_artifact),
            )
        self.emit(
            "observe",
            {
                "url": url,
                "title": (title or "")[:200],
                "text_chars": n,
                "error": error,
                "backend": backend,
                "text_artifact": art,
                "text_hash": _hash_text(text) if text else None,
            },
        )

    def log_affordances(self, affordances: list[dict[str, Any]], *, full: bool = True) -> str:
        """Always persist FULL list to artifact; event carries counts + sample + scope."""
        path = self.save_artifact(f"step_{self._step:03d}_affordances.json", affordances)
        texts = [str(a.get("text") or "") for a in affordances]
        scopes = [str(a.get("scope") or "unknown") for a in affordances]
        kinds = [str(a.get("kind") or "") for a in affordances]
        n_local = sum(1 for s in scopes if s == "local")
        n_global = sum(1 for s in scopes if s == "global")
        n_tab = sum(1 for k in kinds if k == "tab")
        self.emit(
            "affordances",
            {
                "n": len(affordances),
                "artifact": path,
                "sample_first_15": texts[:15],
                "n_local": n_local,
                "n_global": n_global,
                "n_tab": n_tab,
                "has_prijzen_boeken": any(
                    "prijzen" in t.lower() and "boek" in t.lower() for t in texts
                ),
                "has_pakketgarantie": any("pakketgarantie" in t.lower() for t in texts),
                "local_sample": [
                    str(a.get("text") or "")
                    for a in affordances
                    if str(a.get("scope") or "") == "local"
                ][:12],
                "all_texts": texts if full and len(texts) <= 80 else texts[:80],
            },
        )
        return path

    def log_gaps(self, gaps: list[dict[str, Any]], outcomes: dict[str, str] | None = None) -> None:
        self.emit("gaps", {"gaps": gaps, "outcomes": outcomes or {}})

    def log_llm_call(
        self,
        *,
        purpose: str,
        messages: list[dict[str, str]] | None = None,
        raw_response: str | None = None,
        structured: dict[str, Any] | None = None,
        model: str | None = None,
        latency_s: float | None = None,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        io_payload = {
            "purpose": purpose,
            "model": model,
            "messages": [
                {"role": m.get("role"), "content": _truncate(str(m.get("content") or ""), 3000)}
                for m in (messages or [])
            ],
            "raw_response": _truncate(raw_response or "", 4000),
            "structured": structured,
        }
        art = self.save_artifact(f"llm_{self._seq:04d}_{purpose}.json", io_payload)
        self.emit(
            "llm_call",
            {
                "purpose": purpose,
                "model": model,
                "latency_s": latency_s,
                "ok": ok,
                "error": error,
                "io_artifact": art,
                "response_preview": _truncate(raw_response or "", 400),
                "structured_summary": structured,
            },
        )

    def log_code_policy(
        self,
        *,
        action_class: str,
        allowed: bool,
        reason: str,
        target_text: str | None = None,
        target_href: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.emit(
            "code_policy",
            {
                "action_class": action_class,
                "allowed": allowed,
                "reason": reason,
                "target_text": target_text,
                "target_href": target_href,
                **(extra or {}),
            },
        )

    def log_action(
        self,
        action_type: str,
        *,
        payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        self.emit(
            "action",
            {
                "action_type": action_type,
                "payload": payload or {},
                "result": result or {},
                "ok": ok,
                "error": error,
            },
        )

    def log_interpret(
        self,
        outcomes: dict[str, str],
        *,
        eligible: bool | None = None,
        llm_calls: int | None = None,
        duration_s: float | None = None,
        provenance_blocked_n: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        data: dict[str, Any] = {"outcomes": outcomes, "eligible": eligible}
        if llm_calls is not None:
            data["llm_calls"] = llm_calls
        if duration_s is not None:
            data["duration_s"] = duration_s
        if provenance_blocked_n is not None:
            data["provenance_blocked_n"] = provenance_blocked_n
        if extra:
            data.update(extra)
        self.emit("interpret", data)

    def log_eligibility(self, elig: dict[str, Any]) -> None:
        self.emit("eligibility", elig if isinstance(elig, dict) else {"raw": elig})

    def log_acquisition_decision(
        self,
        decision: dict[str, Any],
        *,
        known: dict[str, str] | None = None,
        unknown: list[str] | None = None,
        available_actions_sample: list[str] | None = None,
    ) -> None:
        payload = dict(decision) if isinstance(decision, dict) else {"raw": decision}
        if known is not None:
            payload["decision_context_known"] = known
        if unknown is not None:
            payload["decision_context_unknown"] = unknown
        if available_actions_sample is not None:
            payload["decision_context_actions_sample"] = available_actions_sample
        self.emit("acquisition", payload)

    def log_timing_summary(self, phase_durations: dict[str, float], **extra: Any) -> None:
        """Emit a single summary of where wall-time was spent (browser vs LLM vs etc.)."""
        self.emit(
            "timing",
            {
                "phase_durations_s": phase_durations,
                "total_s": round(sum(phase_durations.values()), 3),
                **extra,
            },
        )

    def log_stop(self, reason: str, **extra: Any) -> None:
        self.emit("stop", {"reason": reason, **extra})

    def log_error(self, message: str, **extra: Any) -> None:
        self.emit("error", {"message": message, **extra})

    def duration_s(self) -> float:
        return round(time.monotonic() - self._t0, 3)

    def load_events(self) -> list[dict[str, Any]]:
        events = []
        if not self.events_path.is_file():
            return events
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events

    def write_summary(self, extra: dict[str, Any] | None = None) -> Path:
        events = self.load_events()
        phases: dict[str, int] = {}
        for e in events:
            p = e.get("phase") or "?"
            phases[p] = phases.get(p, 0) + 1
        urls = []
        for e in events:
            if e.get("phase") == "observe":
                u = (e.get("data") or {}).get("url")
                if u and (not urls or urls[-1] != u):
                    urls.append(u)
        aff_flags = []
        for e in events:
            if e.get("phase") == "affordances":
                d = e.get("data") or {}
                aff_flags.append(
                    {
                        "step": e.get("step"),
                        "n": d.get("n"),
                        "n_local": d.get("n_local"),
                        "n_global": d.get("n_global"),
                        "n_tab": d.get("n_tab"),
                        "has_prijzen_boeken": d.get("has_prijzen_boeken"),
                        "has_pakketgarantie": d.get("has_pakketgarantie"),
                        "local_sample": d.get("local_sample"),
                    }
                )
        acquisitions = [
            {"step": e.get("step"), **(e.get("data") or {})}
            for e in events
            if e.get("phase") == "acquisition"
        ]
        summary = {
            "schema": "trace-summary-v0",
            "run_id": self.run_id,
            "duration_s": self.duration_s(),
            "event_n": len(events),
            "phase_counts": phases,
            "url_sequence": urls,
            "affordance_flags": aff_flags,
            "acquisition_decisions": acquisitions,
            "stop": next(
                (
                    (e.get("data") or {})
                    for e in reversed(events)
                    if e.get("phase") == "stop"
                ),
                None,
            ),
            "extra": extra or {},
        }
        path = self.root / "summary.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_human_audit(self, extra: dict[str, Any] | None = None) -> Path:
        """Generate audit.md + audit.json from events."""
        events = self.load_events()
        lines = [
            f"# Trace audit — `{self.run_id}`",
            "",
            f"- **run_kind:** {self.run_kind}",
            f"- **duration_s:** {self.duration_s()}",
            f"- **task:** {_truncate(self.task_text, 500)}",
            "",
            "## Timeline",
            "",
        ]
        audit_steps: list[dict[str, Any]] = []
        for e in events:
            phase = e.get("phase")
            step = e.get("step")
            d = e.get("data") or {}
            t = e.get("t_rel_s")
            if phase == "observe":
                lines.append(
                    f"### Step {step} @ {t}s — OBSERVE\n"
                    f"- URL: `{d.get('url')}`\n"
                    f"- title: {d.get('title')}\n"
                    f"- text_chars: {d.get('text_chars')}\n"
                )
            elif phase == "affordances":
                lines.append(
                    f"### Step {step} — AFFORDANCES n={d.get('n')}\n"
                    f"- n_local={d.get('n_local')} n_global={d.get('n_global')} n_tab={d.get('n_tab')}\n"
                    f"- has_prijzen_boeken: **{d.get('has_prijzen_boeken')}**\n"
                    f"- has_pakketgarantie: **{d.get('has_pakketgarantie')}**\n"
                    f"- local_sample: {d.get('local_sample')}\n"
                    f"- first_15: {d.get('sample_first_15')}\n"
                    f"- full list: `artifacts/{Path(str(d.get('artifact') or '')).name}`\n"
                )
            elif phase == "gaps":
                lines.append(f"### Step {step} — GAPS\n```json\n{json.dumps(d, indent=2)}\n```\n")
            elif phase == "acquisition":
                lines.append(
                    f"### Step {step} — ACQUISITION DECISION\n"
                    f"- action: **{d.get('action_class')}**\n"
                    f"- target_text: `{d.get('target_text')}`\n"
                    f"- target_href: `{d.get('target_href')}`\n"
                    f"- source: {d.get('source')}\n"
                    f"- reason: {d.get('reason')}\n"
                )
                ctx_k = d.get("decision_context_known")
                ctx_u = d.get("decision_context_unknown")
                if ctx_k or ctx_u:
                    lines.append(
                        f"- known: `{ctx_k}` unknown: `{ctx_u}`\n"
                        f"- actions_sample: {d.get('decision_context_actions_sample')}\n"
                    )
                audit_steps.append({"step": step, "acquisition": d})
            elif phase == "code_policy":
                lines.append(
                    f"### Step {step} — CODE POLICY\n"
                    f"- allowed: {d.get('allowed')} reason: {d.get('reason')}\n"
                )
            elif phase == "llm_call":
                lines.append(
                    f"### Step {step} — LLM `{d.get('purpose')}`\n"
                    f"- latency_s: {d.get('latency_s')} ok: {d.get('ok')}\n"
                    f"- io: `{d.get('io_artifact')}`\n"
                    f"- preview: {_truncate(str(d.get('response_preview') or ''), 200)}\n"
                )
            elif phase == "interpret":
                lines.append(
                    f"### Step {step} — INTERPRET\n"
                    f"- outcomes: `{d.get('outcomes')}` eligible={d.get('eligible')}\n"
                    f"- llm_calls: {d.get('llm_calls')} duration_s: {d.get('duration_s')} "
                    f"provenance_blocked: {d.get('provenance_blocked_n')}\n"
                )
            elif phase == "eligibility":
                lines.append(
                    f"### Step {step} — ELIGIBILITY\n```json\n{json.dumps(d, indent=2)[:1500]}\n```\n"
                )
            elif phase == "timing":
                lines.append(
                    f"### TIMING SUMMARY\n"
                    f"- phase_durations_s: `{d.get('phase_durations_s')}`\n"
                    f"- total_s: {d.get('total_s')}\n"
                    f"- llm_calls_total: {d.get('llm_calls_total')}\n"
                )
            elif phase == "action":
                lines.append(
                    f"### Step {step} — ACTION `{d.get('action_type')}` ok={d.get('ok')}\n"
                    f"- payload: `{_truncate(json.dumps(d.get('payload') or {}), 300)}`\n"
                )
            elif phase == "stop":
                lines.append(f"## STOP\n- reason: **{d.get('reason')}**\n")

        lines.append("\n## Notes for analysis\n")
        lines.append(
            "- Compare affordance `has_prijzen_boeken` vs chosen acquisition target.\n"
            "- Compare URL sequence: same-entity tab vs global marketing path.\n"
            "- Evidence used for FLIGHT_INCLUDED must be judged against final URL/surface.\n"
        )
        if extra:
            lines.append(f"\n## Extra\n```json\n{json.dumps(extra, indent=2)[:2000]}\n```\n")

        md_path = self.root / "audit.md"
        md_path.write_text("\n".join(lines), encoding="utf-8")
        audit_json = {
            "schema": "trace-audit-v0",
            "run_id": self.run_id,
            "duration_s": self.duration_s(),
            "acquisition_steps": audit_steps,
            "event_n": len(events),
            "extra": extra or {},
        }
        (self.root / "audit.json").write_text(
            json.dumps(audit_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return md_path

    def finalize(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        self.write_summary(extra)
        self.write_human_audit(extra)
        return {
            "trace_dir": str(self.root),
            "run_id": self.run_id,
            "duration_s": self.duration_s(),
            "events_path": str(self.events_path),
            "audit_md": str(self.root / "audit.md"),
            "summary": str(self.root / "summary.json"),
        }
