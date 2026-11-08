---
title: T-04 演示页三屏（检测 / 告警 / 报告）（负责人 D）
owner: D
status: final
last_updated: 2026-11-05
related_code: frontend, app/api/web.py
summary: 在 frontend/ 下做三屏页面，后端已支持优先返回它；无构建、无 CDN、手机可读
audience: agent
depends_on: [../INDEX.md, ../需求清单.md]
covers: [FR-3.1, FR-3.2, FR-3.7]
supports: [FR-3.3, FR-3.4]
depends_on_task: []
---

# 任务单：把演示页从"一屏"扩成"三屏"

## 1. 背景（为什么做这件事）

- 对应需求：`FR-3.1`–`FR-3.4`（分级预警 / 语音 / 监护人 / 报告）、`FR-3.7`（角色设置）
- 对应测试用例：`TC-3.1`–`TC-3.3`（L1/L2/L3 三档预警）、`TC-3.8`（报告五段）
- 现状：演示页是 `app/api/web.py` 里一段内联 HTML（134 行），只有"输入 → 出分数 → 证据列表"，
  没有告警页、没有报告页、没有角色切换。演示视频里"分级"和"报告"这两件事讲不出来。
- 一句话：让评委在**一个页面上点三下**，看到"检测 → 告警 → 报告"整条链路。

## 2. 目标（做完之后，什么会不一样）

1. 新建目录 `frontend/`，三个文件：`index.html`、`app.js`、`style.css`（**不用 npm、不用框架、不用 CDN**）
2. 页面内三个视图，用 hash 路由：`#/detect`、`#/alert/<alert_id>`、`#/report/<session_id>`
   - 检测页：粘贴框 + 角色下拉（`normal/elder/child/student/finance`）+ 三个预设按钮
   - 告警页：等级色条（L0 灰 / L1 蓝 / L2 橙 / L3 红）、证据条目（`label` + `text` + 置信度）、"生成报告"按钮
   - 报告页：五段（风险概述 / 证据链 / 剧本匹配 / 处置建议 / 通报记录），来自 `GET /api/v1/report/{session_id}`
3. 切角色后同一句话的等级会变（`TC-2.6` 的可视化证据）
4. 手机宽度 420px 下不横向滚动；不加载任何外部字体/图标

## 3. 输入 / 输出样例（写死，不要"大概"）

后端接口（已存在，只读调用，不要改）：

```
POST /api/v1/detect/text    {"text":"...","session_id":"s1","role":"elder"}
 → {"score":87.3,"level":"L3","reasons":[...],"evidence":[{code,label,text,weight,confidence}...],"alert_id":"..."}
GET  /api/v1/alerts/{alert_id}
GET  /api/v1/report/{session_id}
GET  /api/v1/kb/scripts
```

页面自测的判定：在浏览器控制台里 `location.hash` 应该是 `#/alert/a_xxx` 这种形态，刷新不 404。

## 4. 允许修改的路径（超出即越界）

```
frontend/**            # 新建，全部归你
```

队长已经在 `app/api/web.py` 里加了约定：**`frontend/index.html` 存在时，`GET /` 优先返回它**，
否则退回内置兜底页。所以你不必改后端，也不要改后端。

## 5. 不许做的事（本次特有）

- 不许引入 React/Vue/Tailwind/任何 CDN；不许 `npm install`
- 不许改 `app/**`（包括 `app/api/web.py`）；要改接口先提 issue
- 不许把接口地址写死成 `http://127.0.0.1:8000`（用相对路径 `/api/v1/...`，换机器才跑得动）
- 不许提交真实聊天截图；预设文本用 `data/samples/*.txt` 里那三条改写（脱敏）

## 6. 验收命令（队长会照着跑，必须全绿）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task lint
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task test
python scripts/docs.py check
```

附加验收（人工点一遍，PR 里贴截图或录屏链接）：

- [ ] 起服务后打开 `/`，能看到三屏页（不是兜底页）
- [ ] 点"正常消息"→ L0/L1；点"冒充公检法"→ L3 红色；点"生成报告"→ 五段都有内容
- [ ] 角色从"普通"切到"老人"，同一句话等级升高
- [ ] 手机浏览器（或 DevTools 420px）打开，不横向滚动
- [ ] 直接刷新 `#/report/xxx` 不 404

### 页面还没定稿时怎么看效果（分两步走，别一次等全部）

你就是在做页面，所以"等前端定"这件事对你不成立，但**顺序**成立：先让三屏能点，再让数据是真的。

**第一步（第 1 天就能给人看）**：本地合一个临时分支，起服务，用 mock 数据把三屏走通。

```powershell
git fetch origin
git switch -c try/T-04-<日期> origin/main
git merge <你的分支>
scripts\start.cmd
# 浏览器打开 http://127.0.0.1:8000/
```

这一步的"效果"=**三屏都能打开、按钮都响应**。贴一张截图进 PR，不用等接口。

**第二步（接口通了再验）**：把 mock 换成本地真实服务（现在后端就在 127.0.0.1:8000），
把"正常 / 冒充公检法 / 老人角色"三种输入的返回截图贴进去，证明页面和 `Decision` 对得上。

**判断标准**：能贴出**访问地址 + 截图**，且换一台机器（或换个浏览器）照样打得开。
前端这段时间会变，所以`try/` 分支看完就删，别把试验代码带进 PR。

看完清干净：`try/` 分支不 push，看完删掉；本地 main 保持和 `origin/main` 一致。

## 7. 预计与截止

| 项 | 内容 |
|---|---|
| 负责人 | D |
| 预计耗时 | 3 天（检测页 1 天 / 告警页 1 天 / 报告页 + 手机适配 1 天） |
| 截止 | 周日 22:00 |
| 卡住找谁 | @队长 |

## 8. 交付时会问的三个问题（提前想好）

1. 为什么不用 React？（提示：队友装环境、现场没好网、你一个人维护）
2. 三种等级的颜色和文案怎么定的？和 `app/schemas/alert.py` 里的 `Level` 对得上吗？
3. 演示视频里你会点哪三下，让评委 30 秒看懂？（写出点击顺序）

## 9. 完成记录（智能体填）

```
做了什么：<一句话>
验收命令：scripts/check.ps1 -Task all  +  python scripts/docs.py check
结果：<全绿 / 哪条红，红在哪>
契约变更：无
```
