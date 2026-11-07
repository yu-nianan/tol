"""T-08 混合检索：同义词 + 字符 2-gram + RRF 的单测与验收用例。"""

from __future__ import annotations

from pathlib import Path

from recall_queries import QUERIES

from app.core.config import KB_DIR
from app.pipelines.knowledge.hybrid import (
    SOURCE_FUSED,
    char_ngrams,
    expand_synonyms,
    load_synonyms,
    rrf_fuse,
)
from app.pipelines.knowledge.store import KnowledgeBase
from app.pipelines.text.normalize import tokenize

KB = KnowledgeBase(KB_DIR)


def _single_path_top3(text: str, path: str) -> list[int]:
    """单路召回 + 与 search_cases 相同的多字词过滤，用于证明融合增益。"""
    assert KB.case_index is not None and KB.ngram_index is not None
    if path == "bm25":
        raw = [index for index, _ in KB.case_index.search(tokenize(text), top_k=8)]
        terms: set[str] = set(tokenize(text))
    else:
        raw = [index for index, _ in KB.ngram_index.search(text, top_k=8)]
        terms = set(char_ngrams(text))
    meaningful = {term for term in terms if len(term) > 1}
    kept = [i for i in raw if meaningful & set(tokenize(KB.cases[i].text))]
    return kept[:3]


def test_acceptance_synonym_query_hits_police_case_with_fused() -> None:
    hits = KB.search_cases("把钱转到安全账户做资金审查", top_k=3)
    assert hits, "同义查询不应为空"
    assert any(case.script_id == "S01" and source == SOURCE_FUSED for case, _score, source in hits)
    assert all(source in {"bm25", "ngram", "fused"} for _case, _score, source in hits)


def test_acceptance_weather_query_returns_empty() -> None:
    assert KB.search_cases("今天天气不错", top_k=3) == []
    assert KB.search_cases("   ", top_k=3) == []


def test_search_cases_returns_case_score_source_triples() -> None:
    hits = KB.search_cases("快递丢了说给我双倍赔付", top_k=2)
    assert 0 < len(hits) <= 2
    for case, score, source in hits:
        assert case.id.startswith("C")
        assert 0.0 <= score <= 1.0
        assert source in {"bm25", "ngram", "fused"}


def test_fused_recall_at_3_beats_each_single_path_by_10_points() -> None:
    bm25_hits = ngram_hits = fused_hits = 0
    for text, expected in QUERIES:
        bm25_hits += expected in {KB.cases[i].script_id for i in _single_path_top3(text, "bm25")}
        ngram_hits += expected in {KB.cases[i].script_id for i in _single_path_top3(text, "ngram")}
        fused_hits += any(
            case.script_id == expected for case, _score, _source in KB.search_cases(text, top_k=3)
        )
    n = len(QUERIES)
    assert fused_hits == n, f"fused 应全部命中，实际 {fused_hits}/{n}"
    best_single = max(bm25_hits, ngram_hits) / n
    # 验收口径：fused recall@3 ≥ 单路 +10 个百分点（ticket T-08 §6）
    assert fused_hits / n >= best_single + 0.10, (fused_hits / n, bm25_hits / n, ngram_hits / n)


def test_synonyms_file_keeps_required_group() -> None:
    groups = load_synonyms(Path(KB_DIR) / "synonyms.json")
    assert any({"安全账户", "资金审查", "清查"} <= set(group) for group in groups)


def test_expand_synonyms_only_adds_same_group_terms() -> None:
    groups = load_synonyms(Path(KB_DIR) / "synonyms.json")
    extras = expand_synonyms("他说要验资", groups)
    assert "资金审查" in extras
    assert "中奖" not in extras


def test_char_ngrams_basic() -> None:
    assert char_ngrams("安全账户") == ["安全", "全账", "账户"]
    assert char_ngrams("a b") == ["a", "b"]


def test_rrf_fuse_prefers_items_hit_by_both_paths() -> None:
    fused = rrf_fuse([[0, 1], [1, 2]])
    assert fused[0][0] == 1
    assert dict(fused)[0] < dict(fused)[1]
