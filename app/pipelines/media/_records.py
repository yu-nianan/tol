"""Local audit records; media bytes and recognized text are never persisted here."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

RETENTION_DAYS = 7
_AUDIT_DIR = Path(__file__).resolve().parents[3] / "data" / "samples" / "media" / "audit"
_RECORD_NAME = re.compile(r"media-(\d{8}T\d{12}Z)-[a-f0-9]{32}\.json")


class MediaPreprocessError(ValueError):
    """An explicit processing failure, with its audit record when writing succeeded."""

    def __init__(self, code: str, message: str, record: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.record = record


@dataclass
class MediaResult:
    """In-memory processed bytes plus processing details and a persisted audit receipt."""

    data: bytes
    metadata: dict
    record: dict


def _record(
    data: bytes,
    kind: str,
    *,
    status: str,
    metadata: dict,
    audit_dir: Path | None = None,
) -> dict:
    """Record one attempt, prune our expired receipts, and fail explicitly on I/O errors.

    Callers only pass processing statistics, fixed warnings and operation names. Never
    pass a filename, OCR text, external tool output or media payload in ``metadata``.
    Successful and rejected inputs follow exactly the same retention policy. Only
    this module's timestamped filenames can be removed during retention cleanup.
    """
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    record = {
        "schema_version": 1,
        "record_id": uuid.uuid4().hex,
        "created_at": now.isoformat(),
        "kind": kind,
        "status": status,
        "sha256": hashlib.sha256(data).hexdigest(),
        "input_size_bytes": len(data),
        "warnings": list(metadata.get("warnings", [])),
        "metadata": metadata,
        "raw_stored": False,
        "retention_days": RETENTION_DAYS,
    }
    # Serialize before opening the file so a programming error cannot leave a
    # partial audit receipt that looks successful.
    encoded = json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    directory = Path(audit_dir) if audit_dir is not None else _AUDIT_DIR
    destination = directory / f"media-{stamp}-{record['record_id']}.json"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        cutoff = (now - timedelta(days=RETENTION_DAYS)).strftime("%Y%m%dT%H%M%S%fZ")
        for candidate in directory.glob("media-*.json"):
            match = _RECORD_NAME.fullmatch(candidate.name)
            if match is not None and match.group(1) < cutoff and not candidate.is_symlink():
                candidate.unlink(missing_ok=True)
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    except OSError as exc:
        raise MediaPreprocessError(
            "audit_write_failed", "无法保存媒体处理摘要，请检查本地审计目录的空间和写入权限。"
        ) from exc
    return record
