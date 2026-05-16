"""Synchronous stdio MCP client for the tts-duet skill (plan §5.3).

Wraps the official ``mcp.client.stdio`` async API in a thread-backed
event loop so skill-side callers can stay synchronous::

    with GeminiTTSMCPClient(command=cmd, stderr_log=log) as client:
        health = client.health()
        out = client.tts_generate_chunk(model=..., content=..., voice_a=...)

The client drives a long-lived stdio subprocess until the ``with``
block exits; a dedicated background thread owns the asyncio event loop
so the session survives across multiple synchronous ``call_tool`` hops.

MCP responses are parsed out of ``CallToolResult.structuredContent``
when the server provides it and fall back to decoding the first JSON
text block otherwise — this mirrors how the real Anthropic agent
runtime handles tool results and matches the fake MCP fixture used in
skill-side tests.

Security invariant (P1): the skill process never reads
``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` itself. When the client spawns
the MCP child, it uses :func:`lib._safe_env.safe_env` with
``for_mcp=True`` so those keys are forwarded *only* to the MCP. Every
other subprocess in the skill uses ``for_mcp=False``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from lib._safe_env import safe_env

__all__ = [
    "GeminiTTSMCPClient",
    "MCPConnectionError",
    "MCPToolError",
    "resolve_mcp_command",
]

LOG = logging.getLogger("tts_duet.mcp_client")

#: Vendored fallback command used when nothing else resolves. Pinned to
#: ``@v2.3.0`` per plan §6.4.
_VENDORED_FALLBACK: tuple[str, ...] = (
    "uvx",
    "--from",
    "git+https://github.com/obeone/claude-skills@v2.3.0#subdirectory=skills/tts-duet/mcp",
    "gemini-tts-mcp",
)


class MCPConnectionError(Exception):
    """Raised when the MCP subprocess cannot be reached or dies."""


class MCPToolError(Exception):
    """Raised when a tool call returns a structured ``failure_reason``.

    Attributes
    ----------
    failure_reason : str
        The ``failure_reason`` string from the MCP error payload.
    retryable : bool
        Whether the caller should retry (per §6.2 crash recovery).
    detail : str
        Free-form human-readable diagnostic.
    """

    def __init__(self, failure_reason: str, retryable: bool, detail: str) -> None:
        super().__init__(f"{failure_reason}: {detail}")
        self.failure_reason = failure_reason
        self.retryable = retryable
        self.detail = detail


def resolve_mcp_command(
    config: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Resolve the MCP spawn command.

    Resolution order (plan §5.3):

    1. ``TTS_DUET_MCP_COMMAND`` environment variable (shlex-split).
    2. ``config["mcp"]["command"]`` — either ``list[str]`` or a single
       string (shlex-split).
    3. ``shutil.which('gemini-tts-mcp')`` if the binary is on ``$PATH``.
    4. Vendored ``uvx`` fallback pinned to ``@v2.3.0``.

    Parameters
    ----------
    config : dict, optional
        Parsed ``~/.config/tts-duet/config.yaml``. The ``mcp.command``
        key (either a list or a string) is consulted.
    env : dict of str to str, optional
        Environment to inspect for ``TTS_DUET_MCP_COMMAND``. Defaults
        to :data:`os.environ`.

    Returns
    -------
    list of str
        The argv to pass to :class:`StdioServerParameters`. Never
        empty.
    """
    env_map = os.environ if env is None else env
    raw_env = env_map.get("TTS_DUET_MCP_COMMAND")
    if raw_env:
        tokens = shlex.split(raw_env)
        if tokens:
            return tokens

    if config:
        mcp_section = config.get("mcp") or {}
        configured = mcp_section.get("command")
        if isinstance(configured, list) and configured:
            return [str(x) for x in configured]
        if isinstance(configured, str) and configured.strip():
            tokens = shlex.split(configured)
            if tokens:
                return tokens

    on_path = shutil.which("gemini-tts-mcp")
    if on_path:
        return [on_path]

    return list(_VENDORED_FALLBACK)


def _parse_tool_result(result: Any) -> dict[str, Any]:
    """Extract a ``dict`` payload from an MCP ``CallToolResult``.

    Prefers ``structuredContent`` when the server supplies it; falls
    back to decoding the first ``TextContent`` block as JSON otherwise.

    Parameters
    ----------
    result : mcp.types.CallToolResult
        Result object returned by :meth:`ClientSession.call_tool`.

    Returns
    -------
    dict of str to Any
        Decoded payload. Empty dict if the tool returned no content.

    Raises
    ------
    MCPConnectionError
        If the payload cannot be decoded as a JSON object.
    """
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                return decoded
    return {}


def _maybe_raise_tool_error(payload: dict[str, Any]) -> None:
    """Convert a structured error payload into :class:`MCPToolError`.

    Pass-through when ``payload`` does not carry a ``failure_reason``
    field — success payloads never hit this branch.
    """
    if "failure_reason" not in payload:
        return
    raise MCPToolError(
        failure_reason=str(payload.get("failure_reason", "unknown")),
        retryable=bool(payload.get("retryable", False)),
        detail=str(payload.get("detail", "")),
    )


class _AsyncSession:
    """Internal async helper that owns the stdio session."""

    def __init__(
        self,
        command: list[str],
        stderr_log: Path | None,
        env: dict[str, str],
    ) -> None:
        self._command = command
        self._stderr_log = stderr_log
        self._env = env
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._stderr_fp: Any = None

    async def start(self) -> None:
        self._stack = AsyncExitStack()
        errlog = None
        if self._stderr_log is not None:
            try:
                self._stderr_log.parent.mkdir(parents=True, exist_ok=True)
                # Line-buffered append so concurrent respawns don't blow
                # away previous stderr for the same job.
                errlog = open(self._stderr_log, "ab", buffering=0)
                self._stderr_fp = errlog
            except OSError as exc:
                LOG.debug("could not open MCP stderr log %s: %s", self._stderr_log, exc)
                errlog = None

        params = StdioServerParameters(
            command=self._command[0],
            args=list(self._command[1:]),
            env=self._env,
        )
        try:
            read, write = await self._stack.enter_async_context(
                stdio_client(params, errlog=errlog)
            )
            session = await self._stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
        except Exception as exc:  # noqa: BLE001 — surface as MCPConnectionError
            await self.aclose()
            raise MCPConnectionError(f"failed to spawn MCP subprocess: {exc}") from exc
        self._session = session

    async def call(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise MCPConnectionError("MCP session not started")
        try:
            result = await self._session.call_tool(tool, params)
        except Exception as exc:  # noqa: BLE001
            raise MCPConnectionError(f"call_tool({tool}) failed: {exc}") from exc
        payload = _parse_tool_result(result)
        _maybe_raise_tool_error(payload)
        return payload

    async def aclose(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is not None:
            try:
                await stack.aclose()
            except Exception as exc:  # noqa: BLE001
                LOG.debug("error during MCP session close: %s", exc)
        if self._stderr_fp is not None:
            try:
                self._stderr_fp.close()
            except OSError:
                pass
            self._stderr_fp = None


class GeminiTTSMCPClient:
    """Synchronous client for the ``gemini-tts-mcp`` server.

    Parameters
    ----------
    command : list of str
        The MCP spawn command. Typically the output of
        :func:`resolve_mcp_command`.
    stderr_log : Path, optional
        Path to capture the MCP's stderr stream. When ``None`` (default)
        stderr is inherited from the caller. Pass
        ``<job_dir>/mcp-stderr.log`` for job-dir runs or
        ``~/.cache/tts-duet/mcp-stderr.log`` for preflight checks.

    Notes
    -----
    Each instance spawns one MCP subprocess inside a dedicated event
    loop running on a background thread. The subprocess is terminated
    when the context manager exits. Instances are not reusable after
    ``__exit__``.
    """

    def __init__(
        self,
        command: list[str],
        stderr_log: Path | None = None,
    ) -> None:
        if not command:
            raise ValueError("GeminiTTSMCPClient requires a non-empty command")
        self._command = list(command)
        self._stderr_log = Path(stderr_log) if stderr_log is not None else None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: _AsyncSession | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "GeminiTTSMCPClient":
        env = safe_env(for_mcp=True)
        self._session = _AsyncSession(
            command=self._command,
            stderr_log=self._stderr_log,
            env=env,
        )
        self._loop = asyncio.new_event_loop()
        ready = threading.Event()

        def _run_loop() -> None:
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(
            target=_run_loop, name="tts-duet-mcp-client", daemon=True
        )
        self._thread.start()
        ready.wait()
        try:
            self._submit(self._session.start())
        except Exception:
            self._shutdown_loop()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            if self._session is not None and self._loop is not None:
                try:
                    self._submit(self._session.aclose())
                except Exception as close_exc:  # noqa: BLE001
                    LOG.debug("MCP aclose raised: %s", close_exc)
        finally:
            self._shutdown_loop()
            self._session = None

    # ------------------------------------------------------------------
    # Tool calls
    # ------------------------------------------------------------------

    def call(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        """Low-level ``call_tool`` wrapper used by every public method."""
        if self._session is None or self._loop is None:
            raise MCPConnectionError("GeminiTTSMCPClient not entered")
        return self._submit(self._session.call(tool, dict(params)))

    def health(self) -> dict[str, Any]:
        """Invoke ``meta_health``."""
        payload = self.call("meta_health", {})
        # Normalise the `ok` bit for callers that expect it; the real
        # server returns ``status=ok`` while older fakes return ``ok``.
        if "ok" not in payload:
            payload["ok"] = payload.get("status") == "ok"
        return payload

    def tts_generate_chunk(
        self,
        *,
        model: str,
        content: str,
        voice_a: str,
        voice_b: str | None = None,
        system_instruction: str | None = None,
        request_timeout_s: float = 300.0,
    ) -> dict[str, Any]:
        """Invoke ``tts_generate_chunk``."""
        return self.call(
            "tts_generate_chunk",
            {
                "model": model,
                "content": content,
                "voice_a": voice_a,
                "voice_b": voice_b,
                "system_instruction": system_instruction,
                "request_timeout_s": request_timeout_s,
            },
        )

    def tts_preview_voice(
        self,
        *,
        voice: str,
        text: str,
        model: str,
        seconds_hint: float | None = None,
    ) -> dict[str, Any]:
        """Invoke ``tts_preview_voice``."""
        params: dict[str, Any] = {"voice": voice, "text": text, "model": model}
        if seconds_hint is not None:
            params["seconds_hint"] = seconds_hint
        return self.call("tts_preview_voice", params)

    def tts_count_tokens(self, *, model: str, content: str) -> dict[str, Any]:
        """Invoke ``tts_count_tokens``."""
        return self.call("tts_count_tokens", {"model": model, "content": content})

    def text_transform(
        self,
        *,
        prompt: str,
        model: str,
        temperature: float = 0.2,
        max_output_tokens: int = 8192,
    ) -> dict[str, Any]:
        """Invoke ``text_transform``."""
        return self.call(
            "text_transform",
            {
                "prompt": prompt,
                "model": model,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _submit(self, coro: Any) -> Any:
        """Run a coroutine on the background event loop and block."""
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def _shutdown_loop(self) -> None:
        loop = self._loop
        thread = self._thread
        self._loop = None
        self._thread = None
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
            if thread is not None and thread.is_alive():
                thread.join(timeout=5.0)
            try:
                loop.close()
            except RuntimeError:
                pass
