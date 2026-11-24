from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from ..repository_facts import FactRepository
from ..text import normalize_fingerprint, query_terms

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
    stamp = _parse_time(
        fact.get("last_confirmed_at")
        or fact.get("reviewed_at")
        or fact.get("updated_at")
    )
    if stamp is None:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    days = max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds() / 86400)
    return round(0.5 ** (days / 90.0), 4)


def _aliases_text(fact: dict[str, Any]) -> str:
    return " ".join(str(alias) for alias in fact.get("aliases") or []).lower()


def _tags_text(fact: dict[str, Any]) -> str:
    return " ".join(str(tag) for tag in fact.get("tags") or []).lower()


def _is_stale(fact: dict[str, Any], now: datetime) -> bool:
    stamp = _parse_time(fact.get("valid_until"))
    if stamp is None:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp <= now


def _match_detail(
    fact: dict[str, Any], terms: Iterable[str]
) -> dict[str, Any]:
    title = (fact.get("title") or "").lower()
    content = (fact.get("content_md") or "").lower()
    aliases = _aliases_text(fact)
    tags = _tags_text(fact)
    title_hits: list[str] = []
    alias_hits: list[str] = []
    tag_hits: list[str] = []
    content_hits: list[str] = []
    for term in terms:
        if _contains(title, term):
            title_hits.append(term)
        if _contains(aliases, term):
            alias_hits.append(term)
        if _contains(tags, term):
            tag_hits.append(term)
        if _contains(content, term):
            content_hits.append(term)
    all_hits = set(title_hits) | set(alias_hits) | set(tag_hits) | set(content_hits)
    return {
        "title_hits": title_hits,
        "alias_hits": alias_hits,
        "tag_hits": tag_hits,
        "content_hits": content_hits,
        "all_hits": all_hits,
        "strong": bool(title_hits or alias_hits or tag_hits),
    }


def _score_fact(
    fact: dict[str, Any],
    terms: list[str],
    *,
    hit_rank: int | None,
) -> dict[str, Any]:
    detail = _match_detail(fact, terms)
    term_count = max(1, len(terms))
    title_hits = len(detail["title_hits"])
    alias_hits = len(detail["alias_hits"])
    tag_hits = len(detail["tag_hits"])
    content_hits = len(detail["content_hits"])
    lexical = (
        2.0 * title_hits
        + 1.5 * alias_hits
        + 1.2 * tag_hits
        + 0.5 * content_hits
    )
    lexical_component = min(1.0, lexical / (2.0 * term_count))
    coverage = len(detail["all_hits"]) / term_count
    fts_component = (
        1.0 / (1.0 + max(0, hit_rank) / 5.0)
        if hit_rank is not None
        else 0.0
    )
    recency = _recency_score(fact)
    usage = min(1.0, math.log1p(int(fact.get("use_count") or 0)) / math.log1p(20))
    confidence = fact.get("confidence")
    confidence_component = (
        0.5 + 0.5 * float(confidence)
        if confidence is not None
        else 0.5
    )
    base = (
        0.45 * fts_component
        + 0.25 * lexical_component
        + 0.10 * coverage
        + 0.10 * recency
        + 0.05 * usage
        + 0.05 * confidence_component
    )
    pinned = bool(fact.get("pinned"))
    score = min(1.0, base + (0.5 if pinned else 0.0))
    return {
        "score": round(score, 4),
        "matched": bool(detail["all_hits"]),
        "strong": detail["strong"],
        "matched_terms": sorted(detail["all_hits"]),
        "score_parts": {
            "fts": round(fts_component, 4),
            "lexical": round(lexical_component, 4),
            "coverage": round(coverage, 4),
            "recency": round(recency, 4),
            "usage": round(usage, 4),
            "confidence": round(confidence_component, 4),
        },
        "pinned": pinned,
    }


def _rank_candidates(
    repo: FactRepository,
    *,
    role: str,
    project_id: str | None,
    query: str,
    min_score: float,
    max_items: int | None,
) -> tuple[list[dict[str, Any]], list[str], int]:
    terms = query_terms(query)
    candidates = repo.accepted_context_facts(role, project_id)
    hits = repo.search_facts(query, role, project_id) if terms else []
    hit_index = {fact["id"]: index for index, fact in enumerate(hits)}
    now = datetime.now(timezone.utc)
    ranked: list[dict[str, Any]] = []
    for fact in candidates:
        stale = _is_stale(fact, now)
        detail = _score_fact(
            fact, terms, hit_rank=hit_index.get(fact["id"])
        )
        fact.update(detail)
        fact["search_rank"] = hit_index.get(fact["id"])
        fact["recommended"] = False
        if stale:
            fact["reason"] = "stale"
        elif not terms:
            fact["reason"] = "no_terms" if not fact.get("pinned") else "pinned"
        elif fact["pinned"]:
            fact["reason"] = "pinned"
        elif not fact["matched"]:
            fact["reason"] = "not_relevant"
        elif not fact["strong"] and len(fact["matched_terms"]) < 2:
            fact["reason"] = "not_relevant"
        elif fact["score"] < min_score:
            fact["reason"] = "below_threshold"
        else:
            fact["reason"] = "matched"
        ranked.append(fact)
    ranked.sort(
        key=lambda fact: (
            0 if fact.get("pinned") else 1,
            0 if fact.get("reason") in {"matched", "pinned"} else 1,
            -float(fact.get("score", 0)),
            fact.get("updated_at") or "",
        )
    )
    eligible = [
        fact
        for fact in ranked
        if fact.get("reason") in {"matched", "pinned"}
        and (fact.get("pinned") or float(fact.get("score", 0)) >= min_score)
    ]
    if max_items is not None:
        eligible = eligible[:max_items]
    return ranked, [fact["id"] for fact in eligible], int(round(min_score * 1000))


def select_facts(
    repo: FactRepository,
    *,
    role: str,
    project_id: str | None,
    query: str,
    budget_chars: int,
    explicit_ids: list[str] | None = None,
    min_score: float = 0.55,
    max_items: int | None = 6,
) -> dict[str, Any]:
    terms = query_terms(query)
    candidates, eligible_ids, _ = _rank_candidates(
        repo,
        role=role,
        project_id=project_id,
        query=query,
        min_score=min_score,
        max_items=max_items,
    )
    eligible_set = set(eligible_ids)

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
        abstained = False
        abstain_reason = None
    else:
        selected = []
        used = 0
        for fact in candidates:
            if fact["id"] not in eligible_set:
                continue
            size = len(fact.get("title", "")) + len(fact.get("content_md", "")) + 24
            if used + size > budget_chars:
                fact["reason"] = "budget"
                continue
            fact["recommended"] = True
            if fact["reason"] == "matched":
                fact["reason"] = "pinned" if fact.get("pinned") else "matched"
            selected.append(fact)
            used += size
        selection_mode = "auto"
        abstained = not selected
        if abstained:
            if not terms:
                abstain_reason = "no_terms"
            elif not any(fact.get("matched") for fact in candidates):
                abstain_reason = "no_relevant_facts"
            else:
                abstain_reason = "below_threshold"
        else:
            abstain_reason = None

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
        "abstained": abstained,
        "abstain_reason": abstain_reason,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "top_score": max((float(fact.get("score", 0)) for fact in candidates), default=0.0),
        "threshold": min_score,
    }


def suggest_facts(
    repo: FactRepository,
    *,
    role: str,
    project_id: str | None,
    query: str,
    limit: int = 5,
    min_score: float = 0.55,
) -> dict[str, Any]:
    ranked, eligible_ids, _ = _rank_candidates(
        repo,
        role=role,
        project_id=project_id,
        query=query,
        min_score=min_score,
        max_items=limit,
    )
    eligible = [fact for fact in ranked if fact["id"] in set(eligible_ids)]
    return {
        "query_terms": query_terms(query),
        "abstained": not eligible,
        "facts": eligible,
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
        aliases_raw = raw.get("aliases")
        aliases = (
            [str(a).strip() for a in aliases_raw if str(a).strip()]
            if isinstance(aliases_raw, list)
            else []
        )
        tags_raw = raw.get("tags")
        tags = (
            [str(t).strip() for t in tags_raw if str(t).strip()]
            if isinstance(tags_raw, list)
            else []
        )
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
            "aliases": aliases,
            "tags": tags,
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
            existing["aliases"] = list(
                dict.fromkeys(existing.get("aliases", []) + aliases)
            )
            existing["tags"] = list(
                dict.fromkeys(existing.get("tags", []) + tags)
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
