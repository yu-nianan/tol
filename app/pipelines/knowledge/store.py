"""知识库：剧本（按阶段建模）+ 案例库（BM25 召回）。

设计要点：
1. 剧本按"阶段"组织，而不是一堆关键词 —— 才能在"还没转账"时就报警；
2. 案例检索只用纯 Python BM25（中文按字/双字切），零额外依赖，方便换向量库；
3. 两个库都支持热加载（新案例入库后调 reload 即可）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.pipelines.text.normalize import tokenize
from app.schemas import ScriptHit

log = get_logger(__name__)


@dataclass(frozen=True)
class Stage:
    name: str
    label: str
    weight: float
    signals: tuple[str, ...]


@dataclass(frozen=True)
class Script:
    id: str
    name: str
    risk_base: int
    advice: tuple[str, ...]
    stages: tuple[Stage, ...]


@dataclass(frozen=True)
class Case:
    id: str
    script_id: str
    title: str
    text: str
    level: str


class BM25:
    """经典 BM25（k1=1.5, b=0.75），语料是小规模中文案例。"""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs = corpus
        self.n_docs = len(corpus)
        self.avg_len = sum(len(d) for d in corpus) / self.n_docs if self.n_docs else 0.0
        self.term_freq: list[dict[str, int]] = []
        doc_freq: dict[str, int] = {}
        for doc in corpus:
            counts: dict[str, int] = {}
            for token in doc:
                counts[token] = counts.get(token, 0) + 1
            self.term_freq.append(counts)
            for token in counts:
                doc_freq[token] = doc_freq.get(token, 0) + 1
        self.doc_freq = doc_freq

    def idf(self, term: str) -> float:
        n = self.doc_freq.get(term, 0)
        return math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5))

    def score(self, query: list[str], index: int) -> float:
        tf = self.term_freq[index]
        doc_len = len(self.docs[index]) or 1
        total = 0.0
        for term in query:
            freq = tf.get(term, 0)
            if not freq:
                continue
            denom = freq + self.k1 * (1 - self.b + self.b * doc_len / (self.avg_len or 1))
            total += self.idf(term) * freq * (self.k1 + 1) / denom
        return total

    def search(self, query: list[str], top_k: int = 3) -> list[tuple[int, float]]:
        scored = [(i, self.score(query, i)) for i in range(self.n_docs)]
        scored = [item for item in scored if item[1] > 0]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class KnowledgeBase:
    def __init__(self, kb_dir: Path) -> None:
        self.kb_dir = kb_dir
        self.scripts: list[Script] = []
        self.cases: list[Case] = []
        self.case_index: BM25 | None = None
        self.reload()

    def reload(self) -> None:
        self.scripts = self._load_scripts()
        self.cases = self._load_cases()
        self.case_index = BM25([tokenize(case.text) for case in self.cases]) if self.cases else None
        log.info("知识库已加载 scripts=%s cases=%s", len(self.scripts), len(self.cases))

    def _load_scripts(self) -> list[Script]:
        payload = _load_json(self.kb_dir / "scripts.json")
        scripts: list[Script] = []
        for item in payload.get("scripts", []):
            stages = tuple(
                Stage(
                    name=stage["name"],
                    label=stage["label"],
                    weight=float(stage["weight"]),
                    signals=tuple(stage.get("signals", [])),
                )
                for stage in item.get("stages", [])
            )
            scripts.append(
                Script(
                    id=item["id"],
                    name=item["name"],
                    risk_base=int(item.get("risk_base", 90)),
                    advice=tuple(item.get("advice", [])),
                    stages=stages,
                )
            )
        return scripts

    def _load_cases(self) -> list[Case]:
        payload = _load_json(self.kb_dir / "cases.json")
        return [
            Case(
                id=item["id"],
                script_id=item.get("script_id", ""),
                title=item.get("title", ""),
                text=item.get("text", ""),
                level=item.get("level", "L2"),
            )
            for item in payload.get("cases", [])
        ]

    @property
    def script_count(self) -> int:
        return len(self.scripts)

    @property
    def case_count(self) -> int:
        return len(self.cases)

    def match_script(self, text: str) -> ScriptHit | None:
        """找"走得最远"的那个剧本阶段。

        同一剧本可能有多个阶段命中，取 weight 最高的阶段（= 骗子已经推进到哪一步）。
        """
        best: ScriptHit | None = None
        for script in self.scripts:
            for stage in script.stages:
                hits = [signal for signal in stage.signals if signal in text]
                if not hits:
                    continue
                ratio = len(hits) / max(len(stage.signals), 1)
                stage_score = round(stage.weight * (0.6 + 0.4 * ratio), 3)
                if stage_score < 0.3:
                    continue
                candidate = ScriptHit(
                    script_id=script.id,
                    name=script.name,
                    stage_name=stage.name,
                    stage_label=stage.label,
                    stage_weight=min(stage_score, 0.99),
                    risk_base=script.risk_base,
                    advice=list(script.advice),
                    matched_signals=hits,
                )
                if best is None or candidate.stage_weight > best.stage_weight:
                    best = candidate
        return best

    def search_cases(self, text: str, top_k: int = 2) -> list[tuple[Case, float]]:
        """返回 (案例, 相似度)。相似度用"查询词被案例覆盖的比例"，好解释、范围固定 0–1。"""
        if not self.case_index or not self.cases:
            return []
        query = tokenize(text)
        if not query:
            return []
        query_terms = set(query)
        results: list[tuple[Case, float]] = []
        for index, _score in self.case_index.search(query, top_k=top_k):
            case = self.cases[index]
            case_terms = set(tokenize(case.text))
            overlap = len(query_terms & case_terms) / max(len(query_terms), 1)
            if overlap <= 0:
                continue
            results.append((case, round(min(overlap, 1.0), 3)))
        return results

    def add_case(self, case: Case) -> bool:
        """新增案例（去重）。返回 False 表示重复，未入库。"""
        if any(existing.id == case.id for existing in self.cases):
            return False
        self.cases.append(case)
        self.case_index = BM25([tokenize(c.text) for c in self.cases])
        return True
