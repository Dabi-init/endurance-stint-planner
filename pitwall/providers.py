"""Model-provider boundary. Only a local Ollama endpoint is supported."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pitwall.config import Settings


class ProviderError(RuntimeError):
    """A local model could not be reached or returned an invalid response."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelMessage:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    raw_message: dict[str, Any] = field(default_factory=dict, compare=False)


class ModelProvider(Protocol):
    name: str

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelMessage: ...


class OllamaProvider:
    """Minimal Ollama client using its documented local HTTP API."""

    name = "ollama"

    def __init__(self, settings: Settings, *, timeout_sec: float = 90.0) -> None:
        issues = settings.validate()
        if issues:
            raise ProviderError("; ".join(issues))
        if not settings.model_enabled:
            raise ProviderError("No Ollama model is selected")
        self.host = settings.ollama_host.rstrip("/")
        self.model = settings.model
        self.timeout_sec = timeout_sec

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelMessage:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.1},
        }
        response = self._request("/api/chat", payload)
        message = response.get("message")
        if not isinstance(message, dict):
            raise ProviderError("Ollama returned no assistant message")

        calls: list[ToolCall] = []
        for raw_call in message.get("tool_calls", []) or []:
            function = (
                raw_call.get("function", {}) if isinstance(raw_call, dict) else {}
            )
            name = str(function.get("name", "")).strip()
            arguments = function.get("arguments", {})
            if name:
                calls.append(
                    ToolCall(
                        name=name,
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
        return ModelMessage(
            content=str(message.get("content", "")).strip(),
            tool_calls=tuple(calls),
            raw_message=message,
        )

    def list_models(self) -> list[str]:
        response = self._request("/api/tags")
        models = response.get("models", [])
        return sorted(
            str(item.get("name", ""))
            for item in models
            if isinstance(item, dict) and item.get("name")
        )

    def _request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.host + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Cannot reach local Ollama: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError("Ollama returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise ProviderError("Ollama returned an unexpected response")
        return parsed


def list_local_models(settings: Settings, *, timeout_sec: float = 2.0) -> list[str]:
    """Probe Ollama without requiring a model to already be configured."""
    probe = Settings(
        provider="ollama",
        model=settings.model or "__probe__",
        ollama_host=settings.ollama_host,
        remember_sessions=settings.remember_sessions,
    )
    return OllamaProvider(probe, timeout_sec=timeout_sec).list_models()
