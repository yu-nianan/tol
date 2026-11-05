---
title: T-05 测评集 40 条 + 量测脚本（负责人 A）
owner: A
status: final
last_updated: 2026-11-05
related_code: app/kb, app/pipelines/knowledge, tests/eval
summary: 造出可量测的 40 条黑白 1:1 测评集，并用脚本算出 P/R/F1/准确率
audience: agent
depends_on: [../INDEX.md, ../测试方案.md, ../需求清单.md]
---

# 任务单：测评集 + 量测脚本（"90% 怎么算"的答案就在这里）

## 1. 背景（为什么做这件事）

- 对应需求：`FR-4.1`（测评集）、`D-5.4`（交付物：测评集文件）、创意分里的"证明层"
- 对应测试用例：`TC-4.1`（20 条官方测评集）、`TC-4.2`（准确率 + F1 报告）
- 现状：仓库里只有 `app/kb/cases.json` 20 条案例（检索用），**没有任何带标签的测评集**，
  所以"识别准确率 >90%"这个指标目前**无法自证**——答辩被问一句"怎么算的"就答不上。
- 一句话：造一套带标签的样本，并写一个脚本，跑一次就能打印出混淆矩阵和 P/R/F1。

## 2. 目标（做完之后，什么会不一样）

1. `app/kb/eval_set.csv`：**40 条**，黑白 **1:1**（20 条诈骗 / 20 条正常），字段固定：

```csv
id,text,label,script_id,stage,source
E001,"我是市公安局的，你的账户涉嫌洗钱，请把钱转到安全账户",1,S03,诱导转账,自拟-改编
E021,"妈，我周末回家吃饭，你别等我了",0,,,自拟-日常
```

- `label`：1=诈骗，0=正常；`script_id` 与 `stage` 只对黑样本填（可空）
- 黑样本要**覆盖 ≥10 类剧本**（对应 `app/kb/scripts.json` 的 S01–S10，每类 2 条）
- `source` 写来源：`自拟-改编` / `公开报道` / `亲友转发`，**不许出现真实姓名、真实号码、真实单位**
- 一半黑样本要"半像"（只出现 1–2 个信号，不整段照抄），否则测出来虚高

2. `app/kb/eval_set_official.csv`：从 40 条里挑 **20 条**（黑白 1:1、覆盖 ≥10 类），作为对外提交的"官方集"，
   并在文件头注释写明挑选规则（不是随机挑，要覆盖每一类）

3. `app/pipelines/knowledge/evalcheck.py`：

```python
def load_eval_set(path: Path) -> list[dict]: ...
def validate_eval_set(rows: list[dict]) -> list[str]: ...
    # 返回问题列表：条数≠40、黑白不 1:1、script_id 不在 scripts.json、stage 为空、text<10 字、重复 text
def measure(rows: list[dict]) -> dict: ...
    # {"n":40,"tp":..,"fp":..,"tn":..,"fn":..,"precision":..,"recall":..,"f1":..,"accuracy":..}
```

4. `tests/eval/test_measurement.py`：
   - 用 `DetectionEngine.detect_text` 逐条跑（`role="normal"`，`level in ("L2","L3")` 视作判为诈骗）
   - 打印一张 markdown 表（`id | label | level | score | 判对?`），末尾打印 P/R/F1/准确率
   - 断言先写成 **`accuracy >= 0.70`**（第 2 周基线），并在测试里用注释写明"第 5 周目标 0.85，改这一行要同时改 `docs/测试方案.md`"
   - 另加 3 条纯函数单测：`validate_eval_set` 对"少一条 / 黑白不 1:1 / script_id 不存在"要各报一条问题

## 3. 输入 / 输出样例（写死，不要"大概"）

```
$ python -m pytest tests/eval -q -s
n=40 tp=17 fp=3 tn=17 fn=3  precision=0.85 recall=0.85 f1=0.85 accuracy=0.85
```

## 4. 允许修改的路径（超出即越界）

```
app/kb/eval_set.csv
app/kb/eval_set_official.csv
app/pipelines/knowledge/evalcheck.py
tests/eval/**
```

## 5. 不许做的事（本次特有）

- 不许用大模型批量生成 40 条（评价集和被测评的系统同源，结果不可信）；必须是**人写 + 公开报道改编**
- 不许把测试阈值往下调来"变绿"；跑出来 0.62 就如实写 0.62，然后在回执里写"哪一类拖后腿"
- 不许提交真实截图/真实聊天记录；文本里号码写成 `138****0000`
- 不许改 `app/schemas/**` 与 `app/kb/scripts.json`

## 6. 验收命令（队长会照着跑，必须全绿）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task lint
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task test
python scripts/docs.py check
```

附加验收（人工看一眼）：

- [ ] 贴出 `pytest tests/eval -q -s` 的完整输出（含混淆矩阵四个数与 P/R/F1）
- [ ] 写出"哪一类最容易被漏判"（看 40 条的明细表，按 script_id 归类）
- [ ] 说明 40 条与 20 条官方集的差别（为什么留 20 条对外）

## 7. 预计与截止

| 项 | 内容 |
|---|---|
| 负责人 | A |
| 预计耗时 | 3 天（写 40 条 1.5 天 / 校验与量测 0.5 天 / 测试与调参 1 天） |
| 截止 | 周日 22:00 |
| 卡住找谁 | @队长 |

## 8. 交付时会问的三个问题（提前想好）

1. 40 条够不够？换成 100 条，准确率的置信区间会怎么变？（提示：19/20 的 95% 置信区间大约是 76%–99%）
2. 你的黑样本和 `scripts.json` 里的信号高度重合，这算不算"自己出题自己考"？怎么避免？
3. 如果第 5 周准确率只有 0.78，方案里怎么写才不算翻车？

## 9. 完成记录（智能体填）

```
做了什么：<一句话>
验收命令：scripts/check.ps1 -Task all  +  python scripts/docs.py check
结果：<全绿 / 哪条红，红在哪；贴 P/R/F1>
契约变更：无
```
