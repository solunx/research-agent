"""
Open #31 — structural blocking-overlay dismiss. No consent/cookie lexicon.

Detect [role=dialog] / aria-modal=true. Dismiss control = first button in
DOM order inside that overlay (not shortest visible text). Cross-origin
iframe with no same-origin button → hide the dialog (cannot click inside).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

_TIMEOUTISH_RE = re.compile(r"timeout|intercepts pointer", re.I)


def page_state_key(page_url: str) -> str:
    """Same grain as action_fingerprint path: URL path, no query."""
    try:
        path = (urlparse(page_url or "").path or "/").rstrip("/") or "/"
    except Exception:
        path = "/"
    return path.lower()


def is_timeoutish_error(err: str | None) -> bool:
    return bool(_TIMEOUTISH_RE.search(str(err or "")))


def overlay_dismiss_should_run(
    *,
    prior_timeout_fps: list[str] | None,
    current_fp: str,
) -> bool:
    """True after ≥1 earlier timeout fingerprint on this page, different target.

    Reuses action_fingerprint keys. First failure never dismisses (Coolblue
    Zoeken is one timeout, then a different fallback — must not fire here).
    """
    cur = str(current_fp or "")
    others = [str(f) for f in (prior_timeout_fps or []) if str(f) != cur]
    return len(others) >= 1


class _OverlayParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.overlays: list[dict[str, Any]] = []
        self._cur: dict[str, Any] | None = None
        self._depth = 0
        self._btn: dict[str, Any] | None = None
        self._btn_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {str(k).lower(): str(v or "") for k, v in attrs}
        role = ad.get("role", "").strip().lower()
        modal = ad.get("aria-modal", "").strip().lower()
        t = tag.lower()
        if self._cur is None:
            if role == "dialog" or modal == "true":
                self._cur = {
                    "tag": t,
                    "role": role,
                    "aria_modal": modal,
                    "id": ad.get("id", ""),
                    "buttons": [],
                    "n_iframes": 0,
                }
                self._depth = 1
                self._maybe_start_button(t, ad, role)
            return
        if t == self._cur["tag"]:
            self._depth += 1
        if t == "iframe":
            self._cur["n_iframes"] += 1
        self._maybe_start_button(t, ad, role)

    def _maybe_start_button(self, tag: str, ad: dict[str, str], role: str) -> None:
        if self._cur is None or self._btn is not None:
            return
        is_btn = (
            tag == "button"
            or (tag == "input" and ad.get("type", "").lower() in ("button", "submit"))
            or role == "button"
        )
        if not is_btn:
            return
        self._btn = {
            "tag": tag,
            "text": "",
            "aria_label": ad.get("aria-label", ""),
            "type": ad.get("type", ""),
        }
        self._btn_depth = 1
        if tag == "input":
            val = ad.get("value", "")
            if val:
                self._btn["text"] = val
            self._finish_button()

    def _finish_button(self) -> None:
        if self._cur is None or self._btn is None:
            self._btn = None
            self._btn_depth = 0
            return
        text = (self._btn.get("text") or "").strip() or (self._btn.get("aria_label") or "").strip()
        self._cur["buttons"].append(
            {
                "tag": self._btn["tag"],
                "text": text[:80],
                "aria_label": str(self._btn.get("aria_label") or "")[:80],
            }
        )
        self._btn = None
        self._btn_depth = 0

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if self._btn is not None:
            if t == self._btn["tag"]:
                self._btn_depth -= 1
                if self._btn_depth <= 0:
                    self._finish_button()
        if self._cur is None:
            return
        if t == self._cur["tag"]:
            self._depth -= 1
            if self._depth <= 0:
                self.overlays.append(self._cur)
                self._cur = None
                self._depth = 0

    def handle_data(self, data: str) -> None:
        if self._btn is not None:
            self._btn["text"] = str(self._btn.get("text") or "") + data


def overlays_from_html(html: str) -> list[dict[str, Any]]:
    """Structural overlay list from an HTML string. No host/cookie words."""
    parser = _OverlayParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return []
    return parser.overlays


def pick_overlay_dismiss(overlays: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Choose a dismiss plan. First DOM button beats shortest text.

    iframe-only dialog (2dehands Sourcepoint): no same-origin button →
    method=hide_blocking_dialog. That is still a chosen dismiss target
    (the dialog node), not a lexicon click.
    """
    if not overlays:
        return None
    ov = overlays[0]
    buttons = list(ov.get("buttons") or [])
    if buttons:
        first = buttons[0]
        return {
            "method": "first_button",
            "overlay_id": ov.get("id") or "",
            "overlay_role": ov.get("role") or "",
            "aria_modal": ov.get("aria_modal") or "",
            "n_buttons": len(buttons),
            "n_iframes": int(ov.get("n_iframes") or 0),
            "first_button_text": first.get("text") or first.get("aria_label") or "",
            "click_selector": (
                '[role="dialog"], [aria-modal="true"]'
                " >> button, [role='button'], input[type='button'], input[type='submit']"
            ),
        }
    if int(ov.get("n_iframes") or 0) >= 1 or ov.get("role") == "dialog" or ov.get("aria_modal") == "true":
        return {
            "method": "hide_blocking_dialog",
            "overlay_id": ov.get("id") or "",
            "overlay_role": ov.get("role") or "",
            "aria_modal": ov.get("aria_modal") or "",
            "n_buttons": 0,
            "n_iframes": int(ov.get("n_iframes") or 0),
            "first_button_text": "",
            "click_selector": '[role="dialog"][aria-modal="true"]',
        }
    return None
