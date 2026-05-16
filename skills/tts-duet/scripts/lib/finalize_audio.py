"""Offline audio finalisation helpers for the tts-duet skill.

This module centralises WAV concat + MP3 transcode so both the sync
lane (``finalize_audio.py`` CLI) and ``generate_tts.py`` use the same
code path. All ``subprocess`` spawns pass an explicit
``env=safe_env(for_mcp=False)`` to satisfy the AC-17 lint.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import audio_io  # noqa: E402
from lib._safe_env import safe_env  # noqa: E402

__all__ = [
    "wrap_pcm_to_wav",
    "concat_wavs",
    "wav_to_mp3",
    "ffprobe_exists",
]


def wrap_pcm_to_wav(
    pcm: bytes,
    out_path: Path,
    *,
    framerate: int = 24000,
    sampwidth: int = 2,
    channels: int = 1,
) -> Path:
    """Wrap raw PCM bytes in a WAV container (24 kHz / 16-bit / mono).

    Parameters
    ----------
    pcm : bytes
        Raw PCM bytes exactly as returned by ``tts.generate_chunk``.
    out_path : Path
        Destination WAV path.
    framerate, sampwidth, channels : int, optional
        Forwarded to :func:`lib.audio_io.pcm_to_wav`.

    Returns
    -------
    Path
        ``out_path`` unchanged (for pipeline chaining).
    """
    audio_io.pcm_to_wav(
        pcm,
        out_path,
        framerate=framerate,
        sampwidth=sampwidth,
        channels=channels,
    )
    return out_path


def concat_wavs(wavs: list[Path], out_path: Path) -> Path:
    """Concatenate WAV chunks via lossless frame copy.

    Parameters
    ----------
    wavs : list of Path
        Source chunks, in order.
    out_path : Path
        Destination WAV path.

    Returns
    -------
    Path
        ``out_path`` unchanged.
    """
    audio_io.concat_wavs(wavs, out_path)
    return out_path


def wav_to_mp3(wav: Path, mp3: Path, *, keep_wav: bool = False) -> Path | None:
    """Transcode a WAV to MP3 via ``ffmpeg``.

    Uses :func:`lib.audio_io.wav_to_mp3`, which already passes an
    explicit ``env=`` to ``subprocess.run``.

    Parameters
    ----------
    wav : Path
        Source WAV path.
    mp3 : Path
        Destination MP3 path.
    keep_wav : bool, optional
        Preserve the source WAV when ``True``. Default: ``False``.

    Returns
    -------
    Path or None
        The MP3 path on success. ``None`` if ``ffmpeg`` is absent.
    """
    if not audio_io.has_ffmpeg():
        return None
    audio_io.wav_to_mp3(wav, mp3, keep_wav=keep_wav)
    return mp3


def ffprobe_exists() -> bool:
    """Return whether ``ffprobe`` is discoverable on ``$PATH``.

    Uses an explicit ``env=safe_env(...)`` to avoid inheriting secrets
    when spawning the probe.

    Returns
    -------
    bool
        ``True`` when the probe succeeded.
    """
    try:
        proc = subprocess.run(
            ["ffprobe", "-version"],
            check=False,
            capture_output=True,
            env=safe_env(for_mcp=False),
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# CLI — concat + transcode for the sync lane
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Concatenate per-chunk WAVs and optionally transcode to MP3.",
    )
    parser.add_argument(
        "--chunks-dir",
        type=Path,
        required=True,
        help="Directory containing *.wav chunks in lexical order.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output file stem (extension is added automatically).",
    )
    parser.add_argument(
        "--format",
        choices=("wav", "mp3", "both"),
        default="mp3",
        help="Output format. Default: mp3.",
    )
    parser.add_argument(
        "--keep-wav",
        action="store_true",
        help="Keep intermediate WAV after MP3 transcoding.",
    )
    parser.add_argument(
        "--require-format",
        action="store_true",
        help="Exit 1 if the requested format cannot be produced.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``finalize_audio.py``."""
    args = _parse_args(argv)
    chunks_dir: Path = args.chunks_dir
    if not chunks_dir.is_dir():
        print(f"ERROR: chunks dir does not exist: {chunks_dir}", file=sys.stderr)
        return 1
    wavs = sorted(chunks_dir.glob("*.wav"))
    if not wavs:
        print(f"ERROR: no WAV chunks found in {chunks_dir}", file=sys.stderr)
        return 1

    stem: Path = args.output
    final_wav = stem.with_suffix(".wav")
    final_wav.parent.mkdir(parents=True, exist_ok=True)
    try:
        if len(wavs) == 1:
            # Still run through concat_wavs for validation side-effects.
            concat_wavs(wavs, final_wav)
        else:
            concat_wavs(wavs, final_wav)
    except ValueError as exc:
        print(f"ERROR: concat failed: {exc}", file=sys.stderr)
        return 4

    produced: list[Path] = [final_wav]
    want_mp3 = args.format in ("mp3", "both")
    if want_mp3:
        if not audio_io.has_ffmpeg():
            if args.require_format:
                print(audio_io.FFMPEG_REQUIRED_ERROR, file=sys.stderr)
                return 1
            print(audio_io.FFMPEG_MISSING_WARNING, file=sys.stderr)
        else:
            mp3_path = stem.with_suffix(".mp3")
            try:
                audio_io.wav_to_mp3(
                    final_wav,
                    mp3_path,
                    keep_wav=args.keep_wav or args.format == "both",
                )
            except (FileNotFoundError, RuntimeError) as exc:
                if args.require_format:
                    print(f"ERROR: MP3 transcode failed: {exc}", file=sys.stderr)
                    return 1
                print(f"WARN: MP3 transcode failed: {exc}", file=sys.stderr)
            else:
                produced.append(mp3_path)
                if args.format != "both" and not args.keep_wav:
                    produced = [mp3_path]

    print(f"Finalised: {produced[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
