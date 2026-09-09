"""多智能体编排：persona agent 并行扇出 + 运行状态存储。

架构（详见 doc/后端方案.md）：同构管线、异构知识——每个机构 agent 复用同一
条四拍推理引擎，只注入各自 persona；agent 间无通信（机构独立提案，用户跨机
构组合是产品交互而非 agent 协商）。asyncio 并行扇出，逐拍更新状态供前端轮询。
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings
from ..llm import LLMClient
from ..llm_log import (
    LLMRunLog,
    bind_llm_persona,
    bind_llm_run_log,
    reset_llm_persona,
    reset_llm_run_log,
)
from .beats import beat1_read, beat2_detect, beat3_adjudicate, beat4_compile
from .persona import Persona, PersonaRegistry
from .proposal_explainer import summarize_proposal
from .specfacts import extract_facts, structure_baseline

# 状态 → 进度（前端进度环映射四拍阶段）
STATUS_PROGRESS = {
    "pending": 0.05,
    "reading": 0.2,
    "detecting": 0.45,
    "adjudicating": 0.7,
    "compiling": 0.9,
    "done": 1.0,
    "error": 1.0,
}


@dataclass
class AgentState:
    persona_id: str
    status: str = "pending"
    proposal: dict | None = None
    error: str = ""

    def payload(self) -> dict:
        return {
            "persona_id": self.persona_id,
            "status": self.status,
            "progress": STATUS_PROGRESS.get(self.status, 0),
            "proposal": self.proposal,
            "error": self.error or None,
        }


@dataclass
class RunState:
    run_id: str
    spec: dict
    context: dict
    agents: dict[str, AgentState]
    order: list[str]
    created_at: str
    status: str = "running"
    llm_mode: str = "mock"  # 启动时配置的慢道模式（live|mock）
    agenda: dict | None = None  # 主持人议程合成（live；mock/失败为 None，前端回落本地派生）
    llm_log: LLMRunLog | None = field(default=None, repr=False)
    _supervisor: asyncio.Task | None = field(default=None, repr=False)

    def payload(self) -> dict:
        llm_execution = collect_llm_api_status(self)
        return {
            "run_id": self.run_id,
            "status": self.status,
            "created_at": self.created_at,
            # 仅暴露聚合调用结果，不返回提示词、响应正文或任何凭据。
            "llm_execution": llm_execution,
            "agenda": self.agenda,
            "agents": [self.agents[pid].payload() for pid in self.order],
        }


def collect_llm_api_status(run: RunState) -> dict[str, Any]:
    """汇总运行中实际 LLM 调用结果与是否降级（非「配置即为 mock」）。

    扫描各 agent trace / facts：mock-fallback、失败已降级、视觉 vision_error、
    拍前 role_source 含 llm_fallback。LLMRunLog 是真实 API 往返的唯一计数来源，
    因此 ``real_llm_succeeded`` 只会在 JSON 响应成功解析后变为 true。
    """
    configured = (run.llm_mode or "mock").lower()
    entries = run.llm_log.entries if run.llm_log is not None else []
    successful_calls = sum(1 for entry in entries if entry.get("ok") is True)
    failed_calls = sum(1 for entry in entries if entry.get("ok") is False)
    agent_rows: list[dict[str, Any]] = []
    any_fallback = False

    for pid in run.order:
        state = run.agents.get(pid)
        events: list[dict[str, Any]] = []
        if state is None:
            agent_rows.append({"persona_id": pid, "api_fallback": False, "events": []})
            continue
        prop = state.proposal or {}
        facts = prop.get("facts") if isinstance(prop.get("facts"), dict) else {}

        for t in prop.get("trace") or []:
            if not isinstance(t, dict):
                continue
            mode = str(t.get("mode") or "")
            intent_mode = str(t.get("intent_mode") or "")
            note = str(t.get("note") or "")
            beat = t.get("beat")
            if mode == "mock-fallback" or intent_mode == "mock-fallback" or "失败已降级" in note:
                events.append(
                    {
                        "beat": beat,
                        "mode": mode or intent_mode or None,
                        "note": note[:400],
                    }
                )
            vis = t.get("visual_review") if isinstance(t.get("visual_review"), dict) else None
            skipped = str((vis or {}).get("skipped") or "")
            if skipped.startswith("vision_error"):
                events.append({"beat": beat or 3, "kind": "visual_review", "skipped": skipped[:400]})

        facts_vis = facts.get("visual_review") if isinstance(facts.get("visual_review"), dict) else {}
        skipped_f = str(facts_vis.get("skipped") or "")
        if skipped_f.startswith("vision_error") and not any(
            e.get("kind") == "visual_review" for e in events
        ):
            events.append({"beat": 3, "kind": "visual_review", "skipped": skipped_f[:400]})

        if facts.get("decision_source") == "mock-fallback":
            events.append({"kind": "decision_source", "value": "mock-fallback"})

        rebuild = facts.get("spec_rebuild") if isinstance(facts.get("spec_rebuild"), dict) else {}
        role_source = str(rebuild.get("role_source") or "")
        if "llm_fallback" in role_source:
            events.append({"kind": "spec_rebuild", "role_source": role_source})

        # 仅 live 配置下的降级才算「API 问题导致 mock」
        api_fallback = bool(events) and configured == "live"
        if api_fallback:
            any_fallback = True
        agent_rows.append(
            {
                "persona_id": pid,
                "api_fallback": api_fallback,
                "events": events,
            }
        )

    if configured != "live":
        outcome = "mock_configured"
        summary = "configured_mock（非 API 故障；本次未调用真实 LLM）"
    elif run.status != "done":
        outcome = "live_pending"
        summary = "live 已配置，正在等待真实 LLM 调用结果"
    elif any_fallback:
        outcome = "live_fallback"
        summary = "live 调用失败，已降级 mock/启发式"
    elif successful_calls:
        outcome = "live_succeeded"
        summary = "live 调用成功，未降级 mock/启发式"
    else:
        outcome = "live_no_success"
        summary = "live 已配置，但本次没有成功的真实 LLM 调用"

    return {
        "outcome": outcome,
        "llm_api_mock_fallback": any_fallback,
        "configured_mode": configured,
        "model": settings.model if configured == "live" else None,
        "api_calls": {
            "total": len(entries),
            "successful": successful_calls,
            "failed": failed_calls,
        },
        "real_llm_succeeded": successful_calls > 0,
        "summary": summary,
        "agents": agent_rows,
    }


def allocate_run_id(store: "RunStore | None" = None) -> str:
    """运行记录 id：本地时间精确到分钟（YYYYMMDD-HHMM）；同分钟冲突追加 -2、-3…"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    runs_dir = Path(settings.storage_dir) / "runs"
    n = 1
    while True:
        candidate = stamp if n == 1 else f"{stamp}-{n}"
        in_mem = store is not None and store.get(candidate) is not None
        on_disk = (runs_dir / f"{candidate}.json").exists()
        if not in_mem and not on_disk:
            return candidate
        n += 1


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def get(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def add(self, run: RunState) -> None:
        self._runs[run.run_id] = run

    def snapshot(self, run: RunState) -> None:
        """运行快照落盘（request/response/provenance），供研究留痕复盘。

        **文件第一行**（单行 JSON）：是否因 LLM API 故障进入 mock。
        **第二行起**：完整快照（亦含 ``llm_api_status``）。读取正文用
        ``load_run_snapshot(path)``。目录：``backend/storage/runs/``。
        """
        try:
            runs_dir = settings.storage_dir / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            status = collect_llm_api_status(run)
            line1 = {
                "llm_api_mock_fallback": bool(status["llm_api_mock_fallback"]),
                "configured_mode": status["configured_mode"],
                "summary": status["summary"],
                "run_id": run.run_id,
            }
            doc = {
                "llm_api_mock_fallback": bool(status["llm_api_mock_fallback"]),
                "llm_api_status": status,
                "request": {
                    "spec": run.spec,
                    "persona_ids": run.order,
                    "context": run.context,
                },
                **run.payload(),
            }
            path = runs_dir / f"{run.run_id}.json"
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(line1, ensure_ascii=False) + "\n")
                json.dump(doc, f, ensure_ascii=False, indent=2)
                f.write("\n")
            # 另存本 run 全部 LLM API 往返
            if run.llm_log is not None:
                log_path = run.llm_log.flush()
                if log_path is not None:
                    print(f"[runner] LLM log → {log_path} ({len(run.llm_log.entries)} calls)")
        except OSError as exc:
            print(f"[runner] 快照写入失败: {exc}")


def load_run_snapshot(path: Any) -> dict[str, Any]:
    """读取 run 快照正文（跳过第一行 LLM 降级标记）。"""
    from pathlib import Path as _Path

    text = _Path(path).read_text(encoding="utf-8")
    nl = text.find("\n")
    if nl != -1:
        rest = text[nl + 1 :].lstrip()
        if rest.startswith("{"):
            return json.loads(rest)
    return json.loads(text)


async def _pace(llm: LLMClient) -> None:
    """mock 慢道无真实延时，加入演示节奏便于前端观察四拍推进；live 不加。"""
    if llm.mode != "live" and settings.mock_beat_delay_ms > 0:
        await asyncio.sleep(settings.mock_beat_delay_ms / 1000)


async def _agent_task(run: RunState, persona: Persona, llm: LLMClient) -> None:
    state = run.agents[persona.id]
    started = time.perf_counter()
    log_token = bind_llm_run_log(run.llm_log) if run.llm_log is not None else None
    persona_token = bind_llm_persona(persona.id)
    try:
        state.status = "reading"
        await _pace(llm)
        # 每个 persona 必须从原始 spec 独立开始；不共享任何拍前 rebuild、角色裁决
        # 或已修改 spec。四拍内部仍由该 persona 自己完成读图、检测、裁决和编译。
        working_spec = copy.deepcopy(run.spec)
        prep = {
            "changed": False,
            "actions": [],
            "role_source": "persona_independent_raw_spec",
            "reason": "shared pre-processing disabled",
        }
        facts = extract_facts(working_spec, run.context)
        facts["original_structure"] = structure_baseline(run.spec)
        # 视觉审查不仅看最终像素，还要知道原图有哪些静态注释应被保留；否则 LLM
        # 无法从“少了一行字”的最终图反推出漏失的具体内容。
        from .visual_review import annotation_text_baseline

        facts["annotation_text_baseline"] = annotation_text_baseline(run.spec)
        facts["spec_rebuild"] = prep
        # 可选客户端预览图覆盖；缺省由拍3 服务端 VL→PNG（spec_render）
        if isinstance(run.context.get("preview_image"), str):
            facts["preview_image"] = run.context["preview_image"]
        facts, t1 = await beat1_read(persona, working_spec, facts, llm)
        t1 = {**t1, "spec_rebuild": prep}

        state.status = "detecting"
        await _pace(llm)
        candidates, escalations, verify_list, passes, t2 = beat2_detect(
            persona, working_spec, facts
        )
        # 拍3.6 风格化的表面让位检查需要看到快道候选（如 L1 已带 band padding）
        facts["fast_candidates"] = candidates

        state.status = "adjudicating"
        await _pace(llm)
        adopted, rejected, t3 = await beat3_adjudicate(
            persona, working_spec, facts, escalations, llm
        )

        state.status = "compiling"
        await _pace(llm)
        modified, changes, invariants, t4 = beat4_compile(
            persona, working_spec, facts, candidates, adopted, verify_list, run.context
        )

        # 四拍完成后单独生成面向用户的解释；解释失败不影响结构化提案。
        explanation = await summarize_proposal(
            persona, facts, changes, [t1, t2, t3, t4], llm
        )
        # 保持既有 API 契约：自然语言直接回填原有字段，前端无需改动。
        for change in changes:
            text = explanation.get("change_explanations", {}).get(str(change.get("id")))
            if text:
                change["reason"] = text
                change["prompt"] = text

        n_applied = sum(1 for c in changes if c["status"] == "applied")
        n_suggested = len(changes) - n_applied
        # 快照不落盘整图 base64，仅保留来源元数据
        facts_out = dict(facts)
        raw_preview = facts_out.pop("preview_image", None)
        vis_meta = facts_out.get("visual_review") if isinstance(facts_out.get("visual_review"), dict) else {}
        if isinstance(raw_preview, str) and raw_preview:
            facts_out["preview_image_meta"] = {
                "present": True,
                "chars": len(raw_preview),
                "kind": "data_url" if raw_preview.startswith("data:") else "url",
                "source": vis_meta.get("image_source") or ("client" if run.context.get("preview_image") else "server_render"),
            }
        state.proposal = {
            "persona_id": persona.id,
            "persona_name": persona.name,
            "facts": facts_out,
            "original_spec": run.spec,
            "prepared_spec": working_spec if prep.get("changed") else None,
            "modified_spec": modified,
            "changes": changes,
            "rejected": rejected,
            "invariants": invariants,
            "trace": [t1, t2, t3, t4],
            "summary": (
                f"{explanation.get('goal_summary') or 'The proposal applies the institution guideline to the supplied chart.'} "
                f"({n_applied} changes applied, {n_suggested} suggested, {len(rejected)} rejected.)"
            ),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        state.status = "done"
    except Exception as exc:  # noqa: BLE001 — 单 agent 失败不拖垮整个 run
        state.status = "error"
        state.error = f"{type(exc).__name__}: {exc}"
    finally:
        reset_llm_persona(persona_token)
        if log_token is not None:
            reset_llm_run_log(log_token)


async def _supervise(run: RunState, personas: list[Persona], llm: LLMClient, store: RunStore) -> None:
    await asyncio.gather(*(_agent_task(run, p, llm) for p in personas))
    # 主持人议程合成（live）：跨机构 changes → 自然议题叙事；必须在 status=done 之前
    # 完成（前端在 done 时停止轮询）。mock/失败为 None，前端回落本地确定性派生。
    log_token = bind_llm_run_log(run.llm_log) if run.llm_log is not None else None
    persona_token = bind_llm_persona("moderator")
    try:
        from .agenda import synthesize_agenda

        proposals = {
            pid: run.agents[pid].proposal
            for pid in run.order
            if run.agents[pid].proposal is not None
        }
        run.agenda = await synthesize_agenda(
            run.order, proposals, run.context, llm, personas={p.id: p for p in personas}
        )
    except Exception as exc:  # noqa: BLE001 — 议程失败不阻断 run 完成
        print(f"[runner] agenda synthesis skipped: {type(exc).__name__}: {exc}")
        run.agenda = None
    finally:
        reset_llm_persona(persona_token)
        if log_token is not None:
            reset_llm_run_log(log_token)
    run.status = "done"
    execution = collect_llm_api_status(run)
    calls = execution["api_calls"]
    print(
        f"[runner] run={run.run_id} llm_outcome={execution['outcome']} "
        f"configured_mode={execution['configured_mode']} "
        f"calls={calls['successful']}/{calls['total']} successful "
        f"failed={calls['failed']}",
        flush=True,
    )
    store.snapshot(run)


def start_run(
    store: RunStore,
    registry: PersonaRegistry,
    llm: LLMClient,
    spec: dict,
    persona_ids: list[str],
    context: dict | None = None,
) -> tuple[RunState | None, str]:
    """启动一次多智能体咨询。返回 (run, error_message)。"""
    personas = []
    for pid in persona_ids:
        p = registry.get(pid)
        if p is None:
            return None, f"未知 persona: {pid}"
        personas.append(p)
    if not personas:
        return None, "persona_ids 不能为空"

    run_id = allocate_run_id(store)
    run = RunState(
        run_id=run_id,
        spec=spec,
        context=context or {},
        agents={p.id: AgentState(persona_id=p.id) for p in personas},
        order=[p.id for p in personas],
        created_at=datetime.now(timezone.utc).isoformat(),
        llm_mode=llm.mode,
        llm_log=LLMRunLog(run_id=run_id, kind="advisor"),
    )
    store.add(run)
    print(
        f"[runner] run={run_id} started llm_mode={run.llm_mode} "
        f"model={settings.model if run.llm_mode == 'live' else '-'}",
        flush=True,
    )
    run._supervisor = asyncio.create_task(_supervise(run, personas, llm, store))
    return run, ""


async def wait_run(run: RunState) -> None:
    if run._supervisor is not None:
        await run._supervisor


def make_context(payload: Any) -> dict:
    """请求 context 归一化：媒介参数 + 用户创作意图 + 可选预览图。

    ``user_intent`` 是前端早期使用的别名；统一转为 ``communication_goal``，
    使每个 advisor 共享同一份、可追溯的用户目标。
    ``preview_image``：可选覆盖图（data URL）；缺省由后端 vl-convert 渲 working spec。
    非法或超限则丢弃（不影响四拍主路径）。
    """
    from .visual_review import normalize_preview_image

    ctx = payload if isinstance(payload, dict) else {}
    out = {}
    if isinstance(ctx.get("medium"), str):
        out["medium"] = ctx["medium"]
    if isinstance(ctx.get("viewport_px"), (int, float)):
        out["viewport_px"] = ctx["viewport_px"]
    goal = ctx.get("communication_goal")
    if not isinstance(goal, str) or not goal.strip():
        goal = ctx.get("user_intent")
    if isinstance(goal, str) and goal.strip():
        out["communication_goal"] = goal.strip()[:2000]
    preview = normalize_preview_image(ctx.get("preview_image"))
    if preview:
        out["preview_image"] = preview
    return out
