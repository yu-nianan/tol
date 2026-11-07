---
title: 模块说明：decision（判定引擎与打分器）
owner: 队长
status: final
last_updated: 2026-11-07
summary: 吃多源 Evidence，吐一条 Decision（分数/等级/阶段/证据链/引用案例），是唯一的汇总层
audience: agent
depends_on: [../需求清单.md, ../decisions/ADR-0002-evidence-contract.md, ../tickets/T-07-打分器v2-队长.md]
---

# decision（判定引擎与打分器）

## 一句话职责

**吃 `Evidence` 列表 + 命中的 `ScriptHit`，吐一条 `Decision`**（分数、等级、阶段、理由、引用案例）。
所有"怎么算分"的逻辑都在这里，接口层与其它 pipeline 不许自己算分。

## 输入 / 输出

| 方向 | 类型 | 从哪里来 / 到哪里去 |
| --- | --- | --- |
| 入 | `Evidence` | `text/rules`（规则）、`text/llm`（模型）、`knowledge`（案例召回）、`memory`（上下文/画像） |
| 入 | `ScriptHit` | `knowledge.store.match_script` 的等价物；本模块用"整段对话命中信号数"重选剧本 |
| 出 | `Decision` | 交给 `api/detect`、`notify/guardian`、`notify/report_builder` |

## 关键实现与取舍

- **阶段优先，不等转账**：`stage_index` 1–4 单调不减；会话进入第 3 阶段（隔离）即按 `STAGE_FLOOR_SCORE=60`
  抬到 L2，理由写"会话已进入隔离/转账阶段，按阶段下限给到 60 分（不等转账字样）"。
- **剧本判定按"整段命中数"而不是"单词最高分"**：真实样本一句话通常只含每阶段 1 个信号
  （实测 S01 四阶段各 1/4、1/5），若按 `stage_score` 取最大，S01 立威里的"涉嫌洗钱"会被 S10 转账阶段抢走，
  把会话误推到第 4 阶段。因此 `_match_script` 先按剧本累计命中数选剧本，再取该剧本内阶段分最高者；
  `STAGE_MIN_HITS=2` / `STAGE_MIN_SIM=0.6` 只用于挡"单一通用词"。
- **幻觉抑制（FR-2.7）**：`cited_case_ids` 为空时分数封顶 `CAP_WITHOUT_EVIDENCE=60`（最高 L2），
  `cap_applied=True` 且理由进 `Decision.reasons`，报告里能看出"这次没找到相似案例"。
- **画像偏移只加一次**：角色 bias 由 `scoring.evaluate` 加；`memory.build_profile` 的 `bias` 只用于解释，
  engine 只叠加"近 30 天告警次数"带来的 `offset - bias`（每案 +2，最多 +8）。
- **告警冷却只压通知，不压告警记录**：`memory.should_notify` 30 分钟内同级或更高已推过就不再推，
  原因写进 `reasons`；但 `Alert` 仍然建、仍然落盘（否则第二通电话在报告里会凭空消失）。
  `ack_alert` 同时回写 sqlite（报告"通知记录"可见）。
- **案例召回门禁 `CASE_MIN_SIM=0.25`**：词覆盖率在短句上分辨率只到 0.2 的台阶（15 个词里重叠 3 个通用词
  "我在/电话/晚点"就能到 0.2），0.2 会把"我在地铁上，信号不太好"推成 L2；抬到 0.25 后白样本误报消失，
  30 条 recall@3 仍 30/30。代价是真实但只有 2–3 个词重叠的案例会被丢掉。

## 边界：不做什么

- 不做归一化/脱敏（`text/normalize` 的事）、不做检索（`knowledge` 的事）、不发通知（`notify` 的事）。
- 不调用外部模型接口：模型证据由 `text/llm.extract_evidence` 产出，本模块只消费。
- 不改 `app/schemas`：要加字段找队长走契约变更。

## 怎么测

- 单测位置：`tests/decision/`、`tests/test_scoring.py`、`tests/test_api.py`
- 一行可复制的命令：`python -m pytest tests/decision tests/test_scoring.py -q`

## 常见坑

- `ScriptHit.stage_score` 是 property（= `stage_weight`），而 `match_script` 会把 `stage_weight` 改写成
  加权后的系数；别从 `ScriptHit` 反解"命中比例"，要么查库、要么在选剧本时直接算。
- `Settings` 是 frozen dataclass，测试里 `monkeypatch.setattr(llm.settings, ...)` 会 `FrozenInstanceError`，
  用 `types.SimpleNamespace` 整个替换。
- 同一句话在会话里重复出现，分数不应因轮次上涨（证据去重 + 不按轮次加分），`test_no_round_bonus_within_session` 守着。

## 改动须知

改阈值/权重会同时影响 `tests/decision`、`tests/test_api`、`scripts/smoke.py` 与 T-04 前端的等级配色；
动 `Decision` 字段必须找队长改 `app/schemas/alert.py` 并公告契约变更。
