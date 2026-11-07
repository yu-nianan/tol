---
title: T-02 音频链路骨架：wav → 静音切段 → 转写契约（负责人 B）
owner: B
status: final
last_updated: 2026-11-05
related_code: app/pipelines/audio, tests/audio
summary: 把 asr.py 从"直接抛异常"改成"能切段、能降级、契约固定"的骨架
audience: agent
depends_on: [../INDEX.md, ../需求清单.md]
covers: [FR-1.2]
supports: [FR-1.4, FR-2.4b]
depends_on_task: []
---

# 任务单：音频链路打通骨架（wav → 静音切段 → 转写契约 → 证据）

## 1. 背景（为什么做这件事）

- 对应需求：`FR-1.2`（音频接入）、`NFR-3`（ASR 在噪声/方言下退化要有降级）
- 对应测试用例：`TC-1.3`（30s 录音转文字并进判别）、`TC-1.4`（5min 录音异步出结果）
- 现状：`app/pipelines/audio/asr.py` 只有 22 行，`transcribe()` 直接 `raise ASRNotConfigured()`，
  `POST /api/v1/detect/audio` 返回 501。链路是断的，演示时只能讲"这块还没接"。
- 一句话：先把"能收、能切、能降级"做成，模型可以后补——但要**诚实**（没模型就说没模型，不许假装转出来了）。

## 2. 目标（做完之后，什么会不一样）

1. `app/pipelines/audio/asr.py` 暴露一个固定契约：

```python
@dataclass
class Segment:
    start_s: float
    end_s: float
    rms: float

@dataclass
class Transcript:
    text: str
    segments: list[Segment]
    duration_s: float
    backend: str        # "energy-vad-only" / "funasr" / "mock"
    confidence: float   # 没接模型时必须是 0.0

def transcribe(audio_bytes: bytes, suffix: str = ".wav") -> Transcript: ...
```

2. 纯标准库实现（`wave` + `array` + `struct`，**不许装任何包**）：
   - 读 wav 头（采样率、声道、位深），非 PCM/非 16bit 要么降级要么抛 `UnsupportedAudioFormat`
   - 按 30ms 帧算 RMS，阈值 = 0.15 × 全片峰值能量，连续静音 ≥300ms 切一刀，段数上限 200
   - 立体声先混成单声道；采样率不是 16k 时按最近邻抽到 16k（够用，不追求音质）
   - **没接模型时**：`backend="energy-vad-only"`、`text=""`、`confidence=0.0`，不抛异常
3. `tests/audio/test_asr.py` 至少 5 条：合成 1s 正弦 → 1 段；全静音 → 段数 0 或 1 且 `text==""`；
   乱码字节 → `UnsupportedAudioFormat`；48k 立体声 → 不崩且 `duration_s` 误差 <5%；
   超长（60s 静音 + 1s 正弦）→ 段数 ≤ 200。

## 3. 输入 / 输出样例（写死，不要"大概"）

```python
tr = transcribe(open("data/samples/audio/demo_1s.wav", "rb").read())
# Transcript(text="", segments=[Segment(start_s=0.0, end_s=1.0, rms=0.71)], duration_s=1.0,
#            backend="energy-vad-only", confidence=0.0)
```

## 4. 允许修改的路径（超出即越界）

```
app/pipelines/audio/**
tests/audio/**
data/samples/audio/**       # 你自己录/合成的测试音频，本地放着即可（data/ 不入库）
```

**你不许碰 `app/api/**`**：把音频接进 `POST /api/v1/detect/audio` 是队长的活，
你只要保证 `transcribe()` 的签名和返回结构按上面写死。

## 5. 不许做的事（本次特有）

- 不许新增依赖（不许 `pip install funasr / librosa / numpy`）；模型接入是**下一张**单子
- 不许让 `transcribe()` 在"没模型"时返回编造的文本（这是本项目最大的红线）
- 不许吞异常（`except: pass`），要么抛具体异常，要么在 `backend` 里写清降级原因
- 不许改 `app/schemas/**`；需要新字段先提 issue

## 6. 验收命令（队长会照着跑，必须全绿）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task lint
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Task test
python scripts/docs.py check
```

附加验收（人工看一眼）：

- [ ] 自己用手机录 3 段（诈骗话术 / 正常通话 / 纯静音），放进 `data/samples/audio/`
- [ ] 写个 5 行脚本把 3 段都跑一遍，把 `len(segments)`、`duration_s`、`backend` 打印出来贴进 PR
- [ ] PR 里写明：没接模型时"演示该怎么讲"（一句话，别吹）

## 7. 预计与截止

| 项 | 内容 |
|---|---|
| 负责人 | B |
| 预计耗时 | 2.5 天（wav 解析 0.5 天 / 切段 1 天 / 测试 1 天） |
| 截止 | 周日晚 22:00 |
| 卡住找谁 | @队长 |

## 8. 交付时会问的三个问题（提前想好）

1. 为什么先切段再转写，而不是整段丢给模型？（提示：长音频、静音段、以及"哪一句是转账话术"的定位）
2. 5 分钟的录音走这条路要多久？卡在哪一步？
3. 模型没装的时候，答辩被问"你们音频怎么做的"，你怎么回答才不算吹牛？

## 9. 完成记录（智能体填）

```
做了什么：<一句话>
验收命令：scripts/check.ps1 -Task all  +  python scripts/docs.py check
结果：<全绿 / 哪条红，红在哪>
契约变更：无
```
