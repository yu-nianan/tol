---
title: 任务回执：视觉链路、跨模态矛盾、工程与交付
owner: C
status: final
last_updated: 2026-11-07
related_code: app/pipelines/vision/ocr.py, app/pipelines/vision/template.py, app/pipelines/vision/identity.py, app/pipelines/audio/artifacts.py, scripts/perf_run.py, scripts/guard_24h.py, scripts/eval_crossmodal.py, docker/Dockerfile
summary: T-03/T-10/T-12 交付：OCR 骨架与版面/号码/合成音启发式、可复现的 docker 起服务、压测与 24h 守护脚本、带出处的评估报告
audience: agent
depends_on: [../INDEX.md]
---

# 任务回执：视觉链路 / 跨模态矛盾 / 工程与交付

## 做了什么

- **T-03 视觉链路**：`app/pipelines/vision/ocr.py` 用纯标准库实现 `extract_text(image_bytes) -> OcrResult`：
  - 64 字节内识别 PNG（`89 50 4E 47`）与 JPEG（`FF D8 FF`），PNG 读 IHDR、JPEG 扫 SOF0/SOF2 拿宽高；
  - `> 4MB` 或任一边 `> 4000px` → `ImageTooLarge`，其他字节 → `UnsupportedImageFormat`；
  - 引擎探测顺序 `OCR_CLI` → `shutil.which("tesseract")` → `backend="not-implemented"`，无引擎时
    `confidence=0.0`、`blocks=[]` 直接返回，不抛异常；
  - 有 CLI 时用 `subprocess.run` 调用，tesseract 解析 TSV；超时/非零退出/解析失败都回空结果。
  - `tests/vision/test_ocr.py` 9 条用例（1×1 PNG、手工 SOF0 JPEG、乱码、伪造 5000px IHDR、>4MB、
    monkeypatch 假 CLI 成功与坏输出）。
- **T-12 工程与交付**：
  - 实测 `docker compose up -d --build` 可一键起（详见 §怎么验收）；发现镜像缺 `frontend/` 后已在
    `docker/Dockerfile` 补 `COPY frontend ./frontend`，容器根路径现在返回 D 的 42,249 字节演示页；
  - 新增 `scripts/perf_run.py`（纯标准库，`threading + urllib`，并发与时长可配置，输出成功率与
    P50/P95/P99）；新增 `scripts/guard_24h.py`（每小时一条 JSONL，含健康/检测耗时、目标 RSS、异常计数）；
  - `docs/评估报告.md` 已建立，F1/准确率用 T-05 的 `evalcheck.measure` 实测，时延/压测/守护数据均贴了
    复现命令与原始输出；未跑满 24 小时、正式压测口径未跑的部分明确写"未验证"。
- **T-10 跨模态矛盾**：三个独立函数均返回 `Evidence(kind=SourceKind.CROSS_MODAL)`：
  - `app/pipelines/audio/artifacts.py::audio_artifacts(envelope)`：静音占比、能量平台期、爆破音缺失、
    停顿等长四个信号加权，接受 30ms 帧包络或 T-02 的 `Transcript`；
  - `app/pipelines/vision/template.py::template_deviation(blocks, anchors=None)`：对照
    `app/kb/anchors.json` 的转账页/官方通知页锚点，缺锚点、位置异常、关键动作词缺失都会计入偏离分；
  - `app/pipelines/vision/identity.py::number_identity_mismatch(phone, claim)`：本地区号/号段表
    （`app/kb/phone_prefix.json`）与自称身份比对，跨省/跨市、虚拟运营商+官方自称分别加权，不联网。
  - `tests/crossmodal/` 17 条用例；`scripts/eval_crossmodal.py` 用**构造样本**给出混淆矩阵（见下）。

构造样本自检（6 假 + 6 真/检测器，**不是真实 TTS/PS 数据集**）：

| 检测器 | 阈值 | TP | FP | TN | FN | 精确率 | 召回率 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `audio_artifacts` | 0.50 | 6 | 0 | 6 | 0 | 1.000 | 1.000 |
| `template_deviation` | 0.25 | 6 | 0 | 6 | 0 | 1.000 | 1.000 |
| `number_identity_mismatch` | 0.45 | 6 | 0 | 6 | 0 | 1.000 | 1.000 |

> 样本是按"已知形态"写出来的，1.0 只说明信号链路接得通，**不能当真实准确率**；
> T-10 任务单要求的 10 段真实 TTS 与 20 张 PS 图，仓库里没有素材（`data/samples` 不入库），未跑。

报告中的跨模态结论一律标注："启发式，疑似，不是深度伪造检测器"。

## 没做完 / 已知问题

- **T-10 真实验收未跑**：10 段 TTS ≥7 命中、20 张 PS 图 precision≥0.8/recall≥0.7 都没有真实素材，
  只有上表的构造样本自检；拿到素材后应直接用三个函数重跑。
- **正式压测未跑**：只跑了 3 并发 × 10 秒（1992 请求、100% 成功、P95 31.02ms）；**10 并发 × 10 分钟（600 秒）压测未跑**，报告里已写"未跑"。
- **24 小时守护未跑满**：只有 4 个点的短跑自检（errors_total=0）；长稳与内存曲线待正式跑一天。
- **OCR/ASR 无真实模型**：本机没有 tesseract、`OCR_CLI` 为空；ASR 只有能量 VAD。图片/语音端到端
  准确率不在本次数据范围内。
- `tests/test_api_media.py` 现有 4 条断言（audio 无模型→501、image 无引擎→501）在接口层按新契约重接前
  会红；`app/api/detect.py` 由队长接线，我没有改 `app/api/**`。
- 宿主机 8000 端口被占用时，compose 可能出现"容器 healthy 但 ports 为空"；停掉占用进程后重新 `up`
  即可恢复端口映射，已在评估报告里记录。
- 未运行任何 `git` 命令、未跑 `scripts/docs.py`、未跑全量 pytest（按任务约束，提交与门禁由队长统一做）。

## 下次接手要知道什么

- 入口与契约：
  - `app/pipelines/vision/ocr.py::extract_text(image_bytes) -> OcrResult`；`Block(text, x, y, w, h)`，
    `OcrResult(text, blocks, backend, confidence, width, height)`；backend 取值 `tesseract-cli` /
    `ocr-cli:<cmd>` / `not-implemented`；
  - `app/pipelines/audio/artifacts.py::audio_artifacts(envelope)`；
  - `app/pipelines/vision/template.py::template_deviation(blocks, anchors=None)`；
  - `app/pipelines/vision/identity.py::number_identity_mismatch(phone, claim)`。
- 数据文件：`app/kb/anchors.json`（两个演示模板 + 位置容差 0.12）、`app/kb/phone_prefix.json`
  （20 个区号、40 个号段、虚拟运营商 162/165/167/170/171、官方关键词、17 个城市别名）。
- Evidence 约定：三者 `kind=SourceKind.CROSS_MODAL`；`template_deviation` 用 `category="channel"`、
  `modality=IMAGE`；`number_identity_mismatch` 用 `category="entity"`、`modality=TEXT`；
  `audio_artifacts` 用 `category="other"`、`modality=AUDIO`；`weight` 与 `confidence` 都等于启发式分，
  `meta["note"]` 固定写"启发式，疑似，不是深度伪造检测器"。
- 接线提醒：引擎（T-07，队长侧）需要主动调用这三个函数并把返回的 Evidence 追加进证据列表；
  当前 `scoring.py` 不会自动发现新模块。`category="channel"` 会走现有 channel 维度，
  `modality` 种类数会喂给 cross 维度。
- 阈值都是拍脑袋定的：音频 0.45/0.60/0.40/0.25，模板缺失 0.70、位置 0.60、关键动作缺失 +0.20；
  号码跨省 0.70、同省 0.45、虚拟运营商 0.60、手机官方自称 0.15。要调先改常量再重跑
  `scripts/eval_crossmodal.py`。
- 三个 T-03 交付问题：
  1. 为什么返回空结果而不是 501：图片格式合法但没引擎时，501 会让整条链路失败；返回
     `backend="not-implemented"`、`confidence=0.0`、空 blocks 能让上层继续走文本证据并如实展示"OCR 未启用"，
     不编造识别结果。
  2. 1080P 真机 OCR 耗时：本机无 tesseract，**未实测**；脚本里 CLI 超时设 30s，接入后需在目标机补测。
  3. 截图被 P 的证据信号：本实现只能给版面锚点偏离（缺"确认转账"、按钮位置异常等）作为弱信号，
     不是图像取证；需要更强结论时应接 ELA/元数据/字体渲染检测，并在报告里保留"疑似"表述。
- Docker 现状：`docker compose -f docker/docker-compose.yml up -d --build` 已验证；镜像是
  `python:3.11-slim`，不拷贝 `data/` 与模型；`frontend/` 已进镜像。

## 怎么验收

```text
命令：& .\.venv\Scripts\python.exe -m pytest tests/vision tests/crossmodal -q
输出：
..........................                                               [100%]

（同一组用例加摘要跑法：& .\.venv\Scripts\python.exe -m pytest tests/vision tests/crossmodal）
..........................                                               [100%]
26 passed in 0.32s

命令：& .\.venv\Scripts\python.exe -m ruff check app/pipelines/vision app/pipelines/audio tests/vision tests/crossmodal scripts docker
输出：
All checks passed!

命令：docker --version
输出：
Docker version 29.5.3, build d1c06ef

命令：docker compose version
输出：
Docker Compose version v5.1.4

命令：docker compose -f docker/docker-compose.yml up -d --build 后 docker compose -f docker/docker-compose.yml ps
输出：
NAME           IMAGE        COMMAND                  SERVICE   CREATED         STATUS                   PORTS
docker-app-1   docker-app   "python -m uvicorn a…"   app       6 minutes ago   Up 6 minutes (healthy)   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp

命令：Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health
输出：
{"status":"ok","version":"0.1.0","kb_scripts":15,"kb_cases":50,"llm_enabled":false,"asr_enabled":false,"ocr_enabled":false}

命令：Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/
输出：
demo_status=200 demo_bytes=42249

命令：& .\.venv\Scripts\python.exe scripts\perf_run.py --base-url http://127.0.0.1:8000 --concurrency 3 --duration 10
输出：
压测口径：3 并发 × 10 秒
目标：http://127.0.0.1:8000/api/v1/detect/text
请求总数 1992，成功 1992，失败 0，成功率 100.00%
耗时(ms)：avg 14.99 | p50 13.52 | p95 31.02 | p99 32.26 | max 132.46
吞吐：198.88 req/s（成功请求 / 实际 10.016s）
判定：成功率≥99% PASS；P95<10s PASS
（正式口径为 10 并发 × 10 分钟，本次只跑了 3 并发 × 10 秒短跑，不能当正式结论）

命令：& .\.venv\Scripts\python.exe scripts\guard_24h.py --base-url http://127.0.0.1:8001 --interval 1 --duration 3 --pid 34200
输出（末条）：
{"ts": 1794041109.587, "iso": "2026-11-07T16:45:09+08:00", "tick": 4, "health_ok": true, "health_ms": 20.48, "detect_ok": true, "detect_ms": 258.86, "detect_level": "2", "error": "", "rss_bytes": 59240448, "guard_rss_bytes": 27267072, "errors_total": 0, "failures_total": 0, "ticks_total": 4}
SUMMARY {"out": "data\\guard\\guard_smoke_pid.jsonl", "ticks": 4, "failures_total": 0, "duration_seconds": 3.281}
（连续 24 小时未跑，这是脚本可用性短跑）

命令：& .\.venv\Scripts\python.exe -c "from app.pipelines.knowledge.evalcheck import load_eval_set, measure, EVAL_SET_PATH, OFFICIAL_SET_PATH; print(measure(load_eval_set(EVAL_SET_PATH))); print(measure(load_eval_set(OFFICIAL_SET_PATH)))"
输出：
{'n': 40, 'tp': 20, 'fp': 4, 'tn': 16, 'fn': 0, 'precision': 0.833, 'recall': 1.0, 'f1': 0.909, 'accuracy': 0.9}
{'n': 20, 'tp': 10, 'fp': 2, 'tn': 8, 'fn': 0, 'precision': 0.833, 'recall': 1.0, 'f1': 0.909, 'accuracy': 0.9}

命令：& .\.venv\Scripts\python.exe scripts/eval_crossmodal.py
输出：
== 跨模态矛盾三件套 · 构造样本自检（非真实 TTS/PS 数据集）==
audio_artifacts（阈值 0.50）：{'tp': 6, 'fp': 0, 'tn': 6, 'fn': 0, 'precision': 1.0, 'recall': 1.0, 'accuracy': 1.0}
template_deviation（阈值 0.25）：{'tp': 6, 'fp': 0, 'tn': 6, 'fn': 0, 'precision': 1.0, 'recall': 1.0, 'accuracy': 1.0}
number_identity_mismatch（阈值 0.45）：{'tp': 6, 'fp': 0, 'tn': 6, 'fn': 0, 'precision': 1.0, 'recall': 1.0, 'accuracy': 1.0}
合计：audio TP=6/FP=0，template TP=6/FP=0，identity TP=6/FP=0
```

补充：`python scripts/docs.py check` 已按队长指令跑过，`评估报告.md` 的 depends_on 死链已消除；
剩余两条阻断（`docs/INDEX.md` 索引与磁盘不一致、`docs/需求覆盖表.md` 与任务单不一致）属于队长统一修复范围。
全量 `pytest` 未由我执行（任务约束：提交与门禁由队长统一做）；
`docker compose up` 的首次失败原因是 daemon 未启动，报错原文与恢复过程见 `docs/评估报告.md` §5。

```text
命令：& .\.venv\Scripts\python.exe scripts/docs.py check 2>&1 | Select-Object -Last 10
输出（修复 depends_on 后）：
✗ docs/INDEX.md:1  索引与磁盘不一致（跑 python scripts/docs.py index）
✗ docs/需求覆盖表.md:1  需求覆盖表与任务单不一致（跑 python scripts/docs.py matrix）
! docs/需求覆盖表.md:1  还有 2 条需求没有主责任务：FR-4.2、FR-4.3

FAIL  阻断 2 项 / 警告 1 项
（修复前多一条 `评估报告.md: depends_on 指向不存在的文件：../INDEX.md / ../需求清单.md / ../测试方案.md`，已改为相对 docs/ 的 INDEX.md 等，本条已消失；剩下两条由队长执行 docs.py index / matrix 处理）
```

## 改动清单

- `app/pipelines/vision/ocr.py`（重写：PNG/JPEG 尺寸解析、大小限制、CLI 探测与 TSV 解析、空结果契约）
- `app/pipelines/vision/template.py`（新增：版面锚点偏离启发式）
- `app/pipelines/vision/identity.py`（新增：号码归属与自称身份冲突启发式）
- `app/pipelines/audio/artifacts.py`（新增：合成语音痕迹启发式，未改动 B 的 `asr.py`）
- `app/kb/anchors.json`（新增：两个演示模板的锚点与位置容差）
- `app/kb/phone_prefix.json`（新增：本地区号/号段/官方关键词/城市别名）
- `tests/vision/test_ocr.py`（新增 9 条用例）
- `tests/crossmodal/test_artifacts.py`、`test_template.py`、`test_identity.py`（新增 17 条用例）
- `scripts/perf_run.py`（新增：压测，纯标准库）
- `scripts/guard_24h.py`（新增：24h 守护打点，纯标准库）
- `scripts/eval_crossmodal.py`（新增：构造样本混淆矩阵自检）
- `docker/Dockerfile`（补 `COPY frontend ./frontend`，演示页随镜像发布）
- `docs/评估报告.md`（新增：F1/准确率/时延/压测/24h 口径与实测出处）
- `docs/reports/2026-11-07-vision-engineering-C.md`（本文件）

工具：DSH agent（负责人 C 代理）
