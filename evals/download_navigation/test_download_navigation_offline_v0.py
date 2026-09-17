#!/usr/bin/env python3
"""
Offline tests for navigation that starts a file download (Open #28).

Live citation (`20260917T111714Z`):
  Page.goto: Download is starting
  navigating to "https://arxiv.org/pdf/2609.19059"

No LLM, no GPU. Playwright HTTP fixture is optional.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from browser import (  # noqa: E402
    _is_download_navigation_error,
    _run_keeping_download,
)
from evidence_acquisition import execute_acquisition_action  # noqa: E402

LIVE_ERR = (
    'Page.goto: Download is starting\n'
    'Call log:\n'
    '  - navigating to "https://arxiv.org/pdf/2609.19059", waiting until "domcontentloaded"\n'
)


class _FakeDownload:
    suggested_filename = "paper.pdf"
    url = "https://example.test/paper.pdf"
    cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakePage:
    def __init__(self) -> None:
        self.handlers: list = []
        self.url = "https://example.test/search"

    def on(self, event: str, fn) -> None:
        self.handlers.append((event, fn))

    def title(self) -> str:
        return "Search results"

    def inner_text(self, _sel: str) -> str:
        return "SEARCH LIST STAYS HERE\nShowing 1–50 of 1934 results\n" * 3


def test_detects_live_download_error_string():
    assert _is_download_navigation_error(LIVE_ERR)
    assert _is_download_navigation_error(RuntimeError(LIVE_ERR))
    print("OK test_detects_live_download_error_string")


def test_negative_other_errors_are_not_downloads():
    assert not _is_download_navigation_error("")
    assert not _is_download_navigation_error(None)
    assert not _is_download_navigation_error("Timeout 60000ms exceeded.")
    assert not _is_download_navigation_error("net::ERR_CONNECTION_REFUSED")
    assert not _is_download_navigation_error("Page.goto: net::ERR_ABORTED")
    print("OK test_negative_other_errors_are_not_downloads")


def test_download_navigation_keeps_current_page_text():
    page = _FakePage()
    fired = _FakeDownload()

    def boom() -> None:
        for ev, fn in page.handlers:
            if ev == "download":
                fn(fired)
        raise RuntimeError(LIVE_ERR)

    snap = _run_keeping_download(
        page, boom, requested_url="https://example.test/paper.pdf"
    )
    assert snap is not None
    assert snap.get("download") is True
    assert snap.get("error") is None
    assert "SEARCH LIST STAYS HERE" in str(snap.get("text") or "")
    assert snap.get("download_filename") == "paper.pdf"
    assert fired.cancelled is True
    print("OK test_download_navigation_keeps_current_page_text")


def test_negative_timeout_still_raises():
    page = _FakePage()

    def boom() -> None:
        raise RuntimeError("Timeout 60000ms exceeded.")

    try:
        _run_keeping_download(page, boom, requested_url="https://example.test/")
    except RuntimeError as e:
        assert "Timeout" in str(e)
        print("OK test_negative_timeout_still_raises")
        return
    raise AssertionError("timeout must not be swallowed as a download")


def test_execute_open_url_download_is_ok_not_error():
    import browser as browser_mod

    orig = browser_mod.browser_open

    def fake_open(url: str, **_kw):
        return {
            "url": "https://arxiv.org/search",
            "title": "Search",
            "text": "Showing 1–50 of 1934 results\n" * 5,
            "error": None,
            "download": True,
            "download_filename": "2609.19059.pdf",
            "download_url": url,
            "cookies_dismissed": 0,
        }

    browser_mod.browser_open = fake_open
    try:
        result = execute_acquisition_action(
            {
                "action_class": "OPEN_URL",
                "target_href": "https://arxiv.org/pdf/2609.19059",
            },
            max_chars=4000,
        )
    finally:
        browser_mod.browser_open = orig
    assert result.get("download") is True, result
    assert result.get("ok") is True, result
    assert not result.get("error"), result
    assert "1934 results" in str(result.get("text") or "")
    print("OK test_execute_open_url_download_is_ok_not_error")


def test_execute_open_url_real_error_still_fails():
    import browser as browser_mod

    orig = browser_mod.browser_open

    def fake_open(url: str, **_kw):
        return {
            "url": url,
            "title": "",
            "text": "",
            "error": "Timeout 60000ms exceeded.",
        }

    browser_mod.browser_open = fake_open
    try:
        result = execute_acquisition_action(
            {"action_class": "OPEN_URL", "target_href": "https://example.test/x"},
            max_chars=400,
        )
    finally:
        browser_mod.browser_open = orig
    assert result.get("ok") is False, result
    assert result.get("error"), result
    assert not result.get("download")
    print("OK test_execute_open_url_real_error_still_fails")


def test_playwright_content_disposition_attachment():
    """Optional: local HTTP server returns attachment; stay on list page."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP test_playwright_content_disposition_attachment (no playwright)")
        return
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from browser import browser_open

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_a, **_k):
            return

        def do_GET(self):
            if self.path.startswith("/file.pdf"):
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header(
                    "Content-Disposition", 'attachment; filename="paper.pdf"'
                )
                self.end_headers()
                self.wfile.write(b"%PDF-1.4 fake")
                return
            body = (
                b"<html><body><h1>SEARCH LIST STAYS HERE</h1>"
                b"<p>Showing results</p>"
                b"<a href='/file.pdf'>pdf</a></body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = HTTPServer(("127.0.0.1", 0), H)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        list_url = f"http://127.0.0.1:{port}/"
        pdf_url = f"http://127.0.0.1:{port}/file.pdf"
        first = browser_open(list_url, wait_seconds=0.3, max_chars=4000)
        if first.get("error") and "playwright" in str(first.get("error")).lower():
            print(f"SKIP test_playwright_content_disposition_attachment ({first.get('error')})")
            return
        assert "SEARCH LIST STAYS HERE" in str(first.get("text") or ""), first
        second = browser_open(pdf_url, wait_seconds=0.3, max_chars=4000)
        assert second.get("download") is True, second
        assert not second.get("error"), second
        assert "SEARCH LIST STAYS HERE" in str(second.get("text") or ""), second
        print("OK test_playwright_content_disposition_attachment")
    finally:
        httpd.shutdown()


def main():
    test_detects_live_download_error_string()
    test_negative_other_errors_are_not_downloads()
    test_download_navigation_keeps_current_page_text()
    test_negative_timeout_still_raises()
    test_execute_open_url_download_is_ok_not_error()
    test_execute_open_url_real_error_still_fails()
    test_playwright_content_disposition_attachment()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
