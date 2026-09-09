from fastapi import APIRouter, HTTPException, Request

from ..advisor_v2.runner import start_run_v2, wait_run_v2
from ..config import settings
from ..core.discussion import MAX_QUESTION_CHARS, build_discussion
from ..core.request_context import make_context as make_context_v2
from ..core.runner import make_context, start_run, wait_run
from ..core.specfacts import validate_spec
from ..schemas import DiscussRequest, RunRequest

router = APIRouter()


@router.post("/api/advisor/run")
async def advisor_run(request: Request, body: RunRequest, wait: bool = False):
    """启动多机构 persona agent 并行咨询。默认立即返回 run_id 供轮询；
    wait=true 时等待全部 agent 完成后返回完整结果（脚本/测试用）。

    承接的引擎由 VIZGUIDE_ADVISOR_ENGINE 决定（v1 编译执行 / v2 契约核验）。
    两个引擎的响应结构一致，故前端契约不随切换而变化。
    """
    errors = validate_spec(body.spec)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    if settings.advisor_engine == "v2":
        run, err = start_run_v2(
            request.app.state.v2_runs,
            request.app.state.registry,
            request.app.state.llm,
            body.spec,
            body.persona_ids,
            make_context_v2(body.context),
        )
        if run is None:
            raise HTTPException(status_code=404 if "未知" in err else 400, detail=err)
        if wait:
            await wait_run_v2(run)
        return run.payload()

    run, err = start_run(
        store=request.app.state.runs,
        registry=request.app.state.registry,
        llm=request.app.state.llm,
        spec=body.spec,
        persona_ids=body.persona_ids,
        context=make_context(body.context),
    )
    if run is None:
        raise HTTPException(status_code=404 if "未知" in err else 400, detail=err)
    if wait:
        await wait_run(run)
    return run.payload()


@router.get("/api/advisor/run/{run_id}")
async def advisor_run_status(request: Request, run_id: str):
    """轮询任一引擎发起的 run：两个存储都查，避免切换引擎后旧 run_id 轮询失败。"""
    run = request.app.state.runs.get(run_id) or request.app.state.v2_runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"未知 run: {run_id}")
    return run.payload()


@router.post("/api/advisor/discuss")
async def advisor_discuss(request: Request, body: DiscussRequest):
    """Review Board 议题讨论：机构 persona 回答用户追问（mock 模板 / live LLM）。"""
    errors = validate_spec(body.spec)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")
    if len(question) > MAX_QUESTION_CHARS:
        raise HTTPException(status_code=400, detail=f"question 超长（>{MAX_QUESTION_CHARS} 字符）")
    registry = request.app.state.registry
    unknown = [pid for pid in body.persona_ids if registry.get(pid) is None]
    if unknown:
        raise HTTPException(status_code=404, detail=f"未知 persona: {', '.join(unknown)}")
    return await build_discussion(
        llm=request.app.state.llm,
        registry=registry,
        spec=body.spec,
        persona_ids=body.persona_ids,
        issue=body.issue if isinstance(body.issue, dict) else {},
        question=question,
        history=body.history,
        context=body.context,
    )
