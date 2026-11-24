from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from .text import build_search_text, normalize_fingerprint

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    SCHEMA_VERSION = 10

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
            if version < 9:
                self._migrate_v9(conn)
            if version < 10:
                self._migrate_v10(conn)
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

    def _migrate_v9(self, conn: sqlite3.Connection) -> None:
        # Schema v9 adds metric_rollups (created by schema.sql). It is derived
        # data and can be rebuilt at any time.
        self._setup_fts(conn)

    def _migrate_v10(self, conn: sqlite3.Connection) -> None:
        """Memory 2.0: provenance, validity, pre-tokenized FTS, auto-capture."""
        fact_additions = {
            "tags_json": "TEXT NOT NULL DEFAULT '[]'",
            "origin": "TEXT NOT NULL DEFAULT 'manual'",
            "extraction_id": "TEXT",
            "source_turn_id": "TEXT",
            "valid_until": "TEXT",
            "last_confirmed_at": "TEXT",
            "superseded_by_id": "TEXT",
            "merged_into_id": "TEXT",
            "fingerprint": "TEXT",
            "search_text": "TEXT NOT NULL DEFAULT ''",
        }
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(facts)").fetchall()
        }
        for name, definition in fact_additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE facts ADD COLUMN {name} {definition}")

        extraction_additions = {
            "trigger": "TEXT NOT NULL DEFAULT 'manual'",
            "source_session_id": "TEXT",
            "source_summary_id": "TEXT",
        }
        extraction_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(fact_extractions)").fetchall()
        }
        for name, definition in extraction_additions.items():
            if name not in extraction_columns:
                conn.execute(
                    f"ALTER TABLE fact_extractions ADD COLUMN {name} {definition}"
                )

        for statement in (
            "CREATE INDEX IF NOT EXISTS idx_facts_fingerprint ON facts(fingerprint)",
            "CREATE INDEX IF NOT EXISTS idx_facts_review ON facts(status, reviewed_at, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_facts_validity ON facts(status, valid_until)",
            "CREATE INDEX IF NOT EXISTS idx_facts_extraction ON facts(extraction_id)",
            "CREATE INDEX IF NOT EXISTS idx_facts_source_turn ON facts(source_turn_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_extractions_summary "
            "ON fact_extractions(source_summary_id) "
            "WHERE source_summary_id IS NOT NULL AND trigger = 'session_end'",
        ):
            conn.execute(statement)

        rows = conn.execute("SELECT * FROM facts").fetchall()
        for row in rows:
            data = dict(row)
            aliases = data.get("aliases_json") or "[]"
            try:
                alias_list = json.loads(aliases)
            except (json.JSONDecodeError, TypeError):
                alias_list = []
            tags = data.get("tags_json") or "[]"
            try:
                tag_list = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tag_list = []
            fingerprint = normalize_fingerprint(
                data.get("title") or "",
                data.get("kind") or "",
                data.get("scope") or "",
                data.get("project_id"),
            )
            search_text = build_search_text(
                data.get("title") or "",
                data.get("content_md") or "",
                alias_list,
                tag_list,
            )
            origin = data.get("origin") or "manual"
            if origin == "manual" and data.get("extracted_at"):
                origin = "extraction"
            last_confirmed = data.get("last_confirmed_at")
            if not last_confirmed and data.get("status") == "accepted":
                last_confirmed = data.get("reviewed_at") or data.get("updated_at")
            superseded_by = conn.execute(
                """
                SELECT id FROM facts
                WHERE supersedes_id = ? AND id != ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (data["id"], data["id"]),
            ).fetchone()
            conn.execute(
                """
                UPDATE facts
                SET fingerprint = ?, search_text = ?, origin = ?,
                    last_confirmed_at = ?, superseded_by_id = ?
                WHERE id = ?
                """,
                (
                    fingerprint,
                    search_text,
                    origin,
                    last_confirmed,
                    superseded_by[0] if superseded_by else None,
                    data["id"],
                ),
            )

        # The v9 FTS schema indexed raw text with the default tokenizer. Rebuild
        # it with the shared pre-tokenized representation.
        conn.execute("DROP TABLE IF EXISTS facts_fts")
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
                USING fts5(fact_id UNINDEXED, search_text)
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
                    "SELECT id, search_text FROM facts"
                ).fetchall():
                    conn.execute(
                        """
                        INSERT INTO facts_fts(fact_id, search_text)
                        VALUES (?, ?)
                        """,
                        (row[0], row[1] or ""),
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
