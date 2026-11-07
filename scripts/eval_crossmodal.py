"""跨模态矛盾三件套的**构造样本**自检（T-10）。

注意：这里没有真实的 TTS 音频与 PS 截图，样本全部由代码按已知形态构造：
- 伪造/正常音频各 6 段（30ms 帧能量包络）；
- 伪造/正常转账页各 6 份（OCR 文本块）；
- 伪造/正常来电各 6 条（号码 + 自称）。
因此输出只能说明"检测器在已知形态上是否按预期触发"，**不能当真实准确率**。
真实指标的验收口径见 docs/tickets/T-10-跨模态矛盾-C.md。

运行：
    & .\\.venv\\Scripts\\python.exe scripts/eval_crossmodal.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.audio.artifacts import audio_artifacts  # noqa: E402
from app.pipelines.vision.identity import number_identity_mismatch  # noqa: E402
from app.pipelines.vision.ocr import Block  # noqa: E402
from app.pipelines.vision.template import template_deviation  # noqa: E402

AUDIO_THRESHOLD = 0.50
TEMPLATE_THRESHOLD = 0.25
IDENTITY_THRESHOLD = 0.45


def _tts(level: float, active: int, pause: int, repeats: int) -> list[float]:
    values: list[float] = []
    for _ in range(repeats):
        values.extend([level] * active)
        values.extend([0.0] * pause)
    return values


def _normal_envelope(seed: int) -> list[float]:
    rng = random.Random(seed)
    values = [rng.uniform(0.08, 0.55) for _ in range(300)]
    for start, length in ((40, 12 + seed % 7), (120, 25), (230, 45)):
        for index in range(start, start + length):
            values[index] = 0.0
    for index in range(20, 300, 20):
        if values[index] == 0.0:
            continue
        values[index - 1] = 0.005
        values[index] = 0.85
    return values


def _page(*blocks: tuple[str, int, int]) -> list[Block]:
    return [Block(text=text, x=x, y=y, w=400, h=40) for text, x, y in blocks]


def _fake_pages() -> list[list[Block]]:
    missing = [
        ("转账金额 ¥1,000.00", 50, 100),
        ("收款人 张*", 50, 350),
        ("收款账户 6222****1234", 50, 420),
    ]
    pages = [_page(*missing) for _ in range(3)]
    for offset in (40, 60, 80):
        pages.append(
            _page(
                ("转账金额 ¥2,000.00", 50, 100),
                ("收款人 李*", 50, 350),
                ("收款账户 6222****5678", 50, 420),
                ("确认转账", 300, offset),
            )
        )
    return pages


def _normal_pages() -> list[list[Block]]:
    pages: list[list[Block]] = []
    for index in range(6):
        base = 90 + index * 10
        pages.append(
            _page(
                (f"转账金额 ¥{1000 + index * 100}.00", 50, base),
                ("收款人 张*", 50, base + 250),
                ("收款账户 6222****1234", 50, base + 320),
                ("确认转账", 300, base + 720),
            )
        )
    return pages


def _confusion(pairs: list[tuple[int, bool]], threshold: float) -> dict:
    tp = fp = tn = fn = 0
    for actual, confidence in pairs:
        predicted = confidence >= threshold
        if actual and predicted:
            tp += 1
        elif actual:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    accuracy = (tp + tn) / len(pairs) if pairs else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "accuracy": round(accuracy, 3),
    }


def _report(name: str, pairs: list[tuple[int, bool]], threshold: float) -> dict:
    matrix = _confusion(pairs, threshold)
    print(f"{name}（阈值 {threshold:.2f}）：{matrix}")
    return matrix


def main() -> int:
    fake_audio = [_tts(level, active, pause, repeats) for level, active, pause, repeats in (
        (0.5, 20, 20, 5),
        (0.3, 30, 15, 4),
        (0.7, 12, 12, 6),
        (0.45, 25, 25, 4),
        (0.6, 16, 20, 5),
        (0.35, 18, 22, 5),
    )]
    audio_pairs = [(1, audio_artifacts(values).confidence) for values in fake_audio]
    audio_pairs += [(0, audio_artifacts(_normal_envelope(seed)).confidence) for seed in range(1, 7)]

    template_pairs = [(1, template_deviation(page).confidence) for page in _fake_pages()]
    template_pairs += [(0, template_deviation(page).confidence) for page in _normal_pages()]

    identity_pairs = [
        (1, number_identity_mismatch("01088886666", "我是上海市公安局的").confidence),
        (1, number_identity_mismatch("075588886666", "我是北京市公安局的").confidence),
        (1, number_identity_mismatch("02888886666", "我是深圳市公安局的").confidence),
        (1, number_identity_mismatch("17012345678", "我是派出所民警").confidence),
        (1, number_identity_mismatch("17112345678", "我是检察院的").confidence),
        (1, number_identity_mismatch("075588886666", "我是广州市公安局的").confidence),
        (0, number_identity_mismatch("01088886666", "我是北京市公安局的").confidence),
        (0, number_identity_mismatch("01088886666", "我是快递员").confidence),
        (0, number_identity_mismatch("13800000000", "我是上海市公安局的").confidence),
        (0, number_identity_mismatch("075588886666", "我是深圳市公安局的").confidence),
        (0, number_identity_mismatch("02188886666", "我是上海市公安局的").confidence),
        (0, number_identity_mismatch("01088886666", "我是银行客服").confidence),
    ]

    print("== 跨模态矛盾三件套 · 构造样本自检（非真实 TTS/PS 数据集）==")
    audio = _report("audio_artifacts", audio_pairs, AUDIO_THRESHOLD)
    template = _report("template_deviation", template_pairs, TEMPLATE_THRESHOLD)
    identity = _report("number_identity_mismatch", identity_pairs, IDENTITY_THRESHOLD)
    print(
        "合计："
        f"audio TP={audio['tp']}/FP={audio['fp']}，"
        f"template TP={template['tp']}/FP={template['fp']}，"
        f"identity TP={identity['tp']}/FP={identity['fp']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
