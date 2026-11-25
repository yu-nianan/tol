---
title: ADR-0006 Decision 增加 dims：维度贡献由后端给，前端不许重算
owner: 队长
status: final
last_updated: 2026-11-25
related_code: app/schemas/alert.py, app/pipelines/decision/engine.py, frontend/app.js
summary: 打分器早就把六维得分率算出来了，只是被 engine 丢掉；原型的"维度贡献"要么加字段、要么前端复制权重，选加字段
audience: both
depends_on: [../INDEX.md, ADR-0002-evidence-contract.md]
---

# ADR-0006 · Decision 增加 dims：维度贡献由后端给，前端不许重算

- **状态**：生效（2026-11-25）
- **一句话**：`Decision` 新增 `dims`（各维度得分率 0–1），因为"这一分是怎么来的"属于后端知识，前端复算必然与 `scoring.py` 漂移。

## 背景

接入原型前端时，结果卡要展示"维度贡献"（阶段 / 实体 / 压力 / 跨模态 / 渠道 / 画像各贡献多少）。核查发现：

1. `app/pipelines/decision/scoring.py` 的 `evaluate()` 第 155 行**已经返回** `dims`；
2. `app/pipelines/decision/engine.py` 第 147 行写的是 `score, reasons, _dims, cap_applied = evaluate(...)`——**下划线把 dims 丢了**；
3. 前端能拿到的只有 `evidence[]` 和 `reasons[]`，拿不到聚合后的维度得分。

两种走法：前端按 `evidence[].weight × confidence` 自己聚合（等于把 `scoring.py` 的六维权重、归一化规则、`profile` 维度复制一份到 JS），或者后端把算好的 `dims` 交出来。前者是典型的"两份真相"，只要后端改一次权重口径，页面就和分数对不上，而且没人会发现。

## 决定

1. `Decision` 增加 `dims: dict[str, float]`，键就是 `scoring.DIM_WEIGHTS` 里的维度名（`stage/entity/pressure/cross/channel/profile`），值是 **0–1 的得分率**（不是加权后的分数）。
2. `engine.py` 只做两件事：去掉 `None`（缺失维度不出现，与"不参与归一化"保持一致）、保留三位小数。**权重与聚合口径仍然只在 `scoring.py`**。
3. 前端在没有 `dims` 时显示"后端未提供维度（ADR-0006）"，**不许本地估算**。
4. 契约字段只加不改：老客户端不带 `dims` 也能跑，属于兼容变更，不需要改版本号。

## 代价

- 契约多一个字段，`Decision` 的 payload 大约多 80 字节，可忽略；
- `dims` 是聚合值，`evidence` 是原始条目，两者可能被问"为什么维度有分但证据里没看到对应条目"——因为同一维度可能由多条弱证据累积，答题口径已写进 T-15 §8；
- 前端多一条"字段缺失怎么显示"的分支。

## 什么情况才推翻

如果将来要做"每一维对应哪几条证据"的强解释（`dims` 变成 `dims_detail[{dim, score, evidence_ids}]`），就用新字段替代并保留 `dims` 一个版本做兼容；单独为了省 80 字节而回退到前端重算是**不接受**的。
