"""Deterministic stand-in for the Claude Code CLI used by backend tests."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def main() -> int:
    if "--version" in sys.argv:
        print("fake-cli 0.1")
        return 0
    if "auth" in sys.argv and "status" in sys.argv:
        print(
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "test",
                    "apiProvider": "fake",
                }
            )
        )
        return 0

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-p", "--print", dest="print_mode", action="store_true")
    parser.add_argument("--session-id")
    parser.add_argument("--resume")
    parser.add_argument("--permission-mode", default="default")
    parser.add_argument("--tools", default="")
    parser.add_argument("--output-format", default="text")
    parser.add_argument("--append-system-prompt")
    parser.add_argument("--safe-mode", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--max-turns")
    parser.add_argument("--allowedTools")
    args, _ = parser.parse_known_args()

    session = args.resume or args.session_id or str(uuid4())
    try:
        prompt = sys.stdin.read()
    except OSError:
        prompt = ""

    def emit(payload: dict) -> None:
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    if args.output_format == "json":
        if "Break the research goal" in prompt or "Return only a JSON object" in prompt:
            result = json.dumps(
                {
                    "questions": [
                        "What are the key facts and definitions?",
                        "What are the main open questions?",
                    ]
                }
            )
        elif "Synthesize" in prompt:
            result = (
                "## Known facts\nFake fact.\n\n"
                "## Personal opinions / interpretations\nFake opinion.\n\n"
                "## Unverified hypotheses\nFake hypothesis.\n\n"
                "## Sources\nFake source."
            )
        else:
            result = "FAKE_OK"
        emit(
            {
                "is_error": False,
                "result": result,
                "session_id": session,
                "num_turns": 1,
                "total_cost_usd": 0.001,
                "usage": {},
                "permission_denials": [],
                "subtype": "success",
                "terminal_reason": "completed",
                "api_error_status": None,
            }
        )
        return 0

    emit(
        {
            "type": "system",
            "subtype": "init",
            "session_id": session,
            "cwd": os.getcwd(),
            "model": "fake-cli",
            "permissionMode": args.permission_mode,
            "tools": args.tools.split(",") if args.tools else [],
            "skills": [],
            "plugins": [],
            "mcp_servers": [],
        }
    )

    if "FLAKY" in prompt:
        marker = Path("fake_flaky_count.txt")
        count = int(marker.read_text(encoding="utf-8")) if marker.exists() else 0
        marker.write_text(str(count + 1), encoding="utf-8")
        if count == 0:
            emit(
                {
                    "type": "result",
                    "subtype": "error",
                    "is_error": True,
                    "result": "Transient research failure.",
                    "session_id": session,
                    "num_turns": 1,
                    "total_cost_usd": 0,
                    "usage": {},
                    "permission_denials": [],
                    "terminal_reason": "api_error",
                    "api_error_status": 500,
                }
            )
            return 1
        result_text = "FAKE_RETRY_OK"
    elif "SLEEP" in prompt:
        emit(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_sleep",
                            "name": "PowerShell",
                            "input": {"command": "Start-Sleep -Seconds 60"},
                        }
                    ],
                },
                "session_id": session,
            }
        )
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        Path("fake_child.pid").write_text(str(child.pid), encoding="utf-8")
        child.wait()
        result_text = "FAKE_SLEEP_DONE"
    elif "EDIT" in prompt:
        emit(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_write",
                            "name": "Write",
                            "input": {
                                "file_path": str(Path.cwd() / "fake_output.txt"),
                                "content": "FAKE_EDIT_OK",
                            },
                        }
                    ],
                },
                "session_id": session,
            }
        )
        Path("fake_output.txt").write_text("FAKE_EDIT_OK", encoding="utf-8")
        emit(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_write",
                            "content": "File created",
                            "is_error": False,
                        }
                    ],
                },
                "session_id": session,
            }
        )
        result_text = "FAKE_EDIT_DONE"
    elif "MALFORMED" in prompt:
        print("this line is not json", flush=True)
        result_text = "FAKE_MALFORMED_OK"
    elif "FAIL" in prompt:
        emit(
            {
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "result": "FAKE_API_ERROR",
                "session_id": session,
                "num_turns": 1,
                "total_cost_usd": 0,
                "usage": {},
                "permission_denials": [],
                "terminal_reason": "api_error",
                "api_error_status": 400,
            }
        )
        return 1
    elif "NO_RESULT" in prompt:
        emit(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "NO RESULT"}],
                },
                "session_id": session,
            }
        )
        return 0
    elif "RECALL" in prompt:
        result_text = "FAKE_RECALL_OK"
    elif "FAKE_CONTEXT_MARKER" in prompt:
        result_text = "CONTEXT_SEEN"
    else:
        result_text = "FAKE_OK"

    emit(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": result_text}],
            },
            "session_id": session,
        }
    )
    emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": result_text,
            "session_id": session,
            "num_turns": 1,
            "total_cost_usd": 0.001,
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "permission_denials": [],
            "terminal_reason": "completed",
            "api_error_status": None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
