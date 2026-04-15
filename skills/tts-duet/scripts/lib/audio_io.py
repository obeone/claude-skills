"""Audio I/O helpers for the tts-duet skill.

The Gemini TTS preview models return **raw PCM** (little-endian signed
16-bit, 24 kHz, mono) rather than a WAV file; this module handles the
PCM→WAV framing, lossless WAV concatenation for chunked jobs, and the
optional MP3 transcode via ``ffmpeg``. It also exposes verbatim warning
and error strings that are asserted as literals in the test suite
(§5.1): keep them byte-identical when editing.
"""

from __future__ import annotations

import shutil
import subprocess
import wave
from functools import cache
from pathlib import Path

__all__ = [
    "FFMPEG_MISSING_WARNING",
    "FFMPEG_REQUIRED_ERROR",
    "has_ffmpeg",
    "pcm_to_wav",
    "concat_wavs",
    "wav_to_mp3",
    "wav_duration_seconds",
]

#: Warning emitted when ``--format mp3`` is requested but ``ffmpeg`` is
#: absent and ``--require-format`` was not set. Asserted verbatim in
#: §5.1; change here requires updating the tests too.
FFMPEG_MISSING_WARNING: str = "ffmpeg not found, falling back to WAV"

#: Fatal error emitted when ``--format mp3 --require-format`` is set but
#: ``ffmpeg`` is missing. Asserted verbatim in §5.1.
FFMPEG_REQUIRED_ERROR: str = (
    "ffmpeg required for MP3 output but not found; "
    "install ffmpeg or drop --require-format"
)


@cache
def has_ffmpeg() -> bool:
    """Return whether an ``ffmpeg`` binary is discoverable on ``$PATH``.

    The result is cached for the lifetime of the process: ``ffmpeg``
    availability does not change mid-run, and the lookup is called
    repeatedly (one per job, plus tests).

    Returns
    -------
    bool
        ``True`` if ``shutil.which("ffmpeg")`` resolves, else ``False``.
    """
    return shutil.which("ffmpeg") is not None


def pcm_to_wav(
    pcm: bytes,
    out_path: Path,
    *,
    framerate: int = 24000,
    sampwidth: int = 2,
    channels: int = 1,
) -> None:
    """Write a raw PCM buffer to a proper WAV container.

    Parameters
    ----------
    pcm : bytes
        Raw PCM bytes as returned by the Gemini SDK.
    out_path : Path
        Destination path. Parent directories are created if needed.
    framerate : int, optional
        Sample rate in Hz. Defaults to ``24000`` (Gemini TTS).
    sampwidth : int, optional
        Sample width in bytes. Defaults to ``2`` (16-bit signed).
    channels : int, optional
        Channel count. Defaults to ``1`` (mono).

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If ``pcm`` is empty or its length is not a multiple of
        ``sampwidth * channels``.
    """
    if not pcm:
        raise ValueError("pcm_to_wav: refusing to write empty PCM buffer")
    frame_size = sampwidth * channels
    if len(pcm) % frame_size != 0:
        raise ValueError(
            f"pcm_to_wav: PCM length {len(pcm)} is not a multiple of "
            f"frame size {frame_size} (sampwidth={sampwidth}, "
            f"channels={channels})"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sampwidth)
        wav.setframerate(framerate)
        wav.writeframes(pcm)


def concat_wavs(inputs: list[Path], out_path: Path) -> None:
    """Concatenate WAV files via raw frame copy (lossless).

    All inputs must share the same channel count, sample width and
    frame rate; otherwise a :class:`ValueError` is raised with a full
    parameter report for every input. The output inherits the
    parameters of ``inputs[0]``.

    Parameters
    ----------
    inputs : list of Path
        Non-empty list of source WAV paths, in order.
    out_path : Path
        Destination path. Parent directories are created if needed.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If ``inputs`` is empty or the files' parameters do not match.
    """
    if not inputs:
        raise ValueError("concat_wavs: no input files provided")

    params: list[tuple[Path, int, int, int, int]] = []
    for entry in inputs:
        with wave.open(str(entry), "rb") as reader:
            params.append(
                (
                    entry,
                    reader.getnchannels(),
                    reader.getsampwidth(),
                    reader.getframerate(),
                    reader.getnframes(),
                )
            )

    base = params[0][1:4]
    mismatches = [row for row in params if row[1:4] != base]
    if mismatches:
        report = "\n".join(
            f"  - {path}: channels={ch}, sampwidth={sw}, "
            f"framerate={fr}, nframes={nf}"
            for path, ch, sw, fr, nf in params
        )
        raise ValueError(
            "concat_wavs: input parameters do not match\n" + report
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as writer:
        writer.setnchannels(base[0])
        writer.setsampwidth(base[1])
        writer.setframerate(base[2])
        for entry in inputs:
            with wave.open(str(entry), "rb") as reader:
                writer.writeframes(reader.readframes(reader.getnframes()))


def wav_to_mp3(
    wav_path: Path,
    mp3_path: Path,
    *,
    keep_wav: bool = False,
) -> None:
    """Transcode a WAV file to MP3 via ``ffmpeg``.

    Uses ``libmp3lame`` with ``-qscale:a 2`` (VBR ~190 kbps, a good
    default for spoken audio). The source WAV is removed on success
    unless ``keep_wav`` is ``True``.

    Parameters
    ----------
    wav_path : Path
        Source WAV file.
    mp3_path : Path
        Destination MP3 file. Parent directories are created if needed.
    keep_wav : bool, optional
        If ``True``, keep ``wav_path`` after successful transcoding.

    Returns
    -------
    None

    Raises
    ------
    FileNotFoundError
        If ``ffmpeg`` is not available on ``$PATH``.
    RuntimeError
        If ``ffmpeg`` exits with a non-zero status.
    """
    if not has_ffmpeg():
        raise FileNotFoundError(FFMPEG_REQUIRED_ERROR)

    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(wav_path),
        "-codec:a",
        "libmp3lame",
        "-qscale:a",
        "2",
        str(mp3_path),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed ({proc.returncode}): "
            f"{proc.stderr.decode('utf-8', errors='replace')}"
        )

    if not keep_wav:
        try:
            wav_path.unlink()
        except FileNotFoundError:
            pass


def wav_duration_seconds(wav_path: Path) -> float:
    """Return the duration, in seconds, of a WAV file.

    Parameters
    ----------
    wav_path : Path
        Path to a well-formed WAV file.

    Returns
    -------
    float
        Duration in seconds. ``0.0`` if the file contains no frames.
    """
    with wave.open(str(wav_path), "rb") as reader:
        framerate = reader.getframerate()
        nframes = reader.getnframes()
    if framerate <= 0:
        return 0.0
    return nframes / float(framerate)
