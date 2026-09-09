from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..core.parser_agent import parse_guideline

router = APIRouter()

MAX_GUIDELINE_BYTES = 512 * 1024


@router.get("/api/personas")
async def list_personas(request: Request):
    registry = request.app.state.registry
    return {"personas": [p.meta() for p in registry.list()]}


@router.post("/api/personas/parse")
async def parse_persona(request: Request, file: UploadFile = File(...), name: str = Form("")):
    """上传机构规范 markdown → Parser Agent 解析装配为新 persona agent。"""
    raw = await file.read()
    if len(raw) > MAX_GUIDELINE_BYTES:
        raise HTTPException(status_code=413, detail="规范文件过大（上限 512KB）")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="规范文件必须是 UTF-8 文本")
    if not text.strip():
        raise HTTPException(status_code=400, detail="规范文件为空")

    display_name = name.strip() or (file.filename or "custom").rsplit(".", 1)[0]
    data, warnings = await parse_guideline(display_name, text, request.app.state.llm)
    quality_errors = (
        (data.get("parser_provenance") or {}).get("quality_errors") or []
    )
    if quality_errors:
        raise HTTPException(
            status_code=422,
            detail="Persona 质量门未通过：" + "；".join(str(error) for error in quality_errors),
        )
    data.setdefault("institution", {})["source"] = file.filename or f"{display_name}.md"
    persona = request.app.state.registry.register_custom(data, source_name=file.filename or "")
    return {"persona": persona.meta(), "warnings": warnings}
