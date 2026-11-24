from __future__ import annotations

from app.text import (
    build_search_text,
    normalize_fingerprint,
    query_terms,
    title_similarity,
    token_jaccard,
)


def test_chinese_bigrams_and_shared_search_text():
    terms = query_terms("这周怎么练全身")
    assert "全身" in terms
    indexed = build_search_text(
        "每周全身锻炼 3 次", "偏好晚上训练。", ["健身"], ["fitness"]
    )
    assert "全身" in indexed
    assert "健身" in indexed
    assert "fitness" in indexed


def test_english_terms_are_lowercased_and_stopwords_removed():
    terms = query_terms("How do I use the SQLite FTS5 build?")
    assert "sqlite" in terms
    assert "fts5" in terms
    assert "the" not in terms


def test_fingerprint_normalizes_case_and_punctuation():
    assert normalize_fingerprint(
        "Build: use PNPM!", "constraint", "workspace", "ws-1"
    ) == normalize_fingerprint(
        "build use pnpm", "constraint", "workspace", "ws-1"
    )
    assert normalize_fingerprint(
        "Build: use PNPM!", "constraint", "workspace", "ws-1"
    ) != normalize_fingerprint(
        "Build: use npm!", "constraint", "workspace", "ws-1"
    )


def test_similarity_helpers_are_scope_free_and_deterministic():
    assert title_similarity("构建使用 pnpm", "构建使用 PNPM") > 0.9
    assert token_jaccard("每周全身锻炼", "全身锻炼三次") > 0.3
    assert token_jaccard("", "anything") == 0.0
