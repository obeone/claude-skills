"""Unit tests for the ``_safe_env`` helpers (P1 + AC-17 invariants).

These tests pin the contract from plan §5.3:

- ``safe_env(for_mcp=False)`` MUST drop ``GEMINI_API_KEY`` and
  ``GOOGLE_API_KEY`` from the returned environment.
- ``safe_env(for_mcp=True)`` MUST forward those keys when present in the
  parent environment so the MCP child can read them.

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
# No-mutation invariant
# ---------------------------------------------------------------------------


def test_parent_environment_is_not_mutated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "sk-still-here")
    _ = _safe_env.safe_env(for_mcp=False)
    _ = _safe_env.safe_env(for_mcp=True)
    assert os.environ["GEMINI_API_KEY"] == "sk-still-here"
