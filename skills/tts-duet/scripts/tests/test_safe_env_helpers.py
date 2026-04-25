"""Unit tests for the ``_safe_env`` helpers (P1 + AC-17 invariants).

These tests pin the contract from plan §5.3:

- ``safe_env(for_mcp=False)`` MUST drop ``GEMINI_API_KEY`` and
  ``GOOGLE_API_KEY`` from the returned environment.
- ``safe_env(for_mcp=True)`` MUST forward those keys when present in the
  parent environment so the MCP child can read them.
- ``_safe_env_nohup(...)`` MUST forward ``TTS_DUET_MCP_COMMAND`` (so the
  background re-exec can resolve the MCP binary) AND strip both API
  keys regardless of the parent environment, because API-key material
  must never cross the skill→skill fork boundary.

Until worker-b lands ``scripts/lib/_safe_env.py`` the module import
fails — we skip the entire suite with a clear pointer.
"""

from __future__ import annotations

import os

import pytest

_safe_env = pytest.importorskip(
    "lib._safe_env",
    reason="lib._safe_env not yet landed by worker-b (task #2)",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch):
    """Wipe env keys this suite cares about so each test starts clean."""
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "TTS_DUET_MCP_COMMAND",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


# ---------------------------------------------------------------------------
# safe_env(for_mcp=False)
# ---------------------------------------------------------------------------


def test_safe_env_default_strips_gemini_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "sk-secret-1")
    monkeypatch.setenv("GOOGLE_API_KEY", "sk-secret-2")
    env = _safe_env.safe_env(for_mcp=False)
    assert "GEMINI_API_KEY" not in env
    assert "GOOGLE_API_KEY" not in env


def test_safe_env_default_keeps_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = _safe_env.safe_env(for_mcp=False)
    assert env.get("PATH") == "/usr/bin:/bin"


def test_safe_env_default_strips_arbitrary_unrelated_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFINITELY_NOT_ALLOWLISTED", "leak")
    env = _safe_env.safe_env(for_mcp=False)
    assert "DEFINITELY_NOT_ALLOWLISTED" not in env


# ---------------------------------------------------------------------------
# safe_env(for_mcp=True)
# ---------------------------------------------------------------------------


def test_safe_env_for_mcp_forwards_gemini_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "sk-secret-mcp")
    env = _safe_env.safe_env(for_mcp=True)
    assert env.get("GEMINI_API_KEY") == "sk-secret-mcp"


def test_safe_env_for_mcp_forwards_google_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "sk-google")
    env = _safe_env.safe_env(for_mcp=True)
    assert env.get("GOOGLE_API_KEY") == "sk-google"


def test_safe_env_for_mcp_omits_keys_when_unset() -> None:
    env = _safe_env.safe_env(for_mcp=True)
    # When parent env has no key, helper must not invent one.
    assert "GEMINI_API_KEY" not in env
    assert "GOOGLE_API_KEY" not in env


# ---------------------------------------------------------------------------
# _safe_env_nohup
# ---------------------------------------------------------------------------


def test_safe_env_nohup_strips_api_keys_even_when_parent_has_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "sk-leak")
    monkeypatch.setenv("GOOGLE_API_KEY", "sk-leak-2")
    env = _safe_env._safe_env_nohup(mcp_command=None)
    assert "GEMINI_API_KEY" not in env
    assert "GOOGLE_API_KEY" not in env


def test_safe_env_nohup_forwards_mcp_command_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TTS_DUET_MCP_COMMAND", "uvx --from . gemini-tts-mcp")
    env = _safe_env._safe_env_nohup(mcp_command=None)
    assert env.get("TTS_DUET_MCP_COMMAND") == "uvx --from . gemini-tts-mcp"


def test_safe_env_nohup_explicit_mcp_command_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a caller passes mcp_command explicitly, it should be serialised
    into TTS_DUET_MCP_COMMAND (the contract is documented in §5.3)."""
    env = _safe_env._safe_env_nohup(mcp_command=["gemini-tts-mcp", "--stdio"])
    forwarded = env.get("TTS_DUET_MCP_COMMAND")
    assert forwarded is not None
    # Whatever the encoding (shlex.join / json), both tokens must survive.
    assert "gemini-tts-mcp" in forwarded
    assert "--stdio" in forwarded


def test_parent_environment_is_not_mutated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "sk-still-here")
    _ = _safe_env.safe_env(for_mcp=False)
    _ = _safe_env._safe_env_nohup(mcp_command=None)
    assert os.environ["GEMINI_API_KEY"] == "sk-still-here"
