# A30 多模态反诈智能助手 · 项目骨架

> 赛题：基于多模态的反诈智能助手（浙江工业大学）
> 目标：**今天就能跑起来**的骨架 —— 规则能判别、知识库能召回、报告能生成、接口能联调；
> 模型 / ASR / OCR 留了明确的接入点，接进来不用改下游。

---

## 1. 三条命令（做完才算开发过）

```powershell
cd a30-fraud-assistant
python -m pip install -r requirements.txt

# 起服务（自动挑一个"装好依赖"的解释器，并把浏览器打开）
.\scripts\start.ps1 -Open

# 另一个终端：自检
pwsh scripts/check.ps1 -Task all
```

预期看到：

```
[PASS] lint (ruff)
[PASS] test (pytest)
[PASS] smoke
结果：全绿。把这段输出整段贴进 PR 描述。
```

浏览器打开 <http://127.0.0.1:8000> 是自带演示页（无需前端构建）；
打开 <http://127.0.0.1:8000/docs> 是自动生成的接口文档。

> 没有 `pwsh` 的机器：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task all`
> 机器有多个 Python：`.\scripts\start.ps1 -Python "C:\Python311\python.exe"`

### 网页打不开？按这四条排

| 现象 | 原因 | 解决 |
|---|---|---|
| 浏览器提示"无法访问此网站 / 拒绝连接" | 服务根本没起来（最常见） | 先开一个终端跑 `.\scripts\start.ps1`，看到绿色的地址再开浏览器 |
| 终端报 `No module named 'fastapi'`（或 uvicorn） | 你的 `python` 指向另一个没装依赖的解释器 | 用 `start.ps1`（会自动挑对的），或 `start.ps1 -Python "C:\Python311\python.exe"` |
| 终端报 `[Errno 10048] 端口已被占用` | 8000 被别的程序占了 | `.\scripts\start.ps1 -Port 8010`，地址相应变成 `http://127.0.0.1:8010` |
| 打开的是文件路径（`file:///...`）而不是网址 | 直接双击了 `.py` 或 `.md` 文件 | 地址栏必须是 `http://127.0.0.1:8000` |

> 关掉那个终端窗口 = 服务停止。要长期挂着，就让它一直开着，或第 6 周用 Docker 跑。

---

## 2. 现在能做什么 / 还没做什么

| 能力 | 状态 | 说明 |
|---|---|---|
| 文本检测（12 类话术 → 证据） | ✅ 可跑 | `app/pipelines/text/rules.py` |
| 剧本阶段判定（10 类剧本 × 3–4 阶段） | ✅ 可跑 | `app/kb/scripts.json` |
| 案例召回（BM25，纯 Python） | ✅ 可跑 | `app/pipelines/knowledge/store.py` |
| 融合打分 + 分级（L0–L3） | ✅ 可跑 | `app/pipelines/decision/scoring.py` |
| 告警 + 监护人推送 | ✅ 降级可用 | 没配 webhook 时只记日志，并如实返回 `skipped` |
| 报告（结论/证据链/剧本/建议） | ✅ 可跑 | `app/pipelines/notify/report_builder.py` |
| 案例入库（自更新链路） | ✅ 可跑 | `POST /api/v1/kb/cases`，去重 |
| 音频检测 | ⛔ 501 | 等 `app/pipelines/audio/asr.py` 接入 FunASR |
| 图片检测 | ⛔ 501 | 等 `app/pipelines/vision/ocr.py` 接入 RapidOCR |
| 大模型增强 | ⛔ 未接 | 配 `LLM_BASE_URL/LLM_API_KEY` 后按证据格式补一条 `kind=model` 的证据即可 |

**刻意不用假数据冒充已完成**：音频/图片现在返回 501 + 明确提示，答辩时说"第 3 周接入"比"演示时假装能用"体面得多。

---

## 3. 目录结构

```
app/
  main.py                 入口（只做组装）
  api/                    health / detect / alerts / kb / web
  pipelines/
    text/                 normalize（归一化+脱敏）、rules（12 类话术）
    knowledge/            store（剧本 + BM25 案例召回）
    decision/             scoring（加权打分）、engine（串流程）
    notify/               guardian（推送）、report_builder（报告）
    audio/ vision/        ASR / OCR 接入点（现在是 501）
  core/                   config（环境变量）、logging（JSON 日志）、errors
  schemas/                ★ 契约：Evidence / Decision / Alert / Report / API
  kb/                     scripts.json（10 类剧本）、cases.json（20 条案例）
tests/                    normalize / rules / scoring / api
scripts/                  check.ps1（三条命令）、smoke.py（5 项冒烟）
data/samples/             3 条测试文本
```

---

## 4. 接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 健康检查（含知识库规模、模型/ASR/OCR 是否就绪） |
| POST | `/api/v1/detect/text` | 文本检测 → 分数 / 等级 / 剧本 / 证据 |
| POST | `/api/v1/detect/audio` | 音频检测（现在 501） |
| POST | `/api/v1/detect/image` | 图片检测（现在 501） |
| GET | `/api/v1/report/{session_id}` | 会话报告 |
| GET | `/api/v1/alerts/{id}` · POST `/api/v1/alerts/{id}/ack` | 查询 / 确认告警 |
| GET | `/api/v1/kb/scripts` · `/api/v1/kb/cases` · POST `/api/v1/kb/cases` | 知识库查看与入库 |
| GET | `/api/v1/stats` | 运行概览 |

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/detect/text \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"我是公安，你的卡涉嫌洗钱，把钱转到安全账户\",\"role\":\"elder\"}"
```

---

## 5. 打分怎么算（评委一定会问）

```
score = clip( Σ wᵢ·sᵢ  +  b_profile , 0, 100 )
w = stage .30 | entity .20 | pressure .15 | cross .15 | channel .10 | profile .10
b_profile = 老人 +8 | 儿童 +10 | 学生 +5 | 财务 −3
分级：≥85 L3 紧急 ｜ ≥60 L2 警告 ｜ ≥35 L1 提醒 ｜ 否则 L0 仅记录
```

三条硬规则（都在 `scoring.py` 里，改一处即可）：

1. **没有剧本 / 案例证据支撑时，分数封顶 60** —— 压模型幻觉；
2. **缺失的维度不参与归一化**（纯文本没有"多模态一致性"，不因此被拉低）；
3. **画像只改敏感度，不改阈值表** —— 同一分数不同人群不同等级，但规则可解释、可测试。

---

## 6. 八周怎么往上长

| 周 | 骨架上的增量 | 落地文件 |
|---|---|---|
| W2 | 骨架全绿（本文档） | — |
| W3 | 文本链路接大模型：输出 `kind=model` 的证据 | `pipelines/text/llm.py`（新建） |
| W3 | ASR：VAD 切段 + 转写，置信度低则丢弃 | `pipelines/audio/asr.py` |
| W4 | OCR：截图 → 文本 → 界面类型字段 | `pipelines/vision/ocr.py` |
| W4 | 向量检索替换 BM25（接口不变） | `pipelines/knowledge/store.py` |
| W5 | 分级策略前端化 + 监护人推送接真实渠道 | `api/alerts.py`、`notify/guardian.py` |
| W6 | 评测脚本 + 100 条测评集 + 压测 | `scripts/eval.py`（新建） |
| W7 | 演示脚本 + 录制 | `docs/demo.md`（新建） |

---

## 7. 不要做的事（会影响答辩）

- 不要为了"跑通"把规则注释掉返回固定分数（`AGENTS.md` 里是硬性禁令）；
- 不要在报告里写没发生的推送（没配 webhook 就写"降级为日志"）；
- 不要改 `app/schemas/` 的字段名来图省事 —— 那是全队的接口契约；
- 不要把真实手机号、身份证、银行卡写进测试数据（`normalize.mask_sensitive` 已经做了脱敏，但源数据也别留）。

---

## 8. Docker（第 6 周再用）

```bash
cd docker
docker compose up --build
# 打开 http://127.0.0.1:8000
```

---

## 9. 仓库与团队文档

仓库：<https://github.com/yu-nianan/tol>（默认分支 `main`）

| 文档 | 内容 | 谁看 |
|---|---|---|
| [AGENTS.md](AGENTS.md) | AI 智能体入职须知：能改哪、7 条硬性禁令、怎样算做完 | 每个人（开工前必读） |
| [OWNERS.md](OWNERS.md) | 目录 → 负责人 → 可写/只读，跨模块需求流程 | 每个人 |
| [docs/需求清单.md](docs/需求清单.md) | 28 条功能需求 + 10 条非功能 + 11 项交付物 + 待确认 8 问 | 队长、A |
| [docs/技术学习路线.md](docs/技术学习路线.md) | 21 项技术、5 个里程碑、模块×技术对照 | A/B/C/D |
| [docs/测试方案.md](docs/测试方案.md) | 测试策略、用例、测评集口径 | C、队长 |
| [docs/协作机制说明.md](docs/协作机制说明.md) | 公告话术、认领会脚本、培训脚本、日历 | 队长 |
| [docs/decisions.md](docs/decisions.md) | 技术决策记录（只追加） | 队长 |
| [docs/tickets/模板.md](docs/tickets/模板.md) | 任务单模板（9 段） | 派活的人 |

**自动化**：每次 push / PR，GitHub Actions 会自动跑 `ruff` + `pytest` + 冒烟（[ci.yml](.github/workflows/ci.yml)）。
CI 红了就是不可合并 —— 这条比"记得跑一下"可靠。

分支规矩（见 AGENTS.md §6）：`main` 只放能跑的版本，开发一律走 `feature/<模块>-<短描述>`，PR 必须贴三条命令输出。

---

## 10. 下一步

- 想接大模型：看 `docs/tickets/T-01-接入大模型.md`（待写）
- 想接 ASR：看 `app/pipelines/audio/asr.py` 顶部注释里的实现顺序
- 想加案例：直接 `POST /api/v1/kb/cases`，或编辑 `app/kb/cases.json` 后重启

> 免责声明：本项目为教学与竞赛演练用途，输出不构成法律意见，真实遇骗请拨打 96110。
