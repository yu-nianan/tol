---
title: T-03 视觉链路骨架：图片校验 → 文本块抽取 → 可降级（负责人 C）
owner: C
status: final
last_updated: 2026-11-05
related_code: app/pipelines/vision, tests/vision
summary: 把 ocr.py 从"直接抛 501"改成"先校验、再尝试、不行就诚实返回空"
audience: agent
depends_on: [../INDEX.md, ../需求清单.md]
---

# 任务单：视觉链路骨架 + 截图文本抽取（可降级）

## 1. 背景（为什么做这件事）

- 对应需求：`FR-1.3`（截图/图片接入）、`FR-2.4b`（截图版面与官方模板偏离，靠这里出证据）
- 对应测试用例：`TC-1.5`（聊天截图出文本）、`TC-1.6`（转账页抽出收款方与金额）
- 现状：`app/pipelines/vision/ocr.py` 直接抛 `OcrNotConfigured`，`POST /api/v1/detect/image` 返回 501
- 一句话：先把"这张图能不能收、是不是图、多大"这三件事做对；OCR 引擎有就用，没有就诚实说没有。

## 2. 目标（做完之后，什么会不一样）

1. `app/pipelines/vision/ocr.py` 暴露固定契约：

```python
@dataclass
class Block:
    text: str
    x: int
    y: int
    w: int
    h: int

@dataclass
class OcrResult:
    text: str            # 所有 block 用 \n 拼起来
    blocks: list[Block]
    backend: str         # "tesseract-cli" / "ocr-cli:<cmd>" / "not-implemented"
    confidence: float    # 没引擎时必须 0.0
    width: int
    height: int

def extract_text(image_bytes: bytes) -> OcrResult: ...
```

2. 纯标准库做三件事（**不许装 PIL / pytesseract**）：
   - 认格式：PNG（`89 50 4E 47`）、JPEG（`FF D8 FF`），其他一律 `UnsupportedImageFormat`
   - 读尺寸：PNG 读 `IHDR` 的宽高；JPEG 扫 `SOF0/SOF2` 段。读不到就当 0，不许崩
   - 设上限：>4MB 或 宽或高 >4000px → `ImageTooLarge`
3. 引擎探测顺序：环境变量 `OCR_CLI` → `shutil.which("tesseract")` → 都没有则
   `backend="not-implemented"`、`blocks=[]`、`confidence=0.0`，**返回而不是抛**
4. `tests/vision/test_ocr.py` 至少 5 条：1×1 PNG → 尺寸 1/1 且 `backend="not-implemented"`；
   JPEG 头 → 不崩；乱码 → `UnsupportedImageFormat`；超大（伪造 5000px 的 IHDR）→ `ImageTooLarge`；
   用 monkeypatch 造假 `OCR_CLI` 脚本 → `backend` 前缀正确（不要求真 OCR）。

## 3. 输入 / 输出样例（写死，不要"大概"）

```python
res = extract_text(PNG_1X1)   # 测试里用 base64 常量构造，不要提交真实截图
# OcrResult(text="", blocks=[], backend="not-implemented", confidence=0.0, width=1, height=1)
```

## 4. 允许修改的路径（超出即越界）

```
app/pipelines/vision/**
tests/vision/**
data/samples/images/**      # 自己截图放这里，本地即可（data/samples 只保留 .txt 入库，图不入库）
```

**你不许碰 `app/api/**`**：把 OCR 接进 `POST /api/v1/detect/image` 是队长的活。

## 5. 不许做的事（本次特有）

- 不许新增依赖；不许调用在线 OCR 接口（比赛现场没网）
- 不许把"没引擎"伪装成"识别成功"（`confidence` 必须 0，`blocks` 必须空）
- 不许在测试里提交真实聊天截图（含真实姓名/号码）；测试一律用代码里构造的最小图
- 不许改 `app/schemas/**`

## 6. 验收命令（队长会照着跑，必须全绿）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task lint
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task test
python scripts/docs.py check
```

附加验收（人工看一眼）：

- [ ] 手机截 3 张图（聊天 / 转账页 / 来电屏）放 `data/samples/images/`，跑一遍打印 `backend / width / height`
- [ ] 把一张 5MB 的图丢进去，确认报 `ImageTooLarge` 而不是卡住
- [ ] PR 里写明：本机有没有 tesseract；没有的话现场演示怎么讲

## 7. 预计与截止

| 项 | 内容 |
|---|---|
| 负责人 | C |
| 预计耗时 | 2 天（格式与尺寸 0.5 天 / 引擎探测 0.5 天 / 测试 1 天） |
| 截止 | 周日晚 22:00 |
| 卡住找谁 | @队长 |

## 8. 交付时会问的三个问题（提前想好）

1. 为什么"没引擎就返回空"比"抛 501"更好？（提示：上层可以统一处理，且日志更干净）
2. 一张 1080P 截图在真机上跑 OCR 大概多久？你测过哪一张？
3. 「截图被 P 过」这条证据（`FR-2.4b`）你打算从哪几个信号判断？

## 9. 完成记录（智能体填）

```
做了什么：<一句话>
验收命令：scripts/check.ps1 -Task all  +  python scripts/docs.py check
结果：<全绿 / 哪条红，红在哪>
契约变更：无
```
