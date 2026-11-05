# AGENTS.md —— 给 AI 编程智能体的入职须知

> 本文件是团队的**唯一权威约定**。与任务单冲突时以任务单为准；与"你觉得更优雅"冲突时以本文件为准。
> 人看不懂代码没关系，但**下面四条命令必须全绿**，否则不算做完。
> 本文件的旧版方案（会议流程稿）在 `docs/archive/协作机制说明.md`，只作历史参考。

---

## 0. 开工前按这个顺序读（不要多读）

1. 本文件（你已经在这）
2. `docs/INDEX.md` —— 找到「你负责的模块」那一行
3. `docs/tickets/<你的任务单>.md` —— 你这次只做这一件事
4. `OWNERS.md` —— 你被允许改哪些目录
5. `app/schemas/*.py` —— 模块之间唯一合法的交接格式

**读取上限：一次不超过 3 份文档、总量不超过 600 行。**
超了说明任务切得太大，先找队长拆任务，不要硬读。
文档没写到的背景 ≠ 你可以编；缺了就按第 9 节开 Issue，继续做能做的部分。

---

## 1. 项目地图

```
app/
  main.py               # 入口（禁止修改，要加路由用 include_router）
  api/                  # 路由层：只做参数校验 + 调 pipeline，不写业务
  pipelines/            # 业务链路
    text/               # 文本预处理、规则、Prompt
    audio/              # VAD / ASR
    vision/             # OCR / 截图解析
    decision/           # 打分、阶段判定、融合
    knowledge/          # 剧本库、案例库、检索、入库流水线
    notify/             # 监护人推送、报告生成
  core/                 # 配置、日志、异常、依赖注入
  schemas/              # ★ 契约，只有队长能改
  kb/                   # 知识库数据（剧本、案例）
tests/                  # pytest，按模块建子目录
data/                   # 测试素材（不入库，见 .gitignore）
docs/
  INDEX.md              # ★ 自动生成，禁止手改
  需求清单.md            # 需求基线（28 FR / 10 NFR / 11 交付物）
  技术学习路线.md         # 学什么、按什么顺序学
  测试方案.md            # 用例与指标口径
  modules/              # 每个模块一份说明（新增文档放这里）
  decisions/            # ADR-0001.. 一条决策一个文件
  reports/              # 任务回执（每完成一个任务一份）
  tickets/              # 任务单（派活用）
  archive/              # 归档，不再维护
scripts/
  check.ps1             # 三条代码命令的入口
  docs.py               # 文档门禁：index / check / fix
  smoke.py              # 冒烟脚本
docker/                 # compose 与 Dockerfile
```

---

## 2. 只允许改这些路径

- 你任务单里写明的路径
- 你负责模块目录下的 `tests/`
- 你负责的 `docs/modules/<模块>.md` 与 `docs/reports/` 里你自己的回执

**一律不许碰**（碰了就是越界，PR 会被打回）：

```
app/schemas/**      ← 契约，只有队长改
app/main.py
app/core/**
docker/**
scripts/**
Makefile
docs/INDEX.md       ← 自动生成，手改必冲突
AGENTS.md  OWNERS.md  .github/**
```

要改契约或入口：在任务单评论里写「申请：改 X 的 Y，理由 Z」，等队长改。

---

## 3. 三条命令（交付前必须全部通过）

```powershell
pwsh scripts/check.ps1 -Task lint     # 风格与明显错误
pwsh scripts/check.ps1 -Task test     # 单元测试
pwsh scripts/check.ps1 -Task smoke    # 冒烟：服务能起、能判别、10s 内返回
```

没有 `pwsh` 的机器（只装了 Windows PowerShell）用这个等价写法：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task all
```

机器上有多个 Python、报"没装 ruff"时，显式指定解释器：`-Python "C:\Python311\python.exe"`。
有 `make` 的机器上等价于 `make lint / test / smoke`。

**PR 描述里必须粘贴三条命令的完整输出**（不只是最后一行）。没贴 = 未完成。

**`main` 分支的保护规则（重要）**：人工审批数为 **0**（GitHub 不允许自己批自己，所以不要求人批），
能否合并完全由 CI 决定——`check`（ci.yml）与 `docs`（docs.yml）两个必需检查全绿才能合入。
因此「本地四条命令全绿」和「PR 能合」是同一件事，不要指望有人点 Approve。
CODEOWNERS 目前只用于指派 reviewer，**没有**开启"必须 code owner 批准"。

---

## 4. 第四条命令：文档门禁

```powershell
python scripts/docs.py check
```

它检查六件事，任何一件不合规都会红：

| 检查 | 说明 | 能自动修 |
| --- | --- | --- |
| front-matter | 每份文档开头必须有 `title / owner / status / last_updated / summary / audience` | ✅ `--fix`（owner 除外） |
| owner 代号 | `owner` 只能是 `队长 / A / B / C / D`（见 `scripts/owners.txt`），不许填空、真名、工具名 | ❌ 必须手填 |
| INDEX 一致 | `docs/INDEX.md` 必须与磁盘一致 | ✅ 重跑 `index` |
| 死链 | 正文 `[文字](相对路径)` 与 front-matter `depends_on` 指向的文件都必须存在 | ❌ |
| 合规 | 密钥、真实手机号/身份证、竞赛匿名词 | ❌ 人工改 |
| 回执完整 | `docs/reports/` 里必须有四节：做了什么 / 没做完 / 下次接手 / 怎么验收 | ✅ 补空节 |

**`owner` 永远填人（代号），不填工具。** 你用的 agent 叫什么不重要，署名必须是负责的人；
要记录工具，写在回执正文的「工具：」一行里。

卡住就按提示修，或跑一次：

```powershell
python scripts/docs.py fix      # 补 front-matter、补小节、重建 INDEX
python scripts/docs.py index    # 只重建索引
```

---

## 5. 硬性禁令

1. **不许新增依赖。** 需要新库 → 在任务单写「申请依赖：包名，用途，不装的替代方案」，等批准。
2. **不许提交密钥、token、真实手机号、真实人名、真实身份证。** 示例数据一律用 `138****0000`、`张*`。
3. **不许用硬编码结果"通过测试"。** 不许 `return {"score": 90}`；不许把真实模型调用注释掉再返回假数据。演示用的假数据必须放在 `data/` 并在 PR 里写明"此处为演示数据"。
4. **不许改契约字段名或类型。** 缺字段就提 issue，不要自己加。
5. **不许跨模块 import 内部实现。** 只能 `from app.schemas import ...` 或调用对方模块暴露的 `run()`。
6. **不许为了让测试通过而改测试断言**；不许 `try/except: pass` 吞异常。
7. **不许 `git push --force`、不许直接推 `main`。**
8. **不许手改 `docs/INDEX.md`**；不许在文档里编造没写过的项目背景。

---

## 6. 什么算"做完了"（DoD，五条缺一不可）

1. 三条代码命令全绿；
2. `python scripts/docs.py check` 通过；
3. 你改的核心函数至少有 1 个正例 + 1 个反例的单测；
4. PR 描述里贴了命令的完整输出；
5. PR 里写明「契约变更：无」或「契约变更：需队长改 schemas（已申请）」。

---

## 7. 交付物在哪（最容易做错的一条）

1. **你的交付物是仓库里的文件，不是聊天里的一段话。** 没进 git 的内容等于没做。
2. 写完必须提交：

   ```powershell
   git checkout -b feature/<模块>-<短描述>
   git add <你改的文件>
   git commit -m "docs(<模块>): <做了什么>"
   git push -u origin <分支名>
   ```

3. 任务回执写在 `docs/reports/`，不要发微信、不要只在对话里说。
4. 推不上去（没权限 / 没网 / 报错）：把文件留在本地，在回执里写清
   「文件在 `<绝对路径>`，未推送，原因：`<报错原文>`」。**禁止假装已上传。**

---

## 8. 汇报格式（固定，不要发挥）

回执文件：`docs/reports/YYYY-MM-DD-<模块>-<你的名字>.md`，从 `docs/reports/_模板.md` 复制。
正文四节必须有：**做了什么 / 没做完 / 下次接手要知道什么 / 怎么验收**。

对话里给人看的三行版：

```
做了什么：<一句话>
验收命令：pwsh scripts/check.ps1 -Task all  +  python scripts/docs.py check
结果：<全绿 / 哪条红，红在哪>
```

---

## 9. 什么情况开 Issue（三类模板）

| 模板 | 什么时候用 | 不要用它做的事 |
| --- | --- | --- |
| **需求** `01-requirement` | 要加功能、要改文档、要新素材 | 汇报进度 |
| **阻塞或授权** `02-blocked` | 缺权限、缺账号、缺数据、缺算力 | 问"这个词什么意思" |
| **文档问题** `03-doc-problem` | 文档缺失、过期、自相矛盾 | 提新需求 |

判断标准一句话：**需要队长拍板或给你资源的，开 Issue；只需要让人知道你做完了的，写回执。**

---

## 10. 分支与提交

```
分支：feature/<模块>-<短描述>     例：feature/audio-asr-basic
提交：feat: 加 ASR 转写（FunASR）
      fix: 修正 OCR 置信度低于 0.6 时未降权
      test: 补打分器边界用例
      docs(<模块>): 补任务回执
```

一次提交只做一件事；不要顺手重构别人的模块。

---

## 11. 卡住怎么办（重要）

- 连续两次尝试仍失败 → **停下来**，把报错原文整段贴到任务单评论，@负责人。
- 不许"绕过"：不许注释掉测试、不许关掉 lint 规则、不许把异常吞掉。
- 不确定需求时：**先写测试用例**（输入 → 期望输出），再让人确认，别猜着写。

---

## 12. 跟人沟通的方式

- 别说"我优化了代码结构"，说"四条命令的输出是什么"。
- 别解释实现细节（他们看不懂），说"这个接口现在能吃 X 吐 Y，你可以这样调"。
- 汇报只能用第 8 节的三行格式，不要写成小作文。

---

## 13. 契约变更流程（全队唯一"需要等人"的事）

1. 在任务单评论里写：要加/改哪个模型、哪个字段、为什么现在的字段不够；
2. 队长改 `app/schemas/`，并在群里发一句「契约变更：Decision 加 `stage_index`」；
3. 所有人 `git pull` 后再继续，不要在旧契约上写新代码。

---

## 14. 队长侧的动作（Agent 只读，不用执行）

- 开赛第一周发两条公告：选型表（7 个槽位）+ 认领表，然后 20 分钟培训。
- 只保留一场"认领会"（认领模块 + 认领任务），技术判断由队长单点决定，48 小时异议期。
- 验收看两件事：第 2 周三条命令全绿；第 8 周 `docker compose up` 能演示。

**CI 卡死时的逃生通道（只有队长能用，且要留痕）**

ruleset `main-protection-ci` 没有 bypass 角色，如果 GitHub Actions 自己挂了（不是代码红、是 Actions 红），
任何 PR 都合不进去。此时的唯一出口是临时把规则关掉：

```powershell
gh api repos/yu-nianan/tol/rulesets            # 先拿到 ruleset id
gh api -X PATCH repos/yu-nianan/tol/rulesets/<id> -f enforcement=disabled
# 合完 PR 立刻恢复
gh api -X PATCH repos/yu-nianan/tol/rulesets/<id> -f enforcement=active
```

规矩：**只许在"Actions 故障"时用**，用完当天的回执里必须写一行「逃生通道使用：时间 / 原因 / 已恢复」。
判断顺序永远是：先看本地四条命令 → 再看 Actions 日志红在哪一步 → 确认是 Actions 故障才动规则。

---

## 15. 最后一条

**你不需要把代码写得漂亮，你需要让"四条命令全绿 + 输出能贴出来"。**
这个项目的评分不在代码质量，在"能不能演示、指标能不能自证"。
