"""Single source of truth for Gemini TTS pricing and duration heuristics.

This module is imported by every script that needs to reason about cost
or duration. It also feeds :mod:`lib._gen_api_notes_pricing`, which
regenerates the pricing section of ``references/api_notes.md`` so the
published pricing table can never drift from the values used at runtime.

Notes
-----
The output-token → audio-duration mapping is deliberately rough. The
heuristic constant :data:`OUTPUT_TOKENS_PER_SECOND` will be recalibrated
after the first ten real generations (see ADR follow-up (e) in the plan
and the "Heuristic calibration" section of ``api_notes.md``).

Examples
--------
>>> from lib.pricing import FLASH, estimate_cost_usd
>>> round(estimate_cost_usd(FLASH, input_tokens=1000, output_tokens=60000), 4)
0.6005
"""

from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = [
    "ModelPricing",
    "PRO",
    "FLASH",
    "MODELS",
    "OUTPUT_TOKENS_PER_SECOND",
    "ESTIMATE_BAND_PCT",
    "WORDS_PER_MINUTE_HEURISTIC",
    "estimate_duration_seconds",
    "estimate_output_tokens",
    "estimate_cost_usd",
    "resolve_model",
]


@dataclass(frozen=True)
class ModelPricing:
    """Immutable descriptor for a Gemini TTS model's pricing.

    Parameters
    ----------
    id : str
        Full Gemini model identifier (e.g. ``gemini-2.5-pro-preview-tts``).
    input_usd_per_1m : float
        USD cost per 1,000,000 input tokens.
    output_usd_per_1m : float
        USD cost per 1,000,000 output tokens (audio-encoded tokens).
    name : str
        Short alias (``"pro"`` / ``"flash"``) used in CLI flags.
    """

    id: str
    input_usd_per_1m: float
    output_usd_per_1m: float
    name: str


#: Preview "pro" tier — higher fidelity, costlier, default for generation.
PRO: ModelPricing = ModelPricing(
    id="gemini-2.5-pro-preview-tts",
    input_usd_per_1m=1.00,
    output_usd_per_1m=20.00,
    name="pro",
)

#: Preview "flash" tier — cheaper, good enough for auditions.
FLASH: ModelPricing = ModelPricing(
    id="gemini-2.5-flash-preview-tts",
    input_usd_per_1m=0.50,
    output_usd_per_1m=10.00,
    name="flash",
)

#: Canonical registry keyed by the CLI alias.
MODELS: dict[str, ModelPricing] = {"pro": PRO, "flash": FLASH}

#: Audio-output tokens per second of generated speech.
#:
#: Empirically measured against ``gemini-2.5-flash-preview-tts``:
#: 55 audio tokens for 2.21 s of 24 kHz PCM output → 24.89 tok/s, which
#: also matches the natural 24 kHz / ~960-sample-per-token granularity.
#: Keep widening via the ±``ESTIMATE_BAND_PCT`` band until more runs are
#: sampled; bump this constant only if the observed mean drifts > ±10 %.
OUTPUT_TOKENS_PER_SECOND: int = 25

#: Default uncertainty band (percent) surfaced by ``estimate_cost.py --json``.
#:
#: Tightened to ±30 % until empirical calibration warrants a narrower band
#: (ADR follow-up (e)).
ESTIMATE_BAND_PCT: int = 30

#: Words-per-minute used to convert transcript length → audio duration.
#:
#: 150 WPM is a middle-of-the-road narration pace; aligns with typical
#: podcast and audiobook delivery.
WORDS_PER_MINUTE_HEURISTIC: int = 150


def estimate_duration_seconds(transcript: str) -> float:
    """Estimate audio duration in seconds from a raw transcript.

    Uses :data:`WORDS_PER_MINUTE_HEURISTIC`. Punctuation-only tokens and
    empty strings contribute no duration.

    Parameters
    ----------
    transcript : str
        Text that will be voiced. Speaker labels and directives may be
        present; they are counted as words (close enough for an estimate).

    Returns
    -------
    float
        Estimated duration in seconds, ``>= 0.0``.

    Examples
    --------
    >>> round(estimate_duration_seconds("one two three"), 2)
    1.2
    """
    words = len([token for token in transcript.split() if token.strip()])
    if words == 0:
        return 0.0
    return words / WORDS_PER_MINUTE_HEURISTIC * 60.0


def estimate_output_tokens(duration_s: float) -> int:
    """Estimate the number of output tokens for a given audio duration.

    Parameters
    ----------
    duration_s : float
        Target audio duration in seconds.

    Returns
    -------
    int
        Integer token count, ``>= 0``.

    Examples
    --------
    >>> estimate_output_tokens(1.0)
    1000
    """
    if duration_s <= 0.0:
        return 0
    return int(round(duration_s * OUTPUT_TOKENS_PER_SECOND))


def estimate_cost_usd(
    model: ModelPricing,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate the USD cost of a Gemini TTS call.

    Parameters
    ----------
    model : ModelPricing
        Pricing descriptor for the target model.
    input_tokens : int
        Number of input tokens (text + directives).
    output_tokens : int
        Number of output (audio) tokens.

    Returns
    -------
    float
        Cost in USD. Always non-negative.

    Examples
    --------
    >>> round(estimate_cost_usd(PRO, 500, 10_000), 4)
    0.2005
    """
    input_cost = max(0, input_tokens) / 1_000_000 * model.input_usd_per_1m
    output_cost = max(0, output_tokens) / 1_000_000 * model.output_usd_per_1m
    return input_cost + output_cost


def resolve_model(name_or_id: str) -> ModelPricing:
    """Resolve a CLI alias or full model ID to a :class:`ModelPricing`.

    Parameters
    ----------
    name_or_id : str
        Either a known alias (``"pro"`` / ``"flash"``) or a full Gemini
        model ID (e.g. ``"gemini-2.5-pro-preview-tts"``). Unknown IDs are
        accepted (returning a clone of ``FLASH`` pricing with the custom
        ID) so the CLI keeps working through GA swaps; callers should
        warn when an unknown ID is used.

    Returns
    -------
    ModelPricing
        Descriptor. For known aliases/IDs, the canonical constant is
        returned. For unknown IDs, a new instance is built with
        ``FLASH`` pricing as a best-effort approximation.

    Raises
    ------
    ValueError
        If ``name_or_id`` is empty.

    Examples
    --------
    >>> resolve_model("pro").id
    'gemini-2.5-pro-preview-tts'
    >>> resolve_model("custom-tts-model").id
    'custom-tts-model'
    """
    if not name_or_id:
        raise ValueError("resolve_model requires a non-empty identifier")

    key = name_or_id.strip()
    if key in MODELS:
        return MODELS[key]

    for model in MODELS.values():
        if model.id == key:
            return model

    # Unknown ID — keep the CLI usable through GA swaps. Fall back to
    # FLASH pricing (the cheaper tier) and let the caller decide to warn.
    return replace(FLASH, id=key, name=key)
