from __future__ import annotations

import difflib
import re

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]+")

# Generic task language that should not make a note "relevant".
STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "不要",
    "以及",
    "进行",
    "本周",
    "安排",
    "每次",
    "分钟",
    "输出",
    "说明",
    "修改",
    "文件",
    "符合",
    "推荐",
    "三本",
    "以内",
    "简短",
    "给出",
    "避开",
    "偏好",
    "理由",
    "依据",
}

# Character-level function words that make cross-boundary Chinese bigrams
# noisy (e.g. 好的, 的书, 我阅, 本符). Domain bigrams such as 阅读/健身/
# 水果/过敏 do not contain these characters.
FUNCTION_CHARS = set(
    "的了和与在是我你他她它这那有就不很也都还又而及或等啊吧呢吗个一为以"
    "于把被让给对从向到本"
)


def search_tokens(text: str, limit: int = 2000) -> list[str]:
    """Tokenize English words and Chinese bigrams for local retrieval.

    FTS5's default tokenizer does not segment Chinese phrases well, so we use
    the same overlapping bigrams both when indexing and when querying. Keeping
    one tokenizer for both sides is what makes CJK FTS matching reliable.
    """
    terms: list[str] = []
    for raw in TOKEN_RE.findall(text or ""):
        token = raw.lower()
        if not token or token in STOPWORDS or token.isdigit():
            continue
        if token.isascii():
            terms.append(token)
            continue
        if len(token) == 1:
            continue
        for index in range(len(token) - 1):
            pair = token[index : index + 2]
            if pair in STOPWORDS or any(char in FUNCTION_CHARS for char in pair):
                continue
            terms.append(pair)
        if (
            len(token) <= 4
            and token not in STOPWORDS
            and not any(char in FUNCTION_CHARS for char in token)
        ):
            terms.append(token)
    return list(dict.fromkeys(terms))[:limit]


def query_terms(text: str, limit: int = 32) -> list[str]:
    return search_tokens(text, limit=limit)


def build_search_text(*parts: object) -> str:
    """Build the pre-tokenized text stored in ``facts.search_text``.

    Parts may be strings or lists of strings (aliases/tags). Deduplication
    keeps the FTS index compact while preserving term coverage.
    """
    tokens: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple, set)):
            for item in part:
                tokens.extend(search_tokens(str(item), limit=500))
        else:
            tokens.extend(search_tokens(str(part), limit=1000))
    return " ".join(dict.fromkeys(tokens))


def normalize_for_match(text: str) -> str:
    lowered = (text or "").strip().lower()
    cleaned = re.sub(r"[^\w㐀-鿿]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_fingerprint(
    title: str, kind: str, scope: str, project_id: str | None
) -> str:
    return (
        f"{kind}|{scope}|{project_id or ''}|{normalize_for_match(title)}"
    )


def title_similarity(left: str, right: str) -> float:
    a = normalize_for_match(left)
    b = normalize_for_match(right)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def token_jaccard(left: str, right: str) -> float:
    a = set(search_tokens(left, limit=500))
    b = set(search_tokens(right, limit=500))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
