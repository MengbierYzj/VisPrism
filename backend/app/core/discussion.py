"""Review-board 议题讨论（POST /api/advisor/discuss）。

用户在右栏 Review Board 对某个议题向相关机构 persona 追问：
- mock 模式 / live 失败降级：确定性模板回复，引用只来自该议题 changes 的
  warrant（逐字 quote/story），不发明新知识；
- live 模式：逐 persona 一次 chat_json（机构 briefing 前缀 + 议题上下文 +
  历史 + 追问），citations 必须逐字来自提供的 warrants，程序校验后保留；
- ≥2 机构参与议题时补一条主持人 synthesis（live 一次调用，mock/失败用模板）。
  synthesis 仅是文字建议，不产生新 ops，采纳仍走既有 changes。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from ..llm import LLMClient, LLMError
from .actions import describe_op
from .advisor_briefing import briefing_system_preamble, build_advisor_briefing
from .composer import _op_effects, _persona_id_from_change
from .specfacts import extract_facts

MAX_HISTORY = 8
MAX_QUESTION_CHARS = 2000
MAX_REPLY_CHARS = 900
MAX_CITATIONS = 2

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


def persona_changes(issue: dict, persona_id: str) -> list[dict]:
    """议题 changes 中属于该 persona 的条目（change.id 以 persona 前缀命名）。"""
    out: list[dict] = []
    for ch in issue.get("changes") or []:
        if isinstance(ch, dict) and _persona_id_from_change(ch) == persona_id:
            out.append(ch)
    return out


def _ops_for_effects(change: dict) -> list[dict]:
    """Attach component_detail.spec_paths onto compose_component ops for conflict grain."""
    detail = change.get("component_detail") if isinstance(change.get("component_detail"), dict) else {}
    paths = [p for p in (detail.get("spec_paths") or []) if isinstance(p, str) and p.startswith("/")]
    out: list[dict] = []
    for op in change.get("ops") or []:
        if not isinstance(op, dict):
            continue
        if op.get("action") == "compose_component" and paths and not op.get("spec_paths"):
            out.append({**op, "spec_paths": paths})
        else:
            out.append(op)
    return out


def conflict_nodes(issue: dict) -> list[str]:
    """议题内跨 persona 对同一 spec 节点效果不一致的节点列表（复用 Composer 逻辑）。"""
    by_node: dict[str, dict[str, set[str]]] = {}
    for ch in issue.get("changes") or []:
        if not isinstance(ch, dict) or not ch.get("ops"):
            continue
        pid = _persona_id_from_change(ch)
        for op in _ops_for_effects(ch):
            for node, effect in _op_effects(op):
                by_node.setdefault(node, {}).setdefault(pid, set()).add(effect)
    out: list[str] = []
    for node, per_persona in by_node.items():
        if len(per_persona) < 2:
            continue
        effects: set[str] = set()
        for sigs in per_persona.values():
            effects |= sigs
        if len(effects) > 1:
            out.append(node)
    return sorted(out)


def _primary_change(changes: list[dict]) -> dict | None:
    """回答立足点：优先 applied，再按置信度排序。"""
    pool = [c for c in changes if c.get("status") == "applied"] or changes
    if not pool:
        return None
    return sorted(
        pool, key=lambda c: _CONFIDENCE_RANK.get(str(c.get("confidence")), 3)
    )[0]


def _norm_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


# mock 降级的 reason 常带 "Label (applied): " 前缀与 "（src: L42）" 尾注；
# 讨论气泡是对话语体，剥掉这些代码式包装再进模板。
_REASON_PREFIX = re.compile(r"^[^:：]{0,80}\((?:applied|suggested)\)\s*[:：]\s*")
_SRC_SUFFIX = re.compile(r"[（(]\s*src:\s*[^）)]*[）)]\s*$")


def _clean_reason(reason: Any) -> str:
    s = _norm_space(reason)
    s = _REASON_PREFIX.sub("", s)
    s = _SRC_SUFFIX.sub("", s).strip()
    return s


def _warrant_citations(changes: list[dict]) -> list[dict]:
    """从 changes 的 warrant 收集逐字引用（去重、封顶）。"""
    out: list[dict] = []
    seen: set[str] = set()
    for ch in changes:
        warrant = ch.get("warrant") if isinstance(ch.get("warrant"), dict) else {}
        quote = _norm_space(warrant.get("quote") or warrant.get("story"))
        if not quote or quote in seen:
            continue
        seen.add(quote)
        src = warrant.get("src") if isinstance(warrant.get("src"), list) else []
        out.append(
            {
                "quote": quote,
                "src": [str(s) for s in src],
                "source_file": str(warrant.get("source_file") or ""),
            }
        )
        if len(out) >= MAX_CITATIONS:
            break
    return out


def _mock_reply(persona, changes: list[dict], question: str, others: list[str]) -> dict:
    """确定性模板回复：按问题关键词分支，内容全部来自 changes 的 reason/warrant。"""
    if not changes:
        text = (
            f"We did not flag this issue for your chart — from {persona.name}'s "
            "perspective the current treatment is acceptable. Adopting another "
            "advisor's change here would not conflict with our guidance."
        )
        return {"text": text, "citations": []}

    primary = _primary_change(changes) or changes[0]
    label = str(primary.get("label") or primary.get("rule_id") or "this change")
    reason = _clean_reason(primary.get("reason"))
    q = (question or "").lower()

    if any(k in q for k in ("keep", "original", "without", "skip", "leave")):
        text = (
            "Keeping the original is a legitimate choice — nothing breaks. "
            f"But the issue we raised stands: {reason} "
            f"If you skip \u201c{label}\u201d, the chart keeps reading the way it does now."
        )
    elif any(k in q for k in ("combine", "middle", "both", "merge", "mix")):
        partner = f" with {others[0]}" if others else ""
        text = (
            f"Partial adoption{partner} works. Our non-negotiable on this issue is "
            f"\u201c{label}\u201d; the rest of our bundle is adjustable. Where two advisors "
            "touch the same property, pick one side — the apply step resolves the "
            "remaining collisions deterministically."
        )
    elif any(k in q for k in ("why", "matter", "reason", "point")):
        text = (
            f"{reason} This is not a taste call — the guideline we cite below is "
            "explicit about this situation."
        )
    else:
        text = f"Our position on this issue is \u201c{label}\u201d. {reason}"
    return {"text": text, "citations": _warrant_citations(changes)}


def _mock_synthesis(names: list[str], nodes: list[str]) -> str:
    joined = " and ".join(names)
    if nodes:
        return (
            f"{joined} agree this issue needs attention but disagree on "
            f"{', '.join(nodes[:2])}. A practical path: adopt one side per "
            "conflicting property and keep the non-overlapping changes from both — "
            "the apply step resolves remaining collisions by adoption count."
        )
    return (
        f"{joined} approach this issue from different angles that do not collide. "
        "You can adopt both bundles; each touches a different property of the chart."
    )


def _issue_context_for_llm(
    issue: dict, persona_id: str, all_persona_ids: list[str], registry
) -> dict:
    """单 persona 视角的议题上下文（不传完整 VL spec）。"""
    mine: list[dict] = []
    for ch in persona_changes(issue, persona_id):
        warrant = ch.get("warrant") if isinstance(ch.get("warrant"), dict) else {}
        detail = ch.get("component_detail") if isinstance(ch.get("component_detail"), dict) else {}
        knowledge_rows = ch.get("knowledge_layers") if isinstance(ch.get("knowledge_layers"), list) else []
        if not knowledge_rows and isinstance(ch.get("knowledge"), dict):
            knowledge_rows = [ch["knowledge"]]
        mine.append(
            {
                "label": ch.get("label"),
                "scope": ch.get("scope"),
                "status": ch.get("status"),
                "layer": ch.get("layer"),
                "confidence": ch.get("confidence"),
                "reason": _clean_reason(ch.get("reason")),
                "treatment": _norm_space(detail.get("after") or ch.get("reason")),
                "before": _norm_space(detail.get("before")),
                "effects": [describe_op(op) for op in _ops_for_effects(ch)],
                "knowledge": [
                    {k: item.get(k) for k in ("layer", "rule", "applied", "condition", "philosophy", "quote", "title") if item.get(k)}
                    for item in knowledge_rows
                    if isinstance(item, dict)
                ],
                "warrant": {
                    "quote": warrant.get("quote"),
                    "story": warrant.get("story"),
                    "src": warrant.get("src"),
                    "source_file": warrant.get("source_file"),
                },
            }
        )
    others: list[dict] = []
    for pid in all_persona_ids:
        if pid == persona_id:
            continue
        p = registry.get(pid)
        labels = [str(c.get("label") or "") for c in persona_changes(issue, pid)]
        if labels:
            others.append({"institution": p.name if p else pid, "positions": labels})
    return {
        "issue": issue.get("label"),
        "our_changes": mine,
        "other_advisors": others,
        "conflict_nodes": conflict_nodes(issue),
    }


_LIVE_REPLY_TASK = (
    "## Current task (Review board · issue discussion)\n"
    "You are answering the user's follow-up question in a design-review discussion "
    "about ONE issue on their chart. Speak as this institution in first person plural "
    "(\"we\"). Reply in 2-4 plain, concrete sentences.\n"
    "Ground every claim in the provided our_changes only: reason, treatment/after, "
    "knowledge, and warrants. Name the actual visual treatment this institution "
    "applied on THIS issue (the colour, type, label, or axis change written there). "
    "Do not recite the house style guide in general, and do not talk about other "
    "issues. If our_changes is empty, say you did not flag this issue.\n"
    "If the question is outside this issue, say so briefly and steer back.\n"
    "You may cite ONLY the provided warrants, copying quote text verbatim.\n"
    "Do not invent new rules, hex colors, or actions; do not promise edits beyond the "
    "listed changes.\n"
    'Output JSON only: {"text": "...", "citations": '
    '[{"quote": "verbatim warrant quote", "src": ["..."], "source_file": "..."}]}'
)


async def _live_reply(
    llm: LLMClient, persona, facts: dict, spec: dict, context: dict, question: str, history: list[dict]
) -> dict:
    briefing = build_advisor_briefing(persona, facts, spec)
    system = briefing_system_preamble(briefing) + "\n\n" + _LIVE_REPLY_TASK
    user = json.dumps(
        {**context, "history": history[-MAX_HISTORY:], "question": question},
        ensure_ascii=False,
    )
    parsed = await llm.chat_json(system, user)
    if not isinstance(parsed, dict) or not _norm_space(parsed.get("text")):
        raise LLMError("discuss 回复缺少 text")
    text = _norm_space(parsed.get("text"))[:MAX_REPLY_CHARS]
    # citations 只保留逐字命中提供 warrant 的条目
    allowed: list[str] = []
    for ch in context.get("our_changes") or []:
        warrant = ch.get("warrant") or {}
        for key in ("quote", "story"):
            q = _norm_space(warrant.get(key))
            if q:
                allowed.append(q)
    citations: list[dict] = []
    for cite in parsed.get("citations") or []:
        if not isinstance(cite, dict):
            continue
        quote = _norm_space(cite.get("quote"))
        if not quote:
            continue
        hit = next((a for a in allowed if quote in a or a in quote), None)
        if hit is None:
            continue
        src = cite.get("src") if isinstance(cite.get("src"), list) else []
        citations.append(
            {
                "quote": quote,
                "src": [str(s) for s in src],
                "source_file": str(cite.get("source_file") or ""),
            }
        )
        if len(citations) >= MAX_CITATIONS:
            break
    return {"text": text, "citations": citations}


_LIVE_SYNTH_SYSTEM = (
    "You are LEAD, the neutral moderator of an institutional design review board. "
    "Summarize where the institutions agree and differ on this single issue, then "
    "propose one concrete combination the user could adopt, referencing the change "
    "labels verbatim in quotes. Reply in 2-3 plain sentences. Do not invent new "
    "colors, rules, or actions.\n"
    'Output JSON only: {"text": "..."}'
)


async def _live_synthesis(
    llm: LLMClient, issue: dict, replies: list[dict], nodes: list[str], question: str
) -> str:
    positions = []
    for r in replies:
        positions.append({"institution": r.get("persona_name"), "reply": r.get("text")})
    user = json.dumps(
        {
            "issue": issue.get("label"),
            "question": question,
            "conflict_nodes": nodes,
            "positions": positions,
        },
        ensure_ascii=False,
    )
    parsed = await llm.chat_json(_LIVE_SYNTH_SYSTEM, user)
    text = _norm_space(parsed.get("text")) if isinstance(parsed, dict) else ""
    if not text:
        raise LLMError("synthesis 缺少 text")
    return text[:MAX_REPLY_CHARS]


def _sanitize_history(history: Any) -> list[dict]:
    out: list[dict] = []
    for item in history if isinstance(history, list) else []:
        if not isinstance(item, dict):
            continue
        text = _norm_space(item.get("text"))
        if not text:
            continue
        out.append({"role": str(item.get("role") or "user"), "text": text[:MAX_REPLY_CHARS]})
    return out[-MAX_HISTORY:]


async def build_discussion(
    llm: LLMClient,
    registry,
    spec: dict,
    persona_ids: list[str],
    issue: dict,
    question: str,
    history: Any = None,
    context: dict | None = None,
) -> dict:
    """构建一轮讨论：逐 persona 回复 + 可选主持人 synthesis。"""
    question = _norm_space(question)[:MAX_QUESTION_CHARS]
    clean_history = _sanitize_history(history)
    nodes = conflict_nodes(issue)
    live = llm.mode == "live"

    facts: dict = {}
    if live:
        try:
            facts = extract_facts(spec, context or {})
        except Exception:  # noqa: BLE001 — briefing 缺 facts 不阻断讨论
            facts = {}
        goal = (context or {}).get("communication_goal") or (context or {}).get("user_intent")
        if goal:
            facts["communication_goal"] = goal

    replies: list[dict] = []
    fallback_used = False
    for pid in persona_ids:
        persona = registry.get(pid)
        if persona is None:
            continue
        changes = persona_changes(issue, pid)
        other_names = [
            registry.get(other).name
            for other in persona_ids
            if other != pid and registry.get(other) is not None
        ]
        reply: dict | None = None
        if live and changes:
            ctx = _issue_context_for_llm(issue, pid, persona_ids, registry)
            try:
                reply = await _live_reply(llm, persona, dict(facts), spec, ctx, question, clean_history)
            except LLMError:
                fallback_used = True
        if reply is None:
            reply = _mock_reply(persona, changes, question, other_names)
        replies.append({"persona_id": pid, "persona_name": persona.name, **reply})

    # ≥2 机构对议题有立场时，主持人给一条合成建议
    synthesis: dict | None = None
    with_changes = [r["persona_id"] for r in replies if persona_changes(issue, r["persona_id"])]
    if len(with_changes) >= 2:
        text: str | None = None
        if live:
            try:
                text = await _live_synthesis(llm, issue, replies, nodes, question)
            except LLMError:
                fallback_used = True
        if not text:
            names = [r["persona_name"] for r in replies if r["persona_id"] in with_changes]
            text = _mock_synthesis(names, nodes)
        synthesis = {"text": text}

    outcome = "mock" if not live else ("live_fallback" if fallback_used else "live")
    # mock 演示节奏：与四拍一致的轻微延时，前端能看到“思考中”状态
    if not live:
        from ..config import settings

        delay = min(int(getattr(settings, "mock_beat_delay_ms", 0) or 0), 600)
        if delay:
            await asyncio.sleep(delay / 1000)
    return {
        "issue_key": issue.get("key"),
        "replies": replies,
        "synthesis": synthesis,
        "conflict_nodes": nodes,
        "llm_mode": llm.mode,
        "outcome": outcome,
    }
