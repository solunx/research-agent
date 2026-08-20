"""
Tool registry and execution.

Tiers:
  Tier 1: web_search, web_fetch
  Tier 3: browser_* (fallback when HTTP fails or tactics say so)
"""

from __future__ import annotations

import time
from typing import Any, Callable

from web import web_search, web_fetch
from browser import (
    browser_open,
    browser_extract_text,
    browser_dismiss_cookies,
    browser_click,
    browser_type,
    browser_scroll,
    browser_wait,
)


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web. Returns title, url, snippet. "
                "Use short keyword queries (a few terms), not full sentences or long lists of criteria. "
                "One intent per query. If results are empty or you get a Query notice, try a shorter query. "
                "UI filters (dates, counts, budgets) belong in the browser on the site, not in the search box."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Short keyword query (prefer a few terms, not a full sentence)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch page text via HTTP (fast, low cost). "
                "If you get 403/blocked/empty or prefer_browser, use browser_open on the same URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_open",
            "description": (
                "Open URL in real Chromium, dismiss cookies when possible, return visible text. "
                "Also returns price_hints when euro/price-like lines are found. "
                "Use for JS-heavy sites, 403 after web_fetch, or when you need live listing prices. "
                "Slower than web_fetch — use only when needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to open"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_dismiss_cookies",
            "description": (
                "Explicitly try to dismiss cookie/consent banners on the current page, "
                "then return page text. Call this if the page still shows a cookie wall."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_extract_text",
            "description": (
                "Extract visible text (+ price_hints) from the currently open browser page."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": (
                "Click an element on the current page. "
                "Selector: CSS or Playwright text form, e.g. "
                "button:has-text('Zoeken'), text=Accepteer, #submit. "
                "Returns the updated page text and price_hints so you can read results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS or text selector",
                    },
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": (
                "Type into an input on the current page (dates, destination, travellers, …). "
                "Use press_enter=true to submit a field. Returns updated page text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector for the input",
                    },
                    "text": {"type": "string", "description": "Text to type"},
                    "press_enter": {
                        "type": "boolean",
                        "description": "Press Enter after typing",
                    },
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": (
                "Scroll the current page (often loads more results). Returns page text + price_hints."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": "down or up",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Pixels to scroll (default 800)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait",
            "description": (
                "Wait a few seconds for JS to settle, then return current page text. "
                "Use after click/type when results still loading."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {
                        "type": "number",
                        "description": "Seconds to wait (max 15, default 2)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_shortlist",
            "description": (
                "Record a concrete candidate found during research into the structured shortlist. "
                "Call this as soon as you see a named candidate with a price and/or booking URL "
                "from a tool result — before further clicking. "
                "Idempotent: same name (+ same source URL) updates the entry; "
                "a better (lower) price overwrites the previous price. "
                "The final report is built primarily from this shortlist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Candidate name (hotel, product, package, …)",
                    },
                    "source_url": {
                        "type": "string",
                        "description": "URL where you found this candidate / can book",
                    },
                    "price": {
                        "type": "string",
                        "description": "Price as shown on the page (e.g. '€622 p.p.' or '904')",
                    },
                    "details": {
                        "type": "string",
                        "description": "Short facts: stars, location, meal plan, review score, …",
                    },
                },
                "required": ["name"],
            },
        },
    },
]


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    config: dict[str, Any],
    prefer_browser_for_url: Callable[[str], bool] | None = None,
) -> tuple[Any, float]:
    t0 = time.perf_counter()

    if name == "web_search":
        search_cfg = config.get("tools", {}).get("web_search", {})
        result = web_search(
            query=arguments["query"],
            max_results=search_cfg.get("max_results", 8),
            region=search_cfg.get("region", "be-nl"),
        )
        return result, (time.perf_counter() - t0) * 1000

    if name == "web_fetch":
        fetch_cfg = config.get("tools", {}).get("web_fetch", {})
        url = arguments["url"]
        prefer = bool(prefer_browser_for_url and prefer_browser_for_url(url))
        result = web_fetch(
            url=url,
            max_chars=fetch_cfg.get("max_chars", 12000),
            timeout=fetch_cfg.get("timeout_seconds", 20),
            user_agent=fetch_cfg.get("user_agent"),
            max_retries=fetch_cfg.get("max_retries", 2),
            prefer_browser_hint=prefer,
        )
        return result, (time.perf_counter() - t0) * 1000

    browser_cfg = config.get("tools", {}).get("browser", {})
    headless = browser_cfg.get("headless", True)
    ua = browser_cfg.get("user_agent")
    max_chars = browser_cfg.get("max_chars", 15000)

    if name == "browser_open":
        result = browser_open(
            url=arguments["url"],
            wait_seconds=browser_cfg.get("wait_seconds", 3.0),
            headless=headless,
            user_agent=ua,
            max_chars=max_chars,
        )
        return result, (time.perf_counter() - t0) * 1000

    if name == "browser_dismiss_cookies":
        result = browser_dismiss_cookies()
        return result, (time.perf_counter() - t0) * 1000

    if name == "browser_extract_text":
        result = browser_extract_text(max_chars=max_chars)
        return result, (time.perf_counter() - t0) * 1000

    if name == "browser_click":
        result = browser_click(selector=arguments["selector"], max_chars=10000)
        return result, (time.perf_counter() - t0) * 1000

    if name == "browser_type":
        result = browser_type(
            selector=arguments["selector"],
            text=arguments["text"],
            press_enter=bool(arguments.get("press_enter", False)),
            max_chars=8000,
        )
        return result, (time.perf_counter() - t0) * 1000

    if name == "browser_scroll":
        result = browser_scroll(
            direction=arguments.get("direction", "down"),
            amount=int(arguments.get("amount", 800)),
        )
        return result, (time.perf_counter() - t0) * 1000

    if name == "browser_wait":
        result = browser_wait(seconds=float(arguments.get("seconds", 2.0)))
        return result, (time.perf_counter() - t0) * 1000

    return {"error": f"Unknown tool: {name}"}, (time.perf_counter() - t0) * 1000
