---
title: 前端三屏交付回执（T-04 / 负责人 D）
owner: D
status: final
last_updated: 2026-11-07
related_code: [frontend/index.html, frontend/app.js, frontend/style.css]
summary: 完成检测 / 告警 / 报告三屏、使用指南与演示脚本，并在 8123 端口完成接口与 420px 自测
audience: both
depends_on: [../INDEX.md]
---

# T-04 前端三屏交付回执

- 工具：DSH agent（负责人 D 代理）
- 契约变更：无（未改 `app/**`、`app/schemas/**`、`docs/INDEX.md`）
- 对应任务：`task-4`；需求 `FR-3.1 / FR-3.3 / FR-3.4 / FR-3.7 / FR-5.4`

## 做了什么

1. 新增 `frontend/style.css`、`frontend/app.js`、`frontend/index.html`，实现三屏 hash 路由：
   - `#/detect`：粘贴框、角色下拉（normal / elder / child / student / finance）、三个预设（正常消息 / 冒充公检法 / 客服退款）、L0 时诚实提示「仅记录、不生成告警」；
   - `#/alert/<alert_id>`：L0 灰 `#6b7280`、L1 蓝 `#1e70c0`、L2 橙 `#ef6c00`、L3 红 `#c62828` 色条，证据（label + 原文 + 权重 / 置信度 / 来源）、判定理由、`我已介入(ack)` / `误报，忽略(dismiss)` / `生成报告`；
   - `#/report/<session_id>`：五段（风险概述 / 证据链 / 剧本匹配 / 处置建议 / 通报记录）+ `打印 / 导出 PDF`（`window.print()`）。
2. 接口全部使用同源相对路径 `/api/v1/...`；告警页优先用 `sessionStorage` 里本次检测的 `decision.evidence`，缺失时回退到报告 `evidence_chain`。
3. 修正 `report.notifications` 渲染：它是事件数组（`notify` / `ack`），按通道显示 `recorded` / `skipped` / `acked`，未配置 webhook 时如实显示「未推送（降级）」，不伪造已发送。
4. 新增 `docs/使用指南.md`（安装 / 配置 / 三步操作 / 9 条常见问题）、`docs/演示脚本.md`（5 分钟六幕分镜，含 webhook 未配置的降级话术）。
5. 在 8123 端口完成接口自测与 420px 无横向滚动验证（见下）。

> 说明：`app/api/web.py` 的 `GET /` 只返回 `frontend/index.html`，仓库没有静态文件路由，因此 `index.html` 内联了同一份 CSS / JS；`app.js`、`style.css` 仍是可维护的源文件。**未改后端**。

## 没做完

1. **`docs/INDEX.md` 未重建**：新增两份文档后 `python scripts/docs.py check` 预期会红。按任务边界我不能跑 `scripts/docs.py`，请队长执行 `python scripts/docs.py index`（或 `fix`）后一起提交。
2. **未提交 git**：按任务要求提交由队长统一做。当前工作区有大量其他同学的改动（见「怎么验收」里的说明），提交时只挑本回执「改动清单」中的文件。
3. **监护人真实推送未验证**：本机未配置 `GUARDIAN_WEBHOOK`，只验证了 `guardian · skipped` 的降级路径；真实 webhook 需在有群机器人的环境补测。
4. **未提交截图 / 视频**：按要求不把真实截图入库；自测截图仅存在于 `%TEMP%`，需要时可按「怎么验收」重新生成。
5. 未做前端单元测试（仓库无前端测试设施，T-04 验收也不要求）；交互用无头 Chrome 实测。

## 下次接手要知道什么

1. **改样式 / 脚本后必须重新内联**，否则页面不会变。在仓库根目录执行：

   ```powershell
   $root = (Get-Location).Path
   $idx  = Join-Path $root 'frontend\index.html'
   $css  = [IO.File]::ReadAllText((Join-Path $root 'frontend\style.css'))
   $js   = [IO.File]::ReadAllText((Join-Path $root 'frontend\app.js'))
   $html = [IO.File]::ReadAllText($idx)
   $s = $html.IndexOf('<style>') + 7; $e = $html.IndexOf('</style>')
   $html = $html.Substring(0, $s) + "`n" + $css + "`n" + $html.Substring($e)
   $s = $html.IndexOf('<script>') + 8; $e = $html.LastIndexOf('</script>')
   $html = $html.Substring(0, $s) + "`n" + $js + "`n" + $html.Substring($e)
   [IO.File]::WriteAllText($idx, $html, (New-Object Text.UTF8Encoding($false)))
   ```

   内联后 `frontend/index.html` 约 42 KB；`node --check frontend/app.js` 可先做语法检查。若后续在 `app/main.py` 挂了 `StaticFiles`，可把内联改回 `<link>` / `<script src>`，但那是队长侧改动。

2. **告警与报告存在进程内存**：重启 uvicorn 后旧 `alert_id` / `session_id` 会 404，重新检测即可；不要把它当持久化存储。
3. **等级与角色偏移以 `app/schemas/alert.py` 为准**：阈值 85 / 60 / 35；角色偏移 elder +8、child +10、student +5、finance −3；无证据封顶 60。前端只展示，不重复算分。
4. **`report.notifications` 是事件数组**，不是扁平通道列表；新增通道时在 `notify` 事件的 `channels[]` 里加一项，前端会自动出 chip。
5. **420px 验证方法**：Chrome 最小窗口宽约 500 CSS px，直接 `--window-size=420` 不准；用 CDP `Emulation.setDeviceMetricsOverride {width:420,mobile:true}`，读 `document.documentElement.scrollWidth` 应为 420。
6. **诚实性约束**：L0 不显示告警；webhook 未配必须显示 `skipped`；空证据要写「没有可展示的证据」，不要用占位假数据。

## 怎么验收

环境：`E:\deepseek\服务外部自测试\tol`，解释器 `.\.venv\Scripts\python.exe`。

1. 起服务：

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8123
   ```

2. 首页不是兜底页：

   ```text
   GET / status=200 bytes=42348 title=True
   ```

   （`title=True` 指 HTML 含「反诈智能助手 · 三屏演示（检测 / 告警 / 报告）」，且含 `<style>` 与内联脚本。）

3. 健康检查：

   ```text
   HEALTH={"status":"ok","version":"0.1.0","kb_scripts":15,"kb_cases":50,"llm_enabled":false,"asr_enabled":false,"ocr_enabled":false}
   ```

4. 正常文本 → L0 且 `alert=null`：

   ```text
   NORMAL level=0 score=7.5 alertIsNull=True reasons=1 evidence=0
   ```

5. 冒充公检法（role=elder）→ L3 且有 alert：

   ```text
   SCAM level=3 score=87.3 alert=A092a125f1c status=open script=冒充公检法 stage=诱导转账 evidence=6 needHuman=True
   GET ALERT id=A092a125f1c level=3 score=87.3 status=open script=冒充公检法
   ```

6. 报告有建议、证据与通报记录：

   ```text
   REPORT session=selftest-D-final-l3 level=3 advice=3 evidence=6 notifications=1 turns=1
   ADVICE1=立即挂断，拨打 96110 或 110 核实
   ```

7. ack 回写：

   ```text
   ACK id=A092a125f1c status=acked
   ```

8. 420px 三屏不横向滚动（CDP 实测）：

   ```text
   #/detect  innerWidth=420 scrollWidth=420 title=反诈智能助手 · 检测
   #/alert/… innerWidth=420 scrollWidth=420 title=反诈智能助手 · 告警
   #/report/… innerWidth=420 scrollWidth=420 title=反诈智能助手 · 报告
   ```

9. 前端语法与「未引入 Python 文件」：

   ```text
   node --check frontend/app.js   # 通过，无输出
   ruff check .                   # Found 1 error：tests\knowledge\selfcheck_hybrid.py:10:1 I001
   ```

   `tests/knowledge/selfcheck_hybrid.py` 是其他人的文件；本任务只新增 `frontend/**` 与 `docs/*.md`，没有新增或修改任何 Python 文件。

10. 只看本任务范围的 git 状态：

    ```text
    ?? "docs/使用指南.md"
    ?? "docs/演示脚本.md"
    ?? frontend/
    ```

    注意：完整 `git status --short` 还会出现其他同学并行改动（`app/**`、`docs/tickets/**`、`tests/**`、`scripts/**` 等），**不是本任务造成的**；提交时请只挑上面三项（以及本回执）。

11. 建议队长补跑：

    ```powershell
    .\.venv\Scripts\python.exe scripts\docs.py index
    .\.venv\Scripts\python.exe scripts\docs.py check
    ```

## 改动清单

| 文件 | 大小 | 说明 |
|---|---|---|
| `frontend/index.html` | 42348 B | 三屏单页，内联 CSS/JS（后端只返回这一个文件） |
| `frontend/app.js` | 29154 B | 原生 JS：hash 路由、三屏渲染、fetch、ack、打印、转义 |
| `frontend/style.css` | 11477 B | 等级色、卡片、420px 媒体查询、打印样式 |
| `docs/使用指南.md` | 8844 B | 安装 / 配置 / 三步操作 / 常见问题（FR-5.4） |
| `docs/演示脚本.md` | 8683 B | 5 分钟六幕分镜（含降级话术） |
| `docs/reports/2026-11-07-frontend-D.md` | 本文件 | 任务回执 |

未改：`app/**`、`app/schemas/**`、`docs/INDEX.md`、`AGENTS.md`、`OWNERS.md`、`.github/**`、`scripts/**`、`docker/**`。
