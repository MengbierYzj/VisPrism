"""将四拍 advisor 决策整理为面向用户的自然语言说明。"""
from __future__ import annotations

import json
from typing import Any

from .persona import Persona


def _rule_quote(persona: Persona, rule_id: str) -> str:
    """从 persona 原始 rule/adaptation 中取逐字证据，而不是只读渲染后的 rule。"""
    for item in [*persona.rules, *persona.adaptations]:
        if item.id != rule_id:
            continue
        raw = item.raw if isinstance(item.raw, dict) else {}
        quote = raw.get("evidence_quote") or raw.get("quote")
        if not quote and isinstance(raw.get("evidence"), dict):
            quote = raw["evidence"].get("quote")
        if not quote:
            quote = getattr(item, "rule", None) or getattr(item, "then", None)
        return str(quote or "")[:900]
    for item in persona.philosophy:
        if item.id == rule_id:
            return item.quote[:900]
    return ""


def _chart_context(facts: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "title_text", "mark_type", "category_field", "value_field", "color_field",
        "series_count", "category_count", "color_count", "coloring_mode",
        "emphasis_target", "communication_goal", "summary", "narrative",
        "width", "height", "has_axes", "has_title", "has_annotations",
    )
    return {key: facts.get(key) for key in keys if facts.get(key) not in (None, "", [])}


def _payload(
    persona: Persona,
    facts: dict[str, Any],
    changes: list[dict],
    trace: list[dict],
) -> dict[str, Any]:
    items = []
    for change in changes[:40]:
        warrant = change.get("warrant") if isinstance(change.get("warrant"), dict) else {}
        items.append(
            {
                "id": change.get("id"),
                "label": change.get("label"),
                "rule_id": change.get("rule_id"),
                "layer": change.get("layer"),
                "status": change.get("status"),
                "action_summary": change.get("prompt"),
                "program_reason": change.get("reason"),
                "persona_quote": _rule_quote(persona, str(change.get("rule_id") or ""))
                or str(warrant.get("quote") or "")[:900],
            }
        )
    return {
        "persona": persona.name,
        "chart": _chart_context(facts),
        "changes": items,
        "four_beat_trace": [
            {"beat": t.get("beat"), "name": t.get("name"), "summary": t.get("summary")}
            for t in trace[-4:]
            if isinstance(t, dict)
        ],
    }


def fallback_explanation(
    facts: dict[str, Any], changes: list[dict], *, source: str = "fallback"
) -> dict[str, Any]:
    goal = str(facts.get("communication_goal") or "").strip()
    chart = str(facts.get("summary") or facts.get("narrative") or "the supplied chart").strip()
    if goal:
        goal_text = f"The proposal keeps the chart focused on {goal}. It starts from what the chart shows: {chart}"
    else:
        goal_text = f"The proposal interprets the chart as follows: {chart}"
    by_id = {}
    for change in changes:
        status = "applied" if change.get("status") == "applied" else "suggested"
        label = str(change.get("label") or change.get("rule_id") or "Design adjustment")
        reason = str(change.get("reason") or "The institutional guideline supports this adjustment.")
        by_id[str(change.get("id") or "")] = f"{label} ({status}): {reason}"
    return {"source": source, "goal_summary": goal_text[:1200], "change_explanations": by_id}


async def summarize_proposal(
    persona: Persona,
    facts: dict[str, Any],
    changes: list[dict],
    trace: list[dict],
    llm: Any,
) -> dict[str, Any]:
    """返回稳定 schema；live 失败时只影响解释，不影响 proposal。"""
    base = fallback_explanation(facts, changes)
    if getattr(llm, "mode", "mock") != "live":
        return base
    system = (
        "You explain a visualization advisor proposal to a non-technical user. "
        "Use the chart facts, the actual four-beat trace, applied/suggested status, "
        "and the supplied institutional quotes. Never invent data, colors, actions, "
        "or a reason absent from the evidence. Do not mention YAML, JSON, rule IDs, "
        "or internal pipeline terminology. Explain what the chart is trying to show, "
        "why each change helps this chart, and clearly distinguish applied from suggested. "
        "Write concise natural English. Return JSON only: "
        '{"goal_summary":"2-3 sentences","change_explanations":[{"id":"existing id","text":"1-2 sentences"}]}'
    )
    try:
        raw = await llm.chat_json(system, json.dumps(_payload(persona, facts, changes, trace), ensure_ascii=False))
    except Exception:
        return base
    if not isinstance(raw, dict):
        return base
    goal = str(raw.get("goal_summary") or "").strip()
    result = {"source": "llm", "goal_summary": goal[:1600] or base["goal_summary"], "change_explanations": {}}
    valid_ids = {str(c.get("id")) for c in changes}
    for item in raw.get("change_explanations") or []:
        if not isinstance(item, dict) or str(item.get("id")) not in valid_ids:
            continue
        text = str(item.get("text") or "").strip()
        if text:
            result["change_explanations"][str(item["id"])] = text[:900]
    for key, value in base["change_explanations"].items():
        result["change_explanations"].setdefault(key, value)
    return result
