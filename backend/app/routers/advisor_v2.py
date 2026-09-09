"""契约式四拍引擎的端点，以及历史 run 的列举与回放。"""
from fastapi import APIRouter, HTTPException, Request

from ..advisor_v2.replay import list_records, load_record, start_replay_run
from ..advisor_v2.runner import start_run_v2, wait_run_v2
from ..core.request_context import make_context
from ..core.specfacts import validate_spec
from ..schemas import ReplayRequest, RunRequest

router = APIRouter()


@router.post("/api/v2/advisor/run")
async def advisor_v2_run(request: Request, body: RunRequest, wait: bool = False):
    errors = validate_spec(body.spec)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    run, err = start_run_v2(request.app.state.v2_runs, request.app.state.registry, request.app.state.llm, body.spec, body.persona_ids, make_context(body.context))
    if run is None:
        raise HTTPException(status_code=404 if "未知" in err else 400, detail=err)
    if wait:
        await wait_run_v2(run)
    return run.payload()


@router.get("/api/v2/advisor/run/{run_id}")
async def advisor_v2_run_status(request: Request, run_id: str):
    """轮询进行中的 v2 run；已结束并落盘的历史 run 由 /runs 与 /replay 提供。"""
    run = request.app.state.v2_runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"未知 run: {run_id}")
    return run.payload()


@router.get("/api/v2/advisor/runs")
async def advisor_v2_runs():
    """列出 storage/runs 下所有可回放的历史记录（v1 与 v2 皆可）。"""
    return {"runs": list_records()}


@router.get("/api/v2/advisor/runs/{run_id}")
async def advisor_v2_run_record(run_id: str):
    """直接取回某条历史记录的完整快照，供离线分析与论文取证。"""
    document, err = load_record(run_id)
    if document is None:
        raise HTTPException(status_code=404, detail=err)
    return document


@router.post("/api/v2/advisor/replay")
async def advisor_v2_replay(request: Request, body: ReplayRequest, wait: bool = False):
    """按 run_id 复现一次历史咨询：只读重放，不调用 LLM，不改写原记录。"""
    run, err = start_replay_run(
        request.app.state.v2_runs,
        body.run_id,
        body.persona_ids or None,
        body.beat_delay_ms,
        request.app.state.registry,
    )
    if run is None:
        raise HTTPException(status_code=404 if "未找到" in err else 400, detail=err)
    if wait:
        await wait_run_v2(run)
    return run.payload()
