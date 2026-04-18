"""Director LLM pre-TTS pass for the tts-duet skill.

Enriches a raw script with a 3-part Director's Notes block and action-oriented
inline ``[tag]`` directives before the script is sent to Gemini TTS, improving
the naturalness and expressiveness of the generated audio.

Examples
--------
>>> enriched = auto_direct(raw_script, model="flash", genre="pedagogical")
>>> has_director_notes(enriched)
True
"""

from __future__ import annotations

import os
import re
from typing import Literal

__all__ = [
    "auto_direct",
    "has_director_notes",
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an audio director for Gemini TTS multi-speaker output. Your job is to
enrich a script so that the Gemini TTS model produces natural, expressive audio
with good pacing and tonal variety.

INPUT
-----
You receive a transcript with Speaker A / Speaker B (or Speaker1 / Speaker2)
turns. The speakers may already have some inline [tag] directives, or none at all.

OUTPUT
------
Return the COMPLETE enriched script as plain text (Markdown-compatible).
- No preamble, no explanation, no code fences — just the enriched script itself.
- The very first line must be "## Director's Notes" (a level-2 Markdown heading).

REQUIRED STRUCTURE
------------------
1. A "## Director's Notes" block at the top with exactly three subsections:

   ### Profile
   Who the speakers are: their roles, relationship, expertise level, personality.
   Be concrete: "Speaker A is a senior backend engineer, patient and methodical.
   Speaker B is a junior dev, eager and slightly nervous."

   ### Scene
   Where and when the conversation happens, and the atmosphere.
   Example: "Casual team standup in a co-working space, late morning, relaxed."

   ### Direction
   The performance contract: pacing, dominant tone, anti-patterns to avoid.
   Be actionable: "Measured pace. Natural pauses after key terms. Warm, never
   condescending. Avoid lecture monotone. Speaker B asks genuine questions."

2. The original transcript, VERBATIM after the Director's Notes block.
   - Every speaker label (Speaker A:, Speaker B:, Speaker1:, Speaker2:) MUST
     be preserved exactly as-is, including capitalization.
   - Every word of every turn MUST be preserved verbatim. Do NOT paraphrase,
     summarize, or reorder.
   - You may INSERT inline [tag] directives at the START of speaker turns
     (before the spoken text) where a tonal shift is warranted. Place them
     sparingly — NOT on every turn. Only add a tag when there is a clear
     tonal or emotional reason for it.

INLINE [TAG] RULES
------------------
- Always wrap in square brackets: [warm], [thoughtful], [pause], [curious].
- Use action-oriented adjectives or actions: [warm], [thoughtful], [curious],
  [enthusiastic], [serious], [measured], [gently], [pause], [sigh], [laugh].
- NEVER use "ton:" or "pace:" prefixes — use plain: [warm] not [ton: warm].
- One tag per speaker turn at most. Never adjacent tags.
- Place the tag on the same line as the speaker label, right before the text:
  Speaker A: [warm] Bonjour, on va parler de DNS.
- If the turn already starts with a [tag], leave it as-is or update it if the
  existing one conflicts with the direction. Do not add a second tag.

SAFETY CONSTRAINTS
------------------
- Do NOT remove, reorder, or alter any spoken word in any turn.
- Do NOT change speaker labels or swap A/B assignments.
- Do NOT summarize or abbreviate the transcript in any way.
- The enriched script must contain ALL turns from the original, in the same order.
"""

# ---------------------------------------------------------------------------
# Director's Notes detection
# ---------------------------------------------------------------------------

_DIRECTOR_NOTES_RE = re.compile(
    r"^\s*#{2,3}\s*Director'?s?\s+Notes\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def has_director_notes(script_text: str) -> bool:
    """Return True if the script contains a Director's Notes heading.

    Matches any level-2 or level-3 heading of the form ``## Director's Notes``
    or ``## Directors Notes`` (apostrophe optional), case-insensitive.

    Examples
    --------
    >>> has_director_notes("## Director's Notes\\nWarm tone.")
    True
    >>> has_director_notes("Speaker A: Hi.")
    False
    """
    return bool(_DIRECTOR_NOTES_RE.search(script_text))


# ---------------------------------------------------------------------------
# Speaker-turn counting helper
# ---------------------------------------------------------------------------

_SPEAKER_TURN_RE = re.compile(
    r"^\s*[Ss]peaker\s*[ABab12]\s*:",
    re.MULTILINE,
)


def _count_turns(script_text: str) -> int:
    """Return the number of speaker-turn lines in *script_text*."""
    return len(_SPEAKER_TURN_RE.findall(script_text))


# ---------------------------------------------------------------------------
# Code-fence stripping
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)\n?```\s*$", re.DOTALL)


def _strip_code_fences(text: str) -> str:
    """Remove surrounding Markdown code fences if present."""
    stripped = text.strip()
    m = _CODE_FENCE_RE.match(stripped)
    if m:
        return m.group(1).strip()
    return stripped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_MODEL_MAP: dict[str, str] = {
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
}


def auto_direct(
    script_text: str,
    *,
    model: Literal["flash", "pro"] = "flash",
    genre: str | None = "pedagogical",
    api_key: str | None = None,
) -> str:
    """Enrich a raw TTS script with Director's Notes and inline [tag] directives.

    Sends the script to a Gemini text model (no audio modality) and returns
    the enriched version. The returned text contains:

    - A ``## Director's Notes`` block at the top with Profile / Scene /
      Direction subsections.
    - Action-oriented ``[tag]`` directives inserted sparingly at speaker-turn
      boundaries.
    - The original transcript preserved verbatim in every other respect.

    Parameters
    ----------
    script_text : str
        The raw script text to enrich.
    model : {"flash", "pro"}
        Model tier. ``"flash"`` maps to ``gemini-2.5-flash``;
        ``"pro"`` maps to ``gemini-2.5-pro`` (text-only models, not the
        ``-preview-tts`` audio variants).
    genre : str or None
        Genre hint appended to the prompt (e.g. ``"pedagogical"``,
        ``"interview"``, ``"narrative"``). ``None`` omits the hint.
    api_key : str or None
        Gemini API key. Falls back to ``GEMINI_API_KEY`` then
        ``GOOGLE_API_KEY`` environment variables.

    Returns
    -------
    str
        Enriched script text, ready to be saved and re-parsed.

    Raises
    ------
    RuntimeError
        If the response is empty, missing transcript markers, or if the LLM
        dropped speaker turns from the original script.
    SystemExit
        If the ``google-genai`` package is not installed.

    Examples
    --------
    >>> enriched = auto_direct("Speaker A: Hi.\\nSpeaker B: Hello.")
    >>> has_director_notes(enriched)
    True
    """
    # Resolve API key.
    resolved_key = (
        api_key
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if not resolved_key:
        raise RuntimeError(
            "No API key available. Set GEMINI_API_KEY or pass api_key= explicitly."
        )

    # google-genai is optional: fail loudly only when actually invoked.
    try:
        from google import genai  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "ERROR: google-genai is not installed. "
            "Install with: uv pip install 'google-genai>=1.0'"
        ) from exc

    # Use standard text models, not the -tts audio variants.
    model_id = _MODEL_MAP.get(model, _MODEL_MAP["flash"])

    genre_hint = (
        f"\nGENRE HINT: {genre}\n"
        "Use this to inform the Scene and Direction subsections, and to calibrate\n"
        "pacing and tonal vocabulary.\n"
        if genre
        else ""
    )
    user_prompt = (
        f"{_SYSTEM_PROMPT}\n"
        f"{genre_hint}\n"
        "---\n"
        "INPUT SCRIPT (enrich this):\n\n"
        f"{script_text.strip()}\n"
    )

    client = genai.Client(api_key=resolved_key)
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=user_prompt,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Director LLM call failed: {exc}") from exc

    raw_response = getattr(response, "text", None) or ""
    if not raw_response.strip():
        raise RuntimeError(
            "Director returned an empty response. "
            "Use --no-auto-direct to bypass."
        )

    enriched = _strip_code_fences(raw_response)

    original_turn_count = _count_turns(script_text)
    enriched_turn_count = _count_turns(enriched)
    if original_turn_count > 0 and enriched_turn_count < original_turn_count:
        raise RuntimeError(
            f"Director dropped content: original had {original_turn_count} speaker "
            f"turns, enriched has {enriched_turn_count}. "
            "Use --no-auto-direct to bypass."
        )

    if not has_director_notes(enriched):
        raise RuntimeError(
            "Director response is missing the '## Director's Notes' section. "
            "Use --no-auto-direct to bypass."
        )

    return enriched
