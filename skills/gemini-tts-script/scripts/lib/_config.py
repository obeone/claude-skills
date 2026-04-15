"""Compile-time feature flags for the gemini-tts-script skill.

This module holds the small set of boolean/string constants that drive
behaviour selection across the other helpers in :mod:`lib`. The most
important flag, :data:`USE_SYSTEM_INSTRUCTION_FOR_NOTES`, is the codified
outcome of the P0 spike shipped at
``scripts/lib/_spike_system_instruction.py``: when the spike PASSES (i.e.
``system_instruction`` + ``response_modalities=["AUDIO"]`` work together
without the model speaking the instruction aloud), this flag is ``True``
and Director's Notes are passed through the SDK's ``system_instruction``
field. When the spike FAILS, the flag must be flipped to ``False`` so the
fallback path kicks in: Director's Notes are inlined at the start of the
``contents`` string, guarded by the
:data:`DIRECTOR_NOTES_SENTINEL` marker, and duplicated per chunk.

The constant is intentionally hard-coded (not env-driven) so the shipped
skill has a single, auditable default. Flip it in a follow-up commit if
the spike outcome changes after an SDK bump.
"""

from __future__ import annotations

#: Whether to use the SDK's ``system_instruction`` field for Director's Notes.
#:
#: ``True``  — spike passed: notes go to ``system_instruction`` (clean path).
#: ``False`` — spike failed: notes are inlined with the sentinel below and
#: duplicated on every chunk when chunking is triggered.
USE_SYSTEM_INSTRUCTION_FOR_NOTES: bool = False

#: Sentinel prepended to inline Director's Notes in the fallback path.
#:
#: Chosen to be unambiguous for the model (clearly bracketed, reads as a
#: machine directive) and easy to strip from transcripts during the STT
#: leakage test (§5.3).
DIRECTOR_NOTES_SENTINEL: str = "[director-notes-do-not-speak]"
