from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from ..repository import Repository
from ..roles import get_role
from ..text import query_terms


def _terms(text: str) -> list[str]:
    return query_terms(text)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _recency_score(note: dict[str, Any]) -> float:
    stamp = _parse_time(note.get("updated_at") or note.get("accepted_at"))
    if stamp is None:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    days = max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds() / 86400)
    if days <= 30:
        return 12.0
    if days <= 90:
        return 6.0
    if days <= 365:
        return 2.0
    return 0.0


def _contains(text: str, term: str) -> bool:
    if term.isascii():
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def _aliases_text(note: dict[str, Any]) -> str:
    return " ".join(str(alias) for alias in note.get("aliases") or []).lower()


def _substring_score(note: dict[str, Any], terms: Iterable[str]) -> float:
    title = (note.get("title") or "").lower()
    content = (note.get("content_md") or "").lower()
    aliases = _aliases_text(note)
    score = 0.0
    for term in terms:
        if _contains(title, term):
            score += 8
        if _contains(aliases, term):
            score += 4
        if _contains(content, term):
            score += 2
    return score


def _hit_map(hits: list[dict[str, Any]]) -> dict[str, int]:
    return {note["id"]: index for index, note in enumerate(hits)}


def recommend_context(
    project: dict[str, Any],
    task: dict[str, Any],
    project_notes: list[dict[str, Any]],
    global_notes: list[dict[str, Any]],
    project_hits: list[dict[str, Any]],
    global_hits: list[dict[str, Any]],
    budget_chars: int,
    state_kinds: Iterable[str] = (),
) -> dict[str, Any]:
    query = f"{task.get('title', '')}\n{task.get('goal_md', '')}"
    terms = _terms(query)
    hit_index = {**_hit_map(project_hits), **_hit_map(global_hits)}
    state_kind_set = set(state_kinds)

    candidates: list[dict[str, Any]] = []
    for note in [*project_notes, *global_notes]:
        note = dict(note)
        note.setdefault("scope", "project")
        handoff = bool(note.get("handoff"))
        # Mentor state is an explicit role policy: accepted typed global notes
        # are long-term state, not inferred facts. They stay eligible even when
        # the current task wording does not match them.
        mentor_state = (
            note.get("scope") == "global"
            and note.get("status", "accepted") == "accepted"
            and note.get("kind") in state_kind_set
        )
        rank_index = hit_index.get(note["id"])
        # FTS/Chinese tokenization can be fuzzy. Eligibility is decided by a
        # concrete local term match, an explicit task handoff, or user selection.
        searchable = " ".join(
            [
                (note.get("title") or "").lower(),
                (note.get("content_md") or "").lower(),
                _aliases_text(note),
            ]
        )
        local_matches = [
            term for term in terms if _contains(searchable, term)
        ]
        matched = bool(local_matches) or handoff or mentor_state
        score = (
            _substring_score(note, terms)
            + _recency_score(note)
            + min(int(note.get("use_count", 0)), 20) * 1.5
        )
        if handoff:
            score += 900
        if mentor_state:
            score += 800
        if rank_index is not None and matched:
            score += 300 - min(rank_index, 50) * 4
        if note.get("pinned"):
            score += 1000
        note["search_rank"] = rank_index
        note["matched"] = matched
        note["handoff"] = handoff
        note["mentor_state"] = mentor_state
        note["score"] = round(score, 2)
        note["recommended"] = False
        note["reason"] = "not_relevant"
        candidates.append(note)

    candidates.sort(
        key=lambda note: (
            0 if note.get("mentor_state") else 1,
            0 if note.get("pinned") else 1,
            0 if note.get("matched") else 1,
            note.get("search_rank") if note.get("search_rank") is not None else 999,
            -float(note.get("score", 0)),
            note.get("updated_at") or "",
        )
    )

    note_budget = max(0, budget_chars - 1200)
    selected_ids: list[str] = []
    selected_chars = 0
    matched_selected = False

    for note in candidates:
        # Pinned is a ranking signal, not an unconditional injection rule.
        # A note must be relevant to the current task to be auto-selected.
        if not note.get("matched"):
            continue
        note_size = len(note.get("title", "")) + len(note.get("content_md", "")) + 24
        if selected_chars + note_size > note_budget:
            note["reason"] = "budget"
            continue
        note["recommended"] = True
        if note.get("handoff"):
            note["reason"] = "handoff"
        elif note.get("mentor_state"):
            note["reason"] = "mentor_state"
        elif note.get("pinned"):
            note["reason"] = "pinned"
        else:
            note["reason"] = "matched"
        selected_ids.append(note["id"])
        selected_chars += note_size
        matched_selected = True

    if not matched_selected:
        # Give broad tasks a small continuity fallback: recent project notes.
        recent = [
            note
            for note in candidates
            if note.get("scope") == "project"
            and not note.get("pinned")
            and not note.get("recommended")
        ]
        added = 0
        for note in recent:
            note_size = len(note.get("title", "")) + len(note.get("content_md", "")) + 24
            if selected_chars + note_size > note_budget or added >= 2:
                continue
            note["recommended"] = True
            note["reason"] = "recent"
            selected_ids.append(note["id"])
            selected_chars += note_size
            added += 1

    candidates.sort(
        key=lambda note: (
            0 if note.get("recommended") else 1,
            0 if note.get("pinned") else 1,
            -float(note.get("score", 0)),
            note.get("updated_at") or "",
        )
    )

    return {
        "notes": candidates,
        "selected_note_ids": selected_ids,
        "selected_chars": selected_chars,
        "budget_chars": budget_chars,
        "budget_tokens": max(1, budget_chars // 4),
        "estimated_tokens": max(1, math.ceil((selected_chars + 1200) / 4)),
        "query_terms": terms,
    }


def collect_candidates(
    repo: Repository,
    project: dict[str, Any],
    task: dict[str, Any],
    budget_chars: int,
) -> dict[str, Any]:
    query = f"{task.get('title', '')}\n{task.get('goal_md', '')}"
    project_notes = repo.accepted_notes(project["id"])
    by_id = {note["id"]: note for note in project_notes}
    source_task_id = task.get("source_task_id")
    if source_task_id:
        for note in repo.accepted_notes_for_task(source_task_id):
            existing = by_id.get(note["id"])
            if existing is not None:
                existing["handoff"] = True
            else:
                note = dict(note)
                note["handoff"] = True
                project_notes.append(note)
                by_id[note["id"]] = note
    global_notes = repo.accepted_global_notes()
    project_hits = repo.search_project_notes(project["id"], query)
    global_hits = repo.search_global_notes(query)
    role = get_role(task.get("role"))
    return recommend_context(
        project,
        task,
        project_notes,
        global_notes,
        project_hits,
        global_hits,
        budget_chars,
        state_kinds=role.state_kinds,
    )
