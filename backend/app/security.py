from __future__ import annotations

from pathlib import Path

SENSITIVE_NAMES = {
    ".npmrc",
    ".pypirc",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "credentials",
    "credentials.json",
    "secrets.json",
}


def workspace_warnings(path: Path) -> list[str]:
    """Return non-blocking warnings for likely secret files in a workspace."""
    path = Path(path)
    if not path.is_dir():
        return []
    warnings: list[str] = []
    try:
        entries = list(path.iterdir())
    except OSError:
        return warnings

    for entry in entries:
        name = entry.name
        if name == ".env.example":
            continue
        sensitive = (
            name in SENSITIVE_NAMES
            or name == ".env"
            or name.startswith(".env.")
            or name.endswith((".pem", ".key", ".pfx", ".p12"))
        )
        if sensitive:
            warnings.append(
                f"检测到疑似敏感文件：{name}。任务可能读取它；请确认工作区内容允许发送给模型后端。"
            )
    for directory in (".ssh", ".aws", ".azure", ".config"):
        candidate = path / directory
        if candidate.is_dir():
            warnings.append(
                f"检测到敏感配置目录：{directory}/。建议将其排除在工作区之外或避免让任务读取。"
            )
    return warnings
