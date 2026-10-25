from __future__ import annotations

from .conftest import HEADERS, create_project, create_task, wait_for_run


def _global(client, title, content, kind):
    response = client.post(
        "/api/global-notes",
        headers=HEADERS,
        json={
            "title": title,
            "content_md": content,
            "kind": kind,
            "status": "accepted",
            "pinned": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _mentor_task(client, project_id):
    response = client.post(
        f"/api/projects/{project_id}/tasks",
        headers=HEADERS,
        json={
            "title": "比较两种研究笔记落地方式",
            "goal_md": "比较两种研究笔记落地方式，指出盲点，不要替我决定。",
            "role": "mentor",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_mentor_role_and_typed_global_notes(app_client):
    client, workspace = app_client
    roles = {r["id"]: r for r in client.get("/api/roles").json()}
    assert roles["mentor"]["default_profile"] == "read_only"
    assert roles["mentor"]["allowed_profiles"] == ["read_only"]

    project = create_project(client, workspace)
    goal = _global(
        client,
        "长期目标",
        "提升个人研究能力，建立可复用的研究笔记方法。",
        "goal",
    )
    capability = _global(
        client,
        "当前能力",
        "能使用基本研究工具，但笔记结构不稳定。",
        "capability",
    )
    blind = _global(
        client,
        "研究盲点",
        "容易收集资料但不做每周复核，容易把文章观点当成事实。",
        "blind_spot",
    )
    assert {goal["kind"], capability["kind"], blind["kind"]} == {
        "goal",
        "capability",
        "blind_spot",
    }

    task = _mentor_task(client, project["id"])
    preview = client.get(f"/api/tasks/{task['id']}/context-preview").json()
    assert goal["id"] in preview["selected_note_ids"]
    assert capability["id"] in preview["selected_note_ids"]
    assert blind["id"] in preview["selected_note_ids"]

    response = client.post(
        f"/api/tasks/{task['id']}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": "read_only"},
    )
    assert response.status_code == 200, response.text
    run = wait_for_run(client, response.json()["id"])
    assert run["status"] == "succeeded", run
    assert run["context_manifest"]["role"] == "mentor"

    note = client.post(
        f"/api/projects/{project['id']}/notes",
        headers=HEADERS,
        json={
            "title": "Mentor progress",
            "content_md": "User accepted a staged direction.",
            "kind": "progress",
            "status": "accepted",
            "task_id": task["id"],
            "source_run_id": run["id"],
        },
    ).json()
    stage = client.post(
        f"/api/projects/{project['id']}/tasks",
        headers=HEADERS,
        json={
            "title": "执行第一阶段",
            "goal_md": "执行第一阶段任务。",
            "role": "coding",
            "source_task_id": task["id"],
        },
    ).json()
    stage_preview = client.get(
        f"/api/tasks/{stage['id']}/context-preview"
    ).json()
    selected = {
        n["id"]: n
        for n in stage_preview["notes"]
        if n["recommended"]
    }
    assert note["id"] in selected
    assert selected[note["id"]]["reason"] == "handoff"


def _run(client, task_id, profile="read_only"):
    response = client.post(
        f"/api/tasks/{task_id}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": profile},
    )
    assert response.status_code == 200, response.text
    return wait_for_run(client, response.json()["id"])


def test_mentor_state_is_explicit_and_role_scoped(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    state_notes = [
        _global(
            client,
            f"QZX-77 {kind}",
            f"ZZTOP-991 {kind} alpha-only state.",
            kind,
        )
        for kind in ("goal", "capability", "blind_spot", "progress", "decision")
    ]
    draft = client.post(
        "/api/global-notes",
        headers=HEADERS,
        json={
            "title": "Unaccepted state",
            "content_md": "Must not be injected.",
            "kind": "goal",
            "status": "draft",
        },
    ).json()

    mentor = _mentor_task(client, project["id"])
    preview = client.get(f"/api/tasks/{mentor['id']}/context-preview").json()
    notes = {note["id"]: note for note in preview["notes"]}
    for note in state_notes:
        assert note["id"] in preview["selected_note_ids"]
        assert notes[note["id"]]["reason"] == "mentor_state"
    assert draft["id"] not in preview["selected_note_ids"]

    coding = create_task(
        client,
        project["id"],
        "Unrelated coding work",
        "Nothing to do with the accepted long-term state.",
    )
    coding_preview = client.get(
        f"/api/tasks/{coding['id']}/context-preview"
    ).json()
    assert all(
        note["reason"] != "mentor_state" for note in coding_preview["notes"]
    )


def test_mentor_rejects_write_profiles(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    mentor = _mentor_task(client, project["id"])
    response = client.post(
        f"/api/tasks/{mentor['id']}/runs",
        headers=HEADERS,
        json={"mode": "new", "permission_profile": "edit"},
    )
    assert response.status_code == 422, response.text
    assert "not allowed" in response.text


def test_mentor_stage_and_followup_reuse_long_term_state(app_client):
    client, workspace = app_client
    project = create_project(client, workspace)
    goal = _global(
        client,
        "Durable research habit",
        "Build a weekly research review habit.",
        "goal",
    )
    capability = _global(
        client,
        "Current capability",
        "Can collect sources, but review cadence is unstable.",
        "capability",
    )
    blind = _global(
        client,
        "Recurring blind spot",
        "Skips weekly review and treats article claims as facts.",
        "blind_spot",
    )
    mentor = _mentor_task(client, project["id"])

    tasks_before = client.get(
        f"/api/projects/{project['id']}/tasks"
    ).json()
    global_before = client.get("/api/global-notes").json()

    mentor_run = _run(client, mentor["id"])
    assert mentor_run["status"] == "succeeded", mentor_run
    assert mentor_run["context_manifest"]["role"] == "mentor"
    assert mentor_run["context_manifest"]["mentor_state_note_count"] == 3

    # A Mentor run creates no long-term facts and no staged tasks on its own.
    assert len(client.get("/api/global-notes").json()) == len(global_before)
    assert (
        len(client.get(f"/api/projects/{project['id']}/tasks").json())
        == len(tasks_before)
    )

    # The user confirms a direction and records progress.
    decision = _global(
        client,
        "Selected direction",
        "Try option A for two weeks before choosing again.",
        "decision",
    )
    progress = _global(
        client,
        "First cycle progress",
        "Completed the first weekly review cycle.",
        "progress",
    )

    # The user manually creates a stage task based on the confirmed goal.
    stage = client.post(
        f"/api/projects/{project['id']}/tasks",
        headers=HEADERS,
        json={
            "title": "Stage 1: run the first review cycle",
            "goal_md": "Run the first weekly review cycle and record evidence.",
            "role": "coding",
            "source_task_id": mentor["id"],
        },
    ).json()
    stage_run = _run(client, stage["id"])
    assert stage_run["status"] == "succeeded", stage_run
    stage_note = client.post(
        f"/api/projects/{project['id']}/notes",
        headers=HEADERS,
        json={
            "title": "Stage 1 progress",
            "content_md": "First weekly review completed; two claims remain unverified.",
            "kind": "progress",
            "status": "accepted",
            "task_id": stage["id"],
            "source_run_id": stage_run["id"],
        },
    ).json()
    complete = client.post(
        f"/api/tasks/{stage['id']}/complete", headers=HEADERS
    )
    assert complete.status_code == 200, complete.text

    # A follow-up Mentor task is linked to the stage task. It sees both the
    # accepted global state and the stage progress via explicit handoff.
    follow = client.post(
        f"/api/projects/{project['id']}/tasks",
        headers=HEADERS,
        json={
            "title": "Follow-up Mentor review",
            "goal_md": "Review the stage progress and compare next options. Do not decide for me.",
            "role": "mentor",
            "source_task_id": stage["id"],
        },
    ).json()
    preview = client.get(
        f"/api/tasks/{follow['id']}/context-preview"
    ).json()
    notes = {note["id"]: note for note in preview["notes"]}
    for note in (goal, capability, blind, decision, progress):
        assert note["id"] in preview["selected_note_ids"]
        assert notes[note["id"]]["reason"] == "mentor_state"
    assert stage_note["id"] in preview["selected_note_ids"]
    assert notes[stage_note["id"]]["reason"] == "handoff"

    follow_run = _run(client, follow["id"])
    assert follow_run["status"] == "succeeded", follow_run
    assert follow_run["context_manifest"]["mentor_state_note_count"] == 5
    included = {
        note["id"]
        for note in follow_run["context_manifest"]["included_notes"]
    }
    assert progress["id"] in included
    assert stage_note["id"] in included
