---
title: ADR-0001 后端用 FastAPI
owner: 队长
status: final
last_updated: 2026-11-02
related_code: app/api
summary: 后端统一 FastAPI + Pydantic，不用 Flask/Django
audience: agent
depends_on: [../../AGENTS.md]
---

# ADR-0001 · 后端用 FastAPI

- **状态**：已采纳（2026-11-02）
- **决定**：后端统一 FastAPI + Pydantic，不用 Flask/Django。
- **理由**：自动生成 `/docs` 交互文档，零基础同学也能照示例调接口；契约即代码，与 `app/schemas` 一致。
- **影响**：负责人 A/B/C 都要写 APIRouter；智能体提示词里指定 FastAPI 写法。
- **复核**：若第 3 周出现"路由注册冲突"，再考虑拆服务。

## 代价（写清，免得以后有人以为没成本）

- 同步框架，重计算任务要自己丢后台（`run_in_executor`），不能指望 async 天然解决。
- Pydantic 校验失败时返回 422 而不是 400，前端要按 422 处理。
