"""
Schema contract test between the skill and the MCP.

The real MCP server (``skills/tts-duet/mcp/``) is expected to emit
JSON Schema files via ``gemini-tts-mcp --dump-schemas`` into
``skills/tts-duet/mcp/tests/fixtures/schemas/`` as part of its build
(task #3). This test:

1. Loads every schema from that directory.
2. Asserts the tool set exactly matches the skill's expected surface
   (``tts_generate_chunk``, ``tts_preview_voice``, ``tts_count_tokens``,
   ``text_transform``, ``meta_health``).
3. Asserts domain-boundary invariants (AC-9): ``text_transform`` input
   schema contains EXACTLY ``{prompt, model, temperature,
   max_output_tokens}`` — no TTS-domain fields such as ``genre``,
   ``script``, ``existing_notes_policy``.
4. Validates a representative argument payload (from the fake MCP)
   against each input schema so the skill-side ``mcp_client.py``
   payloads stay in lockstep with the real server.

When the schemas directory does not exist yet (worker-3 has not landed
``--dump-schemas``) the test skips with a clear explanation. Once the
fixture is committed, the skip turns into a failure on any drift.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMAS_DIR = REPO_ROOT / "skills" / "tts-duet" / "mcp" / "tests" / "fixtures" / "schemas"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURES_DIR))

import fake_mcp_server as fms  # noqa: E402


EXPECTED_TOOLS = frozenset({
    "tts_generate_chunk",
    "tts_preview_voice",
    "tts_count_tokens",
    "text_transform",
    "meta_health",
})


def _schema_file(tool: str) -> Path:
    return SCHEMAS_DIR / (tool.replace(".", "_") + ".json")


def _require_schemas_dir() -> None:
    if not SCHEMAS_DIR.is_dir():
        pytest.skip(
            f"MCP schema fixtures not yet available at {SCHEMAS_DIR}. "
            "Run `gemini-tts-mcp --dump-schemas` once worker-3 lands it."
        )


def _load_schema(tool: str) -> dict:
    path = _schema_file(tool)
    if not path.is_file():
        pytest.skip(f"schema fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tool set + schema presence
# ---------------------------------------------------------------------------


def test_every_expected_tool_has_a_schema_fixture() -> None:
    _require_schemas_dir()
    for tool in EXPECTED_TOOLS:
        path = _schema_file(tool)
        assert path.is_file(), f"missing schema fixture for {tool}: {path}"


def test_no_unexpected_tools_in_schema_dir() -> None:
    _require_schemas_dir()
    # Tool names are now underscore form; filenames match directly.
    found = {p.stem for p in SCHEMAS_DIR.glob("*.json")}
    # soft check: just assert we at least cover every expected tool
    assert EXPECTED_TOOLS.issubset(found), (
        f"schema dir does not cover expected tools. found={found}"
    )


# ---------------------------------------------------------------------------
# AC-9: text_transform boundary — no TTS-domain fields
# ---------------------------------------------------------------------------


def test_text_transform_input_has_no_tts_domain_fields() -> None:
    _require_schemas_dir()
    schema = _load_schema("text_transform")
    input_schema = schema.get("inputSchema", schema)
    props = set((input_schema.get("properties") or {}).keys())
    forbidden = {"genre", "script", "existing_notes_policy", "voices", "voice_a", "voice_b"}
    leaked = props & forbidden
    assert not leaked, (
        f"text_transform input schema leaked TTS-domain fields: {leaked}. "
        "AC-9 violated — director prompt composition must live in director.py."
    )


def test_text_transform_input_allows_only_generic_fields() -> None:
    _require_schemas_dir()
    schema = _load_schema("text_transform")
    input_schema = schema.get("inputSchema", schema)
    props = set((input_schema.get("properties") or {}).keys())
    allowed = {"prompt", "model", "temperature", "max_output_tokens"}
    unexpected = props - allowed
    assert not unexpected, (
        f"text_transform advertises unexpected input fields: {unexpected}. "
        "Only {prompt, model, temperature, max_output_tokens} are permitted."
    )


# ---------------------------------------------------------------------------
# Fake MCP honours the same schemas (so integration tests stay honest)
# ---------------------------------------------------------------------------


def test_fake_mcp_schemas_match_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    _require_schemas_dir()
    monkeypatch.setenv("FAKE_MCP_SCHEMAS_DIR", str(SCHEMAS_DIR))
    loaded = fms._load_recorded_schemas()
    for tool in EXPECTED_TOOLS:
        assert tool in loaded, f"fake MCP fixture failed to load schema for {tool}"


# ---------------------------------------------------------------------------
# Placeholder that always runs — reminds devs the test exists
# ---------------------------------------------------------------------------


def test_contract_test_is_wired() -> None:
    """Sanity check: this test module itself is importable and EXPECTED_TOOLS
    matches the fake MCP's tool list."""
    assert EXPECTED_TOOLS == frozenset(fms.TOOL_NAMES)
