"""Shared fixtures.

The ``fake_genai`` fixture monkeypatches ``google.genai.Client`` so the
server's lifespan can construct a client without an API key. Each test
gets its own ``MagicMock`` client; canned responses default to one
second of silence at 24 kHz / 16-bit / mono.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--update-fixtures",
        action="store_true",
        default=False,
        help="Regenerate schema fixtures instead of asserting against them.",
    )


CANNED_PCM = b"\x00" * 48000  # 1 s of silence @ 24 kHz, 16-bit, mono


def _build_audio_response(pcm: bytes = CANNED_PCM) -> MagicMock:
    response = MagicMock()
    part = MagicMock()
    part.inline_data.data = pcm
    candidate = MagicMock()
    candidate.content.parts = [part]
    response.candidates = [candidate]
    response.usage_metadata.prompt_token_count = 100
    response.usage_metadata.candidates_token_count = 24000
    return response


def _build_text_response(text: str = "transformed text") -> MagicMock:
    response = MagicMock()
    response.text = text
    response.candidates = []
    response.usage_metadata.prompt_token_count = 50
    response.usage_metadata.candidates_token_count = 75
    return response


def _build_count_tokens_response(total: int = 123) -> MagicMock:
    response = MagicMock()
    response.total_tokens = total
    return response


@pytest.fixture
def fake_genai(monkeypatch, tmp_path):
    """Replace ``google.genai.Client`` with a deterministic mock.

    Also redirects the ``meta_health`` model cache to ``tmp_path`` so
    parallel runs don't share state with the developer's home cache.
    """

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _build_audio_response()
    fake_client.models.count_tokens.return_value = _build_count_tokens_response()
    fake_client.models.list.return_value = []

    fake_module = MagicMock()
    fake_module.Client = MagicMock(return_value=fake_client)
    monkeypatch.setattr("google.genai.Client", fake_module.Client)
    monkeypatch.setenv("GEMINI_TTS_MCP_CACHE_DIR", str(tmp_path / "cache"))

    fake_client._build_audio_response = _build_audio_response  # type: ignore[attr-defined]
    fake_client._build_text_response = _build_text_response  # type: ignore[attr-defined]
    return fake_client


@pytest.fixture
def app_context(fake_genai):
    """Construct the lifespan ``AppContext`` synchronously for unit tests."""

    from gemini_tts_mcp.client import AppContext

    return AppContext(client=fake_genai, has_api_key=False)
