"""Tests for the Ollama client, with HTTP mocked by respx."""

import json
import re

import httpx
import pytest
import respx

from examrag.config import Settings
from examrag.generation.llm_client import LLMError, OllamaClient, check_llm_available

BASE_URL = "http://ollama.test:11434"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        ollama_base_url=BASE_URL,
        ollama_model="llama3.1:8b",
        llm_timeout_seconds=5.0,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def client(settings: Settings) -> OllamaClient:
    return OllamaClient(settings=settings)


def generate_route() -> str:
    return f"{BASE_URL}/api/generate"


def sent(route: respx.Route) -> dict:
    """The JSON body of the last request made to a route."""
    return json.loads(route.calls.last.request.read())


class TestCompletion:
    @respx.mock
    async def test_the_model_response_is_returned(self, client: OllamaClient) -> None:
        respx.post(generate_route()).mock(
            return_value=httpx.Response(200, json={"response": "  TCP is reliable.  "})
        )

        assert await client.complete("What is TCP?") == "TCP is reliable."

    @respx.mock
    async def test_the_configured_model_and_prompt_are_sent(self, client: OllamaClient) -> None:
        route = respx.post(generate_route()).mock(
            return_value=httpx.Response(200, json={"response": "ok"})
        )

        await client.complete("What is TCP?", system="Be precise.")

        payload = sent(route)
        assert payload["model"] == "llama3.1:8b"
        assert payload["prompt"] == "What is TCP?"
        assert payload["system"] == "Be precise."

    @respx.mock
    async def test_streaming_is_disabled(self, client: OllamaClient) -> None:
        """A streamed body would not parse as one JSON object."""
        route = respx.post(generate_route()).mock(
            return_value=httpx.Response(200, json={"response": "ok"})
        )

        await client.complete("hi")

        assert sent(route)["stream"] is False

    @respx.mock
    async def test_an_empty_response_is_an_error(self, client: OllamaClient) -> None:
        respx.post(generate_route()).mock(return_value=httpx.Response(200, json={"response": "  "}))

        with pytest.raises(LLMError, match="empty response"):
            await client.complete("hi")


class TestJsonMode:
    @respx.mock
    async def test_json_mode_is_requested_and_the_result_parsed(self, client: OllamaClient) -> None:
        route = respx.post(generate_route()).mock(
            return_value=httpx.Response(200, json={"response": '{"questions": [1, 2]}'})
        )

        result = await client.complete_json("Write questions")

        assert result == {"questions": [1, 2]}
        assert sent(route)["format"] == "json"

    @respx.mock
    async def test_a_bare_array_is_accepted(self, client: OllamaClient) -> None:
        respx.post(generate_route()).mock(
            return_value=httpx.Response(200, json={"response": "[1, 2, 3]"})
        )

        assert await client.complete_json("go") == [1, 2, 3]

    @respx.mock
    async def test_invalid_json_is_an_error(self, client: OllamaClient) -> None:
        respx.post(generate_route()).mock(
            return_value=httpx.Response(200, json={"response": "Here you go: {oops"})
        )

        with pytest.raises(LLMError, match="did not return valid JSON"):
            await client.complete_json("go")

    @respx.mock
    async def test_a_json_scalar_is_rejected(self, client: OllamaClient) -> None:
        """A bare number is valid JSON but useless to every caller."""
        respx.post(generate_route()).mock(return_value=httpx.Response(200, json={"response": "42"}))

        with pytest.raises(LLMError, match="Expected a JSON object or array"):
            await client.complete_json("go")


class TestFailures:
    @respx.mock
    async def test_a_missing_model_says_how_to_fix_it(self, client: OllamaClient) -> None:
        respx.post(generate_route()).mock(return_value=httpx.Response(404, text="not found"))

        with pytest.raises(LLMError, match=re.escape("ollama pull llama3.1:8b")):
            await client.complete("hi")

    @respx.mock
    async def test_a_server_error_is_reported(self, client: OllamaClient) -> None:
        respx.post(generate_route()).mock(return_value=httpx.Response(500, text="boom"))

        with pytest.raises(LLMError, match="Ollama returned 500"):
            await client.complete("hi")

    @respx.mock
    async def test_an_unreachable_server_names_the_url(self, client: OllamaClient) -> None:
        respx.post(generate_route()).mock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(LLMError, match=re.escape(BASE_URL)):
            await client.complete("hi")

    @respx.mock
    async def test_a_timeout_names_the_limit(self, client: OllamaClient) -> None:
        respx.post(generate_route()).mock(side_effect=httpx.ReadTimeout("slow"))

        with pytest.raises(LLMError, match="did not respond within"):
            await client.complete("hi")


class TestAvailabilityCheck:
    @respx.mock
    async def test_an_available_model_is_reported(self, settings: Settings) -> None:
        respx.get(f"{BASE_URL}/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
        )

        available, detail = await check_llm_available(settings)

        assert available is True
        assert "llama3.1:8b" in detail

    @respx.mock
    async def test_a_different_tag_of_the_same_model_counts(self, settings: Settings) -> None:
        respx.get(f"{BASE_URL}/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:latest"}]})
        )

        available, _ = await check_llm_available(settings)

        assert available is True

    @respx.mock
    async def test_a_missing_model_says_how_to_pull_it(self, settings: Settings) -> None:
        respx.get(f"{BASE_URL}/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "mistral:7b"}]})
        )

        available, detail = await check_llm_available(settings)

        assert available is False
        assert "ollama pull llama3.1:8b" in detail

    @respx.mock
    async def test_an_unreachable_server_is_not_available(self, settings: Settings) -> None:
        respx.get(f"{BASE_URL}/api/tags").mock(side_effect=httpx.ConnectError("refused"))

        available, detail = await check_llm_available(settings)

        assert available is False
        assert "unreachable" in detail
