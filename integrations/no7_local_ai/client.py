"""Client for the local "No7 AI" (Ollama-compatible) model.

The explainer never lets the LLM invent numbers: it receives a compact,
pre-computed fact sheet and is instructed to only restate it.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx


class No7LocalAI:
    def __init__(self, url: str | None = None, model: str | None = None,
                 enabled: bool | None = None, timeout: float = 12.0) -> None:
        self.url = (url or os.environ.get("NO7_LOCAL_AI_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("NO7_LOCAL_AI_MODEL", "no7-local")
        env_enabled = os.environ.get("NO7_LOCAL_AI_ENABLED", "false").lower() in ("1", "true", "yes")
        self.enabled = env_enabled if enabled is None else enabled
        self.timeout = timeout

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(f"{self.url}/api/tags")
                return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def generate(self, system: str, prompt: str) -> str | None:
        if not self.enabled:
            return None
        payload = {
            "model": self.model,
            "prompt": f"{system}\n\n{prompt}",
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 380},
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.url}/api/generate", json=payload)
                resp.raise_for_status()
                return resp.json().get("response", "").strip() or None
        except Exception:  # noqa: BLE001
            return None

    def describe(self) -> dict[str, Any]:
        return {"url": self.url, "model": self.model, "enabled": self.enabled, "available": self.available()}

    @staticmethod
    def dumps(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, default=str)
