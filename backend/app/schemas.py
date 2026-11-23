from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RoleId = Literal["coding", "scholar"]
PermissionProfile = Literal["read_only", "edit", "execute", "research"]
FactKind = Literal[
    "preference",
    "decision",
    "constraint",
    "artifact",
    "insight",
    "open_question",
    "profile",
]
FactScope = Literal["global", "workspace"]
FactRole = Literal["coding", "scholar", "both"]
FactStatus = Literal["candidate", "accepted", "rejected", "archived"]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    workspace_path: str = Field(min_length=1)
    brief_md: str = ""
    allowed_tools: list[str] = Field(default_factory=list)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    workspace_path: str | None = Field(default=None, min_length=1)
    brief_md: str | None = None
    allowed_tools: list[str] | None = None
    archived: bool | None = None


class SessionCreate(BaseModel):
    role: RoleId = "coding"
    title: str = Field(default="", max_length=200)
    project_id: str | None = None


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "ended", "archived"] | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)
    permission_profile: PermissionProfile | None = None
    fact_ids: list[str] | None = None


class FactCreate(BaseModel):
    scope: FactScope = "global"
    project_id: str | None = None
    role: FactRole = "both"
    kind: FactKind = "insight"
    status: Literal["candidate", "accepted"] = "accepted"
    title: str = Field(min_length=1, max_length=200)
    content_md: str = ""
    aliases: list[str] = Field(default_factory=list)
    pinned: bool = False


class FactUpdate(BaseModel):
    scope: FactScope | None = None
    project_id: str | None = None
    role: FactRole | None = None
    kind: FactKind | None = None
    status: FactStatus | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content_md: str | None = None
    aliases: list[str] | None = None
    pinned: bool | None = None


class FactExtractRequest(BaseModel):
    role: RoleId | None = None
    project_id: str | None = None
    session_ids: list[str] | None = None
    max_sessions: int | None = Field(default=None, ge=1, le=50)
