from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    SCHEMA_VERSION = 8

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.fts_enabled = False

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(schema)
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema version {version} is newer than Iris supports "
                    f"({self.SCHEMA_VERSION})"
                )
            if version < 2:
                self._migrate_v2(conn)
            if version < 3:
                self._migrate_v3(conn)
            else:
                self._setup_fts(conn)
            if version < 4:
                self._migrate_v4(conn)
            if version < 6:
                self._migrate_v6(conn)
            if version < 7:
                self._migrate_v7(conn)
            if version < 8:
                self._migrate_v8(conn)
            conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
        finally:
            conn.close()

    def _migrate_v2(self, conn: sqlite3.Connection) -> None:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()
        }
        additions = {
            "pinned": "INTEGER NOT NULL DEFAULT 0",
            "use_count": "INTEGER NOT NULL DEFAULT 0",
            "last_used_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE notes ADD COLUMN {name} {definition}")

    def _migrate_v3(self, conn: sqlite3.Connection) -> None:
        for table in ("notes", "global_notes"):
            columns = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "aliases_json" not in columns:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN aliases_json TEXT NOT NULL DEFAULT '[]'"
                )
        self._setup_fts(conn, force_rebuild=True)

    def _migrate_v4(self, conn: sqlite3.Connection) -> None:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "role" not in columns:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN role TEXT NOT NULL DEFAULT 'coding'"
            )
        if "source_task_id" not in columns:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN source_task_id TEXT "
                "REFERENCES tasks(id) ON DELETE SET NULL"
            )

    def _migrate_v6(self, conn: sqlite3.Connection) -> None:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(research_subtasks)"
            ).fetchall()
        }
        if "attempts" not in columns:
            conn.execute(
                "ALTER TABLE research_subtasks "
                "ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
            )

    def _migrate_v7(self, conn: sqlite3.Connection) -> None:
        # Schema v7 adds the session/memory tables. They are created by
        # schema.sql (CREATE IF NOT EXISTS); legacy tables are left untouched.
        # Re-run FTS setup so upgraded databases get facts_fts.
        self._setup_fts(conn)

    def _migrate_v8(self, conn: sqlite3.Connection) -> None:
        # Schema v8 adds turn_approvals and permission_rules (created by
        # schema.sql); no legacy data is modified.
        self._setup_fts(conn)

    def _setup_fts(
        self, conn: sqlite3.Connection, force_rebuild: bool = False
    ) -> None:
        try:
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
                USING fts5(note_id UNINDEXED, project_id UNINDEXED, title, content)
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS global_notes_fts
                USING fts5(note_id UNINDEXED, title, content)
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
                USING fts5(fact_id UNINDEXED, title, content)
                """
            )
            self.fts_enabled = True
            rebuild_notes = force_rebuild or "notes_fts" not in existing
            rebuild_global = force_rebuild or "global_notes_fts" not in existing
            if rebuild_notes:
                conn.execute("DELETE FROM notes_fts")
                for row in conn.execute(
                    "SELECT id, project_id, title, content_md, aliases_json FROM notes"
                ).fetchall():
                    aliases = json.loads(row[4] or "[]")
                    alias_text = " ".join(str(alias) for alias in aliases)
                    conn.execute(
                        """
                        INSERT INTO notes_fts(note_id, project_id, title, content)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            row[0],
                            row[1],
                            row[2],
                            row[3] + ("\n" + alias_text if alias_text else ""),
                        ),
                    )
            if rebuild_global:
                conn.execute("DELETE FROM global_notes_fts")
                for row in conn.execute(
                    "SELECT id, title, content_md, aliases_json FROM global_notes"
                ).fetchall():
                    aliases = json.loads(row[3] or "[]")
                    alias_text = " ".join(str(alias) for alias in aliases)
                    conn.execute(
                        """
                        INSERT INTO global_notes_fts(note_id, title, content)
                        VALUES (?, ?, ?)
                        """,
                        (row[0], row[1], row[2] + ("\n" + alias_text if alias_text else "")),
                    )
            rebuild_facts = force_rebuild or "facts_fts" not in existing
            if rebuild_facts:
                conn.execute("DELETE FROM facts_fts")
                for row in conn.execute(
                    "SELECT id, title, content_md, aliases_json FROM facts"
                ).fetchall():
                    aliases = json.loads(row[3] or "[]")
                    alias_text = " ".join(str(alias) for alias in aliases)
                    conn.execute(
                        """
                        INSERT INTO facts_fts(fact_id, title, content)
                        VALUES (?, ?, ?)
                        """,
                        (
                            row[0],
                            row[1],
                            row[2] + ("\n" + alias_text if alias_text else ""),
                        ),
                    )
        except sqlite3.OperationalError:
            self.fts_enabled = False

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid or cursor.rowcount

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        with self.transaction() as conn:
            conn.executemany(sql, rows)

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        conn = self.connect()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def query_all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        conn = self.connect()
        try:
            return list(conn.execute(sql, params).fetchall())
        finally:
            conn.close()

    def backup(self, destination: Path) -> None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
