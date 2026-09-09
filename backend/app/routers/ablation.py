"""Dedicated endpoints for one-shot ablation methods.

This router deliberately has no dependency on either Advisor engine, beats,
review, repair, or the cross-institution composer.
"""
from fastapi import APIRouter, HTTPException, Request

from ..ablation_runner import (
    apply_ablation_candidate,
    load_ablation_record,
    normalize_baseline_context,
    start_ablation_replay,
    start_ablation_run,
    validate_baseline_spec,
    wait_ablation_run,
)
from ..schemas import ApplyRequest, ReplayRequest, RunRequest

router = APIRouter()
_METHODS = {"persona_direct", "prompt_only", "rag"}


@router.post("/api/ablation/run")
async def ablation_run(request: Request, body: RunRequest, wait: bool = False):
    method = str(body.generation_method or "").lower()
    if method not in _METHODS:
        raise HTTPException(status_code=400, detail="generation_method must be persona_direct, prompt_only, or rag")
    errors = validate_baseline_spec(body.spec)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    run, error = start_ablation_run(
        request.app.state.ablation_runs, request.app.state.registry, request.app.state.llm,
        body.spec, body.persona_ids, normalize_baseline_context(body.context), method,
    )
    if run is None:
        raise HTTPException(status_code=404 if "未知" in error else 400, detail=error)
    if wait:
        await wait_ablation_run(run)
    return run.payload()


@router.get("/api/ablation/run/{run_id}")
async def ablation_run_status(request: Request, run_id: str):
    run = request.app.state.ablation_runs.get(run_id)
    if run is None:
        record, error = load_ablation_record(run_id)
        if record is None: raise HTTPException(status_code=404, detail=error)
        return record
    return run.payload()


@router.post("/api/ablation/replay")
async def ablation_replay(request: Request, body: ReplayRequest, wait: bool = False):
    run, error = start_ablation_replay(
        request.app.state.ablation_runs, body.run_id, body.persona_ids or None, body.beat_delay_ms,
    )
    if run is None: raise HTTPException(status_code=404 if "未找到" in error else 400, detail=error)
    if wait: await wait_ablation_run(run)
    return run.payload()


@router.post("/api/ablation/apply")
async def ablation_apply(body: ApplyRequest):
    errors = validate_baseline_spec(body.spec)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return apply_ablation_candidate(body.spec, body.changes, body.instructions)
