"""ASR 接入点（第 3 周由负责人 B 实现）。

契约已经定死：
    transcribe(audio_bytes) -> str  # 返回中文转写文本

推荐实现顺序：silero-vad 切段 → FunASR paraformer-zh 转写 → 置信度 < 0.6 的段落丢弃。
在没接之前，接口层会返回 501 + 明确提示，绝不用假数据冒充"已支持"。
"""

from __future__ import annotations

ASR_ENABLED = False
ASR_BACKEND = "not-implemented"


class ASRNotConfigured(RuntimeError):
    def __init__(self) -> None:
        super().__init__("ASR 未接入：第 3 周由负责人 B 接入 FunASR / sherpa-onnx（见 docs/tickets）")


def transcribe(audio_bytes: bytes) -> str:
    raise ASRNotConfigured()
