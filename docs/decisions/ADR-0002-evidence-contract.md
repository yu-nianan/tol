---
title: ADR-0002 模块之间只传 Evidence / Decision
owner: 队长
status: final
last_updated: 2026-11-02
related_code: app/schemas
summary: 禁止跨模块 import 内部实现，交接只用 app/schemas 的模型
audience: agent
depends_on: [ADR-0001-fastapi.md, ../../AGENTS.md]
---

# ADR-0002 · 模块之间只传 Evidence / Decision

- **状态**：已采纳（2026-11-02）
- **决定**：禁止直接 import 其他模块内部实现，交接只用 `app/schemas` 的模型。
- **理由**：五个人并行开发，没有统一交接物必然对不上；也让契约成为唯一需要 review 的地方。
- **影响**：所有人；改契约需队长公告。
- **复核**：第 5 周联调时若发现字段不足，集中加一次。

## 为什么不是"各自定义 dict"

dict 看起来省事，但字段名一错就是运行期 KeyError，而且没人知道谁该负责。
用 Pydantic 模型，字段错在启动期就报错，责任在契约上，不在调用方。

## 怎么判断你越界了

任务单里没写你能改 `app/schemas/`，而你的代码里出现了 `from app.pipelines.vision.ocr import ...` ——
这就是越界，改成 `from app.schemas import Evidence`。
