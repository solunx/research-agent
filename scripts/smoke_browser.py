#!/usr/bin/env python3
"""Quick Playwright smoke test inside the container.

Usage:
  docker compose run --rm research-agent python scripts/smoke_browser.py
  docker compose run --rm research-agent python scripts/smoke_browser.py https://www.booking.com
"""

from __future__ import annotations

import sys
from pathlib import Path

# allow import from /app
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browser import browser_open


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    print(f"[smoke] Opening: {url}")
    result = browser_open(url, wait_seconds=3.0, headless=True)
    err = result.get("error")
    if err:
        print(f"[smoke] FAIL: {err}")
        return 1
    title = result.get("title") or ""
    text = result.get("text") or ""
    print(f"[smoke] OK title={title[:80]!r}")
    print(f"[smoke] text_chars={len(text)}")
    print(f"[smoke] text_preview=\n{text[:500]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
