from __future__ import annotations

from typing import Any

from ..text import title_similarity, token_jaccard

DUP_TITLE = 0.88
NEAR_SCORE = 0.68
RELATED_SCORE = 0.35
CONFLICT_KINDS = {"decision", "constraint", "preference", "profile"}
CHANGE_MARKERS = (
    "不再",
    "改用",
    "改成",
    "改为",
    "替代",
    "废弃",
    "不要",
    "instead",
    "now use",
    "deprecated",
    "replace",
    "not ",
)


def _scope_compatible(candidate: dict[str, Any], target: dict[str, Any]) -> bool:
    crole = candidate.get("role")
    trole = target.get("role")
    if crole != "both" and trole != "both" and crole != trole:
        return False
    if candidate.get("scope") == "workspace" and target.get(
        "project_id"
    ) != candidate.get("project_id"):
        return False
    if target.get("scope") == "workspace" and candidate.get(
        "project_id"
    ) != target.get("project_id"):
        return False
    return True


def _pair_score(candidate: dict[str, Any], target: dict[str, Any]) -> float:
    title = title_similarity(
        candidate.get("title") or "", target.get("title") or ""
    )
    body = token_jaccard(
        (candidate.get("content_md") or "") + " " + (candidate.get("title") or ""),
        (target.get("content_md") or "") + " " + (target.get("title") or ""),
    )
    return max(title, 0.6 * title + 0.4 * body)


def relation_for_pair(
    candidate: dict[str, Any], target: dict[str, Any]
) -> tuple[str, float] | None:
    if not _scope_compatible(candidate, target):
        return None
    score = _pair_score(candidate, target)
    same_kind = candidate.get("kind") == target.get("kind")
    title = title_similarity(
        candidate.get("title") or "", target.get("title") or ""
    )
    if title >= DUP_TITLE or (same_kind and score >= 0.80):
        return "duplicate", round(score, 3)
    if score >= NEAR_SCORE:
        return "near_duplicate", round(score, 3)
    text = ((candidate.get("title") or "") + " " + (candidate.get("content_md") or "")).lower()
    if (
        same_kind
        and candidate.get("kind") in CONFLICT_KINDS
        and score >= 0.45
        and any(marker in text for marker in CHANGE_MARKERS)
    ):
        return "conflict", round(score, 3)
    if score >= RELATED_SCORE:
        return "related", round(score, 3)
    return None


def find_relations(
    candidate: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for target in targets:
        if target.get("id") == candidate.get("id"):
            continue
        relation = relation_for_pair(candidate, target)
        if not relation:
            continue
        kind, score = relation
        found.append(
            {
                "relation": kind,
                "score": score,
                "target_fact_id": target["id"],
                "target": target,
            }
        )
    found.sort(key=lambda item: item["score"], reverse=True)
    return found[:limit]
