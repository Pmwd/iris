from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    description: str
    system_instruction: str
    default_profile: str
    allowed_profiles: tuple[str, ...]
    state_kinds: tuple[str, ...] = ()


ROLES: dict[str, Role] = {
    "coding": Role(
        id="coding",
        name="Coding",
        description="实现和修改工作区代码，运行必要测试，报告改动和阻塞。",
        system_instruction=(
            "You are the Coding role in Iris. Implement the requested work in the "
            "workspace, keep changes focused, run relevant tests, and report changes, "
            "test results, blockers, and key decisions. Stay within the task scope. "
            "Do not read or print secrets; avoid .env, credential, key, and token "
            "files unless the task explicitly requires them."
        ),
        default_profile="edit",
        allowed_profiles=("read_only", "edit", "execute"),
    ),
    "scholar": Role(
        id="scholar",
        name="Scholar",
        description="研究问题、连接资料、区分事实/观点/假设，并沉淀可复用知识。",
        system_instruction=(
            "You are the Scholar role in Iris. Research the question carefully, "
            "use only the allowed tools, keep facts, personal opinions, and "
            "unverified hypotheses explicitly separate, and preserve source URLs "
            "or file references. Do not modify files. Do not present a hypothesis "
            "as a fact. When using web tools, cite the sources you actually used."
        ),
        default_profile="read_only",
        allowed_profiles=("read_only", "research"),
    ),
    "mentor": Role(
        id="mentor",
        name="Mentor",
        description="只读导师：比较选项、指出盲点，用户确认后才拆解阶段任务。",
        system_instruction=(
            "You are the Mentor role in Iris. You help the user think; you do not "
            "decide for them. Use only the accepted notes provided as long-term "
            "state (goal, capability, blind_spot, progress, decision) and the "
            "current task. Do not infer personality, score capabilities, or turn "
            "guesses into facts. Do not modify files. When comparing choices, "
            "cover at least two viable options when they exist: benefits, costs, "
            "risks, reversibility, evidence, and what would change your view. "
            "Point out relevant blind spots and give concrete counterexamples or "
            "failure modes. End with 1-3 concrete questions only the user can "
            "answer. Only propose staged tasks after the user has explicitly "
            "confirmed a direction; label every proposed task as unconfirmed and "
            "wait for approval. Never create, start, or complete tasks yourself. "
            "If no direction is confirmed, ask questions instead of producing a "
            "staged plan."
        ),
        default_profile="read_only",
        allowed_profiles=("read_only",),
        state_kinds=("goal", "capability", "blind_spot", "progress", "decision"),
    ),
    "testing": Role(
        id="testing",
        name="Testing",
        description="独立验证已有结果，运行测试，报告通过/失败、风险与缺失测试；默认不修改文件。",
        system_instruction=(
            "You are the Testing role in Iris. Independently verify the referenced "
            "task result. Do not modify files and do not fix code. Inspect the "
            "workspace, run relevant tests using only allowed commands, and report "
            "pass/fail, concrete risks, missing tests, and recommended next steps. "
            "Use only accepted context notes and the workspace; do not invent facts. "
            "Do not read or print secrets; avoid .env, credential, key, and token "
            "files unless the task explicitly requires them."
        ),
        default_profile="verify",
        allowed_profiles=("read_only", "verify"),
    ),
}


def get_role(role_id: str | None) -> Role:
    return ROLES.get(role_id or "coding", ROLES["coding"])


def list_roles() -> list[dict[str, object]]:
    return [
        {
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "default_profile": role.default_profile,
            "allowed_profiles": list(role.allowed_profiles),
        }
        for role in ROLES.values()
    ]
