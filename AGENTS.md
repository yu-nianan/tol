# AGENTS.md —— 给 AI 编程智能体的入职须知

> 本文件是团队的**唯一权威约定**。与任务单冲突时以任务单为准；与"你觉得更优雅"冲突时以本文件为准。
> 人看不懂代码没关系，但**这三条命令必须全绿**，否则不算做完。

---

## 0. 开工前按顺序读

1. 本文件（你已经在这）
2. `docs/tickets/<你的任务单>.md` —— 你这次只做这一件事
3. `OWNERS.md` —— 你被允许改哪些目录
4. `app/schemas/*.py` —— 模块之间唯一合法的交接格式

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
  tickets/              # 任务单
  decisions.md          # 技术决策记录（只追加）
scripts/
  check.ps1             # 三条命令的入口
  smoke.py              # 冒烟脚本
docker/                 # compose 与 Dockerfile
```

---

## 2. 只允许改这些路径

- 你任务单里写明的路径
- 你负责模块目录下的 `tests/`

**一律不许碰**（碰了就是越界，PR 会被打回）：

```
app/schemas/**      ← 契约，只有队长改
app/main.py
app/core/**
docker/**
scripts/**
Makefile
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

---

## 4. 硬性禁令

1. **不许新增依赖。** 需要新库 → 在任务单写「申请依赖：包名，用途，不装的替代方案」，等批准。
2. **不许提交密钥、token、真实手机号、真实人名、真实身份证。** 示例数据一律用 `138****0000`、`张*`。
3. **不许用硬编码结果"通过测试"。** 不许 `return {"score": 90}`；不许把真实模型调用注释掉再返回假数据。演示用的假数据必须放在 `data/` 并在 PR 里写明"此处为演示数据"。
4. **不许改契约字段名或类型。** 缺字段就提 issue，不要自己加。
5. **不许跨模块 import 内部实现。** 只能 `from app.schemas import ...` 或调用对方模块暴露的 `run()`。
6. **不许为了让测试通过而改测试断言**；不许 `try/except: pass` 吞异常。
7. **不许 `git push --force`、不许直接推 `main`。**

---

## 5. 什么算"做完了"（DoD，四条缺一不可）

1. 三条命令全绿；
2. 你改的核心函数至少有 1 个正例 + 1 个反例的单测；
3. PR 描述里贴了三条命令的完整输出；
4. PR 里写明「契约变更：无」或「契约变更：需队长改 schemas（已申请）」。

---

## 6. 分支与提交

```
分支：feature/<模块>-<短描述>     例：feature/audio-asr-basic
提交：feat: 加 ASR 转写（FunASR）
      fix: 修正 OCR 置信度低于 0.6 时未降权
      test: 补打分器边界用例
      docs: 补任务单验收命令
```

一次提交只做一件事；不要顺手重构别人的模块。

---

## 7. 卡住怎么办（重要）

- 连续两次尝试仍失败 → **停下来**，把报错原文整段贴到任务单评论，@负责人。
- 不许"绕过"：不许注释掉测试、不许关掉 lint 规则、不许把异常吞掉。
- 不确定需求时：**先写测试用例**（输入 → 期望输出），再让人确认，别猜着写。

---

## 8. 跟人沟通的方式

- 别说"我优化了代码结构"，说"三条命令的输出是什么"。
- 别解释实现细节（他们看不懂），说"这个接口现在能吃 X 吐 Y，你可以这样调"。
- 汇报格式固定三行：

```
做了什么：<一句话>
验收命令：pwsh scripts/check.ps1 -Task all
结果：<全绿 / 哪条红，红在哪>
```

---

## 9. 契约变更流程（全队唯一"需要等人"的事）

1. 在任务单评论里写：要加/改哪个模型、哪个字段、为什么现在的字段不够；
2. 队长改 `app/schemas/`，并在群里发一句「契约变更：Decision 加 `stage_index`」；
3. 所有人 `git pull` 后再继续，不要在旧契约上写新代码。

---

## 10. 最后一条

**你不需要把代码写得漂亮，你需要让"三条命令全绿 + 输出能贴出来"。**
这个项目的评分不在代码质量，在"能不能演示、指标能不能自证"。
