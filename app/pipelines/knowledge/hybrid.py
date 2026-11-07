"""混合检索：字符 n-gram 向量替身 + 同义词扩展 + RRF 融合（T-08）。

设计取舍：
- 不许装依赖，所以用字符 2-gram 的 TF-IDF 余弦当"向量"替身；
- 同义词只参与召回（扩展查询），不参与打分 —— score 仍是"查询词被案例覆盖的比例"，
  范围固定在 0–1，下游 engine 的 ``similarity < 0.2`` 门禁才不会失效；
- RRF 的原始分只有 0.01 量级，绝不直接当 similarity 用，只用来排序。
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

RRF_K = 60
SOURCE_BM25 = "bm25"
SOURCE_NGRAM = "ngram"
SOURCE_FUSED = "fused"


def char_ngrams(text: str, n: int = 2) -> list[str]:
    """按空白切段后取字符 n-gram；不足 n 个字符的段退化为单字。"""
    grams: list[str] = []
    for segment in text.split():
        chars = list(segment)
        if len(chars) < n:
            grams.extend(chars)
        else:
            grams.extend("".join(chars[i : i + n]) for i in range(len(chars) - n + 1))
    return grams


def load_synonyms(path: Path) -> list[tuple[str, ...]]:
    """读同义词表：``{"groups": [["安全账户", "资金审查", ...], ...]}``。"""
    path = Path(path)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("groups", []) if isinstance(payload, dict) else payload
    groups: list[tuple[str, ...]] = []
    for group in raw:
        terms = tuple(str(term).strip() for term in group if str(term).strip())
        if len(terms) >= 2:
            groups.append(terms)
    return groups


def expand_synonyms(text: str, groups: list[tuple[str, ...]]) -> list[str]:
    """命中任意同义词时，把同组其他词也加进查询（去重、保持顺序）。"""
    extras: list[str] = []
    for group in groups:
        if any(term in text for term in group):
            for term in group:
                if term not in text and term not in extras:
                    extras.append(term)
    return extras


class NGramIndex:
    """字符 n-gram 的 TF-IDF 余弦检索，纯 Python，零依赖。"""

    def __init__(self, corpus: list[str], n: int = 2) -> None:
        self.n = n
        self.tf: list[Counter[str]] = [Counter(char_ngrams(text, n)) for text in corpus]
        self.n_docs = len(self.tf)
        doc_freq: Counter[str] = Counter()
        for counts in self.tf:
            doc_freq.update(counts.keys())
        self.idf = {
            term: math.log((1 + self.n_docs) / (1 + freq)) + 1.0 for term, freq in doc_freq.items()
        }
        self.norms = [self._norm(counts) for counts in self.tf]

    def _norm(self, counts: Counter[str]) -> float:
        total = sum((freq * self.idf.get(term, 0.0)) ** 2 for term, freq in counts.items())
        return math.sqrt(total) or 1.0

    def search(
        self, text: str, extras: list[str] | None = None, top_k: int = 8
    ) -> list[tuple[int, float]]:
        terms = char_ngrams(text, self.n)
        for phrase in extras or []:
            terms.extend(char_ngrams(phrase, self.n))
        query = Counter(terms)
        if not query or not self.n_docs:
            return []
        query_norm = (
            math.sqrt(sum((freq * self.idf.get(term, 0.0)) ** 2 for term, freq in query.items()))
            or 1.0
        )
        scored: list[tuple[int, float]] = []
        for index, counts in enumerate(self.tf):
            dot = 0.0
            for term, freq in query.items():
                doc_freq = counts.get(term, 0)
                if not doc_freq:
                    continue
                weight = self.idf.get(term, 0.0)
                dot += freq * weight * doc_freq * weight
            if dot <= 0:
                continue
            scored.append((index, dot / (query_norm * self.norms[index])))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


def rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion：``sum(1 / (k + rank))``，rank 从 1 开始。"""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, index in enumerate(ranking, start=1):
            scores[index] = scores.get(index, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
