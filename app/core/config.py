"""运行配置：全部来自环境变量，不写死在代码里。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
KB_DIR = BASE_DIR / "app" / "kb"
DATA_DIR = BASE_DIR / "data"


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    log_level: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    guardian_webhook: str

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "反诈智能助手"),
        version=os.getenv("APP_VERSION", "0.1.0"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        llm_base_url=os.getenv("LLM_BASE_URL", "").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_model=os.getenv("LLM_MODEL", "").strip(),
        guardian_webhook=os.getenv("GUARDIAN_WEBHOOK", "").strip(),
    )


settings = load_settings()
