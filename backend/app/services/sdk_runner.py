from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..cli.supervisor import WindowsJob
from ..config import Settings, resolve_claude_executable
from ..repository_sessions import SessionRepository
from .approvals import ApprovalManager

logger = logging.getLogger("iris.sdk")


class TurnEventEmitter:
    """Thread-safe event sink shared by the SDK loop and approval API thread."""

    def __init__(
        self,
        repo: SessionRepository,
        turn_id: str,
        max_payload_chars: int,
    ) -> None:
        self.repo = repo
        self.turn_id = turn_id
        self.max_payload_chars = max_payload_chars
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, kind: str, payload: Any, truncated: bool = False) -> None:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) > self.max_payload_chars:
            payload = {"truncated": True, "preview": text[: self.max_payload_chars]}
            truncated = True
        with self._lock:
            self._seq += 1
            seq = self._seq
        try:
            self.repo.add_turn_event(self.turn_id, seq, kind, payload, truncated)
        except Exception:
            logger.exception("sdk.event_write_failed turn_id=%s kind=%s", self.turn_id, kind)


def _to_json(value: Any) -> Any:
    try:
        if dataclasses.is_dataclass(value):
            value = dataclasses.asdict(value)
    except Exception:
        pass
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return repr(value)


def _client_pid(client: Any) -> int | None:
    """Best-effort access to the CLI subprocess spawned by the SDK."""
    transport = getattr(client, "_transport", None)
    process = getattr(transport, "_process", None)
    pid = getattr(process, "pid", None)
    return pid if isinstance(pid, int) else None


def _kill_tree(pid: int) -> None:
    """Windows fallback: kill the CLI and every tool process it spawned."""
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("sdk.kill_tree_failed pid=%s", pid)


def _disallowed_tools(profile: str) -> list[str]:
    no_web = ["WebSearch", "WebFetch"]
    subagents = ["Agent", "Task"]
    if profile == "read_only":
        return [
            "Write",
            "Edit",
            "MultiEdit",
            "NotebookEdit",
            "PowerShell",
            "Bash",
            *no_web,
            *subagents,
        ]
    if profile == "edit":
        return ["PowerShell", "Bash", *no_web, *subagents]
    if profile == "execute":
        return [*no_web, *subagents]
    if profile == "research":
        return [
            "Write",
            "Edit",
            "MultiEdit",
            "NotebookEdit",
            "PowerShell",
            "Bash",
            *subagents,
        ]
    return [*no_web, *subagents]


class SdkTurnRunner:
    """Runs a turn with the Claude Agent SDK and bridges tool permissions."""

    def __init__(
        self,
        repo_sessions: SessionRepository,
        settings: Settings,
        approval_manager: ApprovalManager,
        on_success: Callable[[str], None] | None = None,
    ) -> None:
        self.repo_sessions = repo_sessions
        self.settings = settings
        self.approval_manager = approval_manager
        self.on_success = on_success
        self._lock = threading.Lock()
        self._handles: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._shutting_down = False

    def start(
        self,
        *,
        turn_id: str,
        session_id: str,
        workspace: Path,
        prompt: str,
        profile: str,
        role_instruction: str,
        resume: str | None,
        raw_log_path: Path,
    ) -> None:
        handle: dict[str, Any] = {
            "loop": None,
            "task": None,
            "client": None,
            "cancel_event": threading.Event(),
            "cancel_requested": False,
        }
        with self._lock:
            self._handles[turn_id] = handle
        thread = threading.Thread(
            target=self._thread_main,
            args=(
                handle,
                turn_id,
                session_id,
                workspace,
                prompt,
                profile,
                role_instruction,
                resume,
                raw_log_path,
            ),
            daemon=True,
        )
        self._threads[turn_id] = thread
        thread.start()

    def is_active(self, turn_id: str) -> bool:
        with self._lock:
            return turn_id in self._handles

    def cancel(self, turn_id: str) -> bool:
        with self._lock:
            handle = self._handles.get(turn_id)
        if not handle:
            return False
        handle["cancel_requested"] = True
        handle["cancel_event"].set()
        self.approval_manager.cancel_turn(turn_id)
        # Cancel the async task first so the turn records as canceled even if
        # killing the CLI makes the message stream end without a result.
        loop = handle.get("loop")
        task = handle.get("task")
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(self._cancel_task, task)
            except RuntimeError:
                # The loop already closed: the turn finished on its own.
                pass
        # The SDK terminates claude.exe on disconnect, but tool processes it
        # spawned (PowerShell, python, dev servers) are children of claude.exe
        # and survive on Windows. Kill the whole tree.
        pid = handle.get("cli_pid")
        job = handle.get("job")
        if job is not None:
            job.close()
        if isinstance(pid, int):
            _kill_tree(pid)
        return True

    def shutdown(self) -> None:
        self._shutting_down = True
        with self._lock:
            handles = list(self._handles.keys())
            threads = list(self._threads.values())
        for turn_id in handles:
            self.cancel(turn_id)
        for thread in threads:
            thread.join(timeout=3)

    @staticmethod
    def _cancel_task(task: asyncio.Task) -> None:
        if not task.done():
            task.cancel()

    # ------------------------------------------------------------------
    # Thread / async execution
    # ------------------------------------------------------------------
    def _thread_main(
        self,
        handle: dict[str, Any],
        turn_id: str,
        session_id: str,
        workspace: Path,
        prompt: str,
        profile: str,
        role_instruction: str,
        resume: str | None,
        raw_log_path: Path,
    ) -> None:
        try:
            asyncio.run(
                self._run(
                    handle,
                    turn_id,
                    session_id,
                    workspace,
                    prompt,
                    profile,
                    role_instruction,
                    resume,
                    raw_log_path,
                )
            )
        except Exception as exc:  # noqa: BLE001 - thread boundary
            logger.exception("sdk.thread_crashed turn_id=%s", turn_id)
            try:
                self._finish(
                    turn_id,
                    session_id,
                    status="failed",
                    error_type="sdk_runner_crashed",
                    error_message=str(exc)[:4000],
                )
            except Exception:
                logger.exception("sdk.finish_after_crash_failed turn_id=%s", turn_id)
        finally:
            with self._lock:
                self._handles.pop(turn_id, None)
                self._threads.pop(turn_id, None)

    async def _run(
        self,
        handle: dict[str, Any],
        turn_id: str,
        session_id: str,
        workspace: Path,
        prompt: str,
        profile: str,
        role_instruction: str,
        resume: str | None,
        raw_log_path: Path,
    ) -> None:
        handle["loop"] = asyncio.get_running_loop()
        emitter = TurnEventEmitter(
            self.repo_sessions, turn_id, self.settings.max_event_payload_chars
        )
        self.repo_sessions.set_turn_running(turn_id, None)
        cli_path = resolve_claude_executable(self.settings)
        if cli_path is None:
            self._finish(
                turn_id,
                session_id,
                status="failed",
                error_type="sdk_cli_missing",
                error_message=(
                    "Claude Agent SDK could not find claude.exe. Set "
                    "IRIS_CLAUDE_CLI_PATH to the native Claude Code executable."
                ),
            )
            emitter.emit("process.exit", {"exit_code": 1})
            return

        try:
            from claude_agent_sdk import (  # noqa: PLC0415 - optional dependency
                AssistantMessage,
                ClaudeAgentOptions,
                ClaudeSDKClient,
                ConversationResetMessage,
                PermissionResultAllow,
                PermissionResultDeny,
                RateLimitEvent,
                ResultMessage,
                ServerToolResultBlock,
                ServerToolUseBlock,
                StreamEvent,
                SystemMessage,
                TextBlock,
                ToolResultBlock,
                ToolUseBlock,
                UserMessage,
            )
        except Exception as exc:  # noqa: BLE001
            self._finish(
                turn_id,
                session_id,
                status="failed",
                error_type="sdk_unavailable",
                error_message=(
                    f"claude-agent-sdk is not installed: {exc}. Run "
                    "pip install -e \"backend[dev]\"."
                ),
            )
            emitter.emit("process.exit", {"exit_code": 1})
            return

        stderr_lines: list[str] = []
        stderr_lock = threading.Lock()

        def stderr_cb(line: str) -> None:
            if not line.strip():
                return
            with stderr_lock:
                if len(stderr_lines) < 50:
                    stderr_lines.append(line.rstrip())

        async def can_use_tool(tool_name: str, input_data: dict[str, Any], context: Any):
            if handle["cancel_event"].is_set():
                return PermissionResultDeny(message="Turn was canceled.")
            result = await self.approval_manager.request(
                turn_id=turn_id,
                session_id=session_id,
                tool_name=tool_name,
                input_data=input_data,
                context=context,
                emit=emitter.emit,
            )
            if result.get("behavior") == "allow":
                return PermissionResultAllow(
                    updated_input=result.get("updated_input")
                )
            return PermissionResultDeny(
                message=result.get("message") or "User denied this action."
            )

        options = ClaudeAgentOptions(
            cli_path=str(cli_path),
            cwd=str(workspace),
            permission_mode="default",
            can_use_tool=can_use_tool,
            disallowed_tools=_disallowed_tools(profile),
            resume=resume or None,
            max_turns=self.settings.max_turns,
            system_prompt=role_instruction or None,
            include_partial_messages=True,
            setting_sources=["user"],
            stderr=stderr_cb,
            env={"CLAUDE_AGENT_SDK_CLIENT_APP": "Iris"},
        )

        raw_file = None
        try:
            raw_file = open(raw_log_path, "a", encoding="utf-8", errors="replace")
        except OSError:
            logger.exception("sdk.raw_log_open_failed turn_id=%s", turn_id)

        result_payload = None
        accumulated_text: list[str] = []
        partial_buffer: list[str] = []
        last_partial_emit = 0.0

        def emit(kind: str, payload: Any) -> None:
            emitter.emit(kind, payload)

        def flush_partial(force: bool = False) -> None:
            """Coalesce token deltas into small chunks before persisting.

            Persisting every token would write hundreds of turn_events rows;
            ~60 characters or ~0.1 seconds per event keeps the SSE stream
            terminal-like without flooding SQLite.
            """
            nonlocal last_partial_emit
            if not partial_buffer:
                return
            now = time.monotonic()
            text = "".join(partial_buffer)
            if not force and len(text) < 60 and now - last_partial_emit < 0.1:
                return
            partial_buffer.clear()
            last_partial_emit = now
            emit("assistant.delta", {"text": text})

        def map_message(msg: Any) -> None:
            nonlocal result_payload
            if isinstance(msg, StreamEvent):
                event = msg.event or {}
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text")
                        if isinstance(text, str) and text:
                            partial_buffer.append(text)
                            flush_partial()
                return
            if isinstance(msg, SystemMessage):
                if msg.subtype == "thinking_tokens":
                    return
                if msg.subtype == "init":
                    emit("system.init", msg.data)
                else:
                    emit("system.message", {"subtype": msg.subtype, "data": msg.data})
                return
            if isinstance(msg, AssistantMessage):
                flush_partial(force=True)
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        if block.text:
                            accumulated_text.append(block.text)
                            emit("assistant.text", {"text": block.text})
                    elif isinstance(block, ToolUseBlock):
                        emit(
                            "tool.use",
                            {"id": block.id, "name": block.name, "input": block.input},
                        )
                    elif isinstance(block, ToolResultBlock):
                        emit(
                            "tool.result",
                            {
                                "tool_use_id": block.tool_use_id,
                                "content": block.content,
                                "is_error": bool(block.is_error),
                            },
                        )
                    elif isinstance(block, ServerToolUseBlock):
                        emit(
                            "tool.use",
                            {
                                "id": getattr(block, "id", None),
                                "name": getattr(block, "name", "server_tool"),
                                "input": getattr(block, "input", {}),
                            },
                        )
                    elif isinstance(block, ServerToolResultBlock):
                        emit("tool.result", _to_json(block))
                    else:
                        emit("assistant.block", _to_json(block))
                return
            if isinstance(msg, UserMessage):
                content = msg.content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, ToolResultBlock):
                            emit(
                                "tool.result",
                                {
                                    "tool_use_id": block.tool_use_id,
                                    "content": block.content,
                                    "is_error": bool(block.is_error),
                                },
                            )
                return
            if isinstance(msg, ResultMessage):
                result_payload = msg
                return
            if isinstance(msg, RateLimitEvent):
                emit("rate_limit", _to_json(msg.rate_limit_info))
                return
            if isinstance(msg, ConversationResetMessage):
                emit("system.reset", _to_json(msg))
                return
            emit("sdk.message", _to_json(msg))

        finished = False
        job = WindowsJob()
        handle["job"] = job

        async def consume() -> None:
            nonlocal finished
            if handle["cancel_event"].is_set():
                raise asyncio.CancelledError()
            async with ClaudeSDKClient(options=options) as client:
                handle["client"] = client
                cli_pid = _client_pid(client)
                handle["cli_pid"] = cli_pid
                if cli_pid is not None:
                    if job.available and job.attach(cli_pid):
                        logger.info(
                            "sdk.job_attached turn_id=%s pid=%s", turn_id, cli_pid
                        )
                    else:
                        logger.warning(
                            "sdk.job_attach_failed turn_id=%s pid=%s",
                            turn_id,
                            cli_pid,
                        )
                await client.query(prompt)
                async for msg in client.receive_response():
                    if raw_file is not None:
                        try:
                            raw_file.write(
                                json.dumps(_to_json(msg), ensure_ascii=False) + "\n"
                            )
                            raw_file.flush()
                        except OSError:
                            pass
                    if handle["cancel_event"].is_set():
                        raise asyncio.CancelledError()
                    map_message(msg)
            finished = True

        task = asyncio.create_task(consume())
        handle["task"] = task
        if handle["cancel_requested"]:
            task.cancel()

        status = "failed"
        error_type = None
        error_message = None
        try:
            await asyncio.wait_for(
                task, timeout=self.settings.run_timeout_seconds
            )
            if handle["cancel_requested"] and result_payload is None:
                status = "canceled"
                error_type = "canceled"
                error_message = "Turn was canceled by the user."
            elif result_payload is None:
                error_type = "sdk_no_result"
                error_message = "The SDK ended without a result message."
            else:
                failed = bool(result_payload.is_error) or (
                    result_payload.subtype is not None
                    and result_payload.subtype != "success"
                ) or result_payload.terminal_reason in {"api_error", "error"}
                if failed:
                    error_type = (
                        "cli_api_error"
                        if result_payload.api_error_status
                        else "sdk_error"
                    )
                    error_message = (
                        result_payload.result
                        or "; ".join(result_payload.errors or [])
                        or f"SDK terminated with {result_payload.terminal_reason or result_payload.subtype or 'an error'}"
                    )
                else:
                    status = "succeeded"
        except asyncio.TimeoutError:
            task.cancel()
            status = "failed"
            error_type = "timeout"
            error_message = "Turn exceeded the configured time limit."
        except asyncio.CancelledError:
            status = "interrupted" if self._shutting_down else "canceled"
            error_type = "service_stopped" if self._shutting_down else "canceled"
            error_message = (
                "Iris stopped while the turn was active."
                if self._shutting_down
                else "Turn was canceled by the user."
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("sdk.turn_failed turn_id=%s", turn_id)
            status = "failed"
            error_type = "sdk_error"
            error_message = str(exc)[:4000]
        finally:
            flush_partial(force=True)
            # Closes the kill-on-close job, so any tool process still alive
            # (including on abnormal backend exit) is terminated with the turn.
            job.close()
            self.approval_manager.cancel_turn(turn_id, "Turn ended.")
            if raw_file is not None:
                try:
                    raw_file.close()
                except OSError:
                    pass
            with stderr_lock:
                lines = list(stderr_lines)
            if lines:
                emitter.emit("cli.stderr", {"lines": lines}, truncated=len(lines) >= 50)

        if status == "succeeded" and result_payload is not None:
            result_text = result_payload.result
            if result_text is None:
                result_text = "".join(accumulated_text)
            usage = dict(result_payload.usage or {})
            if result_payload.model_usage is not None:
                usage["model_usage"] = _to_json(result_payload.model_usage)
            self._finish(
                turn_id,
                session_id,
                status="succeeded",
                result_text=result_text,
                cli_session_id=result_payload.session_id or resume,
                cost_usd=result_payload.total_cost_usd,
                usage=usage,
            )
            emitter.emit("process.exit", {"exit_code": 0})
            if self.on_success is not None:
                try:
                    self.on_success(session_id)
                except Exception:
                    logger.exception("sdk.memory_notify_failed session_id=%s", session_id)
        else:
            self._finish(
                turn_id,
                session_id,
                status=status,
                error_type=error_type or "sdk_error",
                error_message=(error_message or "SDK turn failed.")[:4000],
            )
            emitter.emit(
                "process.exit",
                {"exit_code": 0 if status == "canceled" else 1},
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _finish(
        self,
        turn_id: str,
        session_id: str,
        *,
        status: str,
        result_text: str | None = None,
        cli_session_id: str | None = None,
        cost_usd: float | None = None,
        usage: dict[str, Any] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        current = self.repo_sessions.get_turn(turn_id)
        if current and current["status"] not in {
            "starting",
            "running",
            "canceling",
        }:
            return
        self.repo_sessions.finish_turn(
            turn_id,
            session_id,
            status,
            result_text=result_text,
            cli_session_id=cli_session_id,
            cost_usd=cost_usd,
            usage=usage,
            error_type=error_type,
            error_message=error_message,
            add_result_message=status == "succeeded",
        )
