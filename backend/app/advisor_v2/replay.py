"""按 run_id 回放已保存的咨询记录，不调用 advisor 也不调用 LLM。

留痕与回放分离：每次 live run 结束时由 `V2RunStore.snapshot` / v1 `RunStore`
写入 `storage/runs/{run_id}.json`（含请求 spec、context 与各 agent 完整提案）；
回放只读取该文件，按四拍状态机重放给前端，因此同一条记录可以反复复现，
且**不会覆盖或改写原始记录**。

两个引擎的快照结构一致（`request` + `agents[]`），故同一实现可回放 v1 与 v2。
"""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings
from ..core.persona import Persona, PersonaRegistry
from .runner import (
    V2AgentState,
    V2RunState,
    V2RunStore,
    _attach_knowledge,
    _evidence_for,
    _evidence_index,
    _implementation_index,
    _knowledge_index,
    _persona_identity,
    _token_names,
)

REPLAY_STAGES = ("reading", "detecting", "adjudicating", "compiling")


def _backfill_evidence(proposal: dict[str, Any], persona: Persona | None = None) -> dict[str, Any]:
    """给早期快照补上「回应的是什么问题」与「依据的条文原句」。

    问题描述本就在同一份快照的 `facts.visual_review` 里，靠 change.rule_id 与改动
    相连；条文原句则要拿 rule_id 回机构知识库解引用（早期快照存的是叙事编号）。
    两项补齐都只发生在读取时，磁盘上的原始记录不动 —— 历史 run 因此能在回放里
    说清问题与出处，而留痕仍是当初那一份。
    """
    changes = proposal.get("changes")
    if not isinstance(changes, list):
        return proposal
    facts = proposal.get("facts") if isinstance(proposal.get("facts"), dict) else {}
    evidence = _evidence_index(facts.get("visual_review"))
    implementation = _implementation_index(facts.get("layer_implementation"))
    knowledge = _knowledge_index(persona) if persona is not None else {}
    identity = _persona_identity(persona) if persona is not None else {}
    tokens = _token_names(persona) if persona is not None else {}
    if not evidence and not knowledge:
        return proposal

    for change in changes:
        if not isinstance(change, dict):
            continue
        rule_id = str(change.get("rule_id") or "")
        warrant = change.get("warrant") if isinstance(change.get("warrant"), dict) else None

        # 规则引用可能记在 rule_id，也可能只留在 warrant.story_id 上
        cited = knowledge.get(rule_id)
        if cited is None and warrant is not None:
            cited = knowledge.get(str(warrant.get("story_id") or ""))
        if cited and warrant is not None:
            # 存档里的 story 可能是叙事编号（"n-hierarchy"），解引用后才是正文
            if cited.get("quote") and not str(warrant.get("quote") or "").strip():
                warrant["quote"] = cited["quote"]
            if cited.get("story"):
                warrant["story"] = cited["story"]
            if cited.get("src") and not warrant.get("src"):
                warrant["src"] = list(cited["src"])

        finding = {} if change.get("problem") else _evidence_for(rule_id, evidence)
        if finding.get("problem"):
            change["problem"] = finding["problem"]
            if finding.get("observed"):
                change.setdefault("problem_evidence", finding["observed"])
            if finding.get("severity"):
                change.setdefault("severity", finding["severity"])
            if warrant is not None and not str(warrant.get("quote") or "").strip() and finding.get("guideline"):
                warrant["quote"] = finding["guideline"]

        # 层级归因同样是读取时补的：早期快照把机构的条件化适应全压成了 L3-derived
        if persona is not None and warrant is not None:
            _attach_knowledge(persona, change, knowledge, implementation, identity, tokens)
    return proposal


def _runs_dir() -> Path:
    return Path(settings.storage_dir) / "runs"


def _read_record(path: Path) -> dict[str, Any] | None:
    """快照首行可能是紧凑元数据行，正文才是完整 JSON；两种都接受。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for candidate in (raw, raw.split("\n", 1)[-1]):
        try:
            document = json.loads(candidate)
        except (json.JSONDecodeError, IndexError):
            continue
        if isinstance(document, dict) and isinstance(document.get("agents"), list):
            return document
    return None


def list_records() -> list[dict[str, Any]]:
    """列出可回放的历史 run（按时间倒序），供前端或脚本挑选。"""
    directory = _runs_dir()
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        document = _read_record(path)
        if document is None:
            continue
        agents = [agent for agent in document["agents"] if isinstance(agent, dict)]
        request = document.get("request") if isinstance(document.get("request"), dict) else {}
        spec = request.get("spec") if isinstance(request.get("spec"), dict) else {}
        title = spec.get("title")
        records.append({
            "run_id": str(document.get("run_id") or path.stem),
            "engine": str(document.get("engine") or "advisor-v1"),
            "status": str(document.get("status") or "unknown"),
            "created_at": document.get("created_at"),
            "persona_ids": [str(agent.get("persona_id")) for agent in agents],
            "replayable_persona_ids": [
                str(agent.get("persona_id")) for agent in agents if isinstance(agent.get("proposal"), dict)
            ],
            "chart_title": title.get("text") if isinstance(title, dict) else title if isinstance(title, str) else None,
            "communication_goal": (request.get("context") or {}).get("communication_goal") if isinstance(request.get("context"), dict) else None,
            "file": path.name,
            "size_bytes": path.stat().st_size,
        })
    return records


def load_record(run_id: str) -> tuple[dict[str, Any] | None, str]:
    """按 run_id 精确取记录；不做「最新文件」猜测，保证复现可指名。"""
    name = str(run_id or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None, f"非法 run_id: {run_id!r}"
    path = _runs_dir() / f"{name}.json"
    if not path.is_file():
        return None, f"未找到 run 记录: {name}"
    document = _read_record(path)
    if document is None:
        return None, f"run 记录无法解析: {name}"
    return document, ""


async def _replay_agent(
    run: V2RunState,
    persona_id: str,
    proposal: dict[str, Any],
    delay_ms: int,
    persona: Persona | None,
) -> None:
    state = run.agents[persona_id]
    delay = max(delay_ms, 0) / 1000
    for stage in REPLAY_STAGES:
        state.status = stage
        await asyncio.sleep(delay) if delay else await asyncio.sleep(0)
    state.proposal = _backfill_evidence(copy.deepcopy(proposal), persona)
    state.status = "done"


async def _supervise_replay(
    run: V2RunState,
    proposals: dict[str, dict[str, Any]],
    delay_ms: int,
    registry: PersonaRegistry | None,
) -> None:
    # 回放是只读复现：刻意不再快照，避免每看一次就复制一份数 MB 的记录。
    await asyncio.gather(*(
        _replay_agent(run, pid, proposal, delay_ms, registry.get(pid) if registry else None)
        for pid, proposal in proposals.items()
    ))
    run.status = "done"


def start_replay_run(
    store: V2RunStore,
    run_id: str,
    persona_ids: list[str] | None = None,
    beat_delay_ms: int | None = None,
    registry: PersonaRegistry | None = None,
) -> tuple[V2RunState | None, str]:
    """从已存记录复现一次前端可轮询的四拍 run。

    `persona_ids` 缺省回放记录里全部有提案的机构；显式传入则只回放子集，
    便于在同一条记录上对比单个机构。
    """
    document, error = load_record(run_id)
    if document is None:
        return None, error

    recorded = {
        str(agent["persona_id"]): agent["proposal"]
        for agent in document["agents"]
        if isinstance(agent, dict) and agent.get("persona_id") and isinstance(agent.get("proposal"), dict)
    }
    if not recorded:
        return None, f"run 记录中没有可回放的提案: {run_id}"
    wanted = [str(pid) for pid in persona_ids] if persona_ids else list(recorded)
    missing = [pid for pid in wanted if pid not in recorded]
    if missing:
        return None, f"run 记录缺少这些机构的提案: {', '.join(missing)}"

    request = document.get("request") if isinstance(document.get("request"), dict) else {}
    run = V2RunState(
        run_id=_allocate_replay_id(store, str(document.get("run_id") or run_id)),
        spec=request.get("spec") if isinstance(request.get("spec"), dict) else {},
        context=request.get("context") if isinstance(request.get("context"), dict) else {},
        agents={pid: V2AgentState(pid) for pid in wanted},
        order=wanted,
        created_at=datetime.now(timezone.utc).isoformat(),
        replay_of=str(document.get("run_id") or run_id),
    )
    store.add(run)
    delay = settings.replay_beat_delay_ms if beat_delay_ms is None else max(int(beat_delay_ms), 0)
    run._supervisor = asyncio.create_task(
        _supervise_replay(run, {pid: recorded[pid] for pid in wanted}, delay, registry)
    )
    return run, ""


def _allocate_replay_id(store: V2RunStore, source_run_id: str) -> str:
    """回放 run 的 id 带上被回放的原始 id，便于在日志里回溯来源。"""
    stamp = datetime.now().strftime("%H%M%S")
    base = f"replay-{source_run_id}-{stamp}"
    run_id, suffix = base, 1
    while store.get(run_id) is not None:
        suffix += 1
        run_id = f"{base}-{suffix}"
    return run_id
