from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    claude_command: list[str]
    host: str = "127.0.0.1"
    port: int = 8000
    max_turns: int = 30
    run_timeout_seconds: int = 1800
    max_context_chars: int = 16000
    max_event_payload_chars: int = 20000
    sse_poll_seconds: float = 0.25
    research_max_subtasks: int = 5
    research_concurrency: int = 2
    research_subtask_max_turns: int = 8
    research_subtask_timeout_seconds: int = 600
    research_subtask_max_attempts: int = 3
    research_subtask_backoff_seconds: int = 2
    # Three-layer memory (schema v7).
    summary_trigger_turns: int = 8
    summary_trigger_chars: int = 24000
    summary_input_max_chars: int = 30000
    summary_max_turns: int = 2
    summary_timeout_seconds: int = 180
    extraction_max_sessions: int = 8
    extraction_input_max_chars: int = 40000
    extraction_max_turns: int = 2
    extraction_timeout_seconds: int = 180
    memory_concurrency: int = 1
    fact_context_max_chars: int = 4000
    # Execution backend: "sdk" (Claude Agent SDK, interactive approvals) or
    # "cli" (legacy one-shot stream-json runner; used by tests/fake CLI).
    execution_backend: str = "sdk"
    claude_cli_path: str | None = None
    approval_timeout_seconds: int = 600


def _default_claude_command() -> list[str]:
    executable = shutil.which("claude")
    return [executable] if executable else ["claude"]


def load_settings() -> Settings:
    data_dir = Path(
        os.environ.get("IRIS_DATA_DIR", str(PROJECT_ROOT / "data"))
    ).expanduser().resolve()

    raw_command = os.environ.get("IRIS_CLAUDE_COMMAND_JSON")
    if raw_command:
        try:
            command = json.loads(raw_command)
        except json.JSONDecodeError as exc:
            raise ValueError("IRIS_CLAUDE_COMMAND_JSON must be valid JSON") from exc
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            raise ValueError("IRIS_CLAUDE_COMMAND_JSON must be a non-empty list of strings")
    else:
        command = _default_claude_command()

    def _int_env(name: str, default: int) -> int:
        value = os.environ.get(name)
        return int(value) if value else default

    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "iris.db",
        claude_command=command,
        host=os.environ.get("IRIS_HOST", "127.0.0.1"),
        port=_int_env("IRIS_PORT", 8000),
        max_turns=_int_env("IRIS_MAX_TURNS", 30),
        run_timeout_seconds=_int_env("IRIS_RUN_TIMEOUT_SECONDS", 1800),
        max_context_chars=_int_env("IRIS_MAX_CONTEXT_CHARS", 16000),
        max_event_payload_chars=_int_env("IRIS_MAX_EVENT_PAYLOAD_CHARS", 20000),
        research_max_subtasks=_int_env("IRIS_RESEARCH_MAX_SUBTASKS", 5),
        research_concurrency=_int_env("IRIS_RESEARCH_CONCURRENCY", 2),
        research_subtask_max_turns=_int_env("IRIS_RESEARCH_SUBTASK_MAX_TURNS", 8),
        research_subtask_timeout_seconds=_int_env(
            "IRIS_RESEARCH_SUBTASK_TIMEOUT_SECONDS", 600
        ),
        research_subtask_max_attempts=_int_env(
            "IRIS_RESEARCH_SUBTASK_MAX_ATTEMPTS", 3
        ),
        research_subtask_backoff_seconds=_int_env(
            "IRIS_RESEARCH_SUBTASK_BACKOFF_SECONDS", 2
        ),
        summary_trigger_turns=_int_env("IRIS_SUMMARY_TRIGGER_TURNS", 8),
        summary_trigger_chars=_int_env("IRIS_SUMMARY_TRIGGER_CHARS", 24000),
        summary_input_max_chars=_int_env("IRIS_SUMMARY_INPUT_MAX_CHARS", 30000),
        summary_max_turns=_int_env("IRIS_SUMMARY_MAX_TURNS", 2),
        summary_timeout_seconds=_int_env("IRIS_SUMMARY_TIMEOUT_SECONDS", 180),
        extraction_max_sessions=_int_env("IRIS_EXTRACTION_MAX_SESSIONS", 8),
        extraction_input_max_chars=_int_env("IRIS_EXTRACTION_INPUT_MAX_CHARS", 40000),
        extraction_max_turns=_int_env("IRIS_EXTRACTION_MAX_TURNS", 2),
        extraction_timeout_seconds=_int_env("IRIS_EXTRACTION_TIMEOUT_SECONDS", 180),
        memory_concurrency=_int_env("IRIS_MEMORY_CONCURRENCY", 1),
        fact_context_max_chars=_int_env("IRIS_FACT_CONTEXT_MAX_CHARS", 4000),
        execution_backend=os.environ.get("IRIS_EXECUTION_BACKEND", "sdk").strip().lower(),
        claude_cli_path=os.environ.get("IRIS_CLAUDE_CLI_PATH") or None,
        approval_timeout_seconds=_int_env("IRIS_APPROVAL_TIMEOUT_SECONDS", 600),
    )


def resolve_claude_executable(settings: Settings) -> Path | None:
    """Resolve the native Claude Code executable the Agent SDK can spawn.

    The Agent SDK on Windows expects ``claude.exe``; npm's ``claude.cmd`` shim
    is not accepted. We derive the packaged .exe from the shim when possible.
    """
    if settings.claude_cli_path:
        path = Path(settings.claude_cli_path).expanduser()
        return path if path.is_file() else None

    candidate = shutil.which("claude.exe")
    if candidate:
        return Path(candidate)

    candidate = shutil.which("claude")
    if candidate:
        path = Path(candidate)
        if path.suffix.lower() in {".cmd", ".bat"}:
            exe = (
                path.parent
                / "node_modules"
                / "@anthropic-ai"
                / "claude-code"
                / "bin"
                / "claude.exe"
            )
            if exe.is_file():
                return exe
        if path.is_file():
            return path

    if settings.claude_command:
        first = Path(settings.claude_command[0])
        if first.name.lower().startswith("claude") and first.is_file():
            return first
    return None
