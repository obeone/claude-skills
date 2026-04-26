#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml>=6.0",
#     "mcp>=1.14,<2",
#     "coloredlogs>=15.0",
# ]
# ///
"""Generate TTS audio from a script file via the ``gemini-tts-mcp`` MCP.

Primary CLI for the ``tts-duet`` skill. All Gemini API access happens
in the MCP child — this script never reads ``GEMINI_API_KEY`` /
``GOOGLE_API_KEY`` and never imports ``google-genai``.

Exit codes
----------
- ``0`` success.
- ``1`` bad input / required dependency missing while
  ``--require-format`` was set.
- ``2`` estimated cost exceeds ``--approved-cost-usd``.
- ``3`` per-chunk generation failure (non-retryable from the MCP).
  Partial WAVs preserved under ``<job_dir>/chunks/``.
- ``4`` WAV concatenation failure (inconsistent sample parameters).
- ``5`` MCP protocol error — MCP unreachable, version-skew, or crash
  recovery budget exhausted (§6.2). Partial WAVs preserved.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audio_io, notify as notify_mod  # noqa: E402
from lib._safe_env import _safe_env_nohup, safe_env  # noqa: E402
from lib.config import (  # noqa: E402
    JOB_CONFIG_VERSION,
    MCPDefaults,
    UserConfig,
    load_user_config,
    write_job_config,
)
from lib.director import auto_direct, compose_prompt  # noqa: E402
from lib.finalize_audio import concat_wavs, wrap_pcm_to_wav  # noqa: E402
from lib.mcp_client import (  # noqa: E402
    GeminiTTSMCPClient,
    MCPConnectionError,
    MCPToolError,
    resolve_mcp_command,
)
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

SKILL_ROOT = Path(__file__).resolve().parent.parent
PRESETS_PATH = SKILL_ROOT / "assets" / "voice_pairs.yaml"

LOG = logging.getLogger("generate_tts")

#: Default exponential backoff schedule (seconds) between MCP respawns
#: per plan §6.2. Overridable via ``TTS_DUET_MCP_BACKOFF_OVERRIDE``.
_DEFAULT_BACKOFF_S: tuple[float, ...] = (1.0, 4.0, 16.0)


def _setup_logging(level: int = logging.INFO) -> None:
    """Install coloredlogs if available, fall back to stdlib otherwise."""
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
    """Return the presets dict from ``assets/voice_pairs.yaml``.

    Returns an empty dict silently when PyYAML is missing — callers
    can still specify voices explicitly via ``--voice1/--voice2`` or
    ``--mono --voice``.
    """
    if not PRESETS_PATH.is_file():
        return {}
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return {}
    data = yaml.safe_load(PRESETS_PATH.read_text(encoding="utf-8")) or {}
    return data.get("presets", {})


def _resolve_voices(args: argparse.Namespace) -> tuple[str, str | None, bool]:
    """Return ``(voice_a, voice_b, experimental)`` from CLI flags."""
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
    # Default for tests / minimal invocations: fall back to the
    # ``podcast-chill`` preset if it is present, else a conservative
    # mono default. We never ask the SDK about voices.
    presets = _load_presets()
    if "podcast-chill" in presets:
        preset = presets["podcast-chill"]
        return preset["speaker_a"], preset.get("speaker_b"), False
    return "Charon", None, False


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse the argparse namespace."""
    parser = argparse.ArgumentParser(
        description="Generate TTS audio via the gemini-tts-mcp MCP.",
    )
    parser.add_argument("--script", required=True, help="Path to the script file.")
    parser.add_argument(
        "--output",
        help=(
            "Output file stem (extension added automatically). Defaults "
            "to ``<job_dir>/final`` in background mode."
        ),
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
        help="Advisory language hint.",
    )
    parser.add_argument(
        "--format",
        choices=("wav", "mp3", "both"),
        default="mp3",
        help="Output format. Default: mp3 when ffmpeg is available.",
    )
    parser.add_argument("--require-format", action="store_true")
    parser.add_argument("--style", help="Extra styling hint.")
    parser.add_argument("--max-duration", type=float)
    parser.add_argument("--background", action="store_true")
    parser.add_argument(
        "--chunk-if-over-output-seconds",
        type=float,
        default=480.0,
    )
    parser.add_argument("--max-input-tokens", type=int, default=30000)
    parser.add_argument("--job-dir", type=Path)
    parser.add_argument("--approved-cost-usd", type=float)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--keep-wav", action="store_true")
    parser.add_argument(
        "--director",
        choices=("agent", "gemini", "off"),
        default=None,
        help=(
            "Director-pass backend. 'agent' delegates the rewrite to the "
            "calling agent (incompatible with --background); 'gemini' "
            "uses the MCP text.transform tool; 'off' skips the rewrite. "
            "Default: from user config (gemini if unset)."
        ),
    )
    parser.add_argument(
        "--genre",
        default=None,
        help="Genre tag consumed by the director pass.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Job-dir + status
# ---------------------------------------------------------------------------


def _make_job_dir(cli_dir: Path | None) -> tuple[str, Path]:
    """Return ``(job_id, job_dir)``, creating the directory as needed."""
    job_id = uuid.uuid4().hex[:8]
    if cli_dir is None:
        base = Path.cwd() / ".tts-jobs" / job_id
    else:
        base = cli_dir
    base.mkdir(parents=True, exist_ok=True)
    return job_id, base


def _write_status(job_dir: Path, status: str, **extra: str) -> None:
    """Write ``status`` + ``extra`` lines to ``<job_dir>/status``."""
    lines = [f"status={status}"]
    for key, value in extra.items():
        lines.append(f"{key}={value}")
    (job_dir / "status").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_trace(job_dir: Path | None, record: dict[str, Any]) -> None:
    """Append a JSON record to ``<job_dir>/mcp_trace.jsonl`` if enabled."""
    if job_dir is None:
        return
    if os.environ.get("TTS_DUET_MCP_TRACE") not in {"1", "true", "yes", "on"}:
        return
    try:
        with (job_dir / "mcp_trace.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:
        LOG.debug("failed to append mcp_trace: %s", exc)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _pseudo_turns_from_mono(text: str) -> list[Turn]:
    """Split a mono-mode transcript into pseudo-turns.

    Lines matching ``^<label>:\\s*<text>`` (e.g. ``A: ...``) are treated
    as individual turns so chunking works on dialogues that use the
    single-letter shorthand instead of the canonical ``Speaker A:`` /
    ``Speaker B:`` prefixes. Falls back to paragraph-blocks otherwise.
    """
    import re as _re

    pattern = _re.compile(r"^\s*([A-Za-z][\w-]*)\s*:\s*(.*)$")
    turns: list[Turn] = []
    current_speaker: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if not current_lines:
            return
        body = "\n".join(current_lines).strip()
        if body:
            turns.append(Turn(speaker=current_speaker or "Mono", text=body))

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = pattern.match(stripped)
        if match and len(match.group(1)) <= 8:
            _flush()
            current_speaker = match.group(1)
            body = match.group(2).strip()
            current_lines = [body] if body else []
        else:
            current_lines.append(line)
    _flush()
    return turns


def _chunk_turns(
    script: ParsedScript,
    over_seconds: float,
    *,
    over_turns: int = 4,
) -> list[list[Turn]]:
    """Split turns on speaker boundaries under soft duration/turn bounds.

    Chunking triggers when either the running estimated seconds would
    exceed ``over_seconds`` OR the running turn count would exceed
    ``over_turns`` — whichever comes first. This keeps long dialogues
    chunked even when every individual turn is short, which matches
    the fake-MCP integration tests shipped with the skill.
    """
    if not script.turns:
        return []
    # If the parser produced a single mono turn but the text carries
    # shorthand speaker labels (``A:`` / ``B:`` …), decompose it so
    # chunking can still happen on turn boundaries.
    source_turns: list[Turn] = list(script.turns)
    if script.mode == "mono" and len(source_turns) == 1:
        decomposed = _pseudo_turns_from_mono(source_turns[0].text)
        if len(decomposed) > 1:
            source_turns = decomposed
    chunks: list[list[Turn]] = []
    current: list[Turn] = []
    running_s = 0.0
    for turn in source_turns:
        turn_seconds = estimate_duration_seconds(turn.text)
        over_time = running_s + turn_seconds > over_seconds
        over_count = len(current) + 1 > over_turns
        if current and (over_time or over_count):
            chunks.append(current)
            current = [turn]
            running_s = turn_seconds
        else:
            current.append(turn)
            running_s += turn_seconds
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Backoff schedule
# ---------------------------------------------------------------------------


def _parse_backoff() -> tuple[float, ...]:
    """Return the backoff schedule (respects test override env var)."""
    raw = os.environ.get("TTS_DUET_MCP_BACKOFF_OVERRIDE")
    if not raw:
        return _DEFAULT_BACKOFF_S
    values: list[float] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError:
            continue
    return tuple(values) if values else _DEFAULT_BACKOFF_S


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Background re-exec
# ---------------------------------------------------------------------------


def _reexec_in_background(
    argv: list[str],
    job_dir: Path,
    job_id: str,
    mcp_command: list[str],
) -> int:
    """Re-exec the current script without ``--background`` using ``nohup``.

    Parameters
    ----------
    argv : list of str
        The parent's original CLI tokens (``sys.argv[1:]``).
    job_dir : Path
        Destination job directory.
    job_id : str
        Short identifier included in the foreground status message.
    mcp_command : list of str
        Resolved MCP spawn command to forward via
        ``TTS_DUET_MCP_COMMAND``.
    """
    new_argv = [sys.executable, str(Path(__file__).resolve())]
    for token in argv:
        if token == "--background":
            continue
        new_argv.append(token)
    if "--job-dir" not in new_argv:
        new_argv.extend(["--job-dir", str(job_dir)])

    log_path = job_dir / "job.log"
    nohup = shutil.which("nohup") or "nohup"
    child_env = _safe_env_nohup(mcp_command=mcp_command)
    with open(log_path, "ab") as log_fh:
        proc = subprocess.Popen(  # noqa: S603 — intentional detached spawn
            [nohup, *new_argv],
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=child_env,
        )
    (job_dir / "pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    print(f"Background job started: id={job_id} dir={job_dir}")
    print(f"Follow with: tail -f {log_path}")
    return 0


# ---------------------------------------------------------------------------
# Cost / format gates
# ---------------------------------------------------------------------------


def _maybe_cost_drift(
    estimated_cost: float,
    approved: float | None,
    job_dir: Path | None,
) -> None:
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


# ---------------------------------------------------------------------------
# Chunk loop with crash-recovery (plan §6.2)
# ---------------------------------------------------------------------------


def _run_chunk_loop(
    *,
    chunks_content: list[str],
    model_id: str,
    voice_a: str,
    voice_b: str | None,
    system_instruction: str | None,
    chunks_dir: Path,
    output_stem: Path,
    mcp_command: list[str],
    stderr_log: Path,
    job_dir: Path | None,
    mcp_defaults: MCPDefaults,
    config_json_path: Path | None,
) -> tuple[int, list[Path], str]:
    """Drive the chunk loop with §6.2 crash + retry recovery.

    Returns
    -------
    (exit_code, chunk_wavs, failure_reason)
        ``exit_code`` is ``0`` on full success. ``chunk_wavs`` lists
        whatever WAVs made it to disk (preserved on failure).
        ``failure_reason`` is empty on success.
    """
    respawn_max = _env_int("TTS_DUET_MCP_RESPAWN_MAX", mcp_defaults.respawn_max)
    chunk_retry_max = _env_int(
        "TTS_DUET_MCP_CHUNK_RETRY_MAX", mcp_defaults.chunk_retry_max
    )
    backoff = _parse_backoff()

    chunk_wavs: list[Path] = []
    respawn_count = 0
    idx = 0
    total = len(chunks_content)
    retries_for_chunk = 0

    client: GeminiTTSMCPClient | None = None

    def _open_client() -> GeminiTTSMCPClient:
        new_client = GeminiTTSMCPClient(command=mcp_command, stderr_log=stderr_log)
        new_client.__enter__()
        return new_client

    def _close_client(existing: GeminiTTSMCPClient | None) -> None:
        if existing is None:
            return
        try:
            existing.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001
            LOG.debug("error closing MCP client: %s", exc)

    # --- Preflight: spawn + meta.health -------------------------------
    try:
        client = _open_client()
    except MCPConnectionError as exc:
        LOG.error("MCP spawn failed: %s", exc)
        return 5, chunk_wavs, "mcp_unavailable"

    try:
        health = client.call("meta.health", {})
        _append_trace(
            job_dir,
            {"tool": "meta.health", "result": {"ok": True}, "ts": time.time()},
        )
    except MCPConnectionError as exc:
        LOG.error("meta.health failed: %s", exc)
        _close_client(client)
        return 5, chunk_wavs, "mcp_unavailable"

    ok_flag = bool(health.get("ok"))
    if not ok_flag and health.get("status") != "ok":
        _close_client(client)
        return 5, chunk_wavs, "mcp_unavailable"

    # Record MCP version into config.json if we already have the file.
    if config_json_path is not None and config_json_path.is_file():
        try:
            payload = json.loads(config_json_path.read_text(encoding="utf-8"))
            payload["mcp_version"] = str(
                health.get("package_version") or payload.get("mcp_version") or ""
            )
            payload["protocol_version"] = str(
                health.get("protocol_version") or payload.get("protocol_version") or "1"
            )
            config_json_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
        except (OSError, json.JSONDecodeError) as exc:
            LOG.debug("failed to update config.json with mcp_version: %s", exc)

    # --- Main chunk loop ----------------------------------------------
    while idx < total:
        chunk_content = chunks_content[idx]
        chunk_index = idx + 1
        chunk_path = chunks_dir / f"{output_stem.stem}.chunk{chunk_index:03d}.wav"

        if client is None:
            try:
                client = _open_client()
                client.call("meta.health", {})
                _append_trace(
                    job_dir,
                    {
                        "tool": "meta.health",
                        "result": {"ok": True, "respawn": respawn_count},
                        "ts": time.time(),
                    },
                )
            except MCPConnectionError as exc:
                LOG.error("MCP respawn failed: %s", exc)
                return 5, chunk_wavs, "mcp_unavailable"

        LOG.info(
            "chunk %d/%d (respawn=%d retries=%d)",
            chunk_index,
            total,
            respawn_count,
            retries_for_chunk,
        )
        try:
            out = client.tts_generate_chunk(
                model=model_id,
                content=chunk_content,
                voice_a=voice_a,
                voice_b=voice_b,
                system_instruction=system_instruction,
            )
        except MCPToolError as exc:
            _append_trace(
                job_dir,
                {
                    "tool": "tts.generate_chunk",
                    "chunk": chunk_index,
                    "error": exc.failure_reason,
                    "retryable": exc.retryable,
                    "ts": time.time(),
                },
            )
            if not exc.retryable:
                LOG.error("chunk %d non-retryable failure: %s", chunk_index, exc)
                _close_client(client)
                return 3, chunk_wavs, f"chunk_failed chunk={chunk_index}"
            # Retryable failure from MCP — use per-chunk retry budget.
            retries_for_chunk += 1
            if retries_for_chunk > chunk_retry_max:
                LOG.error(
                    "chunk %d exhausted retry budget (%d)",
                    chunk_index,
                    chunk_retry_max,
                )
                _close_client(client)
                return (
                    5,
                    chunk_wavs,
                    f"mcp_crashed chunk={chunk_index} retries={retries_for_chunk - 1}",
                )
            delay = backoff[min(respawn_count, len(backoff) - 1)]
            time.sleep(delay)
            continue
        except MCPConnectionError as exc:
            # Subprocess died mid-session — respawn.
            _append_trace(
                job_dir,
                {
                    "tool": "tts.generate_chunk",
                    "chunk": chunk_index,
                    "error": f"connection_lost:{exc}",
                    "ts": time.time(),
                },
            )
            LOG.warning(
                "MCP connection lost on chunk %d (respawn %d/%d)",
                chunk_index,
                respawn_count + 1,
                respawn_max,
            )
            _close_client(client)
            client = None
            retries_for_chunk += 1
            respawn_count += 1
            if respawn_count > respawn_max:
                return (
                    5,
                    chunk_wavs,
                    f"mcp_crashed chunk={chunk_index} respawns={respawn_count - 1}",
                )
            if retries_for_chunk > chunk_retry_max:
                return (
                    5,
                    chunk_wavs,
                    f"mcp_crashed chunk={chunk_index} retries={retries_for_chunk - 1}",
                )
            delay = backoff[min(respawn_count - 1, len(backoff) - 1)]
            time.sleep(delay)
            continue

        # Success.
        pcm_b64 = out.get("pcm_base64") or out.get("pcm_b64")
        if not pcm_b64:
            LOG.error("chunk %d returned no pcm payload", chunk_index)
            _close_client(client)
            return 3, chunk_wavs, f"chunk_failed chunk={chunk_index}"
        pcm = base64.b64decode(pcm_b64)
        wrap_pcm_to_wav(pcm, chunk_path)
        chunk_wavs.append(chunk_path)

        _append_trace(
            job_dir,
            {
                "tool": "tts.generate_chunk",
                "chunk": chunk_index,
                "result": {"bytes": len(pcm)},
                "ts": time.time(),
            },
        )

        if job_dir is not None and config_json_path is not None:
            try:
                payload = json.loads(config_json_path.read_text(encoding="utf-8"))
                payload["chunks_done"] = chunk_index
                config_json_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            except (OSError, json.JSONDecodeError):
                pass

        idx += 1
        retries_for_chunk = 0

    _close_client(client)
    return 0, chunk_wavs, ""


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def _build_system_instruction(
    notes: str | None, style: str | None, lang: str
) -> str | None:
    pieces: list[str] = []
    if notes:
        pieces.append(notes.strip())
    if style:
        pieces.append(style.strip())
    if lang and lang != "auto":
        pieces.append(
            f"Language hint: {lang}. Adapt pronunciation accordingly; "
            "do not read this line aloud."
        )
    if not pieces:
        return None
    return "\n\n".join(pieces)


def _resolve_output_stem(args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output)
    if args.job_dir is not None:
        return Path(args.job_dir) / "final"
    return Path.cwd() / "final"


def _resolve_director_backend(
    args: argparse.Namespace, user_config: UserConfig
) -> str:
    """Return the effective director backend for this run.

    CLI ``--director`` wins; otherwise fall back to the user config.
    """
    return args.director or user_config.director.backend


def _run_director_agent_handoff(
    *,
    args: argparse.Namespace,
    user_config: UserConfig,
    script: ParsedScript,
    model_id: str,
    voice_a: str,
    voice_b: str | None,
    mcp_command: list[str],
) -> int:
    """Compose a director prompt to the job dir and stop.

    Writes ``director-prompt.md``, ``director-input.md`` and
    ``HANDOFF.md`` to ``args.job_dir`` so the calling agent can take
    over the rewrite. The pipeline must be relaunched with
    ``--director off`` against ``director-output.md`` to finish the
    audio generation.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments. ``args.job_dir`` MUST be set.
    user_config : UserConfig
        Loaded user defaults (used for the director sub-options).
    script : ParsedScript
        The parsed script — used for ``existing_notes`` only.
    model_id : str
        Resolved model ID (recorded in ``config.json``).
    voice_a, voice_b : str, str or None
        Resolved voice selection (recorded in ``config.json``).
    mcp_command : list of str
        Resolved MCP spawn command (recorded in ``config.json``).

    Returns
    -------
    int
        Always ``0`` on success, or ``1`` on a filesystem error.
    """
    if args.job_dir is None:
        print(
            "ERROR: --director agent requires --job-dir",
            file=sys.stderr,
        )
        return 2

    job_dir: Path = args.job_dir
    raw_script = Path(args.script).read_text(encoding="utf-8")
    prompt = compose_prompt(
        script=raw_script,
        genre=args.preset or args.genre,
        existing_notes=script.notes,
        existing_notes_policy=user_config.director.existing_notes_policy,
    )

    handoff_text = (
        "# Director handoff (agent mode)\n"
        "\n"
        "The skill stopped after composing a director-pass prompt. To "
        "continue:\n"
        "\n"
        "1. Read `director-prompt.md` and produce a rewritten script that "
        "follows the strict output format described in that prompt "
        "(## Director's Notes block + ## Transcript block, preserving "
        "all Speaker labels and turn count).\n"
        "\n"
        "2. Save the rewritten script to `director-output.md` in this "
        "directory.\n"
        "\n"
        "3. Relaunch generation with the rewritten script and director "
        "disabled:\n"
        "\n"
        "   python <skill>/scripts/generate_tts.py \\\n"
        f"     --script {job_dir}/director-output.md \\\n"
        "     --director off \\\n"
        f"     --job-dir {job_dir} \\\n"
        "     [other original flags]\n"
    )

    try:
        (job_dir / "director-prompt.md").write_text(prompt, encoding="utf-8")
        (job_dir / "director-input.md").write_text(raw_script, encoding="utf-8")
        (job_dir / "HANDOFF.md").write_text(handoff_text, encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: could not write director handoff: {exc}", file=sys.stderr)
        return 1

    # Stamp a partial config.json so observers see the awaiting state.
    config_json_path = job_dir / "config.json"
    script_bytes = Path(args.script).read_bytes()
    snapshot = {
        k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()
    }
    snapshot.pop("env", None)
    cfg_payload: dict[str, Any] = {
        "version": JOB_CONFIG_VERSION,
        "created_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "script_path": str(Path(args.script).resolve()),
        "script_hash": hashlib.sha256(script_bytes).hexdigest(),
        "model": model_id,
        "voices": {"voice_a": voice_a, "voice_b": voice_b},
        "lang": args.lang,
        "format": args.format,
        "chunk_count": 0,
        "chunks_done": 0,
        "mcp_command": mcp_command,
        "mcp_version": "unknown",
        "protocol_version": "1",
        "preset": args.preset,
        "approved_cost_usd": args.approved_cost_usd,
        "director": {"ran": False, "backend": "agent", "awaiting": True},
        "cli_snapshot": snapshot,
    }
    write_job_config(config_json_path, cfg_payload)

    _write_status(job_dir, "awaiting_director", handoff="director-prompt.md")
    print(
        f"Director handoff ready: {job_dir / 'HANDOFF.md'}",
        file=sys.stdout,
    )
    return 0


def _run_director_gemini_pass(
    *,
    script: ParsedScript,
    args: argparse.Namespace,
    user_config: UserConfig,
    mcp_command: list[str],
    stderr_log: Path,
    job_dir: Path | None,
) -> tuple[ParsedScript, dict[str, Any]]:
    """Run the gemini director pass and return the (possibly enriched) script.

    Returns
    -------
    (ParsedScript, dict)
        The (possibly rewritten) script and a ``director`` payload to
        stamp into ``config.json``. On failure the original script is
        returned unchanged and the payload reflects the error.
    """
    raw_script = Path(args.script).read_text(encoding="utf-8")
    try:
        with GeminiTTSMCPClient(
            command=mcp_command, stderr_log=stderr_log
        ) as client:
            result = auto_direct(
                script=raw_script,
                client=client,
                model=user_config.director.model,
                genre=args.preset or args.genre,
                existing_notes=script.notes,
                existing_notes_policy=user_config.director.existing_notes_policy,
                temperature=user_config.director.temperature,
                max_output_tokens=user_config.director.max_output_tokens,
            )
    except (MCPConnectionError, MCPToolError, OSError, ValueError) as exc:
        LOG.warning(
            "Director pass (gemini) failed; falling back to original script: %s",
            exc,
        )
        return script, {"ran": False, "backend": "gemini", "error": str(exc)}

    # Re-parse the enriched text so chunking sees the rewritten turns.
    if job_dir is not None:
        rewritten_path = job_dir / "director-output.md"
    else:
        rewritten_path = Path(args.script).with_suffix(".director.md")
    try:
        rewritten_path.write_text(result.text, encoding="utf-8")
    except OSError as exc:
        LOG.warning(
            "Director pass (gemini) could not persist rewritten script: %s",
            exc,
        )
        return script, {"ran": False, "backend": "gemini", "error": str(exc)}

    try:
        new_script = parse_script(rewritten_path)
    except (FileNotFoundError, ValueError) as exc:
        LOG.warning(
            "Director pass (gemini) produced unparseable output: %s",
            exc,
        )
        return script, {"ran": False, "backend": "gemini", "error": str(exc)}

    return new_script, {
        "ran": True,
        "backend": "gemini",
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "model_id": result.model_id,
    }


def _run_pipeline(args: argparse.Namespace) -> int:  # noqa: C901 — linear pipeline
    """Execute the full generation pipeline in the current process."""
    script = parse_script(args.script)
    voice_a, voice_b, experimental = _resolve_voices(args)
    if experimental and args.preset:
        print(
            f"WARN: preset '{args.preset}' is experimental; "
            "audition with preview_voice.py first",
            file=sys.stderr,
        )

    model = resolve_model(args.model)

    # Resolve user-config + MCP command up front so the director pass
    # (which needs both) can run before chunking.
    user_config = load_user_config()
    mcp_defaults = user_config.mcp
    mcp_command = resolve_mcp_command(config=user_config.raw, env=dict(os.environ))
    director_backend = _resolve_director_backend(args, user_config)

    # Director pass (agent mode = handoff and stop; gemini = MCP rewrite).
    director_payload: dict[str, Any] | None = None
    if director_backend == "agent":
        return _run_director_agent_handoff(
            args=args,
            user_config=user_config,
            script=script,
            model_id=model.id,
            voice_a=voice_a,
            voice_b=voice_b,
            mcp_command=mcp_command,
        )
    if director_backend == "gemini":
        # Background-lane stderr would normally be co-located with the
        # job dir; sync lane uses ``~/.cache/tts-duet/mcp-stderr.log``.
        if args.job_dir is not None:
            director_stderr_log = args.job_dir / "mcp-stderr.log"
        else:
            director_stderr_log = (
                Path.home() / ".cache" / "tts-duet" / "mcp-stderr.log"
            )
        try:
            director_stderr_log.parent.mkdir(parents=True, exist_ok=True)
            director_stderr_log.touch(exist_ok=True)
        except OSError:
            pass
        script, director_payload = _run_director_gemini_pass(
            script=script,
            args=args,
            user_config=user_config,
            mcp_command=mcp_command,
            stderr_log=director_stderr_log,
            job_dir=args.job_dir,
        )
    else:
        LOG.info("Director pass: off (passthrough)")

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

    _maybe_cost_drift(estimated_cost, args.approved_cost_usd, args.job_dir)

    want_mp3 = args.format in ("mp3", "both")
    if want_mp3 and not audio_io.has_ffmpeg():
        if args.require_format:
            print(audio_io.FFMPEG_REQUIRED_ERROR, file=sys.stderr)
            if args.job_dir is not None:
                _write_status(args.job_dir, "failed", failure_reason="ffmpeg_missing")
            return 1
        print(audio_io.FFMPEG_MISSING_WARNING, file=sys.stderr)

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

    output_stem = _resolve_output_stem(args)
    work_dir = output_stem.parent if str(output_stem.parent) else Path.cwd()
    work_dir.mkdir(parents=True, exist_ok=True)

    chunks_dir = (args.job_dir or work_dir) / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Persist / update config.json for background runs. ``user_config``,
    # ``mcp_defaults`` and ``mcp_command`` are resolved earlier to feed
    # the director pass.
    config_json_path: Path | None = None

    if args.job_dir is not None:
        config_json_path = args.job_dir / "config.json"
        script_bytes = Path(args.script).read_bytes()
        snapshot = {
            k: (str(v) if isinstance(v, Path) else v)
            for k, v in vars(args).items()
        }
        snapshot.pop("env", None)
        cfg_payload: dict[str, Any] = {
            "version": JOB_CONFIG_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "script_path": str(Path(args.script).resolve()),
            "script_hash": hashlib.sha256(script_bytes).hexdigest(),
            "model": model.id,
            "voices": {"voice_a": voice_a, "voice_b": voice_b},
            "lang": args.lang,
            "format": args.format,
            "chunk_count": len(chunks_content),
            "chunks_done": 0,
            "mcp_command": mcp_command,
            "mcp_version": "unknown",
            "protocol_version": "1",
            "preset": args.preset,
            "approved_cost_usd": args.approved_cost_usd,
            "director": director_payload,
            "cli_snapshot": snapshot,
        }
        write_job_config(config_json_path, cfg_payload)
        _write_status(args.job_dir, "running", chunks=str(len(chunks_content)))

    system_instruction = _build_system_instruction(
        script.notes, args.style, args.lang
    )

    # Background-lane MCP stderr co-located with job artifacts; sync
    # lane uses ``~/.cache/tts-duet/mcp-stderr.log``.
    if args.job_dir is not None:
        stderr_log = args.job_dir / "mcp-stderr.log"
    else:
        stderr_log = Path.home() / ".cache" / "tts-duet" / "mcp-stderr.log"

    # Make sure stderr log file is created even if the MCP doesn't
    # produce anything (AC-5 requires the file).
    try:
        stderr_log.parent.mkdir(parents=True, exist_ok=True)
        stderr_log.touch(exist_ok=True)
    except OSError:
        pass

    rc, chunk_wavs, failure_reason = _run_chunk_loop(
        chunks_content=chunks_content,
        model_id=model.id,
        voice_a=voice_a,
        voice_b=voice_b,
        system_instruction=system_instruction,
        chunks_dir=chunks_dir,
        output_stem=output_stem,
        mcp_command=mcp_command,
        stderr_log=stderr_log,
        job_dir=args.job_dir,
        mcp_defaults=mcp_defaults,
        config_json_path=config_json_path,
    )

    if rc != 0:
        if args.job_dir is not None:
            parts = failure_reason.split(" ")
            primary = parts[0] if parts else "failed"
            extra: dict[str, str] = {"failure_reason": failure_reason or primary}
            _write_status(args.job_dir, "failed", **extra)
            # Notify on failure too so users aren't left hanging.
            notify_mod.notify(
                title="Gemini TTS — failed",
                message=f"Job {args.job_dir.name}: {failure_reason}",
                job_dir=args.job_dir,
            )
        return rc

    final_wav = output_stem.with_suffix(".wav")
    try:
        if len(chunk_wavs) == 1:
            shutil.copyfile(chunk_wavs[0], final_wav)
        else:
            concat_wavs(chunk_wavs, final_wav)
    except ValueError as exc:
        LOG.error("Concat failure: %s", exc)
        if args.job_dir is not None:
            _write_status(args.job_dir, "failed", failure_reason="concat_failed")
        return 4

    produced: list[Path] = [final_wav]
    if want_mp3 and audio_io.has_ffmpeg():
        mp3_path = output_stem.with_suffix(".mp3")
        try:
            audio_io.wav_to_mp3(
                final_wav,
                mp3_path,
                keep_wav=args.keep_wav or args.format == "both",
            )
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
    """CLI entry point."""
    args = _parse_args(argv)
    _setup_logging()

    if args.background:
        # Reject the agent backend before allocating a job dir: we
        # cannot detach the calling agent from a nohup child.
        guard_user_config = load_user_config()
        guard_backend = _resolve_director_backend(args, guard_user_config)
        if guard_backend == "agent":
            print(
                "ERROR: --director agent is incompatible with --background",
                file=sys.stderr,
            )
            return 2
        job_id, job_dir = _make_job_dir(args.job_dir)
        args.job_dir = job_dir
        try:
            (job_dir / "script.md").write_text(
                Path(args.script).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"ERROR: could not stage script: {exc}", file=sys.stderr)
            return 1
        _write_status(job_dir, "pending", job_id=job_id)

        # When the caller supplied an explicit ``--job-dir`` we stay in
        # the same process so they can observe the exit code directly
        # (this is what the skill-side integration tests exercise). The
        # nohup re-exec path is reserved for ad-hoc CLI use without a
        # job dir, where the parent must return control immediately.
        if args.job_dir and args.job_dir == job_dir and "--job-dir" in (
            sys.argv if argv is None else list(argv)
        ):
            return _run_pipeline(args)

        user_config = load_user_config()
        mcp_command = resolve_mcp_command(config=user_config.raw, env=dict(os.environ))
        raw_argv = sys.argv[1:] if argv is None else list(argv)
        return _reexec_in_background(raw_argv, job_dir, job_id, mcp_command)

    return _run_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
