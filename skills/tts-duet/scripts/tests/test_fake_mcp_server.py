"""
Unit tests for the fake stdio MCP fixture used by the skill-side
integration suite.

These tests exercise the handler functions directly. The full stdio
round-trip is covered by ``test_mcp_schema_contract.py`` (fixture
discovery) and by the integration tests that spawn
``fake_mcp_server.py`` as a child process.
"""

from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURES_DIR))

import fake_mcp_server as fms  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    """Reset fixture counters and env overrides between tests."""
    for key in list(fms.STATE.__dict__):
        setattr(fms.STATE, key, 0)
    for var in [
        "FAKE_MCP_FAIL_AFTER",
        "FAKE_MCP_FAIL_RETRYABLE",
        "FAKE_MCP_CRASH_AFTER",
        "FAKE_MCP_HEALTH_PROTOCOL",
        "FAKE_MCP_HEALTH_KEY_STATUS",
        "FAKE_MCP_SCHEMAS_DIR",
    ]:
        monkeypatch.delenv(var, raising=False)
    yield


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_generate_chunk_returns_canonical_audio_shape() -> None:
    out = fms.handle_generate_chunk(
        {"model": "flash", "content": "hi", "voice_a": "Charon", "voice_b": None}
    )
    assert out["sample_rate_hz"] == 24000
    assert out["bits_per_sample"] == 16
    assert out["channels"] == 1
    pcm = base64.b64decode(out["pcm_base64"])
    assert len(pcm) > 0
    assert out["input_tokens"] >= 1
    assert out["output_tokens"] >= 1


def test_preview_voice_returns_audio_shape() -> None:
    out = fms.handle_preview_voice({"voice": "Aoede", "text": "hello", "model": "flash"})
    assert out["sample_rate_hz"] == 24000
    assert base64.b64decode(out["pcm_base64"])


def test_count_tokens_is_deterministic() -> None:
    content = "x" * 400
    assert fms.handle_count_tokens({"model": "flash", "content": content})["tokens"] == 100


def test_text_transform_echoes_prompt_content() -> None:
    out = fms.handle_text_transform(
        {"prompt": "turn this into prose", "model": "gemini-2.5-flash", "temperature": 0.2}
    )
    assert "turn this into prose" in out["text"]
    assert out["input_tokens"] >= 1
    assert out["output_tokens"] >= 1


def test_health_default_protocol_is_one() -> None:
    out = fms.handle_health({})
    assert out["ok"] is True
    assert out["protocol_version"] == fms.DEFAULT_PROTOCOL_VERSION
    assert out["api_key_status"] == "ok"


# ---------------------------------------------------------------------------
# Failure injection
# ---------------------------------------------------------------------------


def test_fail_after_produces_structured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MCP_FAIL_AFTER", "2")
    first = fms.handle_generate_chunk({})
    second = fms.handle_generate_chunk({})
    third = fms.handle_generate_chunk({})
    assert "pcm_base64" in first
    assert "pcm_base64" in second
    assert third["failure_reason"] == "tts_chunk_failed"
    assert third["retryable"] is True


def test_fail_after_can_emit_non_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MCP_FAIL_AFTER", "0")
    monkeypatch.setenv("FAKE_MCP_FAIL_RETRYABLE", "false")
    out = fms.handle_generate_chunk({})
    assert out["failure_reason"] == "tts_chunk_failed"
    assert out["retryable"] is False


def test_health_protocol_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MCP_HEALTH_PROTOCOL", "99")
    out = fms.handle_health({})
    assert out["protocol_version"] == "99"


def test_health_key_status_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MCP_HEALTH_KEY_STATUS", "missing")
    out = fms.handle_health({})
    assert out["api_key_status"] == "missing"


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


def test_default_schemas_cover_all_tools() -> None:
    defaults = fms._default_input_schemas()
    assert set(defaults.keys()) == set(fms.TOOL_NAMES)


def test_text_transform_default_schema_excludes_domain_fields() -> None:
    """AC-9: text.transform input schema has no tts-domain fields."""
    schema = fms._default_input_schemas()["text.transform"]
    props = set(schema["properties"])
    assert props == {"prompt", "model", "temperature", "max_output_tokens"}
    for forbidden in ("genre", "script", "existing_notes_policy", "voices"):
        assert forbidden not in props


def test_recorded_schemas_loaded_when_dir_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    fake_schema = {"type": "object", "properties": {"marker": {"type": "string"}}}
    (schemas / "tts_generate_chunk.json").write_text(
        __import__("json").dumps(fake_schema), encoding="utf-8"
    )
    monkeypatch.setenv("FAKE_MCP_SCHEMAS_DIR", str(schemas))
    importlib.reload(fms)
    loaded = fms._load_recorded_schemas()
    assert loaded["tts.generate_chunk"] == fake_schema


def test_recorded_schemas_empty_when_unset() -> None:
    assert fms._load_recorded_schemas() == {}


# ---------------------------------------------------------------------------
# build_server wiring
# ---------------------------------------------------------------------------


def test_build_server_registers_all_tools() -> None:
    server = fms.build_server()
    assert server.name == fms.SERVER_NAME


def test_state_counts_across_tools() -> None:
    fms.handle_generate_chunk({})
    fms.handle_count_tokens({"content": "x"})
    fms.handle_text_transform({"prompt": "y"})
    fms.handle_health({})
    snap = fms.STATE.snapshot()
    assert snap["generate_chunk"] == 1
    assert snap["count_tokens"] == 1
    assert snap["text_transform"] == 1
    assert snap["health"] == 1
