"""Model-provider boundary. Only a local Ollama endpoint is supported."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pitwall.config import Settings

MAX_PROVIDER_RESPONSE_BYTES = 8 * 1024 * 1024


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

        content = message.get("content", "")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ProviderError("Ollama returned invalid assistant content")

        raw_calls = message.get("tool_calls", [])
        if raw_calls is None:
            raw_calls = []
        if not isinstance(raw_calls, list):
            raise ProviderError("Ollama returned invalid tool_calls")

        calls: list[ToolCall] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                raise ProviderError("Ollama returned an invalid tool call")
            function = raw_call.get("function")
            if not isinstance(function, dict):
                raise ProviderError("Ollama returned an invalid tool function")
            name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProviderError("Ollama returned a tool call without a name")
            arguments = function.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ProviderError("Ollama returned invalid tool arguments")
            calls.append(
                ToolCall(
                    name=name.strip(),
                    arguments=arguments,
                )
            )
        raw_message: dict[str, Any] = {
            "role": "assistant",
            "content": content.strip(),
        }
        if raw_calls:
            raw_message["tool_calls"] = raw_calls
        return ModelMessage(
            content=content.strip(),
            tool_calls=tuple(calls),
            raw_message=raw_message,
        )

    def list_models(self) -> list[str]:
        response = self._request("/api/tags")
        models = response.get("models", [])
        if not isinstance(models, list):
            raise ProviderError("Ollama returned an invalid model list")
        names: list[str] = []
        for item in models:
            if not isinstance(item, dict):
                raise ProviderError("Ollama returned an invalid model entry")
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProviderError("Ollama returned a model without a name")
            names.append(name.strip())
        return sorted(names)

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
                encoded = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
                if len(encoded) > MAX_PROVIDER_RESPONSE_BYTES:
                    raise ProviderError(
                        "Ollama response exceeded the 8 MiB safety limit"
                    )
                raw = encoded.decode("utf-8")
                parsed = json.loads(raw, parse_constant=_reject_json_constant)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Cannot reach local Ollama: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise ProviderError("Ollama returned invalid UTF-8") from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError("Ollama returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise ProviderError("Ollama returned an unexpected response")
        return parsed


def _reject_json_constant(value: str) -> None:
    """Reject NaN and infinities, which are not valid JSON values."""
    raise ValueError(f"Invalid JSON constant: {value}")


def list_local_models(settings: Settings, *, timeout_sec: float = 2.0) -> list[str]:
    """Probe Ollama without requiring a model to already be configured."""
    probe = Settings(
        provider="ollama",
        model=settings.model or "__probe__",
        ollama_host=settings.ollama_host,
        remember_sessions=settings.remember_sessions,
    )
    return OllamaProvider(probe, timeout_sec=timeout_sec).list_models()
