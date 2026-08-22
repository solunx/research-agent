"""
Optional Browser Use backend — high-level browser execution for A/B tests.

Not a full rewrite of our research agent: one tool that takes a *narrow*
natural-language instruction (+ optional start URL) and returns page observations.

Requires optional dependency: browser-use (and its Playwright stack).
If missing, the tool returns a clear error so the research agent can fall back
to web_search / web_fetch or complete honestly.
"""

from __future__ import annotations

import asyncio
import os
import traceback
from typing import Any


def browser_use_available() -> bool:
    try:
        import browser_use  # noqa: F401

        return True
    except Exception:
        return False


def run_browser_use_task(
    instruction: str,
    *,
    start_url: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    max_steps: int = 25,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """
    Run a single Browser Use agent on a focused instruction.
    Returns a plain dict safe for our tool layer / notes.
    """
    instruction = (instruction or "").strip()
    if not instruction:
        return {"ok": False, "error": "instruction is required"}

    if start_url:
        instruction = (
            f"Start at: {start_url}\n"
            f"Then: {instruction}\n"
            "Do not complete a purchase or enter payment details. "
            "Stop once you can report hotel/package names, prices, and links visible on screen."
        )

    if not browser_use_available():
        return {
            "ok": False,
            "error": (
                "browser-use is not installed in this image. "
                "Install optional deps (browser-use) and rebuild, "
                "or run with --browser-backend playwright."
            ),
            "backend": "browser_use",
        }

    try:
        return asyncio.run(
            _run_async(
                instruction,
                model=model,
                base_url=base_url,
                max_steps=max_steps,
                timeout_seconds=timeout_seconds,
            )
        )
    except Exception as e:
        return {
            "ok": False,
            "error": f"browser_use failed: {e}",
            "traceback": traceback.format_exc()[-1500:],
            "backend": "browser_use",
        }


async def _run_async(
    instruction: str,
    *,
    model: str | None,
    base_url: str | None,
    max_steps: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """
    Adapter tries a few Browser Use API shapes (library evolves quickly).
    """
    model = model or os.environ.get("BROWSER_USE_MODEL") or os.environ.get(
        "OLLAMA_MODEL", "qwen3.8:27b"
    )
    base_url = base_url or os.environ.get("OLLAMA_BASE_URL") or "http://172.17.0.1:11434"

    # --- LLM ---
    llm = None
    last_llm_err = None
    for factory in (
        lambda: _llm_browser_use_chat_ollama(model, base_url),
        lambda: _llm_langchain_ollama(model, base_url),
    ):
        try:
            llm = factory()
            if llm is not None:
                break
        except Exception as e:
            last_llm_err = e
            llm = None
    if llm is None:
        return {
            "ok": False,
            "error": f"Could not construct LLM for Browser Use ({last_llm_err})",
            "backend": "browser_use",
        }

    # --- Agent ---
    from browser_use import Agent  # type: ignore

    agent_kwargs: dict[str, Any] = {"task": instruction, "llm": llm}
    # Some versions accept max_actions / max_steps
    for k, v in (("max_steps", max_steps), ("max_actions_per_step", 5)):
        agent_kwargs[k] = v

    try:
        agent = Agent(**agent_kwargs)
    except TypeError:
        agent = Agent(task=instruction, llm=llm)

    async def _go() -> Any:
        return await agent.run()

    try:
        history = await asyncio.wait_for(_go(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "error": f"browser_use timed out after {timeout_seconds}s",
            "backend": "browser_use",
            "instruction": instruction[:500],
        }

    text = _history_to_text(history)
    return {
        "ok": True,
        "backend": "browser_use",
        "instruction": instruction[:500],
        "text": text[:12000],
        "url": None,
        "title": "browser_use result",
    }


def _llm_browser_use_chat_ollama(model: str, base_url: str) -> Any:
    """browser_use.llm.ChatOllama if present."""
    try:
        from browser_use.llm import ChatOllama  # type: ignore

        return ChatOllama(model=model, host=base_url.replace("/v1", ""))
    except Exception:
        from browser_use.llm import ChatOllama  # type: ignore

        return ChatOllama(model=model, base_url=base_url)


def _llm_langchain_ollama(model: str, base_url: str) -> Any:
    try:
        from langchain_ollama import ChatOllama  # type: ignore

        return ChatOllama(model=model, base_url=base_url)
    except Exception:
        from langchain_community.chat_models import ChatOllama  # type: ignore

        return ChatOllama(model=model, base_url=base_url)


def _history_to_text(history: Any) -> str:
    if history is None:
        return "(no history)"
    # Newer browser-use: AgentHistoryList with final_result()
    for attr in ("final_result", "extracted_content", "model_thoughts"):
        fn = getattr(history, attr, None)
        if callable(fn):
            try:
                val = fn()
                if val:
                    return str(val)
            except Exception:
                pass
    if isinstance(history, str):
        return history
    if isinstance(history, dict):
        return str(history.get("result") or history.get("text") or history)[:12000]
    # list of steps
    try:
        parts: list[str] = []
        for step in history:
            parts.append(str(step)[:800])
        return "\n".join(parts)[:12000]
    except Exception:
        return str(history)[:12000]
