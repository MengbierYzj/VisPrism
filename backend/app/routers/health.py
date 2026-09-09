from fastapi import APIRouter, Request

from ..config import settings

router = APIRouter()


@router.get("/api/health")
async def health(request: Request):
    registry = request.app.state.registry
    return {
        "ok": True,
        "llm_mode": settings.llm_mode,
        "model": settings.model if settings.llm_mode == "live" else None,
        "prefer_mode": settings.prefer_mode,
        "chart_type_prefer_mode": settings.prefer_mode,  # 兼容旧字段
        "advisor_chart_type_changes_enabled": settings.advisor_chart_type_changes_enabled,
        "personas": len(registry.list()),
    }
