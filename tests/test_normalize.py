from __future__ import annotations

from app.pipelines.text.normalize import mask_sensitive, normalize, split_sentences, tokenize


def test_normalize_fullwidth_and_spaces() -> None:
    assert normalize("　你好　世界　") == "你好 世界"
    assert normalize("ＡＢＣ１２３") == "ABC123"
    assert normalize("   ") == ""


def test_mask_sensitive_hides_phone_card_id() -> None:
    text = "电话 13812345678，卡号 6222021234567890123，身份证 110101199001011234"
    masked = mask_sensitive(text)
    assert "13812345678" not in masked
    assert "138****5678" in masked
    assert "6222****" in masked
    assert "1101********" in masked


def test_split_sentences() -> None:
    parts = split_sentences("第一句。第二句！第三句？")
    assert parts == ["第一句", "第二句", "第三句"]


def test_tokenize_has_unigram_and_bigram() -> None:
    tokens = tokenize("转账abc")
    assert "转" in tokens
    assert "转账" in tokens
    assert "abc" in tokens
