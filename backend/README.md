# Backend（Python / FastAPI）

机构设计人格（Institutional Design Persona）多智能体图表建议服务：
每个机构 agent 以自身 persona 走"慢-快-慢-快"四拍推理，对输入的 Vega-Lite
图表产出带担保依据的修改方案。架构详见 `doc/后端方案.md`。

## 1. 环境要求

- Python `3.11+`
- conda 环境：`vizguide`
- 包管理：统一使用 `python -m pip`（避免装到系统环境）

## 2. 快速启动

```bash
conda activate vizguide
cd backend
# 首次可先生成本地环境变量文件（不配 key 则慢道为 mock，仍可端到端运行）
# cp .env.example .env
./scripts/dev.sh
```

`scripts/dev.sh` 会做两件事：

1. 检查当前 conda 环境是否为 `vizguide`
2. 安装依赖并启动 `uvicorn app.main:app --reload`（存在 `.env` 时自动加载）

默认服务地址：`http://127.0.0.1:8000`

## 3. API 概览

- `GET  /api/health` — 健康检查（含慢道 llm_mode）
- `GET  /api/personas` — 机构 persona 列表（内置 + 自定义）
- `POST /api/personas/parse` — 上传规范 md，Parser Agent 装配新 persona
- `POST /api/upload` — 上传 `vegalite.json`（校验 + 事实提取）
- `POST /api/advisor/run` — 启动多机构并行咨询（`?wait=true` 阻塞式）
- `GET  /api/advisor/run/{run_id}` — 轮询各 agent 四拍状态与提案
- `POST /api/design/apply` — 跨机构采纳合成终稿

接口详细契约请看：`doc/api/接口文档.md`

## 4. 项目结构

```
backend/
  app/
    main.py            # FastAPI 装配（lifespan / CORS / 统一错误结构）
    config.py          # 环境变量配置
    llm.py             # 慢道 LLM 客户端（live/mock）
    schemas.py         # 请求模型
    core/
      persona.py       # persona 三层装载、令牌索引、注册表
      specfacts.py     # spec → 设计状态事实（快道）
      conditions.py    # L2 when 条件三态求值（快道）
      actions.py       # ops 词汇表 + then→ops 编译（令牌直注）
      detectors.py     # L1 检测器 + 不变量核验（快道）
      beats.py         # 慢-快-慢-快四拍管线
      runner.py        # 多智能体并行扇出 + RunStore + 快照
      parser_agent.py  # 规范 md → persona（Parser Agent）
      composer.py      # 跨机构采纳合成（Composer）
    routers/           # health / personas / upload / advisor / design
  tests/               # pytest（14 项）
  scripts/dev.sh       # 开发启动
  requirements.txt
  .env.example
```

## 5. 配置项（环境变量）

推荐做法：

- 本机配置放在 `backend/.env`（已默认忽略，不上传）
- 团队模板放在 `backend/.env.example`（可上传）
- 启动脚本会在存在 `.env` 时自动使用 `uvicorn --env-file .env`

主要变量：`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `VIZGUIDE_MODEL`（慢道 LLM，
兼容 DeepSeek、Qwen 等 OpenAI 兼容服务）；`VIZGUIDE_LLM_MODE=auto|live|mock`；
配置模板见 `.env.example`。

## 6. 测试

运行全部测试：

```bash
conda activate vizguide
cd backend
python -m pytest -q
```

## 7. 运行产物说明

- `backend/storage/uploads/`：上传文件的本地存储
- `backend/storage/runs/`：每次模拟的运行快照（含 request/response/provenance）
- `backend/storage/personas/`：Parser Agent 解析的自定义 persona

这些都属于运行时产物，已在根 `.gitignore` 中忽略，不提交 GitHub。

## 8. 数据位置说明

- 当前项目约定：原始 case 数据与内置 persona 统一放在仓库根目录 `data/`
- 后端默认从 `data/` 读取内置 persona（可用 `VIZGUIDE_DATA_DIR` 覆盖）
- `data/` 作为研究数据资产保留，便于前后端与研究侧共享

