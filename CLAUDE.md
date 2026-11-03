# 本仓库的 AI 约定（给 Claude Code 等工具看的入口）

完整约定在 **`AGENTS.md`**，开工前必须先读它。本文件只做指路，不重复条款。

三条必记：

1. **一次只读 1–3 份文档，总量 ≤ 600 行**；先看 `docs/INDEX.md` 再决定读哪份。
2. **交付物是仓库里的文件**，不是聊天里的话；写完要 commit + push，任务回执写 `docs/reports/`。
3. **交付前跑两条命令**：`pwsh scripts/check.ps1 -Task all` 和 `python scripts/docs.py check`。

`docs/INDEX.md` 由 `python scripts/docs.py index` 生成，**不要手改**。
