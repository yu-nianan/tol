# GitHub Copilot 指令（入口）

完整约定在仓库根目录的 `AGENTS.md`，动手前先读它。本文件只做指路。

必记三条：

1. 一次只读 1–3 份文档、总量 ≤ 600 行；先看 `docs/INDEX.md` 再决定读哪份。
2. 交付物是仓库里的文件，不是聊天里的话；写完 commit + push，任务回执写 `docs/reports/`。
3. 交付前跑 `pwsh scripts/check.ps1 -Task all` 与 `python scripts/docs.py check`。

`docs/INDEX.md` 由 `python scripts/docs.py index` 生成，禁止手改。
