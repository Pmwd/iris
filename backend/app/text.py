from __future__ import annotations

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


def query_terms(text: str, limit: int = 32) -> list[str]:
    """Tokenize English words and Chinese bigrams for local retrieval.

    FTS5's default tokenizer does not segment Chinese phrases well, so we
    generate overlapping bigrams for Han runs. The LIKE fallback then finds
    phrases such as 全身 in 全身锻炼 even when FTS5 does not.
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
