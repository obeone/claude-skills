#!/usr/bin/env python3
"""Generate TTS audio from a script file using Gemini TTS.

Primary CLI for the ``tts-duet`` skill. See
``SKILL.md`` §7 for the full exit-code table and §3.3 of the plan for
the behavioural contract.

Exit codes
----------
0  success.
1  bad input / required dependency missing while ``--require-format``
   was set.
2  estimated cost exceeds ``--approved-cost-usd`` (cost-drift abort).
3  per-chunk generation failure (partial WAVs preserved).
4  WAV concatenation failure (e.g. inconsistent sample parameters).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import _config, audio_io, notify as notify_mod  # noqa: E402
from lib.pricing import (  # noqa: E402
    ESTIMATE_BAND_PCT,
    estimate_cost_usd,
    estimate_duration_seconds,
    estimate_output_tokens,
    resolve_model,
)
from lib.script_parser import (  # noqa: E402
    ParsedScript,
    Turn,
    parse_script,
    to_model_content,
)

import yaml  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
PRESETS_PATH = SKILL_ROOT / "assets" / "voice_pairs.yaml"

LOG = logging.getLogger("generate_tts")


def _setup_logging(level: int = logging.INFO) -> None:
    """Enable coloredlogs if present, fall back to stdlib otherwise."""
    try:
        import coloredlogs  # type: ignore[import-not-found]

        coloredlogs.install(level=level, fmt="%(asctime)s %(levelname)s %(message)s")
    except ImportError:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(message)s",
        )


# ---------------------------------------------------------------------------
# Preset + CLI plumbing
# ---------------------------------------------------------------------------


def _load_presets() -> dict[str, Any]:
    """Return the presets dict from ``assets/voice_pairs.yaml``."""
    data = yaml.safe_load(PRESETS_PATH.read_text(encoding="utf-8")) or {}
    return data.get("presets", {})


def _resolve_voices(args: argparse.Namespace) -> tuple[str, str | None, bool]:
    """Return ``(voice_a, voice_b, experimental)`` from CLI flags.

    ``voice_b`` is ``None`` in mono mode. ``experimental`` is ``True``
    when the preset is flagged experimental.
    """
    if args.preset:
        presets = _load_presets()
        if args.preset not in presets:
            raise SystemExit(f"ERROR: unknown preset {args.preset!r}")
        preset = presets[args.preset]
        return (
            preset["speaker_a"],
            preset.get("speaker_b"),
            bool(preset.get("experimental", False)),
        )
    if args.mono:
        if not args.voice:
            raise SystemExit("ERROR: --mono requires --voice")
        return args.voice, None, False
    if args.voice1 and args.voice2:
        return args.voice1, args.voice2, False
    raise SystemExit(
        "ERROR: specify --preset NAME, --voice1 A --voice2 B, "
        "or --mono --voice NAME"
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse the argparse namespace."""
    parser = argparse.ArgumentParser(
        description="Generate TTS audio from a script file using Gemini TTS.",
    )
    parser.add_argument("--script", required=True, help="Path to the script file.")
    parser.add_argument(
        "--output",
        required=True,
        help="Output file stem (extension is added automatically).",
    )
    parser.add_argument("--preset", help="Named preset from voice_pairs.yaml.")
    parser.add_argument("--voice1", help="Speaker 1 voice name (dual mode).")
    parser.add_argument("--voice2", help="Speaker 2 voice name (dual mode).")
    parser.add_argument("--mono", action="store_true", help="Mono-voice mode.")
    parser.add_argument("--voice", help="Voice name for mono mode.")
    parser.add_argument(
        "--model",
        default="pro",
        help="Model alias (pro/flash) or full Gemini model ID.",
    )
    parser.add_argument(
        "--lang",
        default="auto",
        help=(
            "Advisory language hint (auto, fr, en, ...); passed to the "
            "model via system_instruction. Not a hard forcing."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("wav", "mp3", "both"),
        default="mp3",
        help="Output format. Default: mp3 if ffmpeg else wav + warning.",
    )
    parser.add_argument(
        "--require-format",
        action="store_true",
        help="Abort (exit 1) rather than degrade MP3→WAV.",
    )
    parser.add_argument(
        "--style",
        help="Extra styling hint appended to system_instruction (or notes).",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        help="Warn (only) if estimated duration exceeds this many seconds.",
    )
    parser.add_argument("--background", action="store_true", help="Run in background.")
    parser.add_argument(
        "--chunk-if-over-output-seconds",
        type=float,
        default=480.0,
        help="Primary chunking threshold (seconds of audio).",
    )
    parser.add_argument(
        "--max-input-tokens",
        type=int,
        default=30000,
        help="Secondary chunking threshold (input token count).",
    )
    parser.add_argument(
        "--job-dir",
        type=Path,
        help="Directory where background job state is recorded.",
    )
    parser.add_argument(
        "--approved-cost-usd",
        type=float,
        help="Hard cap on estimated cost; breach → exit 2.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Assume yes to any confirmations (audit trail).",
    )
    parser.add_argument(
        "--keep-wav",
        action="store_true",
        help="Keep intermediate WAV after MP3 transcoding.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Job-dir + status
# ---------------------------------------------------------------------------


def _make_job_dir(cli_dir: Path | None) -> tuple[str, Path]:
    """Create ``.tts-jobs/<id>/`` (or honour ``--job-dir``)."""
    job_id = uuid.uuid4().hex[:8]
    if cli_dir is None:
        base = Path.cwd() / ".tts-jobs" / job_id
    else:
        base = cli_dir
    base.mkdir(parents=True, exist_ok=True)
    return job_id, base


def _write_status(job_dir: Path, status: str, **extra: str) -> None:
    """Write a status file with optional extra key/value lines."""
    lines = [f"status={status}"]
    for key, value in extra.items():
        lines.append(f"{key}={value}")
    (job_dir / "status").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_turns(
    script: ParsedScript,
    over_seconds: float,
) -> list[list[Turn]]:
    """Split turns into chunks whose estimated duration stays under the bound.

    Split points are always on speaker-turn boundaries. The bound
    (``over_seconds``) is treated as a soft limit; if a single turn
    exceeds it we still emit it alone.
    """
    if not script.turns:
        return []
    chunks: list[list[Turn]] = []
    current: list[Turn] = []
    running_seconds = 0.0
    for turn in script.turns:
        turn_seconds = estimate_duration_seconds(turn.text)
        if current and running_seconds + turn_seconds > over_seconds:
            chunks.append(current)
            current = [turn]
            running_seconds = turn_seconds
        else:
            current.append(turn)
            running_seconds += turn_seconds
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# SDK helpers
# ---------------------------------------------------------------------------


def _import_genai() -> tuple[Any, Any]:
    """Import google-genai or raise SystemExit(1)."""
    try:
        from google import genai  # type: ignore[import-not-found]
        from google.genai import types  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "ERROR: google-genai is not installed. "
            "Install with: uv pip install -r scripts/requirements.txt"
        ) from exc
    return genai, types


def _build_speech_config(
    types_mod: Any,
    voice_a: str,
    voice_b: str | None,
) -> Any:
    """Build a ``SpeechConfig`` with one or two voices."""
    if voice_b is None:
        return types_mod.SpeechConfig(
            voice_config=types_mod.VoiceConfig(
                prebuilt_voice_config=types_mod.PrebuiltVoiceConfig(
                    voice_name=voice_a
                )
            )
        )
    return types_mod.SpeechConfig(
        multi_speaker_voice_config=types_mod.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                types_mod.SpeakerVoiceConfig(
                    speaker="Speaker1",
                    voice_config=types_mod.VoiceConfig(
                        prebuilt_voice_config=types_mod.PrebuiltVoiceConfig(
                            voice_name=voice_a
                        )
                    ),
                ),
                types_mod.SpeakerVoiceConfig(
                    speaker="Speaker2",
                    voice_config=types_mod.VoiceConfig(
                        prebuilt_voice_config=types_mod.PrebuiltVoiceConfig(
                            voice_name=voice_b
                        )
                    ),
                ),
            ]
        )
    )


def _build_config(
    types_mod: Any,
    voice_a: str,
    voice_b: str | None,
    *,
    notes: str | None,
    style: str | None,
    lang: str,
) -> Any:
    """Build a ``GenerateContentConfig`` respecting the spike outcome."""
    speech_config = _build_speech_config(types_mod, voice_a, voice_b)
    kwargs: dict[str, Any] = {
        "response_modalities": ["AUDIO"],
        "speech_config": speech_config,
    }
    if _config.USE_SYSTEM_INSTRUCTION_FOR_NOTES:
        pieces: list[str] = []
        if notes:
            pieces.append(notes.strip())
        if style:
            pieces.append(style.strip())
        if lang and lang != "auto":
            pieces.append(
                f"Language hint: {lang}. Adapt pronunciation accordingly; "
                f"do not read this line aloud."
            )
        if pieces:
            kwargs["system_instruction"] = "\n\n".join(pieces)
    return types_mod.GenerateContentConfig(**kwargs)


def _extract_pcm(response: Any) -> bytes:
    """Collect raw PCM bytes from a ``generate_content`` response."""
    pcm = b""
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                pcm += inline.data
    return pcm


# ---------------------------------------------------------------------------
# Background re-exec
# ---------------------------------------------------------------------------


def _reexec_in_background(
    argv: list[str],
    job_dir: Path,
    job_id: str,
) -> int:
    """Re-exec the current script without ``--background`` using ``nohup``."""
    new_argv = [sys.executable, str(Path(__file__).resolve())]
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if token == "--background":
            continue
        new_argv.append(token)
    # Ensure job-dir is explicit in the child invocation.
    if "--job-dir" not in new_argv:
        new_argv.extend(["--job-dir", str(job_dir)])

    log_path = job_dir / "job.log"
    nohup = shutil.which("nohup") or "nohup"
    with open(log_path, "ab") as log_fh:
        proc = subprocess.Popen(  # noqa: S603 — intentional background spawn
            [nohup, *new_argv],
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    (job_dir / "pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    print(f"Background job started: id={job_id} dir={job_dir}")
    print(f"Follow with: tail -f {log_path}")
    return 0


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def _maybe_cost_drift(
    estimated_cost: float,
    approved: float | None,
    job_dir: Path | None,
) -> None:
    """Exit 2 if the estimated cost exceeds the approved cap."""
    if approved is None or estimated_cost <= approved:
        return
    drift_pct = (estimated_cost / approved - 1.0) * 100.0
    print(f"cost_drift_pct={drift_pct:.2f}", file=sys.stderr)
    if job_dir is not None:
        _write_status(
            job_dir,
            "failed",
            failure_reason="cost_drift",
            cost_drift_pct=f"{drift_pct:.2f}",
        )
    raise SystemExit(2)


def _run_pipeline(args: argparse.Namespace) -> int:  # noqa: C901 — linear pipeline
    """Execute the full generation pipeline in the current process."""
    script = parse_script(args.script)
    voice_a, voice_b, experimental = _resolve_voices(args)
    if experimental and args.preset:
        print(
            f"WARN: preset '{args.preset}' is experimental; "
            f"audition with preview_voice.py first",
            file=sys.stderr,
        )
    if args.mono and script.mode == "dual":
        LOG.warning("Script has Speaker labels but --mono was requested; output will flatten labels.")
    if not args.mono and voice_b is None and script.mode == "dual":
        LOG.warning("Dual-speaker script but only one voice provided; output will be mono-ish.")

    model = resolve_model(args.model)
    content = to_model_content(script)
    transcript_for_duration = "\n".join(turn.text for turn in script.turns)
    duration_s = estimate_duration_seconds(transcript_for_duration)
    output_tokens = estimate_output_tokens(duration_s)
    input_tokens_heuristic = max(1, len(content) // 4)
    estimated_cost = estimate_cost_usd(model, input_tokens_heuristic, output_tokens)
    LOG.info(
        "Estimates: duration=%.1fs tokens_in~%d tokens_out~%d cost=$%.4f (±%d%%)",
        duration_s,
        input_tokens_heuristic,
        output_tokens,
        estimated_cost,
        ESTIMATE_BAND_PCT,
    )

    if args.max_duration is not None and duration_s > args.max_duration:
        print(
            f"WARN: estimated duration {duration_s:.1f}s exceeds "
            f"--max-duration {args.max_duration:.1f}s (continuing)",
            file=sys.stderr,
        )

    _maybe_cost_drift(estimated_cost, args.approved_cost_usd, args.job_dir)

    # Format fallback before we call the network.
    want_mp3 = args.format in ("mp3", "both")
    if want_mp3 and not audio_io.has_ffmpeg():
        if args.require_format:
            print(audio_io.FFMPEG_REQUIRED_ERROR, file=sys.stderr)
            if args.job_dir is not None:
                _write_status(args.job_dir, "failed", failure_reason="ffmpeg_missing")
            return 1
        print(audio_io.FFMPEG_MISSING_WARNING, file=sys.stderr)

    genai, types_mod = _import_genai()
    client = genai.Client()
    config_obj = _build_config(
        types_mod,
        voice_a,
        voice_b,
        notes=script.notes,
        style=args.style,
        lang=args.lang,
    )

    chunks = _chunk_turns(script, args.chunk_if_over_output_seconds)
    if len(chunks) <= 1:
        chunks_content = [content]
    else:
        LOG.info("Chunking triggered: %d chunks.", len(chunks))
        chunks_content = []
        for chunk_turns in chunks:
            chunk_script = ParsedScript(
                notes=script.notes,
                mode=script.mode,
                turns=chunk_turns,
                directives=script.directives,
            )
            chunks_content.append(to_model_content(chunk_script))

    if args.job_dir is not None:
        _write_status(args.job_dir, "running", chunks=str(len(chunks_content)))

    output_stem = Path(args.output)
    work_dir = output_stem.parent if str(output_stem.parent) else Path.cwd()
    work_dir.mkdir(parents=True, exist_ok=True)

    chunks_dir = (args.job_dir or work_dir) / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunk_wavs: list[Path] = []
    for idx, chunk_content in enumerate(chunks_content, start=1):
        chunk_path = chunks_dir / f"{output_stem.stem}.chunk{idx:03d}.wav"
        LOG.info("Generating chunk %d/%d (%d bytes)", idx, len(chunks_content), len(chunk_content))
        try:
            response = client.models.generate_content(
                model=model.id,
                contents=chunk_content,
                config=config_obj,
            )
        except Exception as exc:  # noqa: BLE001 — surface SDK churn cleanly
            LOG.error("Chunk %d generation failed: %s", idx, exc)
            if args.job_dir is not None:
                _write_status(args.job_dir, "failed", failure_reason="chunk_failed")
            return 3
        pcm = _extract_pcm(response)
        if not pcm:
            LOG.error("Chunk %d returned no audio.", idx)
            if args.job_dir is not None:
                _write_status(args.job_dir, "failed", failure_reason="chunk_failed")
            return 3
        audio_io.pcm_to_wav(pcm, chunk_path)
        chunk_wavs.append(chunk_path)

    final_wav = output_stem.with_suffix(".wav")
    try:
        if len(chunk_wavs) == 1:
            shutil.copyfile(chunk_wavs[0], final_wav)
        else:
            audio_io.concat_wavs(chunk_wavs, final_wav)
    except ValueError as exc:
        LOG.error("Concat failure: %s", exc)
        if args.job_dir is not None:
            _write_status(args.job_dir, "failed", failure_reason="concat_failed")
        return 4

    produced: list[Path] = [final_wav]
    if want_mp3 and audio_io.has_ffmpeg():
        mp3_path = output_stem.with_suffix(".mp3")
        try:
            audio_io.wav_to_mp3(final_wav, mp3_path, keep_wav=args.keep_wav or args.format == "both")
        except (FileNotFoundError, RuntimeError) as exc:
            if args.require_format:
                LOG.error("MP3 transcode failed: %s", exc)
                if args.job_dir is not None:
                    _write_status(args.job_dir, "failed", failure_reason="ffmpeg_missing")
                return 1
            LOG.warning("MP3 transcode failed (%s); keeping WAV.", exc)
        else:
            produced.append(mp3_path)
            if args.format != "both" and not args.keep_wav:
                produced = [mp3_path]

    final_path = produced[-1]
    LOG.info("Generation complete: %s", final_path)

    if args.job_dir is not None:
        _write_status(
            args.job_dir,
            "done",
            output=str(final_path),
            duration_seconds=f"{duration_s:.2f}",
            estimated_cost_usd=f"{estimated_cost:.4f}",
        )
        notify_mod.notify(
            title="Gemini TTS — done",
            message=f"Output: {final_path}",
            job_dir=args.job_dir,
        )
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. See module docstring."""
    args = _parse_args(argv)
    _setup_logging()

    if args.background:
        job_id, job_dir = _make_job_dir(args.job_dir)
        (job_dir / "script.md").write_text(
            Path(args.script).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        config_snapshot = {
            k: str(v) if isinstance(v, Path) else v
            for k, v in vars(args).items()
        }
        (job_dir / "config.json").write_text(
            json.dumps(config_snapshot, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _write_status(job_dir, "pending", job_id=job_id)
        raw_argv = sys.argv[1:] if argv is None else list(argv)
        return _reexec_in_background(raw_argv, job_dir, job_id)

    return _run_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
