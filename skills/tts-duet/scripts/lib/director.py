"""Director pass — owns prompt composition and genre vocabulary.

Plan §5.3 + AC-9: this module is the load-bearing boundary between
skill-domain knowledge (genres, Director's-Notes format, existing-notes
policy) and the generic ``text.transform`` MCP tool. The MCP sees only
the assembled prompt string and the standard ``(model, temperature,
max_output_tokens)`` trio — no ``genre``, no ``script``, no
``existing_notes_policy`` field crosses the contract boundary.

The module exposes a single public entry point, :func:`auto_direct`,
which ``generate_tts.py`` (and ``/tts-duet-setup`` dry-runs) invoke
when the operator opts into the director pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["auto_direct", "DirectorResult", "compose_prompt"]


# ---------------------------------------------------------------------------
# Genre vocabulary
# ---------------------------------------------------------------------------

#: Map from preset / genre tag to a descriptive phrase used in the
#: composed prompt. Keys are matched case-insensitively; unknown genres
#: are forwarded verbatim with a neutral descriptor.
_GENRE_VOCAB: dict[str, str] = {
    "podcast-chill": (
        "Podcast-chill: warm, unhurried, two-host conversation. Pauses are "
        "welcome; breath is audible but not distracting."
    ),
    "interview-pro": (
        "Interview-pro: informative, measured interviewer/interviewee. "
        "Precise diction, no filler."
    ),
    "narration-duo": (
        "Narration-duo: firm, bright two-voice narration. Crisp "
        "articulation, steady cadence."
    ),
    "deep-warm": (
        "Deep-warm: low-register, intimate conversation. Slow pace, "
        "rounded vowels, generous pauses."
    ),
    "mono-warm": "Mono-warm: solo warm narrator, calm, welcoming.",
    "mono-informative": (
        "Mono-informative: solo narrator, clear and didactic; steady, "
        "authoritative pace."
    ),
}


def _genre_description(genre: str | None) -> str:
    """Return the descriptive phrase for a genre tag."""
    if not genre:
        return "General-purpose podcast narration."
    return _GENRE_VOCAB.get(genre.lower(), f"Genre tag: {genre}.")


# ---------------------------------------------------------------------------
# Prompt composition
# ---------------------------------------------------------------------------


def compose_prompt(
    *,
    script: str,
    genre: str | None,
    existing_notes: str | None = None,
    existing_notes_policy: str = "preserve",
) -> str:
    """Assemble the prompt passed to ``text.transform``.

    The prompt embeds:

    * A description of the genre (from the built-in vocabulary when
      available).
    * The existing-notes policy (``preserve`` keeps author-provided
      Director's Notes verbatim; ``replace`` instructs the model to
      generate fresh notes).
    * The raw script text.
    * A strict output format: ``## Director's Notes`` block followed by
      the enriched transcript, preserving every ``Speaker`` label.

    Parameters
    ----------
    script : str
        The raw script text (as produced by ``script_parser``).
    genre : str or None
        Preset / genre tag — e.g. ``"podcast-chill"``.
    existing_notes : str or None, optional
        Existing Director's Notes, when the script already carries
        them. Used only under the ``"preserve"`` policy.
    existing_notes_policy : {"preserve", "replace"}, optional
        How to treat pre-existing notes. Default: ``"preserve"``.

    Returns
    -------
    str
        The composed prompt, ready to ship to ``text.transform``.
    """
    lines: list[str] = [
        "You are the director of a short audio piece. Produce an "
        "enriched version of the script that preserves every speaker "
        "label and turn count, and emits explicit performance notes in "
        "a Director's Notes block.",
        "",
        f"Genre: {genre or 'unspecified'}",
        f"Vocabulary: {_genre_description(genre)}",
        "",
    ]
    if existing_notes and existing_notes_policy == "preserve":
        lines.extend(
            [
                "Existing Director's Notes (preserve verbatim at the top "
                "of your reply, then add turn-level cues):",
                existing_notes.strip(),
                "",
            ]
        )
    elif existing_notes_policy == "replace":
        lines.append(
            "Replace any existing Director's Notes with fresh ones that "
            "match the genre vocabulary."
        )
        lines.append("")
    lines.extend(
        [
            "Output format (strict):",
            "",
            "## Director's Notes",
            "<two-to-four sentences in the genre vocabulary>",
            "",
            "## Transcript",
            "<enriched script, same Speaker labels, same turn count>",
            "",
            "Script to enrich:",
            "---",
            script.rstrip(),
            "---",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


class _ClientLike(Protocol):
    """Structural protocol for the director's client dependency.

    Matches :class:`lib.mcp_client.GeminiTTSMCPClient.text_transform`;
    tests supply a minimal recording stub that implements the same
    signature. The director never reaches for any other MCP tool.
    """

    def text_transform(
        self,
        *,
        prompt: str,
        model: str,
        temperature: float = ...,
        max_output_tokens: int = ...,
    ) -> dict[str, Any]:  # pragma: no cover - structural only
        ...


@dataclass(frozen=True)
class DirectorResult:
    """Outcome of :func:`auto_direct`.

    Parameters
    ----------
    text : str
        The enriched script text produced by the model, after
        post-processing.
    input_tokens : int
        MCP-reported input tokens.
    output_tokens : int
        MCP-reported output tokens.
    model_id : str
        Model identifier echoed by the MCP (may be empty if the tool
        did not report one).
    """

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str = ""


def _post_process(raw_text: str) -> str:
    """Normalise whitespace / trailing newlines on the enriched script."""
    cleaned = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return cleaned + "\n"


def auto_direct(
    *,
    script: str,
    client: _ClientLike,
    model: str,
    genre: str | None,
    existing_notes: str | None = None,
    existing_notes_policy: str = "preserve",
    temperature: float = 0.2,
    max_output_tokens: int = 8192,
) -> DirectorResult:
    """Run a director pass through the MCP's ``text.transform`` tool.

    Prompt composition and all genre-specific logic happen in this
    function; the MCP receives only ``(prompt, model, temperature,
    max_output_tokens)``.

    Parameters
    ----------
    script : str
        Raw script text.
    client : GeminiTTSMCPClient-like
        Object exposing ``text_transform(**kwargs)`` returning a
        ``{"text": str, "input_tokens": int, "output_tokens": int, ...}``
        dict.
    model : str
        Gemini model ID to use for the text pass.
    genre : str or None
        Preset / genre tag.
    existing_notes : str or None, optional
        Existing Director's Notes (preserved verbatim under the default
        policy).
    existing_notes_policy : {"preserve", "replace"}, optional
        Policy toggle, default ``"preserve"``.
    temperature : float, optional
        Sampling temperature forwarded to ``text.transform``. Default:
        ``0.2``.
    max_output_tokens : int, optional
        Output-token budget forwarded to ``text.transform``. Default:
        ``8192``.

    Returns
    -------
    DirectorResult
        Enriched text plus token usage. The ``text`` field is post-
        processed (normalised newlines, trailing ``\\n``).
    """
    prompt = compose_prompt(
        script=script,
        genre=genre,
        existing_notes=existing_notes,
        existing_notes_policy=existing_notes_policy,
    )
    response = client.text_transform(
        prompt=prompt,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    raw_text = str(response.get("text", "") or "")
    text = _post_process(raw_text)
    return DirectorResult(
        text=text,
        input_tokens=int(response.get("input_tokens", 0) or 0),
        output_tokens=int(response.get("output_tokens", 0) or 0),
        model_id=str(response.get("model_id", "") or ""),
    )
