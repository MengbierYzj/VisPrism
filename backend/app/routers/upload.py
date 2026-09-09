import json
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import settings
from ..core.specfacts import extract_facts, validate_spec

router = APIRouter()

MAX_SPEC_BYTES = 2 * 1024 * 1024


@router.post("/api/upload")
async def upload_spec(file: UploadFile = File(...)):
    """上传 vegalite.json：校验、留存、返回解析后的 spec 与程序化事实。"""
    raw = await file.read()
    if len(raw) > MAX_SPEC_BYTES:
        raise HTTPException(status_code=413, detail="spec 文件过大（上限 2MB）")
    try:
        spec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"不是合法 JSON：{exc}")
    errors = validate_spec(spec)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    file_id = uuid.uuid4().hex[:12]
    uploads = settings.storage_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    with open(uploads / f"{file_id}.json", "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)

    return {"file_id": file_id, "spec": spec, "facts": extract_facts(spec)}
