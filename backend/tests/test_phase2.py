from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import Database
from app.services.context import build_context
from app.services.retrieval import recommend_context

from .conftest import HEADERS, create_project, create_task, wait_for_run


def _note(client, project_id: str, title: str, content: str, **extra):
    response = client.post(
        f"/api/projects/{project_id}/notes",
        headers=HEADERS,
        json={
            "title": title,
            "content_md": content,
            "status": "accepted",
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _global_note(client, title: str, content: str, **extra):
    response = client.post(
        "/api/global-notes",
        headers=HEADERS,
        json={"title": title, "content_md": content, "status": "accepted", **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_global_context_is_recommended_and_used(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    relevant = _note(
        client,
        project["id"],
        "CSV export implementation",
        "CSV export uses the date,category,amount,note header and export_expenses().",
    )
    pinned = _note(
        client,
        project["id"],
        "CSV export preference",
        "Always use the Python standard library for CSV export.",
        pinned=True,
    )
    irrelevant = _note(
        client,
        project["id"],
        "Lunch recipe",
        "Pasta with tomato and basil.",
    )
    global_note = _global_note(
        client,
        "CSV export global convention",
        "CSV export should keep a stable header across projects.",
    )
    task = create_task(
        client,
        project["id"],
        "Add date filtering to CSV export",
        "Extend CSV export with inclusive date bounds and tests.",
    )

    preview = client.get(f"/api/tasks/{task['id']}/context-preview").json()
    by_id = {note["id"]: note for note in preview["notes"]}
    selected = set(preview["selected_note_ids"])
    assert relevant["id"] in selected
    assert pinned["id"] in selected
    assert global_note["id"] in selected
    assert irrelevant["id"] not in selected
    assert by_id[relevant["id"]]["scope"] == "project"
    assert by_id[relevant["id"]]["reason"] == "matched"
    assert by_id[pinned["id"]]["reason"] == "pinned"
    assert by_id[global_note["id"]]["scope"] == "global"
    assert preview["budget_tokens"] > 0
    assert preview["estimated_tokens"] > 0

    response = client.post(
        f"/api/tasks/{task['id']}/runs",
        headers=HEADERS,
        json={
            "mode": "new",
            "permission_profile": "read_only",
            "context_note_ids": [relevant["id"], global_note["id"]],
        },
    )
    assert response.status_code == 200, response.text
    run = wait_for_run(client, response.json()["id"])
    assert run["status"] == "succeeded", run
    assert run["context_manifest"]["selection_mode"] == "manual"
    included = run["context_manifest"]["included_notes"]
    assert {note["scope"] for note in included} == {"project", "global"}

    project_notes = client.get(f"/api/projects/{project['id']}/notes").json()
    used = {note["id"]: note["use_count"] for note in project_notes}
    assert used[relevant["id"]] == 1
    assert used[pinned["id"]] == 0
    globals_after = client.get("/api/global-notes").json()
    assert next(n for n in globals_after if n["id"] == global_note["id"])["use_count"] == 1


def test_pinned_global_notes_require_relevance(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    fitness = _global_note(
        client,
        "健身偏好",
        "用户当前偏好全身锻炼，而不是腿、背等单一部位分化。",
        pinned=True,
    )
    reading = _global_note(
        client,
        "阅读偏好",
        "用户更喜欢文笔优秀的、偏言情类的文字。",
        pinned=True,
    )
    previous = _note(
        client,
        project["id"],
        "本周水果清单",
        "本周水果采购清单，包含当季水果和预算。",
    )
    task = create_task(
        client,
        project["id"],
        "本周全身训练计划",
        "安排本周 3 次健身训练，每次 30 分钟。",
    )
    preview = client.get(f"/api/tasks/{task['id']}/context-preview").json()
    selected = set(preview["selected_note_ids"])
    assert fitness["id"] in selected
    assert reading["id"] not in selected
    assert previous["id"] not in selected

    # Explicit selection must still allow an otherwise non-matching note.
    response = client.post(
        f"/api/tasks/{task['id']}/runs",
        headers=HEADERS,
        json={
            "mode": "new",
            "permission_profile": "read_only",
            "context_note_ids": [reading["id"]],
        },
    )
    assert response.status_code == 200, response.text
    run = wait_for_run(client, response.json()["id"])
    assert run["status"] == "succeeded", run
    assert [note["id"] for note in run["context_manifest"]["included_notes"]] == [
        reading["id"]
    ]


def test_generic_preference_word_does_not_select_every_global_note(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    fruit = _global_note(
        client, "水果偏好", "喜欢蓝莓和苹果，芒果过敏。", pinned=True
    )
    fitness = _global_note(
        client, "健身偏好", "偏好全身锻炼。", pinned=True
    )
    reading = _global_note(
        client, "阅读偏好", "喜欢文笔优秀的言情文字。", pinned=True
    )
    _note(
        client,
        project["id"],
        "水果清单",
        "本周水果采购清单，好的，理由是当季水果。",
    )
    task = create_task(
        client,
        project["id"],
        "推荐三本符合偏好的书",
        "推荐 3 本符合我阅读偏好的书，说明推荐理由。",
    )
    preview = client.get(f"/api/tasks/{task['id']}/context-preview").json()
    selected = set(preview["selected_note_ids"])
    assert reading["id"] in selected
    assert fruit["id"] not in selected
    assert fitness["id"] not in selected


def test_note_aliases_improve_paraphrase_recall(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    note = _global_note(
        client,
        "饮食禁忌",
        "对芒果严重过敏，任何含芒果的食品都不要。",
        aliases=["安全", "聚会", "身体不适"],
    )
    assert note["aliases"] == ["安全", "聚会", "身体不适"]
    task = create_task(
        client,
        project["id"],
        "聚会食物安全",
        "为聚会准备一份安全的食物，避免身体不适。",
    )
    preview = client.get(f"/api/tasks/{task['id']}/context-preview").json()
    selected = {item["id"] for item in preview["notes"] if item["recommended"]}
    assert note["id"] in selected
    assert next(
        item for item in preview["notes"] if item["id"] == note["id"]
    )["reason"] == "matched"


def test_global_note_crud_and_pinning(app_client):
    client, _ = app_client
    note = _global_note(client, "Preference", "Be concise.", pinned=True)
    assert note["scope"] == "global"
    assert note["pinned"] is True

    updated = client.patch(
        f"/api/global-notes/{note['id']}",
        headers=HEADERS,
        json={"pinned": False, "status": "archived", "content_md": "Be very concise."},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["pinned"] is False
    assert updated.json()["status"] == "archived"

    deleted = client.delete(f"/api/global-notes/{note['id']}", headers=HEADERS)
    assert deleted.status_code == 200
    assert client.get("/api/global-notes").json() == []


def test_project_note_pin_update(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    note = _note(client, project["id"], "Pinned", "Remember this.")
    response = client.patch(
        f"/api/notes/{note['id']}",
        headers=HEADERS,
        json={"pinned": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["pinned"] is True


def test_recommendation_budget_excludes_large_notes():
    project = {"workspace_path": "C:/workspace", "brief_md": ""}
    task = {"title": "CSV export", "goal_md": "date filter"}
    huge = {
        "id": "huge",
        "title": "Huge",
        "content_md": "CSV export " + ("x" * 5000),
        "status": "accepted",
        "scope": "project",
        "pinned": True,
        "use_count": 0,
        "updated_at": "2026-10-23T00:00:00+00:00",
    }
    result = recommend_context(
        project,
        task,
        [huge],
        [],
        [{"id": "huge", "search_rank": 0}],
        [],
        budget_chars=600,
    )
    assert result["selected_note_ids"] == []
    assert result["notes"][0]["reason"] == "budget"


def test_deleted_note_is_removed_from_recommendations(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    note = _note(
        client,
        project["id"],
        "CSV export decision",
        "CSV export uses a stable header.",
    )
    task = create_task(
        client, project["id"], "CSV export follow-up", "Extend CSV export."
    )
    preview = client.get(f"/api/tasks/{task['id']}/context-preview").json()
    assert note["id"] in preview["selected_note_ids"]

    deleted = client.delete(f"/api/notes/{note['id']}", headers=HEADERS)
    assert deleted.status_code == 200
    after = client.get(f"/api/tasks/{task['id']}/context-preview").json()
    assert note["id"] not in after["selected_note_ids"]
    assert all(item["id"] != note["id"] for item in after["notes"])
    repo = client.app.state.repo
    assert repo.search_project_notes(project["id"], "CSV export") == []


def test_chinese_search_falls_back_to_like(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    note = _note(
        client,
        project["id"],
        "导出约定",
        "CSV 导出需要保留日期范围过滤和表头。",
    )
    repo = client.app.state.repo
    hits = repo.search_project_notes(project["id"], "日期")
    assert [hit["id"] for hit in hits] == [note["id"]]


def test_v1_database_migrates_to_fts(tmp_path: Path):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE notes (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                task_id TEXT,
                source_run_id TEXT,
                kind TEXT,
                status TEXT,
                title TEXT,
                content_md TEXT,
                created_at TEXT,
                updated_at TEXT,
                accepted_at TEXT
            );
            PRAGMA user_version = 1;
            """
        )
        conn.commit()
    finally:
        conn.close()

    database = Database(db_path)
    database.init()
    assert database.fts_enabled is True
    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
        assert {
            "pinned",
            "use_count",
            "last_used_at",
            "aliases_json",
        } <= columns
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        subtask_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(research_subtasks)")
        }
        assert "attempts" in subtask_columns
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='global_notes'"
        ).fetchone()[0] == 1
        task_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(tasks)")
        }
        assert {"role", "source_task_id"} <= task_columns
        research_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'research_%'"
            )
        }
        assert {"research_jobs", "research_subtasks", "research_events"} <= research_tables
    finally:
        conn.close()


def test_context_builder_marks_global_scope():
    project = {"workspace_path": "C:/workspace", "brief_md": ""}
    task = {"title": "Task", "goal_md": "Goal"}
    note = {
        "id": "g1",
        "title": "Global preference",
        "content_md": "Use concise responses.",
        "status": "accepted",
        "scope": "global",
        "reason": "pinned",
        "updated_at": "now",
    }
    pack = build_context(project, task, [note], ["g1"], 4000)
    assert "[Global]" in pack.prompt
    assert pack.manifest["included_notes"][0]["scope"] == "global"
    assert pack.manifest["estimated_tokens"] > 0
