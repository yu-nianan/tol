r"""T-08 混合检索自检（手动跑，不进 pytest 收集）：

1. 打印三条查询的 bm25 / ngram / fused 对比表；
2. 打印 30 条查询上单路与融合的 recall@3。
运行方式（仓库根目录）：

    $env:PYTHONPATH="."; .\.venv\Scripts\python.exe tests\knowledge\selfcheck_hybrid.py
"""

from __future__ import annotations

from recall_queries import QUERIES

from app.core.config import KB_DIR
from app.pipelines.knowledge.hybrid import char_ngrams
from app.pipelines.knowledge.store import KnowledgeBase
from app.pipelines.text.normalize import tokenize

SAMPLE_QUERIES = [
    "把钱转到安全账户做资金审查",
    "快递丢件了怎么赔",
    "今天天气不错",
]


def _gate(indexes: list[int], terms: set[str], kb: KnowledgeBase) -> list[int]:
    """与 search_cases 相同的过滤：至少共享一个多字词。"""
    meaningful = {term for term in terms if len(term) > 1}
    kept: list[int] = []
    for index in indexes:
        if meaningful & set(tokenize(kb.cases[index].text)):
            kept.append(index)
    return kept


def _fmt(hits: list[tuple[int, float]], kb: KnowledgeBase) -> str:
    if not hits:
        return "空"
    return ", ".join(f"{kb.cases[i].id}({kb.cases[i].script_id}, {s:.2f})" for i, s in hits) or "空"


def main() -> int:
    kb = KnowledgeBase(KB_DIR)
    assert kb.case_index is not None and kb.ngram_index is not None

    print("## 三条查询对比")
    for text in SAMPLE_QUERIES:
        bm25 = kb.case_index.search(tokenize(text), top_k=3)
        ngram = kb.ngram_index.search(text, top_k=3)
        fused = kb.search_cases(text, top_k=3)
        print(f"\n查询：{text}")
        print(f"  bm25 : {_fmt(bm25, kb)}")
        print(f"  ngram: {_fmt(ngram, kb)}")
        print(
            "  fused: "
            + (", ".join(f"{case.id}({case.script_id}, {score:.2f}, {src})" for case, score, src in fused) or "空")
        )

    print("\n## 30 条查询 recall@3")
    bm25_hits = ngram_hits = fused_hits = 0
    for text, expected in QUERIES:
        bm25_top = _gate(
            [i for i, _ in kb.case_index.search(tokenize(text), top_k=8)], set(tokenize(text)), kb
        )[:3]
        ngram_top = _gate(
            [i for i, _ in kb.ngram_index.search(text, top_k=8)], set(char_ngrams(text)), kb
        )[:3]
        bm25_hits += expected in {kb.cases[i].script_id for i in bm25_top}
        ngram_hits += expected in {kb.cases[i].script_id for i in ngram_top}
        fused_hits += any(case.script_id == expected for case, _, _ in kb.search_cases(text, top_k=3))

    n = len(QUERIES)
    print(f"bm25-only = {bm25_hits}/{n} = {bm25_hits / n:.1%}")
    print(f"ngram-only = {ngram_hits}/{n} = {ngram_hits / n:.1%}")
    print(f"fused      = {fused_hits}/{n} = {fused_hits / n:.1%}")
    return 0 if fused_hits == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
