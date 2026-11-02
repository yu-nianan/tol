"""应用入口：组装路由、错误处理、启动日志。

要加新能力，写成 `app/api/*.py` 的 router，然后在这里 include_router，
不要往本文件里堆业务逻辑。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import alerts, detect, health, kb, web
from app.core.config import settings
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.core.logging import get_logger, setup_logging
from app.pipelines.decision.engine import get_engine

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    log.info(
        "服务启动 scripts=%s cases=%s llm=%s",
        engine.kb.script_count,
        engine.kb.case_count,
        settings.llm_enabled,
    )
    yield
    log.info("服务停止")


def create_app() -> FastAPI:
    setup_logging(settings.log_level)
    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="A30 多模态反诈智能助手 —— 规则可跑、模型可插的骨架",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)

    application.include_router(health.router)
    application.include_router(web.router)
    application.include_router(detect.router)
    application.include_router(alerts.router)
    application.include_router(kb.router)
    return application


app = create_app()
