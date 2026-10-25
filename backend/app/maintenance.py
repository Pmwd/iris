from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_settings
from .db import Database


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def _metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def backup_database(db_path: Path, backup_dir: Path) -> dict[str, Any]:
    db_path = Path(db_path)
    backup_dir = Path(backup_dir)
    destination = backup_dir / f"iris-{_timestamp()}.db"
    Database(db_path).backup(destination)
    return _metadata(destination)


def list_backups(backup_dir: Path) -> list[dict[str, Any]]:
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    paths = sorted(
        backup_dir.glob("iris-*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [_metadata(path) for path in paths]


def _validate_backup(backup_path: Path) -> None:
    check = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"backup failed SQLite integrity_check: {integrity}")
        tables = {
            row[0]
            for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "projects" not in tables or "tasks" not in tables:
            raise ValueError("backup does not look like an Iris database")
    finally:
        check.close()


def restore_backup(db_path: Path, backup_path: Path) -> Path | None:
    """Restore a backup. The caller must stop the Iris server first."""
    db_path = Path(db_path)
    backup_path = Path(backup_path)
    if not backup_path.is_file():
        raise FileNotFoundError(backup_path)
    if backup_path.resolve() == db_path.resolve():
        raise ValueError("backup path and database path are the same")
    _validate_backup(backup_path)

    safety_copy = None
    if db_path.exists():
        safety_copy = db_path.parent / "backups" / f"pre-restore-{_timestamp()}.db"
        Database(db_path).backup(safety_copy)

    shutil.copy2(backup_path, db_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    return safety_copy


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Iris database maintenance")
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backup", help="create a backup")
    subparsers.add_parser("list", help="list backups")
    restore = subparsers.add_parser(
        "restore", help="restore a backup (stop the Iris server first)"
    )
    restore.add_argument("backup", type=Path)
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    db_path = data_dir / "iris.db"
    backup_dir = data_dir / "backups"

    if args.command == "backup":
        if not db_path.exists():
            print(f"database not found: {db_path}")
            return 1
        print(backup_database(db_path, backup_dir))
        return 0
    if args.command == "list":
        for item in list_backups(backup_dir):
            print(item)
        return 0
    if args.command == "restore":
        print("WARNING: stop the Iris server before restoring.")
        safety = restore_backup(db_path, args.backup)
        print(f"Restored {args.backup} -> {db_path}")
        if safety:
            print(f"Previous database saved at {safety}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
