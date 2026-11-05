---
title: ADR-0004 模块边界暂缓，等"改 A 断 B"的症状出现再做
owner: 队长
status: draft
last_updated: 2026-11-05
related_code: app/api/**, app/pipelines/**/__init__.py
summary: 现在不改模块结构，只记录触发条件；命中后再做"包入口 + 架构测试"这一步，40 行改动
audience: both
depends_on: [../../AGENTS.md, ADR-0003-check-commands.md]
---

# ADR-0004 · 模块边界暂缓，等"改 A 断 B"的症状出现再做

- **状态**：暂缓（2026-11-05 记录，W2 复盘复核）
- **一句话**：现在不改模块结构，先记触发条件；症状出现再做"包入口 + 架构测试"，40 行改动、1 小时。

## 背景

5 个人和各自的 agent 同时改一个仓库，`app/api` 现在直接 import 别人模块的**内部文件**：

```
app/api/detect.py  →  from app.pipelines.audio.asr import transcribe
app/api/detect.py  →  from app.pipelines.vision.ocr import extract_text
app/api/health.py  →  from app.pipelines.audio.asr import ASR_ENABLED
app/api/alerts.py  →  from app.pipelines.decision.engine import get_engine
```

风险很具体：C 把 `transcribe` 改个名字（正常重构），演示页当场 500，而报错里看不出是谁改的。
AGENTS.md 第 5 节第 5 条写着"不许跨模块 import 内部实现"，但目前**没有机器在拦它**。

队长还没学到这块技术，无法当场判断要不要改。**不硬拍板**，改为把决定挂到一个不需要懂架构就能观察的症状上。

## 决定

现在**不做**任何模块化改造：不加包入口、不写架构测试、不调目录。

## 理由（代价不对称）

| 时机 | 成本 | 最坏结果 |
| --- | --- | --- |
| 现在做 | 约 10 分钟 | 多 6 个 3 行的文件，不影响功能 |
| 到 W6 做 | 半天以上 | api、测试、文档都长在旧写法上，回头修十几处 |

便宜且可逆，但**不紧急**：8 周里唯一的硬目标是"链路能跑起来、能录视频"。
在没有症状时投入，挤占的是真正关键的时间（M1 链路、评测集、演示视频）。

## 触发条件（任一命中就执行"最小一步"）

| # | 症状（不需要懂架构就能观察） | 在哪看 |
| --- | --- | --- |
| 1 | 改了一个模块，另一个模块报错（演示页 500 / 测试变红） | 每周五复盘时问一句"这周有没有互相踩过" |
| 2 | 同一个文件一周内出现 ≥2 次合并冲突 | PR 冲突记录、`git log --merges` |
| 3 | 单文件 > 300 行，且改一处要读三处 | 改的人自己在任务单评论里报 |

没命中就不做，W4 再看一次。

## 触发后执行什么（届时另开 PR，不在此条内）

1. 每个 `app/pipelines/<模块>/__init__.py` 只导出对外入口（约 3 行）；
2. `app/api/*.py` 改成 `from app.pipelines.<模块> import <入口>`；
3. 加 `tests/test_architecture.py`：AST 检查「pipelines 不许跨模块 import」「api 不许越过包边界」；
4. 同步 `docs/modules/<模块>.md` 三行说明（吃什么 / 吐什么 / 谁负责）。

不新增依赖，不改业务逻辑，不动 `app/schemas`。

## 明确不做的（避免以后重复讨论）

- 拆微服务 / 多进程；事件总线 / 消息队列；DI 容器 / 抽象基类；
- 为"将来可能换模型"预写适配层。

理由：一个 uvicorn 进程跑完所有事，8 周内没有第二个部署单元的需求；
边界还没稳定就抽象，等于把错误固化下来。

## 影响

- 本周零代码改动，`app/api` 维持现状。
- 若触发，改动只落在 api 层 import 与 6 个 `__init__.py`，其它模块不受影响。

## 复核

- W2 复盘（约 2026-11-19）：三条触发条件是否命中；未命中则继续暂缓，W4 再看一次。
