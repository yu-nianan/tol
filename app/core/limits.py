"""上传体积与类型的唯一来源：上限常量、魔数表、限量读取、请求体中间件。

为什么单独一个模块：

- ``MAX_AUDIO_BYTES`` / ``MAX_IMAGE_BYTES`` **只在这里定义一次**。音频预处理（T-13）
  要限体积请 ``from app.core.limits import MAX_AUDIO_BYTES``，不要另起常量，
  否则两处数字一旦不同步，就会出现"路由放行、预处理报错"的怪现象；
- 三层防护：① 中间件看 ``Content-Length``（不读内容）② ``read_limited`` 读时限量
  （防伪造头）③ 领域层看魔数（防扩展名撒谎）。三层各自独立，缺一层都能被绕过。

错误码约定（与 ``app/core/errors.py`` 一致，前端按 code 分支）：

- ``file_too_large`` → 413
- ``unsupported_audio_format`` / ``unsupported_image_format`` → 415（由领域层抛）
"""

from __future__ import annotations

import json

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import AppError

# ---- 上限：只在这里定义一次 ----
MAX_AUDIO_BYTES = 8 * 1024 * 1024
"""音频上限 8MB：16k/16bit 单声道 wav ≈ 4 分钟。"""

MAX_IMAGE_BYTES = 4 * 1024 * 1024
"""图片上限 4MB：与 ``app/pipelines/vision/ocr.py`` 既有口径保持一致。"""

MAX_REQUEST_BYTES = 12 * 1024 * 1024
"""整个请求体上限：取两者较大值再留一点余量给 multipart 边界。"""

# ---- 魔数：判类型不看扩展名 ----
AUDIO_MAGIC = (b"RIFF",)
"""wav 只有 RIFF 一种合法容器；mp3 的 ID3、m4a 的 ftyp 都不在这里，直接 415。"""

IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff")
"""PNG / JPEG，与 ``ocr.py`` 的签名判断保持一致。"""


def has_magic(data: bytes, magics: tuple[bytes, ...]) -> bool:
    """数据是否以任一魔数开头（文件太短也算不匹配）。"""
    return bool(data) and any(data.startswith(magic) for magic in magics)


async def read_limited(upload, limit: int) -> bytes:
    """按上限读取上传内容，超出抛 413。

    读 ``limit + 1`` 字节而不是 ``limit``：多出来的那个字节就是"超限"的证据，
    既不会把整个大文件读进内存，也不用相信客户端给的 ``Content-Length``。
    """
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise AppError(
            f"文件过大：超过上限 {limit // (1024 * 1024)}MB，请裁剪后重试",
            code="file_too_large",
            status=413,
        )
    return data


def _too_large(limit: int) -> AppError:
    return AppError(
        f"请求体过大：超过上限 {limit // (1024 * 1024)}MB",
        code="file_too_large",
        status=413,
    )


class BodySizeLimitMiddleware:
    """请求体上限的兜底：只看 Content-Length，超限在进路由前就 413。

    ASGI 中间件（不是 ``BaseHTTPMiddleware``）：不读请求体、不缓冲，唯一开销是
    一次头部判断。没有 ``Content-Length`` 的请求（分块传输）交给
    ``read_limited`` 的读时限量兜底，所以这一层不需要处理无头的情况。
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        length = Headers(scope=scope).get("content-length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                declared = -1
            if declared < 0:
                await self._reject(send, AppError("Content-Length 不是合法整数", code="bad_request", status=400))
                return
            if declared > self.max_bytes:
                await self._reject(send, _too_large(self.max_bytes))
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send, error: AppError) -> None:
        body = json.dumps(
            {"error": {"code": error.code, "message": error.message}},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = MutableHeaders()
        headers["content-type"] = "application/json; charset=utf-8"
        headers["content-length"] = str(len(body))
        message: Message = {
            "type": "http.response.start",
            "status": error.status,
            "headers": headers.raw,
        }
        await send(message)
        await send({"type": "http.response.body", "body": body})
