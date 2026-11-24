from __future__ import annotations

import json
import subprocess
from typing import Any

from ..config import Settings


def probe_cli(settings: Settings) -> dict[str, Any]:
    """Best-effort CLI version/auth probe. Never raises."""
    info: dict[str, Any] = {
        "installed": False,
        "version": None,
        "auth_ok": None,
        "auth_method": None,
        "api_provider": None,
    }
    try:
        version = subprocess.run(
            [*settings.claude_command, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if version.returncode == 0:
            info["installed"] = True
            info["version"] = (version.stdout or "").strip().splitlines()[0][:200]
    except (OSError, subprocess.SubprocessError, IndexError):
        pass

    try:
        auth = subprocess.run(
            [*settings.claude_command, "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if auth.returncode == 0 and auth.stdout.strip():
            try:
                payload = json.loads(auth.stdout)
                info["auth_ok"] = bool(payload.get("loggedIn"))
                info["auth_method"] = payload.get("authMethod")
                info["api_provider"] = payload.get("apiProvider")
            except json.JSONDecodeError:
                pass
    except (OSError, subprocess.SubprocessError):
        pass
    return info
