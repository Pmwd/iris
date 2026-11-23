from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from ..repository_facts import FactRepository, normalize_fingerprint
from ..text import query_terms

FACT_KINDS = {
    "preference",
    "decision",
    "constraint",
    "artifact",
    "insight",
    "open_question",
    "profile",
}
FACT_SCOPES = {"global", "workspace"}
FACT_ROLES = {"coding", "scholar", "both"}
FACT_ACTIONS = {"new", "update"}


class FactSelectionError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ExtractionParseError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _contains(text: str, term: str) -> bool:
    if term.isascii():
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _recency_score(fact: dict[str, Any]) -> float:
    stamp = _parse_time(fact.get("updated_at") or fact.get("reviewed_at"))
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


def _aliases_text(fact: dict[str, Any]) -> str:
    return " ".join(str(alias) for alias in fact.get("aliases") or []).lower()


def _substring_score(fact: dict[str, Any], terms: Iterable[str]) -> float:
    title = (fact.get("title") or "").lower()
    content = (fact.get("content_md") or "").lower()
    aliases = _aliases_text(fact)
    score = 0.0
    for term in terms:
        if _contains(title, term):
            score += 8
        if _contains(aliases, term):
            score += 4
        if _contains(content, term):
            score += 2
    return score


def select_facts(
    repo: FactRepository,
    *,
    role: str,
    project_id: str | None,
    query: str,
    budget_chars: int,
    explicit_ids: list[str] | None = None,
) -> dict[str, Any]:
    terms = query_terms(query)
    candidates = repo.accepted_context_facts(role, project_id)
    hits = repo.search_facts(query, role, project_id)
    hit_index = {fact["id"]: index for index, fact in enumerate(hits)}

    for fact in candidates:
        searchable = " ".join(
            [
                (fact.get("title") or "").lower(),
                (fact.get("content_md") or "").lower(),
                _aliases_text(fact),
            ]
        )
        local_matches = [term for term in terms if _contains(searchable, term)]
        rank_index = hit_index.get(fact["id"])
        score = (
            _substring_score(fact, terms)
            + _recency_score(fact)
            + min(int(fact.get("use_count", 0)), 20) * 1.5
        )
        if fact.get("pinned"):
            score += 1000
        if rank_index is not None and local_matches:
            score += 300 - min(rank_index, 50) * 4
        fact["matched"] = bool(local_matches)
        fact["search_rank"] = rank_index
        fact["score"] = round(score, 2)
        fact["recommended"] = False
        fact["reason"] = "not_relevant"

    candidates.sort(
        key=lambda fact: (
            0 if fact.get("pinned") else 1,
            0 if fact.get("matched") else 1,
            fact.get("search_rank") if fact.get("search_rank") is not None else 999,
            -float(fact.get("score", 0)),
            fact.get("updated_at") or "",
        )
    )

    if explicit_ids is not None:
        wanted = list(dict.fromkeys(explicit_ids))
        by_id = {fact["id"]: fact for fact in candidates}
        missing = [fact_id for fact_id in wanted if fact_id not in by_id]
        if missing:
            raise FactSelectionError(
                "some selected facts are not accepted for this role/workspace"
            )
        selected: list[dict[str, Any]] = []
        used = 0
        for fact_id in wanted:
            fact = by_id[fact_id]
            size = len(fact.get("title", "")) + len(fact.get("content_md", "")) + 24
            if used + size > budget_chars:
                raise FactSelectionError(
                    "selected facts exceed the context budget; remove some or raise "
                    "IRIS_FACT_CONTEXT_MAX_CHARS"
                )
            fact["recommended"] = True
            fact["reason"] = "manual"
            selected.append(fact)
            used += size
        selection_mode = "manual"
    else:
        selected = []
        used = 0
        for fact in candidates:
            # Pinned facts are always eligible; everything else needs a match.
            eligible = fact.get("matched") or fact.get("pinned")
            if not eligible:
                continue
            size = len(fact.get("title", "")) + len(fact.get("content_md", "")) + 24
            if used + size > budget_chars:
                fact["reason"] = "budget"
                continue
            fact["recommended"] = True
            fact["reason"] = "pinned" if fact.get("pinned") else "matched"
            selected.append(fact)
            used += size
        selection_mode = "auto"

    candidates.sort(
        key=lambda fact: (
            0 if fact.get("recommended") else 1,
            0 if fact.get("pinned") else 1,
            -float(fact.get("score", 0)),
            fact.get("updated_at") or "",
        )
    )
    return {
        "facts": candidates,
        "selected_ids": [fact["id"] for fact in selected],
        "selected_chars": used,
        "budget_chars": budget_chars,
        "query_terms": terms,
        "selection_mode": selection_mode,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ExtractionParseError("The extractor did not return a JSON object.")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ExtractionParseError(f"The extractor returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExtractionParseError("The extractor returned a non-object payload.")
    return payload


def parse_extraction(
    text: str,
    *,
    allowed_session_ids: Iterable[str],
    project_id: str | None,
    existing_facts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate extractor output. Returns (candidates, dropped_reasons)."""
    payload = _extract_json_object(text)
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ExtractionParseError("The extractor returned no candidates list.")

    allowed = set(allowed_session_ids)
    accepted_by_fact_id = {
        fact["id"]: fact for fact in existing_facts if fact.get("status") == "accepted"
    }
    by_fingerprint = {
        normalize_fingerprint(
            fact.get("title", ""), fact.get("kind", ""), fact.get("scope", ""),
            fact.get("project_id"),
        ): fact
        for fact in existing_facts
        if fact.get("status") == "accepted"
    }

    dropped: list[str] = []
    merged: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_candidates):
        if not isinstance(raw, dict):
            dropped.append(f"candidate {index}: not an object")
            continue
        kind = str(raw.get("kind") or "").strip()
        scope = str(raw.get("scope") or "global").strip()
        role = str(raw.get("role") or "both").strip()
        action = str(raw.get("action") or "new").strip()
        title = str(raw.get("title") or "").strip()
        content_md = str(raw.get("content_md") or "").strip()
        evidence_md = str(raw.get("evidence_md") or "").strip()
        source_ids = raw.get("source_session_ids")
        if not isinstance(source_ids, list):
            source_ids = []
        source_ids = [str(s) for s in source_ids if str(s) in allowed]

        if kind not in FACT_KINDS:
            dropped.append(f"candidate {index}: bad kind {kind!r}")
            continue
        if scope not in FACT_SCOPES:
            dropped.append(f"candidate {index}: bad scope {scope!r}")
            continue
        if role not in FACT_ROLES:
            dropped.append(f"candidate {index}: bad role {role!r}")
            continue
        if action not in FACT_ACTIONS:
            action = "new"
        if not title:
            dropped.append(f"candidate {index}: empty title")
            continue
        if not source_ids:
            dropped.append(f"candidate {index}: no valid source_session_ids")
            continue
        candidate_project = project_id if scope == "workspace" else None
        if scope == "workspace" and not candidate_project:
            dropped.append(f"candidate {index}: workspace fact without a workspace")
            continue

        target_fact_id = raw.get("target_fact_id")
        target_fact_id = str(target_fact_id) if target_fact_id else None
        if target_fact_id and target_fact_id not in accepted_by_fact_id:
            target_fact_id = None
        fingerprint = normalize_fingerprint(title, kind, scope, candidate_project)
        update_target = target_fact_id
        if action == "update" and not update_target:
            existing = by_fingerprint.get(fingerprint)
            update_target = existing["id"] if existing else None
        if update_target is None and fingerprint in by_fingerprint:
            action = "update"
            update_target = by_fingerprint[fingerprint]["id"]
        elif update_target is None:
            action = "new"

        confidence = raw.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None
        if confidence_value is not None:
            confidence_value = min(1.0, max(0.0, confidence_value))

        candidate = {
            "kind": kind,
            "scope": scope,
            "project_id": candidate_project,
            "role": role,
            "title": title,
            "content_md": content_md,
            "evidence_md": evidence_md,
            "source_session_ids": source_ids,
            "confidence": confidence_value,
            "action": action,
            "target_fact_id": update_target,
            "fingerprint": fingerprint,
        }
        existing = merged.get(fingerprint)
        if existing:
            existing["source_session_ids"] = list(
                dict.fromkeys(existing["source_session_ids"] + source_ids)
            )
            if len(content_md) > len(existing["content_md"]):
                existing["content_md"] = content_md
            if evidence_md and evidence_md not in existing["evidence_md"]:
                existing["evidence_md"] = (
                    existing["evidence_md"] + "\n" + evidence_md
                ).strip()
            if existing.get("confidence") is not None and confidence_value is not None:
                existing["confidence"] = max(
                    float(existing["confidence"]), confidence_value
                )
            continue
        merged[fingerprint] = candidate

    return list(merged.values()), dropped
