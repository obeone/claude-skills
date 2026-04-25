"""Parser for the tts-duet input format.

The format is intentionally minimal Markdown-ish:

* Optional ``## Director's Notes`` heading at the top. Content until the
  first ``Speaker N:`` (or EOF for mono files) is captured as
  Director's Notes.
* ``Speaker A:`` / ``Speaker B:`` or ``Speaker1:`` / ``Speaker2:``
  labels delimit turns (the two forms are interchangeable). Text
  following a label until the next label (or EOF) is the turn's spoken
  content.
* Inline directives such as ``[ton: warm]`` or ``[pace: slow]`` are
  left untouched in the turn text (the Gemini model handles them
  natively) but also aggregated in :attr:`ParsedScript.directives`.
* If no speaker labels are detected, the script is parsed in mono
  mode: every non-notes line is merged into a single ``Mono`` turn.

The ``to_model_content`` helper renders the normalized representation
that the SDK consumes as ``contents``. When
:data:`lib._config.USE_SYSTEM_INSTRUCTION_FOR_NOTES` is ``True`` the
notes are **not** included (they are supposed to travel through
``system_instruction`` instead); otherwise they are prepended and
guarded by :data:`lib._config.DIRECTOR_NOTES_SENTINEL`.

See ``references/script_format.md`` for the full specification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import _config

__all__ = ["ParsedScript", "Turn", "parse_script", "to_model_content"]

#: Canonical speaker labels used inside the parser and emitted by
#: :func:`to_model_content`. Input ``Speaker A:`` / ``Speaker B:``
#: labels are normalized to these.
_SPEAKER1 = "Speaker1"
_SPEAKER2 = "Speaker2"
_MONO = "Mono"

# Accept "Speaker A:", "speaker b:", "Speaker1:", "Speaker 2:" (optional
# whitespace between "Speaker" and the identifier).
_SPEAKER_LINE_RE = re.compile(
    r"^\s*[Ss]peaker\s*(?P<id>[ABab12])\s*:\s*(?P<text>.*)$"
)
_DIRECTIVE_RE = re.compile(r"\[(?P<key>[a-zA-Z_][\w\-]*)\s*:\s*(?P<value>[^\]]+)\]")
_DIRECTORS_NOTES_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s*Director'?s\s+Notes\s*$",
    re.IGNORECASE,
)
_TRANSCRIPT_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s*Transcript\s*$",
    re.IGNORECASE,
)


@dataclass
class Turn:
    """A single speaker turn.

    Parameters
    ----------
    speaker : str
        One of ``"Speaker1"``, ``"Speaker2"`` or ``"Mono"``. Input
        labels such as ``Speaker A`` are normalized here.
    text : str
        The spoken text, with inline directives preserved verbatim.
    """

    speaker: str
    text: str


@dataclass
class ParsedScript:
    """Structured representation of a parsed TTS script.

    Parameters
    ----------
    notes : str or None
        The Director's Notes block, if any. ``None`` when the source
        file has no ``## Director's Notes`` heading.
    mode : {"mono", "dual"}
        ``"dual"`` whenever at least one explicit ``Speaker`` label is
        found, ``"mono"`` otherwise.
    turns : list of Turn
        Ordered list of speaker turns.
    directives : dict of str to str
        Flat map of the last occurrence of each inline directive. The
        original turn text retains all occurrences — this dict is a
        convenience summary for callers that want to inspect the
        collected directives (e.g. for logging).
    """

    notes: str | None
    mode: Literal["mono", "dual"]
    turns: list[Turn]
    directives: dict[str, str] = field(default_factory=dict)


def _normalize_speaker(raw: str) -> str:
    """Normalize an input speaker identifier to ``Speaker1`` / ``Speaker2``.

    Parameters
    ----------
    raw : str
        Single character from the regex group (``A``, ``B``, ``1``, ``2``).

    Returns
    -------
    str
        ``"Speaker1"`` for ``A``/``a``/``1``; ``"Speaker2"`` for
        ``B``/``b``/``2``.
    """
    upper = raw.upper()
    if upper in ("A", "1"):
        return _SPEAKER1
    if upper in ("B", "2"):
        return _SPEAKER2
    raise ValueError(f"Unknown speaker identifier: {raw!r}")


def _collect_directives(text: str) -> dict[str, str]:
    """Return a ``key → value`` map of every inline directive in ``text``."""
    found: dict[str, str] = {}
    for match in _DIRECTIVE_RE.finditer(text):
        found[match.group("key").strip()] = match.group("value").strip()
    return found


def parse_script(path: Path | str) -> ParsedScript:
    """Parse a script file into a :class:`ParsedScript`.

    Parameters
    ----------
    path : Path or str
        Filesystem path to the script file (UTF-8 assumed).

    Returns
    -------
    ParsedScript
        Normalized representation. See the class docstring for details.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the file is empty or contains only whitespace.

    Examples
    --------
    >>> from pathlib import Path
    >>> import tempfile
    >>> with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
    ...     _ = fh.write("## Director's Notes\\nWarm tone.\\n\\nSpeaker A: hi.\\nSpeaker B: hello.\\n")
    ...     tmp = fh.name
    >>> script = parse_script(tmp)
    >>> script.mode
    'dual'
    >>> [t.speaker for t in script.turns]
    ['Speaker1', 'Speaker2']
    """
    file_path = Path(path)
    raw = file_path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError(f"Script file is empty: {file_path}")

    lines = raw.splitlines()

    notes_lines: list[str] = []
    body_lines: list[str] = []
    in_notes = False
    notes_seen = False

    # Walk the file once, splitting pre-speaker content into Director's
    # Notes (if a heading was seen) vs. "other preamble" that gets
    # discarded in dual mode / merged into the mono turn otherwise.
    first_speaker_idx: int | None = None
    for idx, line in enumerate(lines):
        if _SPEAKER_LINE_RE.match(line):
            first_speaker_idx = idx
            break

    if first_speaker_idx is None:
        # Mono mode: the whole file is (optional notes) + mono transcript.
        preamble = lines
        body_lines = []
    else:
        preamble = lines[:first_speaker_idx]
        body_lines = lines[first_speaker_idx:]

    for line in preamble:
        if _DIRECTORS_NOTES_HEADING_RE.match(line):
            in_notes = True
            notes_seen = True
            continue
        if _TRANSCRIPT_HEADING_RE.match(line):
            in_notes = False
            continue
        if in_notes:
            notes_lines.append(line)

    notes_text: str | None = None
    if notes_seen:
        notes_text = "\n".join(notes_lines).strip() or None

    turns: list[Turn] = []
    directives: dict[str, str] = {}

    if first_speaker_idx is None:
        # Mono mode: use everything that isn't a notes/transcript heading
        # and isn't inside the notes block as the single mono turn.
        mono_parts: list[str] = []
        in_notes = False
        for line in lines:
            if _DIRECTORS_NOTES_HEADING_RE.match(line):
                in_notes = True
                continue
            if _TRANSCRIPT_HEADING_RE.match(line):
                in_notes = False
                continue
            if in_notes:
                continue
            mono_parts.append(line)
        mono_text = "\n".join(mono_parts).strip()
        if mono_text:
            turns.append(Turn(speaker=_MONO, text=mono_text))
            directives.update(_collect_directives(mono_text))
        mode: Literal["mono", "dual"] = "mono"
    else:
        current_speaker: str | None = None
        current_buffer: list[str] = []

        def _flush() -> None:
            """Commit the current buffer as a :class:`Turn`."""
            if current_speaker is None:
                return
            text = "\n".join(current_buffer).strip()
            if not text:
                return
            turns.append(Turn(speaker=current_speaker, text=text))
            directives.update(_collect_directives(text))

        for line in body_lines:
            match = _SPEAKER_LINE_RE.match(line)
            if match:
                _flush()
                current_speaker = _normalize_speaker(match.group("id"))
                initial = match.group("text").rstrip()
                current_buffer = [initial] if initial else []
            else:
                if current_speaker is not None:
                    current_buffer.append(line)
        _flush()
        mode = "dual"

    return ParsedScript(
        notes=notes_text,
        mode=mode,
        turns=turns,
        directives=directives,
    )


def to_model_content(script: ParsedScript) -> str:
    """Render the ``contents`` string passed to the Gemini SDK.

    In dual mode, turns are emitted as ``Speaker1: …`` /
    ``Speaker2: …`` to match the labels the SDK expects in
    ``multi_speaker_voice_config``. In mono mode the text is emitted
    verbatim.

    Director's Notes handling depends on
    :data:`lib._config.USE_SYSTEM_INSTRUCTION_FOR_NOTES`:

    * ``True``  — notes are omitted (the caller passes them via
      ``system_instruction``).
    * ``False`` — notes are prepended, preceded by
      :data:`lib._config.DIRECTOR_NOTES_SENTINEL` on its own line.

    Parameters
    ----------
    script : ParsedScript
        Parsed script produced by :func:`parse_script`.

    Returns
    -------
    str
        The normalized content string.

    Examples
    --------
    >>> s = ParsedScript(notes=None, mode="dual", turns=[
    ...     Turn("Speaker1", "Hi."), Turn("Speaker2", "Hello.")
    ... ])
    >>> to_model_content(s)
    'Speaker1: Hi.\\nSpeaker2: Hello.'
    """
    if script.mode == "mono":
        body_lines = [turn.text for turn in script.turns]
    else:
        body_lines = [f"{turn.speaker}: {turn.text}" for turn in script.turns]
    body = "\n".join(body_lines).strip()

    if script.notes and not _config.USE_SYSTEM_INSTRUCTION_FOR_NOTES:
        return f"{_config.DIRECTOR_NOTES_SENTINEL}\n{script.notes}\n\n{body}"
    return body
