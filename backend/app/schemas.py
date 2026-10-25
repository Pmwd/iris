from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    workspace_path: str = Field(min_length=1)
    brief_md: str = ""
    allowed_tools: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    workspace_path: str | None = Field(default=None, min_length=1)
    brief_md: str | None = None
    allowed_tools: list[str] | None = None
    archived: bool | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    goal_md: str = ""
    role: Literal["coding", "scholar", "mentor", "testing"] = "coding"
    source_task_id: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    goal_md: str | None = None


class RunStart(BaseModel):
    mode: Literal["new", "resume"] = "new"
    permission_profile: Literal[
        "read_only", "edit", "execute", "verify", "research"
    ] | None = None
    context_note_ids: list[str] | None = None


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content_md: str = ""
    aliases: list[str] = Field(default_factory=list)
    kind: Literal[
        "outcome",
        "decision",
        "note",
        "research",
        "goal",
        "capability",
        "blind_spot",
        "progress",
    ] = "outcome"
    status: Literal["draft", "accepted"] = "accepted"
    pinned: bool = False
    task_id: str | None = None
    source_run_id: str | None = None


class ResearchPlanCreate(BaseModel):
    allow_web: bool = False


class ResearchPlanUpdate(BaseModel):
    questions: list[str] = Field(default_factory=list)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content_md: str | None = None
    aliases: list[str] | None = None
    status: Literal["draft", "accepted", "archived"] | None = None
    pinned: bool | None = None


class GlobalNoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content_md: str = ""
    aliases: list[str] = Field(default_factory=list)
    kind: Literal[
        "outcome",
        "decision",
        "note",
        "research",
        "goal",
        "capability",
        "blind_spot",
        "progress",
    ] = "note"
    status: Literal["draft", "accepted"] = "accepted"
    pinned: bool = False


class GlobalNoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content_md: str | None = None
    aliases: list[str] | None = None
    status: Literal["draft", "accepted", "archived"] | None = None
    pinned: bool | None = None
