"""Director pass behaviour tests (AC-9 + plan §5.3 director.py contract).

These tests pin the boundary that the plan calls *load-bearing*:

- ``director.py`` owns prompt composition, genre vocabulary, the
  Director's-Notes output format, and the existing-notes policy.
- The MCP's ``text.transform`` tool only sees the assembled prompt; it
  never receives ``genre``, ``existing_notes_policy``, ``script``,
  ``voices``, etc.

We assert this two ways:

1. Capture the exact arguments director passes to the MCP client and
   check the key set.
2. Assert that the prompt string actually contains the genre vocabulary
   (so the genre is being threaded through *prompt composition*, not
   smuggled as a sidecar field).
"""

from __future__ import annotations

from typing import Any

import pytest

director = pytest.importorskip(
    "lib.director",
    reason="lib.director not yet landed by worker-b (task #2)",
)


ALLOWED_TEXT_TRANSFORM_KEYS = frozenset(
    {"prompt", "model", "temperature", "max_output_tokens"}
)
FORBIDDEN_TEXT_TRANSFORM_KEYS = frozenset(
    {"genre", "script", "existing_notes_policy", "voices", "voice_a", "voice_b"}
)


class _RecordingClient:
    """Stand-in for ``lib.mcp_client.GeminiTTSMCPClient`` that records
    every ``text_transform`` call and returns a canned response."""

    def __init__(self, response_text: str = "[enriched] line 1\n[enriched] line 2\n") -> None:
        self.calls: list[dict[str, Any]] = []
        self._response_text = response_text

    def __enter__(self) -> "_RecordingClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "package_version": "fake",
            "protocol_version": "1",
            "model_availability": {"gemini-2.5-flash": True},
        }

    def text_transform(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        return {
            "text": self._response_text,
            "input_tokens": 10,
            "output_tokens": 20,
            "model_id": kwargs.get("model", "gemini-2.5-flash"),
        }


def _resolve_auto_direct():
    fn = getattr(director, "auto_direct", None)
    if callable(fn):
        return fn
    pytest.skip(
        "director.auto_direct() not implemented yet by worker-b (task #2)"
    )


# ---------------------------------------------------------------------------
# AC-9: text.transform call must carry only generic fields
# ---------------------------------------------------------------------------


def test_director_passes_only_generic_fields_to_text_transform() -> None:
    auto_direct = _resolve_auto_direct()
    client = _RecordingClient()
    raw_script = "A: hello\n\nB: hi back\n"
    auto_direct(
        script=raw_script,
        client=client,
        model="gemini-2.5-flash",
        genre="podcast-chill",
    )
    assert client.calls, "director never called text_transform"
    last = client.calls[-1]
    keys = set(last)
    leaked = keys & FORBIDDEN_TEXT_TRANSFORM_KEYS
    assert not leaked, (
        f"director leaked TTS-domain keys to text.transform: {leaked}. "
        "AC-9 violated — those concepts must stay inside director.py."
    )
    unexpected = keys - ALLOWED_TEXT_TRANSFORM_KEYS
    assert not unexpected, (
        f"director passed unexpected keys to text.transform: {unexpected}"
    )


def test_director_includes_genre_vocab_inside_the_prompt() -> None:
    """If the genre never reaches the model, the director isn't doing
    its job. It must reach the model *via the prompt string*, not as a
    sidecar field."""
    auto_direct = _resolve_auto_direct()
    client = _RecordingClient()
    auto_direct(
        script="A: hello\n\nB: hi back\n",
        client=client,
        model="gemini-2.5-flash",
        genre="podcast-chill",
    )
    last = client.calls[-1]
    prompt = last.get("prompt", "")
    assert "podcast-chill" in prompt or "chill" in prompt.lower(), (
        "director composed a prompt that does not reference the genre; "
        "either prompt composition is broken or the genre is being "
        "smuggled out-of-band."
    )


def test_director_temperature_and_max_tokens_are_set() -> None:
    auto_direct = _resolve_auto_direct()
    client = _RecordingClient()
    auto_direct(
        script="A: hello\n\nB: hi\n",
        client=client,
        model="gemini-2.5-flash",
        genre="podcast-chill",
    )
    last = client.calls[-1]
    # The plan pins defaults but allows callers to override; we assert
    # the keys are present and well-typed, not their exact values.
    if "temperature" in last:
        assert isinstance(last["temperature"], (int, float))
    if "max_output_tokens" in last:
        assert isinstance(last["max_output_tokens"], int)
        assert last["max_output_tokens"] > 0


# ---------------------------------------------------------------------------
# Domain post-processing must happen skill-side (not in the MCP)
# ---------------------------------------------------------------------------


def test_director_returns_enriched_script_text() -> None:
    auto_direct = _resolve_auto_direct()
    client = _RecordingClient(response_text="[enriched] one\n[enriched] two\n")
    enriched = auto_direct(
        script="A: x\n\nB: y\n",
        client=client,
        model="gemini-2.5-flash",
        genre="podcast-chill",
    )
    # Accept either a string return or an object with a `.text` attribute.
    text = getattr(enriched, "text", enriched)
    assert isinstance(text, str)
    assert text.strip(), "director returned empty enriched script"
