from fastapi import APIRouter, HTTPException, Request

from ..core.composer import apply_design
from ..core.specfacts import validate_spec
from ..schemas import ApplyRequest

router = APIRouter()


@router.post("/api/design/apply")
async def design_apply(request: Request, body: ApplyRequest):
    """跨机构采纳合成：确定性重放被采纳修改的 ops，可选自由文本微调（live）。"""
    errors = validate_spec(body.spec)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return await apply_design(body.spec, body.changes, body.instructions, request.app.state.llm)
