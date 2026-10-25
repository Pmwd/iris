from __future__ import annotations

import json
from typing import Any

from ..config import Settings

BASE_SYSTEM_PROMPT = (
    "You are the execution backend for a task in Iris. "
    "Stay within the scope of the task, do not claim work you did not perform, "
    "and report changes, tests, blockers, and key decisions. "
    "Do not read or print secrets; avoid .env, credential, key, and token files "
    "unless the task explicitly requires them."
)

PROFILE_TOOLS = {
    "read_only": "Read,Glob,Grep",
    "edit": "Read,Glob,Grep,Write,Edit",
    "execute": "Read,Glob,Grep,Write,Edit,PowerShell",
    "verify": "Read,Glob,Grep,PowerShell",
    "research": "Read,Glob,Grep,WebSearch,WebFetch",
}

BASE_ALLOWED_FOR_EXECUTE = ["Read", "Glob", "Grep", "Write", "Edit"]
BASE_ALLOWED_FOR_VERIFY = ["Read", "Glob", "Grep"]
BASE_ALLOWED_FOR_RESEARCH = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]


def build_command(
    settings: Settings,
    session_id: str,
    mode: str,
    profile: str,
    allowed_tools: list[str],
    role_instruction: str = "",
    max_turns: int | None = None,
) -> list[str]:
    # The prompt is written to stdin by ProcessSupervisor. Passing a multi-line
    # prompt as an argument through the npm .cmd wrapper corrupts the command
    # line on Windows and can make the CLI lose both the task and later flags.
    # Do not stack the base and role prompts: the CLI/endpoint can misclassify
    # PowerShell permissions when both are appended together. A role prompt is
    # self-contained and replaces the generic base prompt.
    system_prompt = role_instruction.strip() or BASE_SYSTEM_PROMPT
    command = [
        *settings.claude_command,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--safe-mode",
        "--append-system-prompt",
        system_prompt,
        "--max-turns",
        str(max_turns or settings.max_turns),
        "--tools",
        PROFILE_TOOLS[profile],
    ]

    if mode == "resume":
        command.extend(["--resume", session_id])
    else:
        command.extend(["--session-id", session_id])

    if profile in {"execute", "verify", "research"}:
        if profile == "verify":
            base_allowed = BASE_ALLOWED_FOR_VERIFY
        elif profile == "research":
            base_allowed = BASE_ALLOWED_FOR_RESEARCH
        else:
            base_allowed = BASE_ALLOWED_FOR_EXECUTE
        permitted = [*base_allowed]
        if profile != "research":
            permitted.extend(allowed_tools)
        # Preserve order while removing duplicates.
        permitted = list(dict.fromkeys(tool for tool in permitted if tool))
        command.extend(
            [
                "--permission-mode",
                "dontAsk",
                "--allowedTools",
                ",".join(permitted),
            ]
        )
    else:
        command.extend(["--permission-mode", "acceptEdits"])

    return command


def _payload(value: Any, max_chars: int) -> tuple[Any, bool]:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= max_chars:
        return value, False
    return {"truncated": True, "preview": text[:max_chars]}, True


def normalize_event(
    event: dict[str, Any], max_chars: int
) -> list[tuple[str, Any, bool]]:
    event_type = event.get("type")

    if event_type == "system":
        if event.get("subtype") == "thinking_tokens":
            return []
        payload, truncated = _payload(event, max_chars)
        return [("system.init", payload, truncated)]

    if event_type == "assistant":
        results: list[tuple[str, Any, bool]] = []
        content = event.get("message", {}).get("content", [])
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type in {"thinking", "redacted_thinking"}:
                    continue
                if block_type == "text":
                    text = block.get("text", "")
                    if text:
                        payload, truncated = _payload({"text": text}, max_chars)
                        results.append(("assistant.text", payload, truncated))
                elif block_type == "tool_use":
                    payload, truncated = _payload(
                        {
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "input": block.get("input", {}),
                        },
                        max_chars,
                    )
                    results.append(("tool.use", payload, truncated))
                else:
                    payload, truncated = _payload(block, max_chars)
                    results.append(("assistant.block", payload, truncated))
        return results

    if event_type == "user":
        results = []
        content = event.get("message", {}).get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    payload, truncated = _payload(
                        {
                            "tool_use_id": block.get("tool_use_id"),
                            "content": block.get("content"),
                            "is_error": bool(block.get("is_error")),
                        },
                        max_chars,
                    )
                    results.append(("tool.result", payload, truncated))
        return results

    if event_type == "result":
        payload, truncated = _payload(event, max_chars)
        return [("run.result", payload, truncated)]

    payload, truncated = _payload(event, max_chars)
    return [("cli.event", payload, truncated)]
