#!/usr/bin/env python3
"""
Local Research Agent – general-purpose Phase 1+

- External notes + research_state (context stays smaller)
- Memory: site tactics + strategies (self-improving tool routing)
- Longer LLM timeout; forced report from notes on failure
- Optional Docker-only guard
- Tool timings in CLI
- Optional planner/executor mode (--planned): split task, flush LLM
  context between sub-tasks, synthesize at the end
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from llm import OllamaClient
from memory_store import MemoryStore
from storage import (
    append_conversation,
    append_note,
    compact_session_handoff,
    create_run_dir,
    load_notes,
    notes_as_prompt_text,
    save_metadata,
    save_report,
    save_sources,
    save_state,
    save_task,
)
from tools import TOOL_DEFINITIONS, execute_tool


MAX_TOOL_RESULT_CHARS = 2500
MAX_SEARCH_ITEMS_IN_CONTEXT = 5

# Generic planner: respects task primary sources / funnel; sequential phases
PLANNER_SYSTEM = """You are a research planner. Given a user research task, split it into
a small number of sequential research phases.

Rules:
- Output ONLY a JSON array of strings (no markdown fences, no commentary).
- Maximum 3 phases. Prefer 2 when the task is already focused.
- If the task names primary sources or a required approach/funnel, phase 1 MUST be:
  work only on those primary sources until a shortlist of concrete candidates exists.
- Later phases verify or deepen that shortlist — they must not restart broad discovery
  on unrelated source types as if nothing was found yet.
- Final global ranking is done by a separate synthesizer — do not include ranking as a phase.
- Keep each phase concrete and scoped. Same language as the user task.
- Do not invent brand names or domains that are not in the task.
"""


def require_docker_or_exit(config: dict[str, Any]) -> None:
    safety = config.get("safety") or {}
    if not safety.get("require_docker", True):
        return
    if os.environ.get("ALLOW_HOST_RUN") == "1":
        return
    if not os.path.exists("/.dockerenv"):
        print(
            "STOP: agent must run inside Docker (no /.dockerenv).\n"
            "  Use: docker compose run --rm research-agent python agent.py --task ...\n"
            "  Or set ALLOW_HOST_RUN=1 / safety.require_docker: false for debug.",
            file=sys.stderr,
        )
        sys.exit(2)


def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_task(task_arg: str) -> str:
    p = Path(task_arg)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return task_arg.strip()


def load_system_prompt(prompts_dir: str = "prompts", memory_block: str = "") -> str:
    path = Path(prompts_dir) / "system.md"
    base = (
        path.read_text(encoding="utf-8")
        if path.exists()
        else "You are a careful research agent. Cite sources. Never invent facts."
    )
    if memory_block:
        return base + "\n\n" + memory_block
    return base


def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    return message.get("tool_calls") or []


def is_complete(message: dict[str, Any]) -> bool:
    content = (message.get("content") or "").upper()
    return "RESEARCH_COMPLETE" in content


def truncate_tool_result(name: str, result: Any, max_chars: int = MAX_TOOL_RESULT_CHARS) -> Any:
    """
    Keep tool results small for the LLM context.
    Always preserve status/error/blocked flags so the model can escalate correctly.
    """
    if name == "web_search" and isinstance(result, list):
        trimmed = []
        for item in result[:MAX_SEARCH_ITEMS_IN_CONTEXT]:
            trimmed.append(
                {
                    "title": (item.get("title") or "")[:200],
                    "url": item.get("url") or "",
                    "snippet": (item.get("snippet") or "")[:300],
                }
            )
        return trimmed

    if isinstance(result, dict):
        # Always keep control fields; only truncate long text bodies
        out: dict[str, Any] = {}
        for key in (
            "url",
            "title",
            "error",
            "status_code",
            "blocked",
            "prefer_browser",
            "ok",
            "cookies_dismissed",
        ):
            if key in result:
                out[key] = result[key]
        # Keep price hints fully (short list)
        if isinstance(result.get("price_hints"), list):
            out["price_hints"] = result["price_hints"][:20]
        text = result.get("text")
        if isinstance(text, str):
            if len(text) > max_chars:
                out["text"] = (
                    text[:max_chars]
                    + f"\n...[truncated {len(text)} -> {max_chars} chars]"
                )
            else:
                out["text"] = text
        for k, v in result.items():
            if k in out or k in ("text", "price_hints"):
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v
        return out

    s = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
    if len(s) > max_chars:
        return s[:max_chars] + f"...[truncated {len(s)} chars]"
    return result


def _message_text(message: dict[str, Any]) -> str:
    content = (message.get("content") or "").strip()
    if content:
        return content
    return (message.get("thinking") or "").strip()


def note_from_tool(
    name: str,
    arguments: dict[str, Any],
    result: Any,
) -> dict[str, Any] | None:
    """Compact evidence stored outside the LLM chat context."""
    if name == "web_search" and isinstance(result, list):
        # one note summarizing search hits
        urls = [r.get("url") for r in result if r.get("url")][:5]
        titles = [r.get("title") for r in result if r.get("title")][:5]
        return {
            "source_type": "search",
            "query": arguments.get("query"),
            "title": f"search: {arguments.get('query', '')[:80]}",
            "summary": "; ".join(t for t in titles if t)[:500],
            "url": urls[0] if urls else "",
            "urls": urls,
        }
    browser_like = (
        "web_fetch",
        "browser_open",
        "browser_extract_text",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_wait",
        "browser_dismiss_cookies",
    )
    if name in browser_like and isinstance(result, dict):
        url = result.get("url") or arguments.get("url") or ""
        title = result.get("title") or ""
        blocked = bool(result.get("blocked") or result.get("prefer_browser"))
        err = result.get("error")
        text = (result.get("text") or "").strip()
        hints = result.get("price_hints") or []

        if err and not text:
            return {
                "source_type": name,
                "title": title,
                "url": url,
                "summary": f"ERROR: {err}",
                "ok": False,
                "blocked": blocked,
            }
        if blocked and len(text) < 400:
            return {
                "source_type": name,
                "title": title,
                "url": url,
                "summary": (
                    f"BLOCKED/SHORT ({err or 'little text'}). "
                    "Treat claims from this URL as unverified until browser succeeds."
                ),
                "ok": False,
                "blocked": True,
            }
        summary = text[:800]
        if hints:
            summary = "PRICES: " + " | ".join(str(h) for h in hints[:8]) + "\n" + summary
        return {
            "source_type": name,
            "title": title,
            "url": url,
            "summary": summary[:1200],
            "ok": not bool(err),
            "blocked": blocked,
        }
    return None


def build_partial_report(
    messages: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    status: str,
    task_text: str,
    notes_text: str = "",
) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant":
            content = _message_text(m)
            if len(content) > 200:
                header = (
                    f"# Research Report (partial – status: {status})\n\n"
                    f"> Run did not complete normally. Best available draft below.\n\n"
                )
                return header + content

    lines = [
        f"# Research Report (partial – status: {status})",
        "",
        "## Research question",
        task_text[:800] + ("..." if len(task_text) > 800 else ""),
        "",
        "## Notes collected",
        notes_text or "(none)",
        "",
        "## Sources retrieved",
    ]
    seen: set[str] = set()
    for s in sources:
        url = s.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        title = s.get("title") or url
        err = s.get("error")
        if err:
            lines.append(f"- {title} — {url} (error: {err})")
        else:
            lines.append(f"- {title} — {url}")
    if not seen:
        lines.append("- (no sources retrieved)")
    lines += [
        "",
        "## Uncertainties & limitations",
        f"- Run ended with status: `{status}`",
        "- No complete agent report was produced.",
        "",
    ]
    return "\n".join(lines)


def try_forced_report(
    client: OllamaClient,
    run_dir: Path,
    task_text: str,
    system_prompt: str,
) -> str | None:
    """Synthesize from notes + state only — avoid huge chat history."""
    notes = load_notes(run_dir, limit=120)
    notes_text = notes_as_prompt_text(notes, max_chars=12000, prioritize=True)
    force_messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Research question:\n{task_text}\n\n"
                f"Collected notes (only source of facts; prioritized):\n{notes_text}\n\n"
                "STOP. No tools. Write the final Markdown report now.\n"
                "Rules:\n"
                "- Use ONLY facts present in the notes. Invent nothing.\n"
                "- If notes contain prices, URLs, or feature claims from browser/fetch, "
                "include them with the appropriate verification status. "
                "Do NOT say 'not investigated' when notes already have that evidence.\n"
                "- Prefer candidates that have primary-source or browser evidence over "
                "search-snippet-only names.\n"
                "First line exact: RESEARCH_COMPLETE\n"
                "Structure: Research question, Executive summary, Ranking, "
                "Details, Uncertainties, Sources."
            ),
        },
    ]
    try:
        print("[agent] Forced report from notes (minimal context)...")
        append_conversation(run_dir, {"type": "forced_report_request", "mode": "notes_only"})
        message = client.chat(force_messages, tools=None)
        append_conversation(run_dir, {"type": "forced_report_response", "message": message})
        content = _message_text(message)
        if len(content) > 100:
            if "RESEARCH_COMPLETE" not in content.upper():
                content = "RESEARCH_COMPLETE\n\n" + content
            return content
    except Exception as e:
        print(f"[agent] Forced report failed: {e}")
        append_conversation(run_dir, {"type": "forced_report_error", "error": str(e)})
    return None


def plan_subtasks(client: OllamaClient, task_text: str, run_dir: Path) -> list[str]:
    """
    Generic planner: one fresh LLM call → JSON list of independent sub-tasks.
    Falls back to a single sub-task (= full task) on parse failure.
    """
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {
            "role": "user",
            "content": (
                "Split this research task into independent sub-tasks.\n\n"
                f"TASK:\n{task_text}\n\n"
                "Respond with ONLY a JSON array of strings."
            ),
        },
    ]
    print("[agent] Planner: splitting task into sub-tasks...")
    append_conversation(run_dir, {"type": "planner_request"})
    try:
        message = client.chat(messages, tools=None)
        append_conversation(run_dir, {"type": "planner_response", "message": message})
        raw = _message_text(message).strip()
        # Allow optional markdown fence
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        # Find first JSON array
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            subtasks = [str(x).strip() for x in parsed if str(x).strip()]
            subtasks = subtasks[:3]
            if subtasks:
                print(f"[agent] Planner produced {len(subtasks)} sub-task(s)")
                for i, s in enumerate(subtasks, 1):
                    print(f"[agent]   {i}. {s[:120]}{'...' if len(s) > 120 else ''}")
                (run_dir / "plan.json").write_text(
                    json.dumps(subtasks, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                return subtasks
    except Exception as e:
        print(f"[agent] Planner failed ({e}); falling back to single session")
        append_conversation(run_dir, {"type": "planner_error", "error": str(e)})

    return [task_text]


def build_subtask_prompt(
    full_task: str,
    subtask: str,
    index: int,
    total: int,
    prior_handoff: str = "",
) -> str:
    """Focused user message for one executor session (generic)."""
    handoff_block = ""
    if prior_handoff.strip():
        handoff_block = (
            "\n## Findings from previous phase (read-only; do not re-discover from scratch)\n"
            f"{prior_handoff.strip()}\n\n"
            "Build on this shortlist/evidence where relevant. "
            "Do not ignore concrete URLs, prices, or names already found.\n"
        )
    return (
        f"## Full research task (context only)\n{full_task}\n\n"
        f"## Your focus for this session ({index}/{total})\n{subtask}\n"
        f"{handoff_block}\n"
        "Work only on this focus. Gather verifiable notes via tools. "
        "When this focus is done (enough verified info or clear dead end), "
        "output RESEARCH_COMPLETE with a short Markdown summary of findings "
        "for this sub-task only (not the global final ranking)."
    )


def run_session(
    *,
    client: OllamaClient,
    config: dict[str, Any],
    system_prompt: str,
    user_content: str,
    run_dir: Path,
    memory: MemoryStore,
    mem_cfg: dict[str, Any],
    sources: list[dict[str, Any]],
    counters: dict[str, int],
    limits: dict[str, Any],
    start_time: float,
    max_runtime: float,
    verbose: bool,
    session_label: str = "main",
    session_llm_budget: int | None = None,
) -> dict[str, Any]:
    """
    One tool-using research loop with its own message list (fresh context).
    Notes/sources append to the shared run_dir / sources list.
    Returns {status, stop_reason, final_content, messages}.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    max_llm = limits.get("max_llm_calls", 80)
    max_tools = limits.get("max_tool_calls", 150)
    max_search = limits.get("max_search_calls", 60)
    max_tool_result_chars = int(
        config.get("limits", {}).get("max_tool_result_chars", MAX_TOOL_RESULT_CHARS)
    )
    session_llm_start = counters["llm_calls"]
    session_tool_fail_streak = 0

    def prefer_browser(url: str) -> bool:
        return memory.preferred_tool_for_url(url) == "browser_open"

    status = "running"
    stop_reason: str | None = None
    final_content = ""

    append_conversation(
        run_dir,
        {"type": "session_start", "session": session_label, "user_preview": user_content[:200]},
    )

    try:
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_runtime:
                print(f"[agent] [{session_label}] Max runtime reached")
                status = "timeout_runtime"
                stop_reason = "limit"
                break
            if counters["llm_calls"] >= max_llm:
                print(f"[agent] [{session_label}] Max LLM calls reached")
                status = "timeout_llm"
                stop_reason = "limit"
                break
            if session_llm_budget is not None:
                used = counters["llm_calls"] - session_llm_start
                if used >= session_llm_budget:
                    print(
                        f"[agent] [{session_label}] Session LLM budget reached "
                        f"({used}/{session_llm_budget})"
                    )
                    status = "session_budget"
                    stop_reason = "session_budget"
                    break
            if counters["tool_calls"] >= max_tools:
                print(f"[agent] [{session_label}] Max tool calls reached")
                status = "timeout_tools"
                stop_reason = "limit"
                break

            counters["llm_calls"] += 1
            call_n = counters["llm_calls"]
            print(f"[agent] [{session_label}] LLM call #{call_n} ...")
            append_conversation(
                run_dir,
                {
                    "type": "llm_request",
                    "session": session_label,
                    "call": call_n,
                    "message_count": len(messages),
                },
            )

            try:
                t_llm = time.perf_counter()
                message = client.chat(messages, tools=TOOL_DEFINITIONS)
                llm_ms = (time.perf_counter() - t_llm) * 1000
                print(f"[agent] [{session_label}] LLM call #{call_n} done ({llm_ms:.0f} ms)")
            except Exception as e:
                print(f"[agent] [{session_label}] LLM error after retries: {e}")
                append_conversation(
                    run_dir,
                    {"type": "llm_error", "session": session_label, "error": str(e)},
                )
                status = "llm_error"
                stop_reason = "llm_error"
                break

            append_conversation(
                run_dir,
                {
                    "type": "llm_response",
                    "session": session_label,
                    "call": call_n,
                    "message": message,
                },
            )

            if verbose:
                thinking = (message.get("thinking") or "")[:400]
                if thinking:
                    print(f"[agent] thinking: {thinking}...")

            tool_calls = extract_tool_calls(message)
            if tool_calls:
                messages.append(message)

                for tc in tool_calls:
                    counters["tool_calls"] += 1
                    func = tc.get("function") or {}
                    name = func.get("name") or ""
                    raw_args = func.get("arguments") or "{}"

                    if isinstance(raw_args, str):
                        try:
                            arguments = json.loads(raw_args)
                        except json.JSONDecodeError:
                            arguments = {}
                    else:
                        arguments = raw_args

                    print(f"[agent] [{session_label}] Tool call: {name}({arguments})")

                    if name == "web_search":
                        counters["search_calls"] += 1
                        if counters["search_calls"] > max_search:
                            result: Any = {"error": "max_search_calls exceeded"}
                            duration_ms = 0.0
                        else:
                            result, duration_ms = execute_tool(
                                name, arguments, config, prefer_browser_for_url=prefer_browser
                            )
                    else:
                        result, duration_ms = execute_tool(
                            name, arguments, config, prefer_browser_for_url=prefer_browser
                        )

                    print(
                        f"[agent] [{session_label}] Tool {name} finished in {duration_ms:.0f} ms"
                    )

                    url = None
                    ok = True
                    blocked = False
                    err = None
                    if isinstance(result, dict):
                        url = result.get("url") or arguments.get("url")
                        err = result.get("error")
                        blocked = bool(result.get("blocked"))
                        ok = not err or (result.get("text") and not blocked)
                    if name == "web_search":
                        ok = isinstance(result, list) and len(result) > 0
                        if isinstance(result, list) and result:
                            non_notice = [
                                r
                                for r in result
                                if (r.get("title") or "") != "Query notice"
                            ]
                            ok = len(non_notice) > 0 and not (
                                len(non_notice) == 1
                                and (non_notice[0].get("title") or "") == "Search error"
                            )
                        url = None

                    # Generic: repeated tool failures → stop thrashing this session
                    tool_failed = bool(err) or blocked or not ok
                    if name.startswith("browser_") or name in ("web_fetch", "web_search"):
                        if tool_failed and name.startswith("browser_"):
                            session_tool_fail_streak += 1
                        elif not tool_failed:
                            session_tool_fail_streak = 0
                    if session_tool_fail_streak >= 3:
                        print(
                            f"[agent] [{session_label}] "
                            "3 consecutive browser failures — ending session early"
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "content": json.dumps(
                                    {
                                        "error": (
                                            "Repeated browser interaction failures. "
                                            "Stop UI retries; summarize what you have "
                                            "and RESEARCH_COMPLETE for this focus."
                                        )
                                    },
                                    ensure_ascii=False,
                                ),
                                "name": name,
                            }
                        )
                        # One more LLM turn will be allowed; streak breaks loop after complete
                        session_tool_fail_streak = 0
                        # Fall through to append normal result too below

                    if mem_cfg.get("enabled", True):
                        memory.record_tool_result(
                            tool=name,
                            url=url if isinstance(url, str) else None,
                            ok=ok,
                            duration_ms=duration_ms,
                            error=err if isinstance(err, str) else None,
                            blocked=blocked,
                        )

                    note = note_from_tool(name, arguments, result)
                    if note:
                        note["session"] = session_label
                        append_note(run_dir, note)
                        counters["notes_count"] += 1

                    if name == "web_search" and isinstance(result, list):
                        for r in result:
                            if r.get("url"):
                                sources.append(
                                    {
                                        "url": r["url"],
                                        "title": r.get("title", ""),
                                        "source_type": "search_result",
                                        "retrieved_at": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                        "snippet": r.get("snippet", ""),
                                        "session": session_label,
                                    }
                                )
                    elif name in (
                        "web_fetch",
                        "browser_open",
                        "browser_extract_text",
                        "browser_click",
                        "browser_type",
                        "browser_scroll",
                        "browser_wait",
                        "browser_dismiss_cookies",
                    ) and isinstance(result, dict):
                        if result.get("url"):
                            entry = {
                                "url": result["url"],
                                "title": result.get("title", ""),
                                "source_type": (
                                    "page" if name == "web_fetch" else "browser"
                                ),
                                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                "error": result.get("error"),
                                "session": session_label,
                            }
                            if result.get("price_hints"):
                                entry["price_hints"] = result["price_hints"][:15]
                            sources.append(entry)

                    result_for_context = truncate_tool_result(
                        name, result, max_chars=max_tool_result_chars
                    )

                    append_conversation(
                        run_dir,
                        {
                            "type": "tool_result",
                            "session": session_label,
                            "tool": name,
                            "arguments": arguments,
                            "duration_ms": round(duration_ms, 1),
                            "result_preview": str(result_for_context)[:500],
                        },
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                result_for_context, ensure_ascii=False
                            ),
                            "name": name,
                        }
                    )

                save_state(
                    run_dir,
                    {
                        "status": "running",
                        "session": session_label,
                        "llm_calls": counters["llm_calls"],
                        "tool_calls": counters["tool_calls"],
                        "sources_count": len(sources),
                        "notes_count": counters["notes_count"],
                        "progress": f"{session_label} after LLM {call_n}",
                        "key_findings": "",
                    },
                )
                continue

            content = message.get("content") or ""
            messages.append(message)

            if is_complete(message):
                print(f"[agent] [{session_label}] RESEARCH_COMPLETE")
                final_content = content
                status = "completed"
                break

            # Model replied without tools and without complete — nudge once via loop continue
            # (avoid infinite empty replies: treat as soft complete if long enough)
            if len(content) > 500 and "RESEARCH_COMPLETE" not in content.upper():
                # Ask model to either tool-call or finish — by appending a short user nudge
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue with tools if more evidence is needed, "
                            "or finish with RESEARCH_COMPLETE and a short summary for this focus."
                        ),
                    }
                )
                continue

    except KeyboardInterrupt:
        print(f"\n[agent] [{session_label}] Interrupted")
        status = "cancelled"
        stop_reason = "cancelled"
        raise
    except Exception as e:
        print(f"[agent] [{session_label}] Unexpected error: {e}")
        append_conversation(
            run_dir,
            {"type": "fatal_error", "session": session_label, "error": str(e)},
        )
        status = "error"
        stop_reason = "error"

    append_conversation(
        run_dir,
        {
            "type": "session_end",
            "session": session_label,
            "status": status,
            "stop_reason": stop_reason,
        },
    )
    # Drop message list — context flush for next session
    return {
        "status": status,
        "stop_reason": stop_reason,
        "final_content": final_content,
        "messages": messages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Research Agent")
    parser.add_argument("--task", required=True, help="Path to task file or task string")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--verbose", action="store_true", help="Print thinking snippets")
    parser.add_argument(
        "--planned",
        action="store_true",
        help=(
            "Planner/executor mode: split task into sub-tasks, fresh LLM context "
            "per sub-task (flush), synthesize report from notes at the end"
        ),
    )
    args = parser.parse_args()

    config = load_config(args.config)
    require_docker_or_exit(config)

    task_text = load_task(args.task)
    verbose = args.verbose or bool(config.get("verbose"))
    planned = bool(args.planned)

    mem_cfg = config.get("memory") or {}
    memory = MemoryStore(config.get("storage", {}).get("memory_dir", "memory"))
    if mem_cfg.get("enabled", True):
        memory.ensure_seed_strategies()
        memory_block = memory.prompt_block(
            max_tactics=int(mem_cfg.get("max_tactics_in_prompt", 40)),
            max_strategies=int(mem_cfg.get("max_strategies_in_prompt", 15)),
            retest_after_days=int(mem_cfg.get("retest_after_days", 30)),
        )
    else:
        memory_block = ""

    system_prompt = load_system_prompt(memory_block=memory_block)

    llm_cfg = config.get("llm", {})
    limits = config.get("limits", {})
    storage_cfg = config.get("storage", {})

    client = OllamaClient(
        base_url=llm_cfg.get("base_url", "http://172.17.0.1:11434"),
        model=llm_cfg.get("model", "qwen3.8:27b"),
        temperature=llm_cfg.get("temperature", 0.2),
        timeout=llm_cfg.get("timeout_seconds", 480),
        max_retries=llm_cfg.get("max_retries", 2),
        retry_backoff_seconds=llm_cfg.get("retry_backoff_seconds", 2.0),
    )

    task_slug = Path(args.task).stem if Path(args.task).exists() else "research"
    run_dir = create_run_dir(storage_cfg.get("runs_dir", "runs"), task_slug)
    save_task(run_dir, task_text)

    print(f"[agent] Run directory: {run_dir}")
    print(f"[agent] Model: {client.model}")
    print(f"[agent] Timeout: {client.timeout}s")
    print(f"[agent] Task loaded ({len(task_text)} chars)")
    print(f"[agent] Mode: {'planned (planner/executor/critic)' if planned else 'single session'}")
    if mem_cfg.get("enabled", True):
        print(f"[agent] Memory: {memory.root} (tactics+strategies loaded)")

    sources: list[dict[str, Any]] = []
    start_time = time.time()
    counters = {
        "llm_calls": 0,
        "tool_calls": 0,
        "search_calls": 0,
        "notes_count": 0,
    }
    max_runtime = limits.get("max_runtime_minutes", 120) * 60
    status = "running"
    final_report = ""
    last_messages: list[dict[str, Any]] = []
    stop_reason: str | None = None

    append_conversation(
        run_dir,
        {
            "type": "run_start",
            "model": client.model,
            "mode": "planned" if planned else "single",
            "task_preview": task_text[:300],
        },
    )
    save_state(
        run_dir,
        {
            "status": "running",
            "mode": "planned" if planned else "single",
            "llm_calls": 0,
            "tool_calls": 0,
            "sources_count": 0,
            "notes_count": 0,
            "progress": "started",
            "key_findings": "",
        },
    )

    try:
        if planned:
            subtasks = plan_subtasks(client, task_text, run_dir)
            counters["llm_calls"] += 1  # planner used one call
            n_subs = max(len(subtasks), 1)
            # Reserve headroom for planner (done) + critic (~1) + margin
            remaining = max(limits.get("max_llm_calls", 80) - counters["llm_calls"] - 4, n_subs * 8)
            per_sub_budget = max(8, remaining // n_subs)
            print(f"[agent] Per-sub LLM budget: ~{per_sub_budget} (sequential phases: {n_subs})")

            prior_handoff = ""
            for i, sub in enumerate(subtasks, 1):
                if time.time() - start_time > max_runtime:
                    status = "timeout_runtime"
                    stop_reason = "limit"
                    break
                label = f"sub{i}"
                print(f"\n[agent] === Executor session {i}/{len(subtasks)} ===")
                user_content = build_subtask_prompt(
                    task_text, sub, i, len(subtasks), prior_handoff=prior_handoff
                )
                result = run_session(
                    client=client,
                    config=config,
                    system_prompt=system_prompt,
                    user_content=user_content,
                    run_dir=run_dir,
                    memory=memory,
                    mem_cfg=mem_cfg,
                    sources=sources,
                    counters=counters,
                    limits=limits,
                    start_time=start_time,
                    max_runtime=max_runtime,
                    verbose=verbose,
                    session_label=label,
                    session_llm_budget=per_sub_budget,
                )
                last_messages = result.get("messages") or []
                # Handoff: compact notes from this session for the next phase
                prior_handoff = compact_session_handoff(
                    load_notes(run_dir, limit=80), label, max_chars=2500
                )
                if result["status"] == "cancelled":
                    status = "cancelled"
                    stop_reason = "cancelled"
                    break
                if result["status"] == "llm_error":
                    print(f"[agent] Session {label} hit llm_error; continuing if possible")
                    stop_reason = "llm_error"
                    continue
                if result["status"] in (
                    "timeout_runtime",
                    "timeout_llm",
                    "timeout_tools",
                ):
                    status = result["status"]
                    stop_reason = "limit"
                    break
                # session_budget → continue to next phase (intentional)

            # Critic / synthesis — always from notes (flush-safe)
            print("\n[agent] === Critic: synthesize from notes ===")
            forced = try_forced_report(client, run_dir, task_text, system_prompt)
            if forced:
                final_report = forced
                status = "completed" if stop_reason is None else f"{stop_reason}+forced_report"
            else:
                status = status if status != "running" else "error"
                if stop_reason is None:
                    stop_reason = "critic_failed"
        else:
            result = run_session(
                client=client,
                config=config,
                system_prompt=system_prompt,
                user_content=task_text,
                run_dir=run_dir,
                memory=memory,
                mem_cfg=mem_cfg,
                sources=sources,
                counters=counters,
                limits=limits,
                start_time=start_time,
                max_runtime=max_runtime,
                verbose=verbose,
                session_label="main",
            )
            last_messages = result.get("messages") or []
            status = result["status"]
            stop_reason = result.get("stop_reason")
            final_report = result.get("final_content") or ""

            if not final_report and stop_reason in ("limit", "llm_error"):
                forced = try_forced_report(client, run_dir, task_text, system_prompt)
                if forced:
                    final_report = forced
                    if status != "completed":
                        status = status + "+forced_report"

    except KeyboardInterrupt:
        print("\n[agent] Interrupted by user")
        status = "cancelled"
        stop_reason = "cancelled"
    except Exception as e:
        print(f"[agent] Unexpected error: {e}")
        append_conversation(run_dir, {"type": "fatal_error", "error": str(e)})
        status = "error"
        stop_reason = "error"

    elapsed = time.time() - start_time
    notes_text = notes_as_prompt_text(load_notes(run_dir), max_chars=4000)

    if not final_report:
        final_report = build_partial_report(
            last_messages, sources, status, task_text, notes_text=notes_text
        )
        print(f"[agent] Writing partial report (status={status})")

    save_report(run_dir, final_report)
    save_sources(run_dir, sources)
    save_state(
        run_dir,
        {
            "status": status,
            "mode": "planned" if planned else "single",
            "llm_calls": counters["llm_calls"],
            "tool_calls": counters["tool_calls"],
            "sources_count": len(sources),
            "notes_count": counters["notes_count"],
            "progress": "finished",
            "key_findings": "",
        },
    )

    metadata = {
        "run_id": run_dir.name,
        "status": status,
        "mode": "planned" if planned else "single",
        "model": client.model,
        "started_at": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "llm_calls": counters["llm_calls"],
        "tool_calls": counters["tool_calls"],
        "search_calls": counters["search_calls"],
        "sources_count": len(sources),
        "notes_count": counters["notes_count"],
        "limits": limits,
    }
    save_metadata(run_dir, metadata)
    append_conversation(run_dir, {"type": "run_end", "status": status, "metadata": metadata})

    print(f"\n[agent] Finished with status: {status}")
    print(f"[agent] Report written to: {run_dir / 'report.md'}")
    print(
        f"[agent] Duration: {elapsed/60:.1f} min | LLM: {counters['llm_calls']} | "
        f"Tools: {counters['tool_calls']} | Notes: {counters['notes_count']}"
    )
    print(f"[agent] Memory tactics: {memory.tactics_path}")

    return 0 if status == "completed" or status.endswith("+forced_report") else 1


if __name__ == "__main__":
    sys.exit(main())
