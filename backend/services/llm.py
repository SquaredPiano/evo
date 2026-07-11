"""Unified LLM client for Evo — every model call routes through OpenRouter.

OpenRouter exposes an OpenAI-compatible Chat Completions API, so a single
httpx-based async client covers all of Evo's LLM needs:

  - `complete_text()`   — one-shot completion returning plain text
  - `stream_text()`     — token/chunk streaming via SSE (for explanations)
  - `complete_json()`   — JSON-mode completion parsed into a dict

This replaces the previous ad-hoc Gemini / Claude / LangChain / OpenAI paths.
Provider and model are chosen entirely by configuration (`LLM_MODEL`,
`LLM_FAST_MODEL`), so swapping models is a one-line env change with no code
changes. When no API key is configured, `llm_available()` returns False and
callers fall back to their deterministic behaviour.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("evo")

# OpenRouter recommends these headers for attribution / rankings. Harmless if ignored.
_ATTRIBUTION_HEADERS = {
    "HTTP-Referer": "https://github.com/evo-genomics/evo",
    # HTTP header values must be latin-1/ASCII encodable — keep this plain ASCII
    # (no em dash) or httpx raises UnicodeEncodeError when building the request.
    "X-Title": "Evo - Genomic Design IDE",
}


class LLMError(RuntimeError):
    """Raised when an OpenRouter request fails after the client tried its best."""


def llm_available() -> bool:
    """True when an OpenRouter API key is configured."""
    return bool(settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", ""))


def default_model() -> str:
    return settings.llm_model


def fast_model() -> str:
    """A cheaper/faster model for planning and short structured calls."""
    return settings.llm_fast_model or settings.llm_model


def _headers() -> dict[str, str]:
    key = settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        **_ATTRIBUTION_HEADERS,
    }


def _base_url() -> str:
    return settings.openrouter_base_url.rstrip("/")


async def complete_text(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 700,
    timeout: float = 30.0,
) -> str:
    """Run a chat completion and return the assistant's text content."""
    if not llm_available():
        raise LLMError("No OPENROUTER_API_KEY configured")

    payload: dict[str, Any] = {
        "model": model or default_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{_base_url()}/chat/completions", headers=_headers(), json=payload
        )
        resp.raise_for_status()
        data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected OpenRouter response shape: {exc}") from exc


async def complete_json(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 900,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Run a JSON-mode completion and return the parsed object.

    Requests OpenRouter's ``response_format={"type": "json_object"}`` and
    defensively extracts the first JSON object if the model wraps it in prose
    or fenced code blocks.
    """
    if not llm_available():
        raise LLMError("No OPENROUTER_API_KEY configured")

    payload: dict[str, Any] = {
        "model": model or fast_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{_base_url()}/chat/completions", headers=_headers(), json=payload
        )
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"] or "{}"
    return _extract_json_object(content)


async def stream_text(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 700,
    timeout: float = 45.0,
) -> AsyncGenerator[str, None]:
    """Stream assistant text chunks via OpenRouter SSE.

    Yields content deltas as they arrive. Raises LLMError on transport failure
    so callers can fall back to a deterministic path.
    """
    if not llm_available():
        raise LLMError("No OPENROUTER_API_KEY configured")

    payload: dict[str, Any] = {
        "model": model or default_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", f"{_base_url()}/chat/completions", headers=_headers(), json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if chunk == "[DONE]":
                    break
                try:
                    parsed = json.loads(chunk)
                    delta = parsed["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                if delta:
                    yield delta


def _extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from model output."""
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` fences
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    logger.warning("Could not parse JSON from LLM output: %s", text[:200])
    return {}
