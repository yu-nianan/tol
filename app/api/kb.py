"""知识库接口：查看剧本、新增案例（自更新链路的入口）。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.pipelines.decision.engine import get_engine

router = APIRouter(prefix="/api/v1/kb", tags=["kb"])


class IngestCaseRequest(BaseModel):
    text: str = Field(..., min_length=4, max_length=2000)
    script_id: str = Field("", max_length=16)
    title: str = Field("", max_length=80)
    level: str = Field("L2", max_length=4)
    id: str | None = Field(None, max_length=16)


@router.get("/scripts", summary="剧本列表")
def list_scripts() -> dict[str, object]:
    engine = get_engine()
    return {
        "count": engine.kb.script_count,
        "scripts": [
            {
                "id": script.id,
                "name": script.name,
                "risk_base": script.risk_base,
                "stages": [
                    {"name": stage.name, "label": stage.label, "weight": stage.weight}
                    for stage in script.stages
                ],
            }
            for script in engine.kb.scripts
        ],
    }


@router.get("/cases", summary="案例数量与最近入库")
def list_cases(limit: int = 20) -> dict[str, object]:
    engine = get_engine()
    cases = engine.kb.cases[-max(1, min(limit, 200)) :]
    return {
        "count": engine.kb.case_count,
        "cases": [
            {"id": case.id, "title": case.title, "script_id": case.script_id, "level": case.level}
            for case in cases
        ],
    }


@router.post("/cases", summary="新增案例（去重）")
def create_case(payload: IngestCaseRequest) -> dict[str, object]:
    engine = get_engine()
    added, message = engine.ingest_case(payload.model_dump())
    return {"added": added, "message": message, "count": engine.kb.case_count}
