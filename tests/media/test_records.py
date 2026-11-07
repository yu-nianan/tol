"""Audit retention and absence of original media in persisted receipts."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.pipelines.media._records import MediaPreprocessError, _record


def test_record_persists_hash_and_processing_stats_without_media(tmp_path):
    original = b"synthetic private recording: no raw storage"
    record = _record(
        original, "audio", status="ready",
        metadata={"operations": ["resample"], "truncated": False, "warnings": []},
        audit_dir=tmp_path,
    )
    receipt = next(tmp_path.glob("media-*.json")).read_text(encoding="utf-8")
    assert json.loads(receipt) == record
    assert record["sha256"] == hashlib.sha256(original).hexdigest()
    assert record["raw_stored"] is False
    assert record["retention_days"] == 7
    assert original.decode() not in receipt


def test_rejected_attempt_is_also_recorded(tmp_path):
    record = _record(b"invalid", "image", status="rejected", metadata={"error_code": "invalid_image"}, audit_dir=tmp_path)
    assert record["status"] == "rejected"
    assert record["warnings"] == []
    assert len(list(tmp_path.glob("media-*.json"))) == 1


def test_retention_removes_only_expired_owned_receipts(tmp_path):
    stale = (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y%m%dT%H%M%S%fZ")
    expired = tmp_path / f"media-{stale}-{'a' * 32}.json"
    expired.write_text("{}", encoding="utf-8")
    unrelated = tmp_path / "media-keep.json"
    unrelated.write_text("do not touch", encoding="utf-8")
    _record(b"new", "audio", status="ready", metadata={}, audit_dir=tmp_path)
    assert not expired.exists()
    assert unrelated.read_text(encoding="utf-8") == "do not touch"
    assert len(list(tmp_path.glob("media-*.json"))) == 2


def test_unwritable_audit_directory_is_explicit_failure(tmp_path):
    occupied = tmp_path / "file"
    occupied.write_text("occupied", encoding="utf-8")
    with pytest.raises(MediaPreprocessError, match="无法保存媒体处理摘要") as caught:
        _record(b"new", "audio", status="ready", metadata={}, audit_dir=occupied)
    assert caught.value.code == "audit_write_failed"
    assert caught.value.record is None
