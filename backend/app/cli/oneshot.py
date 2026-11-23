from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import Settings


class OneShotError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class OneShotResult:
    text: str
    cost_usd: float | None = None
    usage: dict[str, Any] = field(default_factory=dict)


def run_oneshot(
    settings: Settings,
    system_instruction: str,
    prompt: str,
    *,
    cwd: Path | None = None,
    max_turns: int = 2,
    timeout: int = 180,
) -> OneShotResult:
    """Run a single, tool-less CLI call and return its JSON result text.

    Used by the memory pipeline (session summaries and fact extraction). The
    ``--tools ""`` flag removes file/web tools so the call only reasons over
    the prompt we provide. A fresh session id is used for every call.
    """
    command = [
        *settings.claude_command,
        "-p",
        "--output-format",
        "json",
        "--safe-mode",
        "--append-system-prompt",
        system_instruction,
        "--max-turns",
        str(max_turns),
        "--tools",
        "",
        "--session-id",
        str(uuid4()),
    ]
    try:
        process = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise OneShotError("Memory call timed out.", 504) from exc
    except OSError as exc:
        raise OneShotError(f"Could not start the CLI: {exc}", 502) from exc

    stdout = (process.stdout or "").strip()
    if not stdout:
        detail = (process.stderr or "").strip()[:2000]
        raise OneShotError(
            f"The CLI exited without output (code {process.returncode}). {detail}".strip(),
            502,
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise OneShotError(
            f"The CLI returned non-JSON output: {stdout[:500]}", 502
        ) from exc
    if not isinstance(payload, dict):
        raise OneShotError("The CLI returned an unexpected payload.", 502)
    if payload.get("is_error"):
        raise OneShotError(
            str(payload.get("result") or "The CLI reported an error."), 502
        )
    result = payload.get("result")
    if not isinstance(result, str) or not result.strip():
        raise OneShotError("The CLI returned an empty result.", 502)
    cost = payload.get("total_cost_usd")
    usage = payload.get("usage")
    return OneShotResult(
        text=result.strip(),
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        usage=usage if isinstance(usage, dict) else {},
    )
