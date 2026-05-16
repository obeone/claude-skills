"""Adaptation pre-pass — raw text to runnable Speaker-A/B / mono / interview script.

This module is the load-bearing boundary between skill-domain knowledge
(shape vocabulary, language directives, target-duration hints) and the
generic ``text_transform`` MCP tool. Like :mod:`lib.director`, the MCP
sees only the assembled prompt string and the standard
``(model, temperature, max_output_tokens)`` trio — no ``shape``,
``language`` or ``target_duration_s`` field crosses the contract
boundary.

The module exposes a single public entry point, :func:`auto_adapt`,
called by ``adapt_script.py`` when the user opts into the gemini
backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["auto_adapt", "AdaptationResult", "compose_prompt"]


# ---------------------------------------------------------------------------
# Shape vocabulary
# ---------------------------------------------------------------------------

#: Per-shape formatting rules embedded in the adaptation prompt. Keys
#: must match :data:`lib.config.VALID_SHAPES`.
_SHAPE_RULES: dict[str, str] = {
    "dialogue": (
        "Two-voice dialogue. Format every turn as either `Speaker A: ...` "
        "or `Speaker B: ...`, alternating naturally; keep turns short "
        "enough to feel like a real conversation (typically 1-3 "
        "sentences each). Never merge two consecutive turns onto one "
        "line."
    ),
    "mono": (
        "Single-voice monologue. Format every paragraph as `Mono: ...`. "
        "Keep paragraphs focused; one idea per paragraph."
    ),
    "interview": (
        "Interview format with a clear interviewer/interviewee dynamic. "
        "Format questions as `Speaker A: ...` (the interviewer) and "
        "answers as `Speaker B: ...` (the interviewee). Strictly "
        "alternate Q/A turns; no narrator interjections."
    ),
}

#: Approximate spoken words-per-minute used to translate a target
#: duration in seconds into a word-count hint inside the prompt.
_WORDS_PER_MINUTE: int = 150


def _shape_rule(shape: str) -> str:
    """Return the formatting rule for a shape tag."""
    return _SHAPE_RULES.get(shape.lower(), _SHAPE_RULES["dialogue"])


def _language_directive(language: str) -> str:
    """Return the language directive embedded in the prompt."""
    tag = (language or "auto").strip()
    if not tag or tag.lower() == "auto":
        return (
            "Language: match the language of the input verbatim. Do not "
            "translate."
        )
    return (
        f"Language: write the entire output in {tag}. Translate the "
        "input if necessary."
    )


def _target_word_count(target_duration_s: float) -> int:
    """Translate a target duration in seconds to a word-count hint."""
    if target_duration_s <= 0:
        return 0
    return max(1, int(round(target_duration_s * _WORDS_PER_MINUTE / 60.0)))


# ---------------------------------------------------------------------------
# Prompt composition
# ---------------------------------------------------------------------------


def compose_prompt(
    *,
    raw_input: str,
    shape: str,
    language: str,
    target_duration_s: float,
    style: str | None = None,
) -> str:
    """Assemble the adaptation prompt passed to ``text_transform``.

    The prompt embeds:

    * The chosen shape with its concrete formatting rule.
    * The target duration plus the implied word count (~150 wpm).
    * The language directive (``auto`` -> match the input; otherwise
      write in that language).
    * An optional style hint passed through verbatim.
    * The raw input verbatim, fenced by ``---`` markers.
    * A strict output format: just the adapted script, no preamble, no
      fences, ready to feed to ``generate_tts.py``.

    Parameters
    ----------
    raw_input : str
        The raw user text (article, transcript, paper, notes, ...).
    shape : {"dialogue", "mono", "interview"}
        Target script shape.
    language : str
        BCP-47 tag or ``"auto"``.
    target_duration_s : float
        Desired spoken duration in seconds. Drives the implicit
        word-count hint.
    style : str or None, optional
        Free-form style hint forwarded verbatim.

    Returns
    -------
    str
        The composed prompt, ready to ship to ``text_transform``.
    """
    word_count = _target_word_count(target_duration_s)
    duration_line = (
        f"Target duration: ~{int(round(target_duration_s))} seconds "
        f"(~{word_count} words at {_WORDS_PER_MINUTE} wpm)."
    )

    lines: list[str] = [
        "You are adapting raw input text into a script ready for "
        "text-to-speech generation. Produce ONLY the adapted script, "
        "with no preamble, no commentary, no Markdown fences.",
        "",
        f"Shape: {shape}",
        f"Formatting rule: {_shape_rule(shape)}",
        "",
        duration_line,
        _language_directive(language),
        "",
    ]
    if style and style.strip():
        lines.extend(
            [
                f"Style hint: {style.strip()}",
                "",
            ]
        )
    lines.extend(
        [
            "Output format (strict):",
            "- One turn per line, prefixed with the speaker label "
            "(`Speaker A:`, `Speaker B:`, or `Mono:`).",
            "- No section headings, no bullet lists, no Director's "
            "Notes, no fenced code blocks.",
            "- The output must be directly consumable by a downstream "
            "TTS pipeline.",
            "",
            "Raw input to adapt:",
            "---",
            raw_input.rstrip(),
            "---",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


class _ClientLike(Protocol):
    """Structural protocol for the adaptation's client dependency.

    Matches :meth:`lib.mcp_client.GeminiTTSMCPClient.text_transform`;
    tests supply a minimal recording stub that implements the same
    signature. Adaptation never reaches for any other MCP tool.
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
class AdaptationResult:
    """Outcome of :func:`auto_adapt`.

    Parameters
    ----------
    text : str
        The adapted script, post-processed (normalised newlines,
        trailing ``\\n``, surrounding fences stripped).
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
    """Normalise newlines, strip stray markdown fences and trailing space."""
    cleaned = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    # Defensive: occasionally the model wraps the output in ``` fences
    # despite the strict-output instruction. Strip a single outer pair.
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
        cleaned = cleaned.strip()
    return cleaned + "\n"


def auto_adapt(
    *,
    raw_input: str,
    client: _ClientLike,
    model: str,
    shape: str,
    language: str,
    target_duration_s: float,
    style: str | None = None,
    temperature: float = 0.3,
    max_output_tokens: int = 8192,
) -> AdaptationResult:
    """Run an adaptation pass through the MCP's ``text_transform`` tool.

    Prompt composition and all shape-/language-specific logic happen in
    this function; the MCP receives only ``(prompt, model,
    temperature, max_output_tokens)``.

    Parameters
    ----------
    raw_input : str
        The raw text to adapt.
    client : GeminiTTSMCPClient-like
        Object exposing ``text_transform(**kwargs)`` returning a
        ``{"text": str, "input_tokens": int, "output_tokens": int, ...}``
        dict.
    model : str
        Gemini model ID to use for the text pass.
    shape : {"dialogue", "mono", "interview"}
        Target script shape.
    language : str
        BCP-47 tag or ``"auto"``.
    target_duration_s : float
        Desired spoken duration in seconds.
    style : str or None, optional
        Free-form style hint.
    temperature : float, optional
        Sampling temperature forwarded to ``text_transform``. Default:
        ``0.3``.
    max_output_tokens : int, optional
        Output-token budget forwarded to ``text_transform``. Default:
        ``8192``.

    Returns
    -------
    AdaptationResult
        Adapted text plus token usage. The ``text`` field is post-
        processed.
    """
    prompt = compose_prompt(
        raw_input=raw_input,
        shape=shape,
        language=language,
        target_duration_s=target_duration_s,
        style=style,
    )
    response = client.text_transform(
        prompt=prompt,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    raw_text = str(response.get("text", "") or "")
    text = _post_process(raw_text)
    return AdaptationResult(
        text=text,
        input_tokens=int(response.get("input_tokens", 0) or 0),
        output_tokens=int(response.get("output_tokens", 0) or 0),
        model_id=str(response.get("model_id", "") or ""),
    )
