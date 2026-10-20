"""Minimal client for generating JSON with a local Ollama model (standard library only).

Used by the optional LLM query mapper (Step 5) and later by the explanation step. The
pipeline never depends on it: callers catch LLMError and fall back to rule-based code.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional


class LLMError(RuntimeError):
    """Ollama unreachable, model missing, or the reply was unusable."""


class ModelMissingError(LLMError):
    """The server is up but does not have the requested model."""


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool = False
    host: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:7b"
    fallback_model: str = "qwen2.5-coder:3b"
    timeout_seconds: float = 60.0

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]] = None, **overrides: Any) -> "LLMSettings":
        section = (cfg or {}).get("llm", {}) or {}
        known = {k: v for k, v in section.items() if k in cls.__dataclass_fields__}
        settings = replace(cls(), **known)
        return replace(settings, **{k: v for k, v in overrides.items() if v is not None})


class OllamaJSON:
    """Asks one model for one JSON object, constrained by a JSON schema when the server supports it."""

    def __init__(self, model: str, host: str = "http://localhost:11434", timeout: float = 60.0):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = urllib.request.Request(
            self.host + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code == 404 and "model" in body.lower():
                raise ModelMissingError(
                    f"Ollama does not have the model '{self.model}'. Run: ollama pull {self.model}"
                ) from exc
            error = LLMError(f"Ollama returned HTTP {exc.code}: {body[:200]}")
            error.http_status = exc.code  # type: ignore[attr-defined]
            raise error from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Cannot reach Ollama at {self.host} ({exc.reason}). Start it with: ollama serve") from exc
        except (TimeoutError, OSError) as exc:
            raise LLMError(f"Ollama request to {self.host} failed: {exc}") from exc
        except ValueError as exc:
            raise LLMError(f"Ollama sent a response that is not valid JSON: {exc}") from exc

    def generate_json(self, prompt: str, schema: Optional[Dict[str, Any]] = None) -> Any:
        """Return the parsed JSON the model produced. Raises LLMError for anything unusable."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": schema if schema else "json",
            "options": {"temperature": 0},
        }
        try:
            reply = self._post(payload)
        except LLMError as exc:
            # Older Ollama versions reject a schema in "format" (HTTP 400); retry in plain JSON mode.
            if schema and getattr(exc, "http_status", None) == 400:
                payload["format"] = "json"
                reply = self._post(payload)
            else:
                raise
        text = reply.get("response") if isinstance(reply, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise LLMError("Ollama returned an empty response")
        try:
            return json.loads(text)
        except ValueError as exc:
            raise LLMError(f"the model did not return valid JSON: {text[:120]!r}") from exc
