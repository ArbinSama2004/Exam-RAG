"""Talk to the LLM provider.

Ollama runs the model locally, which suits a single-user application that
should work offline and cost nothing per call. It is reached over its HTTP API
rather than its Python package, so the only dependency is httpx, which the
project already has.

`LLMClient` is the seam: prompt building, MCQ generation and answer generation
depend on this interface, not on Ollama. Adding a hosted provider later means
adding a class here, not editing the callers.
"""

import json
import logging
from typing import Any, Protocol

import httpx

from examrag.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """The model was unreachable, timed out or returned something unusable."""


class LLMClient(Protocol):
    """What the generation layer needs from a language model."""

    @property
    def model_name(self) -> str: ...

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        """Return the model's text response."""

    async def complete_json(
        self, prompt: str, *, system: str | None = None
    ) -> dict[str, Any] | list[Any]:
        """Return the model's response parsed as JSON."""


class OllamaClient:
    """LLM access through a local Ollama server."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def model_name(self) -> str:
        return self._settings.ollama_model

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        return await self._generate(prompt, system=system, json_mode=False)

    async def complete_json(
        self, prompt: str, *, system: str | None = None
    ) -> dict[str, Any] | list[Any]:
        """Generate with Ollama's JSON mode and parse the result.

        JSON mode constrains decoding to valid JSON, which removes the most
        common failure of small local models — prose wrapped around the object.
        It does not guarantee the *shape*, so callers still validate.
        """
        raw = await self._generate(prompt, system=system, json_mode=True)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"The model did not return valid JSON: {exc}") from exc

        if not isinstance(parsed, dict | list):
            raise LLMError(f"Expected a JSON object or array, got {type(parsed).__name__}.")
        return parsed

    async def _generate(self, prompt: str, *, system: str | None, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self._settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                # Low temperature: exam questions and grounded answers should
                # be reproducible, not creative.
                "temperature": self._settings.llm_temperature,
                "num_ctx": self._settings.llm_context_tokens,
            },
        }
        if system is not None:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        url = f"{self._settings.ollama_base_url}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"{self._settings.ollama_model} did not respond within "
                f"{self._settings.llm_timeout_seconds}s."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMError(self._explain(exc)) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Could not reach Ollama at {self._settings.ollama_base_url}: {exc}"
            ) from exc

        text = str(body.get("response", "")).strip()
        if not text:
            raise LLMError("The model returned an empty response.")
        return text

    def _explain(self, exc: httpx.HTTPStatusError) -> str:
        """Turn Ollama's status codes into something actionable."""
        if exc.response.status_code == 404:
            return (
                f"Ollama does not have the model {self._settings.ollama_model}. "
                f"Pull it with: ollama pull {self._settings.ollama_model}"
            )
        return f"Ollama returned {exc.response.status_code}: {exc.response.text[:200]}"


async def check_llm_available(settings: Settings | None = None) -> tuple[bool, str]:
    """Report whether Ollama is reachable and has the configured model.

    Used by the readiness endpoint, so a missing model is visible before a user
    waits on a generation request that cannot succeed.
    """
    settings = settings or get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            names = {model["name"] for model in response.json().get("models", [])}
    except httpx.HTTPError as exc:
        return False, f"Ollama is unreachable at {settings.ollama_base_url}: {exc}"

    # Ollama reports tagged names, so `llama3.1:8b` may be listed as-is while
    # a request for `llama3.1` also works.
    if settings.ollama_model in names or any(
        name.split(":")[0] == settings.ollama_model.split(":")[0] for name in names
    ):
        return True, f"{settings.ollama_model} is available"
    return False, (
        f"Ollama is running but does not have {settings.ollama_model}. "
        f"Pull it with: ollama pull {settings.ollama_model}"
    )
