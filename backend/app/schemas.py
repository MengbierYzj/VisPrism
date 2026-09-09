"""API 请求模型（契约见 doc/api/接口文档.md）。响应为动态结构，用 dict 返回。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    spec: dict
    persona_ids: list[str] = Field(min_length=1)
    context: dict = Field(default_factory=dict)
    generation_method: str = "advisor"


class ReplayRequest(BaseModel):
    """回放历史 run：spec 与 context 取自记录本身，故只需指名 run_id。"""

    run_id: str
    persona_ids: list[str] = Field(default_factory=list)
    beat_delay_ms: int | None = None


class ApplyRequest(BaseModel):
    spec: dict
    changes: list[dict] = Field(default_factory=list)
    instructions: str = ""


class DiscussRequest(BaseModel):
    """Review Board 议题讨论：issue 携带该议题聚合的跨机构 changes 原样回传。"""

    spec: dict
    persona_ids: list[str] = Field(min_length=1)
    issue: dict = Field(default_factory=dict)
    question: str = ""
    history: list[dict] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
