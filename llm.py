"""
Minimal Ollama client with tool-calling support and retries.
"""

from __future__ import annotations

import time
from typing import Any

import requests

# Defaults match config.yaml (only used if caller omits args)
DEFAULT_BASE_URL = "http://172.17.0.1:11434"
DEFAULT_MODEL = "qwen3.8:27b"
DEFAULT_TIMEOUT = 480


class OllamaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = 2,
        retry_backoff_seconds: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Send a chat request to Ollama.
        Retries on 5xx / connection errors (not on read timeout of a long generation).
        Returns the raw message object from the response.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
            },
        }
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/api/chat"
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                # Read timeout must cover long report generation
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code >= 500 and attempt < self.max_retries:
                    wait = self.retry_backoff_seconds * (attempt + 1)
                    time.sleep(wait)
                    last_error = requests.HTTPError(
                        f"{resp.status_code} Server Error for url: {url}"
                    )
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", data)
            except requests.Timeout as e:
                # Do not retry timeouts: generation was likely still running
                last_error = e
                raise
            except requests.ConnectionError as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = self.retry_backoff_seconds * (attempt + 1)
                    time.sleep(wait)
                    continue
                raise
            except requests.HTTPError as e:
                last_error = e
                status = (
                    getattr(e.response, "status_code", None)
                    if hasattr(e, "response")
                    else None
                )
                if status and status >= 500 and attempt < self.max_retries:
                    wait = self.retry_backoff_seconds * (attempt + 1)
                    time.sleep(wait)
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Ollama chat failed after retries")

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            return [m.get("name", "") for m in models]
        except Exception:
            return []
