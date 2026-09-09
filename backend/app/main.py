"""vizguide backend：机构设计人格多智能体图表建议服务。

- GET  /api/health              健康检查
- GET  /api/personas            机构 persona 列表（内置 + 自定义）
- POST /api/personas/parse      规范 md → Parser Agent 装配新 persona
- POST /api/upload              上传 vegalite.json（校验 + 事实提取）
- POST /api/advisor/run         启动多机构并行咨询（四拍快慢管线）
- GET  /api/advisor/run/{id}    轮询各 agent 逐拍状态与提案
- POST /api/v2/advisor/run      契约式引擎：拍3 自由生成 spec，拍4 程序核验
- POST /api/advisor/discuss     Review Board 议题讨论（机构回答用户追问）
- POST /api/design/apply        跨机构采纳合成终稿
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .advisor_v2.runner import V2RunStore
from .config import settings
from .core.persona import PersonaRegistry
from .core.runner import RunStore
from .llm import LLMClient
from .routers import advisor, advisor_v2, design, health, personas, upload


@asynccontextmanager
async def lifespan(app: FastAPI):
    custom_dir = settings.storage_dir / "personas"
    custom_dir.mkdir(parents=True, exist_ok=True)
    app.state.registry = PersonaRegistry(data_dir=settings.data_dir, custom_dir=custom_dir)
    app.state.llm = LLMClient()
    app.state.runs = RunStore()
    app.state.v2_runs = V2RunStore()
    loaded = [p.id for p in app.state.registry.list()]
    print(f"[vizguide] personas: {loaded} | llm_mode: {settings.llm_mode}")
    yield


app = FastAPI(title="vizguide backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """统一错误结构，避免前端解析失败。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": str(exc.detail)}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {"code": 500, "message": f"{type(exc).__name__}: {exc}"}},
    )


for r in (health, personas, upload, advisor, advisor_v2, design):
    app.include_router(r.router)
