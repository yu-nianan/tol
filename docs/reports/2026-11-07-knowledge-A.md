---
title: 任务回执：知识库扩充 + 40 条测评集 + 混合检索（负责人 A）
owner: A
status: final
last_updated: 2026-11-07
related_code: app/kb/, app/pipelines/knowledge/, app/pipelines/decision/scoring.py, tests/knowledge/, tests/eval/
summary: T-01 扩到 15 类剧本/50 条案例（Top-1 100%）；T-05 40 条黑白测评集 + 量测脚本（P/R/F1/accuracy=1.000）；T-08 同义词 + 字符 2-gram + RRF 融合（30 查询 recall@3 30/30）
audience: agent
depends_on: [../INDEX.md]
---

# 任务回执：知识库扩充 + 测评集 + 混合检索

工具：DSH agent（负责人 A 代理）

## 做了什么

1. **T-01 知识库扩充**：剧本 10→15 类（新增 S11 快递丢件理赔、S12 虚假投资平台、S13 冒充熟人 AI 语音、S14 虚假招聘、S15 短信钓鱼），案例 20→50 条（C001–C050，旧 10 类各 3 条、新 5 类各 4 条；L1 8 / L2 12 / L3 10，噪声 7 条）；补 `validate_cases()` 做结构校验。检索自检：**每条案例原文检索，Top-1 命中自身 script_id = 50/50 = 100.0%**（目标 ≥85%）。
2. **T-05 测评集与量测**：`app/kb/eval_set.csv` 40 条（E001–E020 黑，覆盖 S01–S15；E021–E040 白，黑白 1:1）；`app/kb/eval_set_official.csv` 20 条（E001–E010 + E021–E030，文件头注明挑选规则）；`evalcheck.py` 提供 `load_eval_set / validate_eval_set / measure`；`tests/eval/test_measurement.py` 6 条测试（含 3 条反例）。最终实测 **n=40 tp=20 fp=0 tn=20 fn=0，P=1.000 R=1.000 F1=1.000 accuracy=1.000**。
3. **T-08 混合检索**：`app/kb/synonyms.json` 11 组同义词；`hybrid.py` 实现字符 2-gram TF-IDF 余弦 + RRF（k=60，两路各 top8 → 融合 top3）；`KnowledgeBase.search_cases(text, top_k)` 改为返回 **`(case, score, source)` 三元组**，`source ∈ {bm25, ngram, fused}`。

## 没做完 / 已知问题

- **没做**：T-12 的真向量模型（本任务按 ticket 用字符 n-gram 替身，无新依赖）；真实通话转写样本的复测；同义词表仍是手工 11 组，未做自动挖掘。
- **Caveat（重要）**：40 条测评集为自拟/公开报道改编，黑样本信号与 `scripts.json` 有重合，1.000 是理想上界；真实转写文本（错字、口语、方言、上下文缺失）会掉。第 5 周必须换真实样本复测，不要把 1.000 当对外承诺。
- **最容易被漏判**：E016「我是派出所的，有个案子需要你配合调查，不要挂断」、E007「我是王总，换号了」、E020——共同点是只有 1 个身份类信号、没有转账/验证码等强动作，靠相似案例 + 会话上下文才过 L2。
- **T-08 引入的一段弯路**：混合检索把「只共享 2–3 个常用双字词」的日常话术（E025「我在地铁上，信号不太好，晚点回你电话。」）抬到案例相似度 0.2，engine 旧门禁 `< 0.2` 放行，accuracy 一度掉到 0.975。修法两步：① `search_cases` 的 score 改为只统计**多字词**覆盖（单字几乎每个案例都含，是虚高主因）；② 队长把 `CASE_MIN_SIM` 提到 **0.25**（`app/pipelines/decision/scoring.py:46`，不在本任务写权限内，由队长改）。两步后回到 1.000。
- 本次只跑了 scoped 测试（`tests/knowledge tests/eval`），未跑全量 pytest、未跑 `scripts/docs.py`（并行队友在改代码 / 文档门禁由队长统一跑）。

## 下次接手要知道什么

- **入口**：`app/pipelines/knowledge/store.py::KnowledgeBase.search_cases(text, top_k=2) -> list[tuple[Case, float, str]]`。第三个元素是召回来源，engine 已适配（`app/pipelines/decision/engine.py` 取 `row[2]`，写进 `evidence.meta.source` 与 `decision.cited_case_ids` 对应证据）。**改签名前后两元组/三元组不兼容，改完必须全队同步**。
- **门禁**：`app/pipelines/decision/scoring.py:46` 的 `CASE_MIN_SIM = 0.25` 是案例证据的最低相似度，**别降回 0.2**——0.2 是 E025 误报的直接原因。案例 score 是「多字词覆盖比例」（0–1），不是 RRF 原始分；RRF 原始分只有 0.01 量级，任何 <0.2 门禁都会全灭。
- **同义词只扩召回、不改变排名分数口径**：`expand_synonyms()` 把同组词加进 `query_terms`，命中同义词也计入分子，所以「验资 → 资金审查」能得分；但 score 分母同样包含扩展词，短句得分天然偏低（0.1–0.4），这是 0.25 门禁能同时挡住误报、又不误杀验收查询的原因。
- **重建索引**：`KnowledgeBase.reload()` 会重读 `scripts.json / cases.json / synonyms.json` 并重建 BM25 + `NGramIndex`；`add_case()` 也会重建两路索引。新增案例后不需要手动清缓存。
- **测试资产**：30 条查询在 `tests/knowledge/recall_queries.py`；出对比表跑 `tests/knowledge/selfcheck_hybrid.py`；T-01 自检跑 `tests/knowledge/selfcheck_retrieval.py`；pytest 断言在 `tests/knowledge/test_hybrid.py`（fused recall@3 ≥ 单路 +10 个百分点，当前 100% vs 86.7%，余量 13.3pp）。
- **已知死路**：纯字符 n-gram 对「今天天气不错」这类无意义查询仍可能有 BM25 假命中（C023/C019/C030），但 ngram/fused 为空 —— 最终 fused 返回空，别再给 BM25 单独开旁路。
- **文档**：`docs/tickets/T-08-混合检索-A.md` §2/§6 是队长冻结口径（source 用 `bm25|ngram|fused`），不要改成 `vector/hybrid`。
- 新案例 text 必须 20–80 字、写受害者听到的原话；`validate_cases()` 会查重复与 script_id 存在性，提交前跑一遍。

## 怎么验收

```
命令：$env:PYTHONPATH="."; & .\.venv\Scripts\python.exe -m pytest tests/knowledge tests/eval -q
输出：
........................                                                 [100%]

命令：& .\.venv\Scripts\python.exe -m ruff check app/kb app/pipelines/knowledge tests/knowledge tests/eval
输出：All checks passed!

命令：& .\.venv\Scripts\python.exe -m pytest tests/eval -q -s
输出（表头 + 前三行）：
| id | label | level | score | 判对? |
| --- | --- | --- | --- | --- |
| E001 | 1 | L2 | 79.2 | ✓ |
| E002 | 1 | L2 | 74.5 | ✓ |
| E003 | 1 | L2 | 76.0 | ✓ |
...
n=40 tp=20 fp=0 tn=20 fn=0 P=1.000 R=1.000 F1=1.000 accuracy=1.000

命令：$env:PYTHONPATH="."; & .\.venv\Scripts\python.exe tests\knowledge\selfcheck_retrieval.py
输出：scripts=15 cases=50；Top-1 自命中 50/50 = 100.0%

命令：$env:PYTHONPATH="."; & .\.venv\Scripts\python.exe tests\knowledge\selfcheck_hybrid.py
输出（三条查询对比）：
查询：把钱转到安全账户做资金审查
  bm25 : C021(S01, 49.20), C001(S01, 38.19), C036(S12, 16.80)
  ngram: C021(S01, 0.51), C001(S01, 0.35), C036(S12, 0.11)
  fused: C021(S01, 0.71, fused), C001(S01, 0.57, fused), C036(S12, 0.21, fused)
查询：快递丢件了怎么赔
  bm25 : C033(S11, 28.22), C008(S04, 15.34), C034(S11, 12.99)
  ngram: C033(S11, 0.41), C034(S11, 0.17), C008(S04, 0.17)
  fused: C033(S11, 0.44, fused), C032(S11, 0.22, fused), C034(S11, 0.33, fused)
查询：今天天气不错 → bm25 有 3 条假命中，ngram / fused 均为空
30 条查询 recall@3：bm25 26/30 = 86.7%；ngram 25/30 = 83.3%；fused 30/30 = 100.0%
```

文档门禁（`python scripts/docs.py check`）与全量 pytest 由队长统一跑；本回执未伪造这两条输出。

## 改动清单

- `app/kb/scripts.json`（T-01：新增 S11–S15，S08/S09 risk_base → 80；S05/S08 补 signal）
- `app/kb/cases.json`（T-01：C021–C050 共 30 条新案例）
- `app/kb/synonyms.json`（T-08：11 组同义词，新建）
- `app/kb/eval_set.csv` / `app/kb/eval_set_official.csv`（T-05：40 条 / 20 条测评集，新建）
- `app/pipelines/knowledge/validate.py`（T-01：`validate_cases` 结构校验，新建）
- `app/pipelines/knowledge/evalcheck.py`（T-05：`load_eval_set / validate_eval_set / measure`，新建）
- `app/pipelines/knowledge/hybrid.py`（T-08：`char_ngrams / load_synonyms / expand_synonyms / NGramIndex / rrf_fuse`，新建）
- `app/pipelines/knowledge/store.py`（T-08：`search_cases` 返回三元组；score 改为多字词覆盖；加载 synonyms、重建双索引）
- `tests/knowledge/test_kb_shape.py`、`tests/knowledge/selfcheck_retrieval.py`（T-01）
- `tests/knowledge/test_hybrid.py`、`tests/knowledge/recall_queries.py`、`tests/knowledge/selfcheck_hybrid.py`（T-08）
- `tests/eval/test_measurement.py`（T-05：6 条测试）
- `docs/tickets/T-01-知识库扩充.md`、`docs/tickets/T-05-eval-set-A.md`（按 ticket 要求补口径与实测）
- `docs/reports/2026-11-07-knowledge-A.md`（本回执）
