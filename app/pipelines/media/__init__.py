"""Pre-recognition media preparation, without model calls or media persistence.

Use ``prepare_audio`` / ``prepare_image`` before the existing recognition entry
points. ``mark_sensitive_regions`` conservatively locates OCR blocks for later
redaction. The API layer and shared schemas are unchanged by this module.
"""

from app.pipelines.media._records import MediaPreprocessError, MediaResult
from app.pipelines.media.audio import prepare_audio
from app.pipelines.media.image import mark_sensitive_regions, prepare_image

__all__ = ["MediaPreprocessError", "MediaResult", "prepare_audio", "prepare_image", "mark_sensitive_regions"]
