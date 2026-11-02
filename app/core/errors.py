"""统一错误：业务错误都带 code，前端/脚本按 code 分支，不靠猜文案。"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, message: str, code: str = "bad_request", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}},
    )
