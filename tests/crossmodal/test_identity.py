"""T-10：号码归属与自称身份的冲突启发式。"""

from __future__ import annotations

from app.pipelines.vision.identity import number_identity_mismatch
from app.schemas import Modality, SourceKind


def test_number_identity_mismatch_same_city_returns_zero() -> None:
    evidence = number_identity_mismatch("010-8888-6666", "我是北京市公安局的")

    assert evidence.confidence == 0.0
    assert evidence.kind == SourceKind.CROSS_MODAL
    assert evidence.modality == Modality.TEXT
    assert "启发式" in evidence.meta["note"]


def test_number_identity_mismatch_different_city_fires() -> None:
    evidence = number_identity_mismatch("01088886666", "我是上海市公安局的")

    assert evidence.confidence >= 0.5
    assert "different_region" in evidence.meta["signals"]
    assert evidence.meta["area"]["city"] == "北京"


def test_number_identity_mismatch_same_province_diff_city_is_weaker() -> None:
    evidence = number_identity_mismatch("075588886666", "我是广州市公安局的")

    assert evidence.confidence == 0.45
    assert "same_province_diff_city" in evidence.meta["signals"]


def test_number_identity_mismatch_virtual_operator_authority_fires() -> None:
    evidence = number_identity_mismatch("17012345678", "我是派出所民警，你涉嫌洗钱")

    assert evidence.confidence >= 0.5
    assert evidence.meta["virtual_operator"] is True
    assert "virtual_operator_authority" in evidence.meta["signals"]


def test_number_identity_mismatch_mobile_authority_is_weak() -> None:
    evidence = number_identity_mismatch("13800000000", "我是上海市公安局的")

    assert 0.0 < evidence.confidence <= 0.2
    assert "authority_mobile_weak" in evidence.meta["signals"]


def test_number_identity_mismatch_garbage_returns_zero() -> None:
    for phone in ("", "abc", "12345"):
        evidence = number_identity_mismatch(phone, "我是公安局的")
        assert evidence.confidence == 0.0


def test_number_identity_mismatch_masked_phone_stays_masked() -> None:
    evidence = number_identity_mismatch("138****0000", "我是上海市公安局的")

    assert evidence.meta["phone_masked"] == "138****0000"
