"""快慢双通道规范执行：慢-快-慢-快四拍管线。

- 拍1 慢道·读图立意：LLM 读 chart_slice → Decision IR（意图/配色模式/结构叙述）
- 拍2 快道·规范检测：L1 程序化检测 + L2 结构化条件匹配；判不了的列升级清单
- 拍3 慢道·溯源裁决：LLM 对照 chart_slice + 指南裁决；令牌 ops 由程序选取
- 拍4 快道·编译执行与校验：编排 + 有 diff 才 applied + coloring_mode 落地核验

live/mock 只切换拍1、拍3（及拍前角色）的实现；**LLM 不写 VL / 不发明 hex**。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from ..llm import LLMClient, LLMError
from .actions import (
    apply_ops_with_effect,
    build_emphasis_ops,
    compile_strategy,
    compile_then,
    describe_ops,
    fill_emphasis_ops,
)
from .conditions import MATCH, NO_MATCH, UNKNOWN, eval_when
from .advisor_briefing import (
    beat1_read_system,
    beat3_adjudicate_system,
    build_advisor_briefing,
    chrome_roles_system,
    intent_analyze_system,
)
from .decision_ir import (
    attach_slice_to_escalation_items,
    build_chart_slice,
    infer_color_structure,
    infer_emphasis_binding,
    normalize_read_decision,
)
from .detectors import detect_rule, run_invariants
from .persona import Persona
from .specfacts import extract_facts, structure_baseline
from .user_intent import (
    attach_user_intent,
    mock_analyze_goal,
    normalize_live_analysis,
)
from .view_geometry import apply_role_overrides, walk_annotated_units

# 修改标签（前端 chips 的展示语言）；未登记的 id 走 humanize 兜底
LABELS = {
    "s-type-hierarchy": "Type hierarchy",
    "s-text-left": "Left-aligned text",
    "s-title-case": "Sentence case title",
    "s-source": "Source attribution",
    "s-grid-horizontal": "Horizontal gridlines",
    "s-grid-vertical": "No vertical grid",
    "s-whitespace": "Generous whitespace",
    "s-legend-top": "Legend on top",
    "s-legend-notitle": "No legend title",
    "s-title-descriptive": "Descriptive title",
    "s-accessibility": "Accessibility check",
    "s-branding": "Subtle branding",
    "a-color-single": "House blue series",
    "a-color-two": "Blue + orange pair",
    "a-color-multi": "House palette",
    "a-color-highlight": "Orange highlight",
    "a-color-support": "Gray supporting series",
    "a-color-teal": "Teal for topic",
    "a-size-digital": "Standard 640x450",
    "a-color-crosschart": "Cross-chart color",
    "s-palette-blues": "Navy palette",
    "s-color-cap": "Max 6 colors",
    "s-color-restraint": "Restrained color",
    "s-decoration": "No decoration",
    "s-type-scale": "Type scale",
    "s-leading": "Leading ratios",
    "s-type-contrast": "Type contrast",
    "s-grid-harmony": "Grid harmony",
    "s-imagery": "Purposeful imagery",
    "s-wit": "Restrained wit",
    "a-color-manyseries": "One strong color",
    "a-color-party": "Party colors",
    "a-emphasis": "Strong accent",
    "a-chart-bubble": "Bubble chart",
    "a-chart-thermometer": "Thermometer chart",
    "a-chart-bar-gap": "Bar chart for huge gap",
    "a-chart-pie-gap": "Pie chart for huge gap",
    "a-grid-narrow": "Narrow grid spacing",
    "a-grid-wide": "Wide grid spacing",
    "a-static-rounding": "Static rounding",
    "d-canvas-bg": "Canvas background",
    "d-color-assignment": "Color assignment principles",
    "s-house-palette": "House palette",
    "v-overlap": "Mark/label overlap",
    "v-color-similarity": "Pairwise color contrast",
    "v-whitespace": "Visual whitespace",
    "v-visual": "Visual L3 review",
}


def label_for(rule_id: str) -> str:
    if rule_id in LABELS:
        return LABELS[rule_id]
    if rule_id.startswith("u-"):
        return "User " + rule_id[2:].replace("-", " ").replace("_", " ")
    stripped = rule_id
    for prefix in ("s-", "a-", "d-"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    return stripped.replace("-", " ").replace("_", " ").capitalize()


def _trace(beat: int, lane: str, name: str, started: float, summary: str, **extra) -> dict:
    return {
        "beat": beat,
        "lane": lane,
        "name": name,
        "ms": round((time.perf_counter() - started) * 1000, 1),
        "summary": summary,
        **extra,
    }


# ---------------------------------------------------------------------------
# 拍1 慢道 · 读图立意
# ---------------------------------------------------------------------------

TOPIC_KEYWORDS = {
    "business": ["销量", "销售", "营收", "收入", "利润", "价格", "产品", "市场", "sales", "revenue", "product", "market", "gdp", "price"],
    "health": ["健康", "疫", "病", "医", "死亡", "health", "covid", "disease", "mortality", "vaccine"],
    "environment": ["环境", "气候", "碳", "排放", "污染", "climate", "carbon", "emission", "pollution"],
    "politics": ["选举", "政党", "投票", "议席", "election", "party", "vote", "poll", "seat"],
}
INTENT_BY_MARK = {
    "bar": "comparison", "line": "trend", "area": "trend", "point": "correlation",
    "circle": "correlation", "arc": "composition", "rect": "distribution",
}

COLORING_MODES = frozenset({"uniform", "paired", "categorical", "highlight"})


def infer_coloring_mode(facts: dict, *, intent: str | None = None) -> str:
    """读图立意用的配色模式（语义原则，非图型硬编码）。

    - composition / 颜色承载类别身份 → categorical
    - 多序列 → paired / categorical
    - 比较类且类别彩虹无额外信息 → uniform（可收束机构主色）
    """
    intent = intent or str(facts.get("intent") or "")
    series_n = facts.get("series_count")
    try:
        series_n = int(series_n) if series_n is not None else 1
    except (TypeError, ValueError):
        series_n = 1
    cat_n = facts.get("category_count")
    try:
        cat_n = int(cat_n) if cat_n is not None else 0
    except (TypeError, ValueError):
        cat_n = 0
    per_cat = bool(facts.get("per_category_coloring"))
    color_field = facts.get("color_field")

    if intent == "composition":
        return "categorical"
    if series_n >= 3:
        return "categorical"
    if series_n == 2:
        return "paired"
    # 单序列但 color 区分多个有意义的身份（非整图一色）
    if color_field and per_cat and cat_n >= 2 and intent not in ("comparison", "distribution", "trend"):
        return "categorical"
    if color_field and not per_cat and series_n > 1:
        return "categorical" if series_n >= 3 else "paired"
    # 字面 value+condition 双色（如末年/峰值强调）→ highlight，勿收成单色
    if facts.get("literal_color_encoding") and facts.get("accent_color"):
        return "highlight"
    if facts.get("emphasis_target") and intent in ("comparison", "distribution"):
        # 强调留给 highlight 规则；底色模式仍为 uniform
        return "uniform"
    return "uniform"


def _mock_read(spec: dict, facts: dict) -> dict:
    corpus = " ".join(
        str(x) for x in [
            facts.get("title_text"),
            facts.get("category_field"),
            facts.get("value_field"),
            facts.get("communication_goal"),
        ] if x
    ).lower()
    topic = "general"
    for t, kws in TOPIC_KEYWORDS.items():
        if any(k in corpus for k in kws):
            topic = t
            break
    intent = INTENT_BY_MARK.get(str(facts.get("mark_type")), "comparison")
    emphasis = None
    if facts.get("mark_type") == "bar" and facts.get("max_category"):
        emphasis = facts["max_category"]["name"]
    coloring_mode = infer_coloring_mode(facts, intent=intent)
    maxc = facts.get("max_category") or {}
    summary = (
        f"{facts.get('mark_type') or '图'}图，{facts.get('category_count') or '?'} 个类别"
        + (f"，最大值 {maxc.get('name')}({maxc.get('value')})" if maxc else "")
        + f"；主题 {topic}，意图 {intent}，配色 {coloring_mode}。"
        + (f" 用户目标：{facts['communication_goal']}" if facts.get("communication_goal") else "")
    )
    bind = infer_emphasis_binding(
        {**facts, "emphasis_target": emphasis},
        emphasis_target=emphasis,
        color_structure=infer_color_structure(facts),
    )
    return {
        "data_topic": topic,
        "intent": intent,
        "emphasis_target": bind.get("emphasis_target", emphasis),
        "emphasis_field": bind.get("emphasis_field"),
        "emphasis_mechanism": bind.get("emphasis_mechanism"),
        "coloring_mode": coloring_mode,
        "summary": summary,
    }


async def _refine_chrome_roles_live(
    spec: dict, facts: dict, llm: LLMClient
) -> tuple[dict, str]:
    """复合图层多时，live 复核 heuristic 角色；失败则保留启发式。"""
    if (facts.get("unit_count") or 0) < 6:
        return facts, ""
    layers = facts.get("chrome_layers") or []
    if not layers:
        return facts, ""
    try:
        raw = await llm.chat_json(
            chrome_roles_system(),
            json.dumps(
                {
                    "layers": layers,
                    "heuristic_mark_type": facts.get("mark_type"),
                    "title_text": facts.get("title_text"),
                    "has_drawn_grid": facts.get("has_drawn_grid"),
                },
                ensure_ascii=False,
            ),
        )
        overrides = raw.get("overrides") if isinstance(raw, dict) else None
        if not isinstance(overrides, list) or not overrides:
            return facts, "chrome_roles:no_overrides"
        units = walk_annotated_units(spec)
        apply_role_overrides(units, overrides)
        # 用覆盖后的角色刷新 layer_roles；主几何若变更则提示（完整重抽留给下次）
        facts = {
            **facts,
            "layer_roles": [
                {
                    "index": u["index"],
                    "mark_type": u["mark_type"],
                    "role": u["role"],
                    "score": u["score"],
                }
                for u in units
            ],
            "chrome_role_overrides": overrides,
        }
        # 若 LLM 把某层标为 primary 且分数更高，更新 primary 索引提示
        primaries = [u for u in units if u["role"] == "primary_data"]
        if primaries:
            best = max(primaries, key=lambda u: u["score"])
            facts["primary_unit_index"] = best["index"]
            facts["primary_unit_role"] = best["role"]
            if best.get("mark_type"):
                facts["mark_type"] = best["mark_type"]
        return facts, f"chrome_roles:overrides={len(overrides)}"
    except LLMError as exc:
        return facts, f"chrome_roles:fallback:{exc}"


async def beat1_read(persona: Persona, spec: dict, facts: dict, llm: LLMClient) -> tuple[dict, dict]:
    started = time.perf_counter()
    # 每个 advisor 在自己的原始 spec 副本上建立组件理解，不与其它 persona 共享。
    from .component_assembler import build_component_ir
    facts["component_ir"] = build_component_ir(spec)
    chrome_note = ""
    # 拍前 rebuild 已做 LLM/启发式角色裁决时不再重复；仅 passthrough 复合图补一轮
    rebuilt = facts.get("spec_rebuild") if isinstance(facts.get("spec_rebuild"), dict) else {}
    if llm.mode == "live" and not rebuilt.get("changed"):
        facts, chrome_note = await _refine_chrome_roles_live(spec, facts, llm)

    # 工作前基础设定：机构专家身份 + 读图事实 + 用户目标 + 三层知识摘要
    briefing = build_advisor_briefing(persona, facts, spec)
    facts = {**facts, "advisor_briefing": briefing}

    mode = llm.mode
    semantics: dict[str, Any]
    note = ""
    intent_note = ""
    chart_slice = build_chart_slice(spec, facts)
    facts = {**facts, "chart_slice": chart_slice}
    if mode == "live":
        system = beat1_read_system(briefing)
        # Decision IR 输入：紧凑 slice + facts，不再塞完整 VL（理解交给 LLM）
        user = json.dumps(
            {
                "chart_slice": chart_slice,
                "chart_audit": facts.get("chart_audit"),
                "facts": {k: facts[k] for k in (
                    "mark_type", "category_field", "value_field", "categories",
                    "category_count", "series_count", "color_field",
                    "per_category_coloring", "colors_effective", "color_count",
                    "title_text", "max_category", "layer_roles",
                ) if k in facts},
                "communication_goal": facts.get("communication_goal"),
                "advisor_briefing": {
                    "persona_id": briefing.get("persona_id"),
                    "chart_narrative": (briefing.get("chart") or {}).get("narrative"),
                    "user_goal": briefing.get("user_goal"),
                    "color_principles": briefing.get("color_principles"),
                },
            },
            ensure_ascii=False,
        )
        try:
            raw = await llm.chat_json(system, user)
            base = _mock_read(spec, facts)
            # 合法 coloring_mode 以 LLM 为准；仅非法枚举才回退启发式
            semantics = normalize_read_decision(raw, facts, fallback=base)
            if str(raw.get("coloring_mode") or "").strip().lower() not in COLORING_MODES:
                semantics["coloring_mode"] = infer_coloring_mode(
                    {**facts, **base, "intent": semantics["intent"]},
                    intent=semantics["intent"],
                )
                semantics["decision_source"] = "llm+infer_coloring"
        except LLMError as exc:
            semantics = {**_mock_read(spec, facts), "decision_source": "mock-fallback", "organization": ""}
            note = f"live 调用失败已降级启发式：{exc}"
            mode = "mock-fallback"
    else:
        semantics = {**_mock_read(spec, facts), "decision_source": "mock", "organization": ""}
    # Decision IR 留痕（不经 LLM 写 VL）；含强调绑定
    decision_ir = {
        "data_topic": semantics.get("data_topic"),
        "intent": semantics.get("intent"),
        "emphasis_target": semantics.get("emphasis_target"),
        "emphasis_field": semantics.get("emphasis_field"),
        "emphasis_mechanism": semantics.get("emphasis_mechanism"),
        "coloring_mode": semantics.get("coloring_mode"),
        "summary": semantics.get("summary"),
        "organization": semantics.get("organization") or "",
        "source": semantics.get("decision_source"),
        "chart_slice": chart_slice,
        "chart_audit": facts.get("chart_audit"),
    }
    facts = {
        **facts,
        **{k: semantics[k] for k in (
            "data_topic", "intent", "emphasis_target", "emphasis_field",
            "emphasis_mechanism", "coloring_mode", "summary",
        ) if k in semantics},
        "organization": semantics.get("organization") or "",
        "decision_ir": decision_ir,
    }
    # 读图后重建 briefing，使配色模式与原则进入拍3 system prompt
    briefing = build_advisor_briefing(persona, facts, spec)
    briefing = {
        **briefing,
        "read_summary": semantics.get("summary"),
        "data_topic": semantics.get("data_topic"),
        "intent": semantics.get("intent"),
        "emphasis_target": semantics.get("emphasis_target"),
        "coloring_mode": semantics.get("coloring_mode"),
        "organization": semantics.get("organization") or "",
    }
    facts = {**facts, "advisor_briefing": briefing}

    # 意图分析：归类 communication / edit / mixed / other，并在指南约束内编译
    analysis: dict[str, Any]
    intent_mode = "mock"
    if llm.mode == "live" and facts.get("communication_goal"):
        try:
            raw_intent = await llm.chat_json(
                intent_analyze_system(facts.get("advisor_briefing")),
                json.dumps(
                    {
                        "communication_goal": facts.get("communication_goal"),
                        "chart_slice": facts.get("chart_slice") or chart_slice,
                        "facts": {
                            k: facts.get(k)
                            for k in (
                                "mark_type",
                                "categories",
                                "category_field",
                                "value_field",
                                "max_category",
                                "intent",
                                "emphasis_target",
                                "coloring_mode",
                                "organization",
                            )
                        },
                    },
                    ensure_ascii=False,
                ),
            )
            analysis = normalize_live_analysis(raw_intent, facts)
            # live 分类后仍用 mock 补全可执行 edit ops（禁止模型发明 action/hex）
            mock_fallback = mock_analyze_goal(facts.get("communication_goal"), facts)
            analysis = _merge_intent_analysis(analysis, mock_fallback)
            intent_mode = "live"
        except LLMError as exc:
            analysis = mock_analyze_goal(facts.get("communication_goal"), facts)
            intent_note = f"意图分析 live 降级：{exc}"
            intent_mode = "mock-fallback"
    else:
        analysis = mock_analyze_goal(facts.get("communication_goal"), facts)

    attach_user_intent(persona, spec, facts, analysis)
    summary = semantics["summary"]
    if analysis.get("kind") and analysis["kind"] != "other":
        summary = f"{summary}｜用户意图:{analysis.get('kind')}"
    trace = _trace(
        1,
        "slow",
        "读图立意",
        started,
        summary,
        mode=mode,
        note="; ".join(x for x in (note, intent_note, chrome_note) if x),
        intent_mode=intent_mode,
        user_intent_kind=analysis.get("kind"),
        advisor=briefing.get("persona_id"),
        decision_source=semantics.get("decision_source"),
    )
    return facts, trace


def _merge_intent_analysis(live: dict, mock: dict) -> dict:
    """保留 live 的 communication slots；edit 的可执行 ops 以 mock 接地为准。"""
    live_items = [i for i in (live.get("items") or []) if isinstance(i, dict)]
    mock_items = [i for i in (mock.get("items") or []) if isinstance(i, dict)]
    comm = [i for i in live_items if i.get("kind") == "communication"]
    if not comm:
        comm = [i for i in mock_items if i.get("kind") == "communication"]
    edits = [i for i in mock_items if i.get("kind") == "edit"]
    # live 提出但 mock 未覆盖的 edit focus → 建议项
    mock_focus = {(i.get("focus"), str((i.get("slots") or {}).get("chart_type") or "")) for i in edits}
    for i in live_items:
        if i.get("kind") != "edit":
            continue
        key = (i.get("focus"), str((i.get("slots") or {}).get("chart_type") or ""))
        if key not in mock_focus:
            edits.append({**i, "ops": [], "suggested_only": True, "grounding": i.get("grounding") or "none"})
    items = comm + edits
    if not items:
        return mock
    kinds = {i["kind"] for i in items}
    if "communication" in kinds and "edit" in kinds:
        top = "mixed"
    elif "edit" in kinds:
        top = "edit"
    elif "communication" in kinds:
        top = "communication"
    else:
        top = "other"
    return {"kind": top, "items": items, "summary": live.get("summary") or top}


# ---------------------------------------------------------------------------
# 拍2 快道 · 规范检测
# ---------------------------------------------------------------------------

def _then_target(then: Any) -> str | None:
    if not isinstance(then, dict):
        return None
    for verb in ("set", "prefer", "override", "enforce"):
        if verb in then and isinstance(then.get(verb), str):
            return then[verb]
    return None


def _is_color_assignment_then(then: Any) -> bool:
    target = _then_target(then)
    return target in (
        "mark.color",
        "color.range",
        "emphasized-mark.color",
        "supporting-mark.color",
    )


def _ops_collapse_categorical(ops: list[dict] | None) -> bool:
    return any(
        isinstance(op, dict) and op.get("action") == "remove_encoding_channel" and op.get("channel") == "color"
        for op in (ops or [])
    )


def _palette_colors(persona: Persona) -> list[str]:
    """机构分类色板：优先 tokens.palette.categorical，否则 ui.palette / 令牌中的 hex。"""
    if hasattr(persona, "resolve_color_list"):
        colors = persona.resolve_color_list("{palette.categorical}") or []
        out = [c for c in colors if isinstance(c, str)]
        if out:
            return out
    ui = getattr(persona, "ui", None) or {}
    raw = ui.get("palette") or []
    out = [c for c in raw if isinstance(c, str)]
    if out:
        return out
    # 最后从 color 令牌收集（Economist 等无独立 categorical 列表）
    tokens = getattr(persona, "tokens", None) or {}
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", node.strip()):
            h = node.strip()
            if h not in found:
                found.append(h)

    walk(tokens.get("color") or tokens)
    return found


def _literal_highlight_ops(colors: list[str]) -> list[dict]:
    """字面 value+condition：必须改写 encoding，不能写 scale.range。"""
    if not colors:
        return []
    op: dict = {"action": "set_mark_color", "color": colors[0]}
    if len(colors) >= 2 and colors[1] != colors[0]:
        op["accent_color"] = colors[1]
    return [op]


def _needs_literal_highlight_ops(facts: dict) -> bool:
    """字面双色或已判定 highlight 且无 color.field → 禁止走 set_color_range。"""
    if facts.get("color_field"):
        return False
    if facts.get("literal_color_encoding"):
        return True
    mode = str(facts.get("coloring_mode") or "").strip().lower()
    return mode == "highlight" and bool(facts.get("accent_color") or facts.get("emphasis_target"))


def _range_ops(colors: list[str], facts: dict) -> list[dict]:
    if not colors:
        return []
    # category_field（如 year）≠ color.field：字面双色上写 range 无效
    if _needs_literal_highlight_ops(facts):
        return _literal_highlight_ops(list(colors))
    if facts.get("color_field") or facts.get("per_category_coloring") or facts.get("category_field"):
        return [{"action": "set_color_range", "colors": list(colors)}]
    return [{"action": "set_mark_color", "color": colors[0]}]


def _ops_for_coloring_mode(persona: Persona, facts: dict, mode: str) -> list[dict]:
    """按 coloring_mode 生成机构色板内的可执行 ops（令牌已解析）。"""
    palette = _palette_colors(persona)
    if not palette:
        return []
    mode = (mode or "uniform").strip().lower()
    # 字面双色：无论请求 paired/categorical/uniform，都改写 value+condition
    if _needs_literal_highlight_ops(facts):
        return _literal_highlight_ops(palette[:2] if len(palette) >= 2 else palette[:1])
    if mode == "highlight":
        # 保留强调结构：主色 + 色板第二色（或强调规则色）
        return _literal_highlight_ops(palette[:2] if len(palette) >= 2 else palette[:1])
    if mode == "uniform":
        ops: list[dict] = []
        if facts.get("per_category_coloring") or (
            facts.get("color_field") and (facts.get("color_count") or 0) > 1
        ):
            ops.append({"action": "remove_encoding_channel", "channel": "color"})
        ops.append({"action": "set_mark_color", "color": palette[0]})
        return ops
    if mode == "paired":
        return _range_ops(palette[:2], facts)
    if mode == "categorical":
        try:
            n = max(
                int(facts.get("category_count") or 0),
                int(facts.get("series_count") or 0),
                3,
            )
        except (TypeError, ValueError):
            n = 3
        return _range_ops(palette[: max(n, 2)], facts)
    return []


def _norm_hex(c: Any) -> str:
    if not isinstance(c, str):
        return ""
    s = c.strip().lower()
    if re.fullmatch(r"[0-9a-f]{6}", s):
        return f"#{s}"
    return s


def _coloring_mode_satisfied(persona: Persona, facts: dict, mode: str) -> bool:
    """当前着色是否已落实 coloring_mode 原则（不仅是「落在色板里」）。"""
    mode = (mode or "uniform").strip().lower()
    palette = [_norm_hex(c) for c in _palette_colors(persona)]
    colors = [_norm_hex(c) for c in (facts.get("colors_effective") or []) if _norm_hex(c)]
    if not palette:
        return True
    if mode == "highlight":
        # 基色=机构主色，强调色=色板内非主色，且保留 condition/accent 结构
        accent = _norm_hex(facts.get("accent_color"))
        if not accent and not facts.get("emphasis_target"):
            return False
        if not colors or colors[0] != palette[0]:
            return False
        if not accent or accent == palette[0] or accent not in palette:
            return False
        return True

    if mode == "uniform":
        # 原则：单机构主色；类别彩虹即使颜色都在色板内也不算合规
        if facts.get("literal_color_encoding") and facts.get("accent_color"):
            return False
        if facts.get("per_category_coloring") and (facts.get("color_count") or 0) > 1:
            return False
        distinct = list(dict.fromkeys(colors))
        if len(distinct) > 1:
            return False
        if distinct and distinct[0] != palette[0]:
            return False
        return True

    if mode == "paired":
        expected = palette[:2]
        if len(expected) < 2:
            return True
        # 需要类别/序列着色通道
        if not (facts.get("color_field") or facts.get("per_category_coloring")):
            if (facts.get("series_count") or 1) >= 2:
                return False
            return True
        # 须使用指南双色对（顺序优先）
        if colors[:2] == expected:
            return True
        return set(colors[:2]) == set(expected) and len(set(colors)) <= 2

    if mode == "categorical":
        try:
            n = max(
                int(facts.get("category_count") or 0),
                int(facts.get("series_count") or 0),
                3,
            )
        except (TypeError, ValueError):
            n = 3
        expected = palette[: max(n, 2)]
        if not expected:
            return True
        # 组成/多类必须保留 color 通道
        if not (facts.get("color_field") or facts.get("per_category_coloring")):
            return False
        # 须按指南色板前缀顺序（原则：机构序，而非「任意子集」）
        if colors[: len(expected)] == expected:
            return True
        # 长度不足但已是正确前缀
        if colors and expected[: len(colors)] == colors and len(colors) >= min(3, len(expected)):
            return True
        return False

    return True


def _color_alternatives(persona: Persona, facts: dict, primary_comp: dict | None = None) -> list[dict]:
    """为慢道提供 uniform / paired / categorical / highlight 可执行备选（令牌已解析，无新 hex）。"""
    alts: list[dict] = []
    for mode_id, label in (
        ("uniform", "single institutional primary"),
        ("paired", "two-series guide pair"),
        ("categorical", "distinct palette colors for parts/series"),
        ("highlight", "base + accent for emphasis bars"),
    ):
        # 一律按 coloring_mode 标准构建；primary_comp 仅作兼容入参（勿把收束 ops 塞进 categorical）
        _ = primary_comp
        ops = _ops_for_coloring_mode(persona, facts, mode_id)
        alts.append(
            {
                "id": mode_id,
                "label": label,
                "ops": ops,
                "action_space": describe_ops(ops) or None,
            }
        )
    return alts


def _color_assignment_escalation(persona: Persona, facts: dict) -> dict | None:
    """拍1 coloring_mode 未在当前图上落实 → 派生升级（即使颜色已在色板内）。"""
    mode = str(facts.get("coloring_mode") or "").strip().lower()
    if mode not in COLORING_MODES:
        return None
    if not _palette_colors(persona):
        return None
    if _coloring_mode_satisfied(persona, facts, mode):
        return None
    ops = _ops_for_coloring_mode(persona, facts, mode)
    if not ops:
        return None
    alts = _color_alternatives(persona, facts, {"ops": ops})
    story = next(
        (
            s
            for s in (persona.stories or {}).values()
            if any(
                k in (s.story + s.id).lower()
                for k in ("color", "palette", "consist", "recognis", "restraint")
            )
        ),
        None,
    )
    return {
        "layer": "L2-derived",
        "rule_id": "d-color-assignment",
        "rule_text": (
            f"Apply institutional color assignment principles "
            f"(coloring_mode={mode}; not merely in-palette)"
        ),
        "strength": "should",
        "check": "programmatic",
        "story_id": story.id if story else "",
        "src": ["advisor_briefing:color_principles", f"facts.coloring_mode={mode}"],
        "derived": True,
        "why": (
            f"当前着色未落实配色原则 coloring_mode={mode}"
            f"（colors_effective={facts.get('colors_effective')}；"
            f"per_category={facts.get('per_category_coloring')}）→ 交慢道按原则择一"
        ),
        "compiled": {
            "ops": ops,
            "needs": [],
            "renderable": True,
            "any_of": None,
            "color_alternatives": alts,
            "note": f"preferred coloring_mode={mode}",
        },
        "when_details": [],
    }


def _color_assignment_needs_slow_path(then: Any, comp: dict, facts: dict) -> bool:
    """配色分配有歧义时升级慢道，由 LLM 按 coloring_mode/原则裁决。"""
    if not _is_color_assignment_then(then):
        return False
    mode = str(facts.get("coloring_mode") or "uniform")
    target = _then_target(then)
    ops = comp.get("ops") or []
    if _ops_collapse_categorical(ops) and mode in ("categorical", "paired"):
        return True
    if target == "mark.color" and mode in ("categorical", "paired"):
        return True
    if target == "color.range" and mode == "uniform" and facts.get("per_category_coloring"):
        # 多色规则撞上「应收束」情境 → 也交慢道确认
        return True
    if mode == "categorical" and (facts.get("per_category_coloring") or facts.get("color_field")):
        if target == "mark.color":
            return True
    return False


def beat2_detect(persona: Persona, spec: dict, facts: dict) -> tuple[list, list, list, list, dict]:
    """返回 (candidates, escalations, verify_list, passes, trace)。"""
    started = time.perf_counter()
    candidates: list[dict] = []
    escalations: list[dict] = []
    verify_list: list[dict] = []
    passes: list[dict] = []

    def rule_meta(r, layer):
        return {
            "layer": layer,
            "rule_id": r.id,
            "rule_text": getattr(r, "rule", "") or "",
            "strength": r.strength,
            "check": r.check,
            "story_id": r.story,
            "src": r.src,
            "derived": getattr(r, "derived", False),
        }

    # —— L1：程序化检测器直判；check:llm 或无检测器 → 升级 ——
    for rule in persona.rules:
        det = detect_rule(persona, rule, spec, facts)
        if rule.check == "programmatic" and det is not None:
            if not det.applicable:
                passes.append({**rule_meta(rule, "L1"), "note": det.detail})
            elif det.verify_only:
                verify_list.append({**rule_meta(rule, "L1"), "violated": det.violated, "detail": det.detail})
            elif det.violated:
                # 收束类别色与 coloring_mode 冲突 → 升级慢道（配色原则裁决）
                if (
                    _ops_collapse_categorical(det.ops)
                    and str(facts.get("coloring_mode") or "") in ("categorical", "paired")
                ):
                    alts = _color_alternatives(
                        persona, facts, {"ops": det.ops, "needs": [], "renderable": True}
                    )
                    escalations.append(
                        {
                            **rule_meta(rule, "L1"),
                            "why": (
                                f"配色模式={facts.get('coloring_mode')}，"
                                "单色收束会抹掉类别区分 → 交慢道按原则择一"
                            ),
                            "compiled": {
                                "ops": det.ops,
                                "needs": [],
                                "renderable": True,
                                "any_of": None,
                                "color_alternatives": alts,
                            },
                            "when_details": [],
                        }
                    )
                else:
                    candidates.append(
                        {
                            **rule_meta(rule, "L1"),
                            "ops": det.ops,
                            "detail": det.detail,
                            "confidence": "high" if rule.strength in ("must", "never", "never-exceed") else "medium",
                            "suggested_only": False,
                        }
                    )
            else:
                passes.append({**rule_meta(rule, "L1"), "note": "合规"})
        else:
            why = "check:llm 需语义判断" if rule.check == "llm" else "无编译检测器"
            escalations.append({**rule_meta(rule, "L1"), "why": why, "compiled": None, "when_details": []})

    # —— L2：结构化条件快判；unknown → 升级 ——
    for ad in persona.adaptations:
        meta = {
            "layer": "L2",
            "rule_id": ad.id,
            "rule_text": json.dumps(ad.then, ensure_ascii=False) if not isinstance(ad.then, str) else ad.then,
            "strength": ad.strength,
            "check": ad.check,
            "story_id": ad.story,
            "src": ad.src,
            "derived": ad.derived,
            "when": ad.when,
        }
        if ad.scope and ad.scope != "chart":
            passes.append({**meta, "note": f"scope={ad.scope}，超出单图范围"})
            continue
        verdict, details = eval_when(ad.when, facts)
        if verdict == NO_MATCH:
            passes.append({**meta, "note": "条件不成立", "when_details": details})
            continue
        comp = compile_then(persona, ad.then, facts)
        if verdict == MATCH:
            if _color_assignment_needs_slow_path(ad.then, comp, facts):
                alts = _color_alternatives(persona, facts, comp)
                escalations.append(
                    {
                        **meta,
                        "why": (
                            f"配色分配需按原则裁决（coloring_mode={facts.get('coloring_mode')}；"
                            f"then={_then_target(ad.then)}）"
                        ),
                        "compiled": {**comp, "color_alternatives": alts},
                        "when_details": details,
                    }
                )
            elif comp["ops"] and not comp["needs"]:
                candidates.append(
                    {
                        **meta,
                        "ops": comp["ops"],
                        "detail": "; ".join(d["note"] for d in details) if details else "无条件适配",
                        "confidence": "high" if ad.strength == "must" else "medium",
                        "suggested_only": False,
                    }
                )
            elif not comp["renderable"] and not comp["any_of"]:
                # 条件快判成立但目标超出单图 spec → 建议（不进慢道，条件已决）
                candidates.append(
                    {
                        **meta,
                        "ops": [],
                        "detail": comp.get("note", ""),
                        "confidence": "medium",
                        "suggested_only": True,
                    }
                )
            else:
                escalations.append({**meta, "why": "需语义槽位/策略择一", "compiled": comp, "when_details": details})
        else:  # UNKNOWN
            unknown_keys = [d["key"] for d in details if d["verdict"] == UNKNOWN]
            escalations.append(
                {**meta, "why": f"条件不可程序判定: {', '.join(unknown_keys)}", "compiled": comp, "when_details": details}
            )

    # —— 派生：颜色已在色板内，但未落实拍1 coloring_mode 分配原则 ——
    # 若 L1/L2 已产出配色 ops 或带 color_alternatives 的升级，避免重复派生。
    def _pending_color_fix() -> bool:
        color_actions = {"set_color_range", "set_mark_color", "remove_encoding_channel"}
        for c in candidates:
            for op in c.get("ops") or []:
                if isinstance(op, dict) and op.get("action") in color_actions:
                    return True
        for e in escalations:
            comp = e.get("compiled") if isinstance(e.get("compiled"), dict) else {}
            if comp.get("color_alternatives"):
                return True
            for op in comp.get("ops") or []:
                if isinstance(op, dict) and op.get("action") in color_actions:
                    return True
        return False

    if not _pending_color_fix():
        derived_esc = _color_assignment_escalation(persona, facts)
        if derived_esc:
            escalations.append(derived_esc)

    audit = facts.get("chart_audit") if isinstance(facts.get("chart_audit"), dict) else {}
    audit_flags = []
    axes_audit = audit.get("axes") if isinstance(audit.get("axes"), dict) else {}
    labels_audit = audit.get("labels") if isinstance(audit.get("labels"), dict) else {}
    if axes_audit.get("x_dense"):
        audit_flags.append("dense-x-labels")
    if labels_audit.get("value_labels_present") and axes_audit.get("x_dense"):
        audit_flags.append("label-density-conflict")
    summary = f"L1/L2 直判 {len(candidates)} 项候选，{len(escalations)} 项升级，{len(verify_list)} 项核验"
    if audit_flags:
        summary += f"；图表审计发现 {','.join(audit_flags)}"
    trace = _trace(2, "fast", "规范检测", started, summary,
                   candidates=[c["rule_id"] for c in candidates],
                   escalated=[e["rule_id"] for e in escalations], audit_flags=audit_flags)
    return candidates, escalations, verify_list, passes, trace


# ---------------------------------------------------------------------------
# 拍3 慢道 · 溯源裁决
# ---------------------------------------------------------------------------

# mock 慢道的语义门（live 模式由 LLM 溯源裁决；这里是确定性替身）
MOCK_GATES = {
    "a-color-highlight": lambda f: bool(f.get("emphasis_target")),
    "a-emphasis": lambda f: bool(f.get("emphasis_target")),
    "a-chart-bubble": lambda f: (f.get("data_range_ratio") or 0) > 100,
    "a-chart-thermometer": lambda f: f.get("category_count") == 2,
    "a-color-party": lambda f: f.get("data_topic") == "politics",
    "a-color-support": lambda f: False,
}


def _mock_gate(esc: dict, facts: dict) -> bool | None:
    """确定性验证常见语义条件；不依赖自定义规则 id。"""
    gate = MOCK_GATES.get(esc["rule_id"])
    if gate:
        return gate(facts)

    when = esc.get("when") if isinstance(esc.get("when"), dict) else {}
    task = when.get("task")
    if isinstance(task, str) and task.strip():
        expected = re.sub(r"[-_]+", " ", task.strip().lower())
        goal = re.sub(
            r"[-_]+", " ", str(facts.get("communication_goal") or "").lower()
        )
        return expected in goal

    # 用户传播意图分析：when.intent 与分析/facts 一致时放行
    analysis = facts.get("user_intent_analysis") if isinstance(facts.get("user_intent_analysis"), dict) else {}
    user_kind = analysis.get("kind")
    if user_kind in ("communication", "mixed") and "intent" in when:
        want = when.get("intent")
        have = facts.get("intent")
        if isinstance(want, str) and have and want == have:
            return True
        if isinstance(want, list) and have in want:
            return True
    if user_kind in ("communication", "mixed") and facts.get("emphasis_target"):
        # 需要强调目标的升级项：用户已给出强调对象时倾向成立
        if esc.get("rule_id") in ("a-color-highlight", "a-emphasis") or "emphasis" in str(esc.get("rule_id")):
            return True
    return None


def _ensure_emphasis_binding(facts: dict, target: Any = None) -> dict:
    """保证 facts 含 emphasis_field/mechanism；target 变更时重绑。"""
    local = dict(facts)
    if target is not None:
        local["emphasis_target"] = target
    if (
        not local.get("emphasis_mechanism")
        or not local.get("emphasis_field")
        or (
            target is not None
            and str(target) != str(facts.get("emphasis_target") or "")
        )
    ):
        bind = infer_emphasis_binding(
            local,
            emphasis_target=local.get("emphasis_target"),
            color_structure=infer_color_structure(local),
        )
        local.update({k: v for k, v in bind.items() if v is not None or k == "emphasis_target"})
    return local


def _fill_emphasis(
    ops: list[dict], facts: dict, target: str | None, persona: Any = None
) -> list[dict]:
    """按 Binding IR 填充强调 ops；错机制的 highlight_category 可重编译为 set_color_range。"""
    local = _ensure_emphasis_binding(facts, target)
    value = local.get("emphasis_target")
    mech = local.get("emphasis_mechanism")
    # 旧编译残留：series_scale 却仍是 highlight_category → 按 IR 重编译
    if (
        mech == "series_scale"
        and persona is not None
        and any(isinstance(o, dict) and o.get("action") == "highlight_category" for o in ops)
    ):
        accent = next(
            (
                o.get("color")
                for o in ops
                if isinstance(o, dict) and o.get("action") == "highlight_category" and o.get("color")
            ),
            None,
        )
        if isinstance(accent, str):
            base = next(
                (
                    o.get("base_color")
                    for o in ops
                    if isinstance(o, dict) and o.get("base_color")
                ),
                None,
            )
            rebuilt, _needs = build_emphasis_ops(
                persona, {**local, "emphasis_target": value}, accent=accent, base=base
            )
            if rebuilt:
                return fill_emphasis_ops(rebuilt, local, value)
    return fill_emphasis_ops(ops, local, value)


def _pick_color_alternative(
    comp: dict, facts: dict, coloring_choice: str | None = None
) -> list[dict] | None:
    """从 color_alternatives 按 coloring_choice / facts.coloring_mode 选取 ops。"""
    alts = comp.get("color_alternatives") if isinstance(comp, dict) else None
    if not isinstance(alts, list) or not alts:
        return None
    by_id = {a.get("id"): a for a in alts if isinstance(a, dict) and a.get("id")}
    choice = (coloring_choice or facts.get("coloring_mode") or "uniform")
    if isinstance(choice, str):
        choice = choice.strip().lower()
    if choice == "highlight":
        # 字面双色：用 highlight 备选（主色+辅色）；否则底色走 uniform
        if not (
            facts.get("literal_color_encoding") and facts.get("accent_color")
        ):
            choice = "uniform"
    alt = by_id.get(choice) or by_id.get(str(facts.get("coloring_mode") or "uniform"))
    if not alt:
        return None
    ops = list(alt.get("ops") or [])
    return ops if ops else None


_EMPHASIS_COLOR_RULES = frozenset({"a-emphasis", "a-color-highlight"})


def _has_existing_emphasis(facts: dict) -> bool:
    """图上已有强调目标或字面双色强调结构。"""
    if facts.get("emphasis_target") is not None and str(facts.get("emphasis_target")) != "":
        return True
    return bool(facts.get("literal_color_encoding") and facts.get("accent_color"))


def _house_emphasis_color_ops(persona: Persona, facts: dict) -> list[dict]:
    """机构主色 + 强调色；字面双色走 set_mark_color(+accent)。"""
    palette = _palette_colors(persona)
    accent = None
    if hasattr(persona, "resolve_color"):
        for key in (
            "{color.bbc-orange}",
            "{color.accent}",
            "{color.hong-kong}",
            "bbc-orange",
            "color.accent",
        ):
            accent = persona.resolve_color(key)
            if isinstance(accent, str) and accent:
                break
    if not accent and len(palette) >= 2:
        accent = palette[1]
    if not accent and palette:
        accent = palette[0]
    base = None
    if hasattr(persona, "resolve_color"):
        base = (
            persona.resolve_color("{color.primary}")
            or persona.resolve_color("{color.bbc-blue}")
        )
    if not base and palette:
        base = palette[0]
    if not isinstance(accent, str) or not accent:
        return []
    ops, _needs = build_emphasis_ops(persona, facts, accent=accent, base=base)
    if ops:
        return ops
    # 回退：至少改写字面双色
    if _needs_literal_highlight_ops(facts) and base:
        return _literal_highlight_ops([base, accent] if accent != base else [base])
    return []


def _promote_emphasis_color_rules(
    persona: Persona,
    facts: dict,
    escalations: list[dict],
    adopted: list[dict],
    rejected: list[dict],
) -> tuple[list[dict], list[dict]]:
    """已有强调时，a-emphasis / a-color-highlight 不得因 LLM 摇摆空转。

    - 已有可执行配色 op → 保留
    - reject / suggested-empty → 程序补机构 set_mark_color(+accent) 并 applied
    """
    if not _has_existing_emphasis(facts):
        return adopted, rejected

    esc_by_id = {
        e.get("rule_id"): e
        for e in escalations
        if isinstance(e, dict) and e.get("rule_id") in _EMPHASIS_COLOR_RULES
    }
    if not esc_by_id:
        return adopted, rejected

    def _has_color_ops(item: dict) -> bool:
        return any(
            isinstance(o, dict)
            and o.get("action") in ("set_mark_color", "highlight_category", "set_color_range")
            for o in (item.get("ops") or [])
        )

    adopted_ids = {a.get("rule_id") for a in adopted}
    # 已有可执行配色 → 若 suggested_only，升为 applied
    for a in adopted:
        if a.get("rule_id") not in esc_by_id:
            continue
        if _has_color_ops(a) and a.get("suggested_only"):
            a["suggested_only"] = False
            a["rationale"] = (
                str(a.get("rationale") or "")
                + "；（程序：已有强调结构，强制落地机构强调色）"
            ).lstrip("；")
        elif not _has_color_ops(a):
            ops = _house_emphasis_color_ops(persona, facts)
            if ops:
                a["ops"] = ops
                a["suggested_only"] = False
                a["rationale"] = (
                    str(a.get("rationale") or "")
                    + "；（程序：已有强调结构，补全机构强调色 ops）"
                ).lstrip("；")

    # 驳回项：已落地则丢弃；否则拉回 adopted
    keep_rejected: list[dict] = []
    for r in rejected:
        rid = r.get("rule_id")
        if rid not in esc_by_id:
            keep_rejected.append(r)
            continue
        if rid in adopted_ids:
            continue
        ops = _house_emphasis_color_ops(persona, facts)
        if not ops:
            keep_rejected.append(r)
            continue
        esc = esc_by_id[rid]
        adopted.append(
            _adopt(
                esc,
                ops,
                "medium",
                (str(r.get("rationale") or r.get("reason") or "")
                 + "；（程序：已有强调结构，覆盖驳回并落地机构强调色）").lstrip("；"),
            )
        )
        adopted_ids.add(rid)

    # 升级列表里有、但裁决完全漏掉的规则
    for rid, esc in esc_by_id.items():
        if rid in adopted_ids:
            continue
        ops = _house_emphasis_color_ops(persona, facts)
        if not ops:
            continue
        adopted.append(
            _adopt(
                esc,
                ops,
                "medium",
                "程序：已有强调结构，强制采纳机构强调色",
                derived=True,
            )
        )

    return adopted, keep_rejected


def _adopt(esc: dict, ops: list[dict], confidence: str, rationale: str, suggested_only: bool = False, derived: bool = False) -> dict:
    return {
        **{k: esc[k] for k in ("layer", "rule_id", "rule_text", "strength", "story_id", "src")},
        "derived": derived or esc.get("derived", False),
        "ops": ops,
        "confidence": confidence,
        "rationale": rationale,
        "suggested_only": suggested_only,
        "detail": rationale,
    }


def _reject(esc: dict, reason: str) -> dict:
    return {
        "rule_id": esc["rule_id"],
        "layer": esc["layer"],
        "label": label_for(esc["rule_id"]),
        "reason": reason,
        "src": esc.get("src", []),
        "story_id": esc.get("story_id", ""),
    }


def _is_default_white_background(bg: Any) -> bool:
    """未设底色，或导出器默认白底 → 可用 canvas 令牌覆盖。"""
    if bg is None:
        return True
    if not isinstance(bg, str):
        return False
    s = bg.strip().lower().replace(" ", "")
    return s in (
        "#fff",
        "#ffffff",
        "white",
        "rgb(255,255,255)",
        "rgba(255,255,255,1)",
        "rgba(255,255,255,1.0)",
    )


def _derived_proposals(persona: Persona, spec: dict, facts: dict) -> list[dict]:
    """哲学/令牌可推导的额外提案（derived，降置信）。通用规则：存在 canvas
    令牌组且图表未设（或仍为默认白）背景 → 以最浅 canvas 色为图底。"""
    from .detectors import relative_luminance

    out = []
    canvas = persona.token_index().get("color.canvas")
    if isinstance(canvas, dict) and _is_default_white_background(facts.get("background")):
        hexes = [(k, v) for k, v in canvas.items() if isinstance(v, str) and v.startswith("#")]
        if hexes:
            name, color = max(hexes, key=lambda kv: relative_luminance(kv[1]) or 0)
            # 若已是该色则无需再提
            cur = facts.get("background")
            if isinstance(cur, str) and cur.strip().lower() == color.strip().lower():
                return out
            harmony = next(
                (p for p in persona.philosophy if "harmony" in (p.id + p.title).lower()),
                persona.philosophy[0] if persona.philosophy else None,
            )
            out.append(
                {
                    "layer": "L3-derived",
                    "rule_id": "d-canvas-bg",
                    "rule_text": f"以版面令牌 {name} 作为图表底色（哲学推导，非指南明文）",
                    "strength": "may",
                    "story_id": harmony.id if harmony else "",
                    "src": [f"tokens.color.canvas.{name}"],
                    "derived": True,
                    "ops": [{"action": "set_background", "color": color}],
                    "confidence": "low",
                    "rationale": f"指南未明文绑定图底色；由 canvas 令牌组与「{harmony.title or harmony.id if harmony else '视觉和谐'}」哲学推导，降置信采纳",
                    "suggested_only": False,
                    "philosophy_quote": harmony.quote if harmony else "",
                }
            )
    return out


def _mock_adjudicate(persona: Persona, facts: dict, escalations: list[dict]) -> tuple[list, list]:
    adopted, rejected = [], []
    for esc in escalations:
        rid = esc["rule_id"]
        comp = esc.get("compiled") or {}
        # 配色备选：按拍1 coloring_mode 确定性择一（live 由 LLM 填 coloring_choice）
        if isinstance(comp, dict) and comp.get("color_alternatives"):
            ops = _pick_color_alternative(comp, facts)
            mode = facts.get("coloring_mode") or "uniform"
            if ops:
                adopted.append(
                    _adopt(
                        esc,
                        ops,
                        "medium",
                        f"按配色原则采纳 coloring_mode={mode}（mock 慢道）",
                    )
                )
            else:
                rejected.append(_reject(esc, f"配色备选无可用 ops（mode={mode}）→ 驳回不改"))
            continue
        if esc["layer"] == "L2":
            comp = esc.get("compiled") or {"ops": [], "needs": [], "renderable": False, "any_of": None}
            gate_ok = _mock_gate(esc, facts)

            if comp.get("any_of"):
                chosen = next(
                    (s for s in comp["any_of"]
                     if "高亮" in s or "强色" in s or "highlight" in s.lower() or "strong" in s.lower()),
                    None,
                )
                if chosen and _has_existing_emphasis(facts):
                    comp2 = compile_strategy(persona, chosen, facts)
                    if comp2["ops"]:
                        ops = _fill_emphasis(comp2["ops"], facts, None, persona)
                        adopted.append(_adopt(esc, ops, "medium", f"择策略「{chosen}」，明文担保 src {', '.join(esc['src'])}"))
                        continue
                    # any-of 编译空时仍尝试机构强调色（字面双色）
                    ops = _house_emphasis_color_ops(persona, facts)
                    if ops:
                        adopted.append(
                            _adopt(esc, ops, "medium", f"择策略「{chosen}」，程序补全机构强调色")
                        )
                        continue
                rejected.append(_reject(esc, "候选策略均不可执行或无强调目标 → 无担保，驳回不改"))
                continue

            if comp.get("needs"):
                if "emphasis_target" in comp["needs"] and _has_existing_emphasis(facts) and gate_ok is not False:
                    ops = _fill_emphasis(comp["ops"], facts, None, persona)
                    if not ops:
                        ops = _house_emphasis_color_ops(persona, facts)
                    if ops:
                        adopted.append(
                            _adopt(
                                esc,
                                ops,
                                "medium",
                                f"读图立意/字面强调给出目标，明文担保采纳",
                            )
                        )
                    else:
                        rejected.append(_reject(esc, "缺少可执行强调 ops → 驳回不改"))
                else:
                    rejected.append(_reject(esc, "缺少语义槽位（强调目标）→ 驳回不改"))
                continue

            if gate_ok is True:
                if comp["ops"]:
                    adopted.append(_adopt(esc, comp["ops"], "medium", "语义门核验成立，明文担保采纳"))
                else:
                    # 强调色规则：条件成立但 compiled 空 → 补机构色，勿空建议
                    if rid in _EMPHASIS_COLOR_RULES and _has_existing_emphasis(facts):
                        ops = _house_emphasis_color_ops(persona, facts)
                        if ops:
                            adopted.append(
                                _adopt(esc, ops, "medium", "语义门成立，程序补全机构强调色")
                            )
                            continue
                    adopted.append(_adopt(esc, [], "low", "条件成立但超出单图可执行范围，作为建议", suggested_only=True))
            elif gate_ok is False:
                rejected.append(_reject(esc, "语义条件核验不成立 → 无担保，驳回不改"))
            else:
                rejected.append(_reject(esc, "mock 慢道无担保验证能力，保守驳回（live 模式交 LLM 溯源裁决）"))
        else:
            # L1 check:llm 规则
            if rid == "s-title-case":
                from .actions import _to_sentence_case, _normalize_plain_text

                title = _normalize_plain_text(facts.get("title_text") or "")
                if any(c.isascii() and c.isalpha() for c in title):
                    rewritten = _to_sentence_case(title)
                    if rewritten and rewritten != title:
                        adopted.append(
                            _adopt(
                                esc,
                                [{"action": "set_title_text", "text": rewritten}],
                                "medium",
                                "标题改为 sentence case（明文 must）",
                            )
                        )
                    else:
                        rejected.append(_reject(esc, "标题已符合 sentence case → 无需改动"))
                else:
                    rejected.append(_reject(esc, "标题非拉丁文字，大小写规范不适用 → 驳回"))
            elif rid == "s-title-descriptive":
                from .actions import _descriptive_title_ops

                ops = _descriptive_title_ops(facts)
                if ops:
                    adopted.append(
                        _adopt(
                            esc,
                            ops,
                            "medium",
                            "标题/副标题按「陈述要点、副标题补语境」启发式改写",
                        )
                    )
                else:
                    rejected.append(_reject(esc, "标题已够简洁或已是要点式 → 无需改动"))
            elif esc["strength"] in ("must", "never"):
                adopted.append(_adopt(esc, [], "medium", "must 级规范但需人工/语义判断，作为建议保留", suggested_only=True))
            else:
                rejected.append(_reject(esc, "should/may 级语义规范，mock 慢道无法验证 → 保守驳回留痕"))
    return adopted, rejected


async def beat3_adjudicate(
    persona: Persona, spec: dict, facts: dict, escalations: list[dict], llm: LLMClient
) -> tuple[list, list, dict]:
    started = time.perf_counter()
    mode = llm.mode
    note = ""
    # 视觉审图只提供问题证据；同一拍中再用 persona YAML 的专属策略把它转成
    # 可裁决候选，避免所有机构直接套用相同的 v-* 通用动作。
    from .visual_review import run_visual_review, strategy_escalations_from_findings
    from .component_assembler import select_component_assembly, plan_component_assembly_with_llm

    assembly_plan = select_component_assembly(persona, facts.get("component_ir") or {})

    vis_adopted, vis_rejected, vis_meta = await run_visual_review(persona, spec, facts, llm)
    facts["visual_review"] = vis_meta
    assembly_plan = await plan_component_assembly_with_llm(persona, facts, llm, assembly_plan)
    facts["component_assembly_plan"] = assembly_plan
    strategy_escalations = strategy_escalations_from_findings(persona, facts, vis_meta)
    all_escalations = list(escalations) + strategy_escalations

    if mode == "live" and all_escalations:
        try:
            adopted, rejected = await _live_adjudicate(persona, spec, facts, all_escalations, llm)
        except LLMError as exc:
            adopted, rejected = _mock_adjudicate(persona, facts, all_escalations)
            note = f"live 裁决失败已降级启发式：{exc}"
            mode = "mock-fallback"
    else:
        adopted, rejected = _mock_adjudicate(persona, facts, all_escalations)

    adopted, rejected = _promote_emphasis_color_rules(
        persona, facts, all_escalations, adopted, rejected
    )

    adopted.extend(_derived_proposals(persona, spec, facts))

    # 拍3.6 · L3 风格化：哲学 → 受控布局/几何动作（live；失败静默让位）。
    # 表面占用检查须同时看到慢道采纳与快道候选（两路 ops 都会进拍4）。
    from .style_pass import style_proposals

    planned = adopted + list(facts.get("fast_candidates") or [])
    style_items = await style_proposals(persona, spec, facts, planned, llm)
    if style_items:
        adopted.extend(style_items)
        note = (note + "｜" if note else "") + f"style_pass:{len(style_items)}"

    # 用户意图与 L1 never 冲突的驳回并入 rejected
    rejected.extend(list(facts.get("user_intent_rejected") or []))

    if vis_rejected:
        rejected.extend(vis_rejected)
    if vis_meta.get("ran"):
        note = (note + "｜" if note else "") + f"visual_review:{len(strategy_escalations)} strategy/{len(vis_rejected)}r"
    if assembly_plan:
        note = (note + "｜" if note else "") + f"component_assembly:{assembly_plan['rule_id']}"
    elif vis_meta.get("skipped"):
        note = (note + "｜" if note else "") + f"visual_skip:{vis_meta['skipped']}"

    summary = f"采纳 {sum(1 for a in adopted if not a['suggested_only'])} 项、建议 {sum(1 for a in adopted if a['suggested_only'])} 项、驳回 {len(rejected)} 项"
    trace = _trace(3, "slow", "溯源裁决", started, summary, mode=mode, note=note,
                   adopted=[a["rule_id"] for a in adopted], rejected=[r["rule_id"] for r in rejected],
                   visual_review=vis_meta,
                   component_assembly={"selected": bool(assembly_plan), "rule_id": (assembly_plan or {}).get("rule_id"),
                                       "planner": (assembly_plan or {}).get("planner", "deterministic")})
    return adopted, rejected, trace


async def _live_adjudicate(persona, spec, facts, escalations, llm) -> tuple[list, list]:
    eligible: list[dict] = []
    rejected = []
    for esc in escalations:
        when = esc.get("when") if isinstance(esc.get("when"), dict) else {}
        # data_role / audience 不是当前读图立意可凭空推断的槽位。缺少事实时先验驳回，
        # 防止模型把“辅助数据用灰色”误用于整张普通图。
        missing = [
            key
            for key in ("data_role", "audience")
            if key in when and not facts.get(key)
        ]
        if missing:
            rejected.append(
                _reject(
                    esc,
                    f"缺少语义槽位（{', '.join(missing)}）→ 不允许 LLM 猜测，驳回不改",
                )
            )
        else:
            eligible.append(esc)

    if not eligible:
        return [], rejected

    chart_slice = facts.get("chart_slice")
    if not isinstance(chart_slice, dict):
        chart_slice = build_chart_slice(spec, facts)
    items = []
    for esc in eligible:
        comp = esc.get("compiled") or {}
        alts = comp.get("color_alternatives") if isinstance(comp, dict) else None
        items.append(
            {
                "id": esc["rule_id"],
                "layer": esc["layer"],
                "rule": esc["rule_text"],
                "strength": esc["strength"],
                "src": esc["src"],
                "story": persona.story_text(esc.get("story_id", "")),
                "when": esc.get("when"),
                "why_escalated": esc["why"],
                "chart_audit": facts.get("chart_audit"),
                "action_space": describe_ops(comp.get("ops") or []) or None,
                "any_of": comp.get("any_of"),
                "needs": comp.get("needs") or [],
                "color_alternatives": [
                    {
                        "id": a.get("id"),
                        "label": a.get("label"),
                        "action_space": a.get("action_space"),
                    }
                    for a in (alts or [])
                    if isinstance(a, dict)
                ]
                or None,
            }
        )
    items = attach_slice_to_escalation_items(items, chart_slice)
    system = beat3_adjudicate_system(
        persona,
        facts.get("advisor_briefing") if isinstance(facts.get("advisor_briefing"), dict) else None,
    )
    base_payload = {
        "facts": {k: facts.get(k) for k in (
            "mark_type", "categories", "series_count", "color_field", "per_category_coloring",
            "colors_effective", "coloring_mode", "data_topic", "intent", "data_role",
            "emphasis_target", "emphasis_field", "emphasis_mechanism", "series_values",
            "title_text", "summary", "organization", "communication_goal",
            "data_range_ratio", "category_count", "user_intent_analysis",
        )},
        "chart_slice": chart_slice,
        "chart_audit": facts.get("chart_audit"),
        "persona_knowledge": {
            "diagnostics": getattr(persona, "diagnostics", [])[:40],
            "chart_type_guidance": getattr(persona, "chart_type_guidance", [])[:20],
            "palette_guidance": getattr(persona, "palette_guidance", [])[:20],
            "conflicts": getattr(persona, "conflicts", [])[:20],
        },
    }

    def _verdicts_of(raw: Any) -> list[dict]:
        seq = raw.get("verdicts") if isinstance(raw, dict) else raw
        return [v for v in (seq or []) if isinstance(v, dict)]

    raw = await llm.chat_json(system, json.dumps({**base_payload, "items": items}, ensure_ascii=False))
    verdict_map = {v.get("id"): v for v in _verdicts_of(raw)}
    # 小模型偶发漏答部分条目；对缺失项定向补裁一次（短列表不易再漏），仍缺才保守驳回
    missing_items = [it for it in items if it.get("id") not in verdict_map]
    if missing_items:
        try:
            raw2 = await llm.chat_json(
                system, json.dumps({**base_payload, "items": missing_items}, ensure_ascii=False)
            )
            for v in _verdicts_of(raw2):
                verdict_map.setdefault(v.get("id"), v)
        except Exception:  # noqa: BLE001 — 补裁失败维持原有保守驳回路径
            pass

    adopted = []
    for esc in eligible:
        v = verdict_map.get(esc["rule_id"])
        if not v:
            rejected.append(_reject(esc, "慢道未给出裁决 → 保守驳回"))
            continue
        rationale = str(v.get("rationale") or "")
        if v.get("verdict") != "adopt":
            rejected.append(_reject(esc, rationale or "无担保，驳回不改"))
            continue
        comp = esc.get("compiled") or {"ops": [], "needs": [], "any_of": None}
        ops = list(comp.get("ops") or [])
        # 配色备选优先：LLM coloring_choice → 令牌已解析的 ops
        if comp.get("color_alternatives"):
            choice = v.get("coloring_choice")
            picked = _pick_color_alternative(comp, facts, choice if isinstance(choice, str) else None)
            if picked is None:
                rejected.append(_reject(esc, "配色备选未选定或无可用 ops → 驳回不改"))
                continue
            ops = picked
        elif comp.get("any_of") and v.get("strategy"):
            comp2 = compile_strategy(persona, str(v["strategy"]), facts)
            ops = comp2["ops"]
        if any(
            isinstance(op, dict)
            and (
                op.get("action") == "highlight_category"
                or op.get("_emphasis_fill")
                or "emphasis_target" in (comp.get("needs") or [])
            )
            for op in ops
        ) or "emphasis_target" in (comp.get("needs") or []):
            emp_t = v.get("emphasis_target") or facts.get("emphasis_target")
            ops = _fill_emphasis(ops, facts, emp_t, persona)
            if any(
                isinstance(op, dict)
                and op.get("action") == "highlight_category"
                and not op.get("value")
                for op in ops
            ):
                rejected.append(_reject(esc, "采纳需要强调目标但慢道未给出 → 驳回"))
                continue
            if any(
                isinstance(op, dict)
                and op.get("action") == "set_color_range"
                and op.get("_emphasis_fill")
                for op in ops
            ):
                rejected.append(_reject(esc, "采纳需要强调目标但慢道未给出 → 驳回"))
                continue
        # L1 标题类：compiled 常为空，用确定性改写落地（不经 LLM 发明文案）
        if not ops and esc.get("layer") == "L1":
            title = str(facts.get("title_text") or "")
            if esc["rule_id"] == "s-title-case" and any(
                c.isascii() and c.isalpha() for c in title
            ):
                from .actions import _to_sentence_case, _normalize_plain_text

                rewritten = _to_sentence_case(_normalize_plain_text(title))
                if rewritten and rewritten != _normalize_plain_text(title):
                    ops = [{"action": "set_title_text", "text": rewritten}]
            elif esc["rule_id"] == "s-title-descriptive":
                from .actions import _descriptive_title_ops

                ops = _descriptive_title_ops(facts)
        confidence = v.get("confidence") if v.get("confidence") in ("high", "medium", "low") else "medium"
        adopted.append(
            _adopt(esc, ops, confidence, rationale or "明文担保采纳",
                   suggested_only=not ops, derived=bool(v.get("derived")))
        )
    # 拍3.5：被采纳的标题类规范交给慢道撰写机构口吻文案，快道核验后替换确定性模板；
    # 失败回落上面已填好的确定性 ops，行为不劣化。
    from .copywriter import apply_title_copywriter

    adopted = await apply_title_copywriter(persona, facts, adopted, llm)
    return adopted, rejected


# ---------------------------------------------------------------------------
# 拍4 快道 · 编译执行与校验
# ---------------------------------------------------------------------------

def _build_change(persona: Persona, item: dict, status: str) -> dict:
    rule_id = item["rule_id"]
    story = persona.story_text(item.get("story_id", ""))
    reason_parts = []
    if story:
        reason_parts.append(story)
    if item.get("rationale"):
        reason_parts.append(item["rationale"])
    if item.get("rule_text") and item["rule_text"] not in reason_parts:
        reason_parts.append(item["rule_text"])
    src = item.get("src") or []
    reason = "；".join(p for p in reason_parts if p)
    if src:
        reason += f"（src: {', '.join(src)}）"
    prompt = describe_ops(item.get("ops") or []) or item.get("rule_text", "")
    out = {
        "id": f"{persona.id}:{rule_id}",
        "rule_id": rule_id,
        "label": item.get("label") or label_for(rule_id),
        "reason": reason,
        "prompt": prompt,
        "layer": item.get("layer", "L1"),
        "strength": item.get("strength", "should"),
        "confidence": item.get("confidence", "medium"),
        "status": status,
        "warrant": {
            "src": src,
            "story_id": item.get("story_id", ""),
            "story": story,
            "quote": item.get("philosophy_quote", ""),
            "source_file": persona.source_file,
            "derived": bool(item.get("derived")),
        },
        "ops": item.get("ops") or [],
    }
    return out


# 用户明确改件锁住的 action：同 action 的机构 ops 不再 applied，降为 suggested 保留展示
_USER_PRIORITY_ACTIONS = frozenset({"set_mark_type"})


def _user_pie_ops(user_exec: list[dict]) -> bool:
    for item in user_exec:
        for op in item.get("ops") or []:
            if op.get("chart_type") == "pie" or (
                op.get("action") == "set_mark_type" and op.get("mark_type") == "arc"
            ):
                return True
    return False


def _user_locked_actions(user_exec: list[dict]) -> set[str]:
    locked: set[str] = set()
    for item in user_exec:
        for op in item.get("ops") or []:
            action = op.get("action")
            if action in _USER_PRIORITY_ACTIONS:
                locked.add(str(action))
    # 饼图按类别着色：禁用单色 mark.color（指南分类色板才是正确层级）
    if _user_pie_ops(user_exec):
        locked.add("set_mark_color")
    return locked


def _ops_hit_lock(ops: list[dict], locked: set[str]) -> bool:
    return any(op.get("action") in locked for op in (ops or []))


# 机构层同节点冲突键：基础配色合并为一类（不含 highlight——可叠在基色之上）
_COLOR_ENCODING_ACTIONS = frozenset(
    {"set_color_range", "set_mark_color", "remove_encoding_channel"}
)
_STRENGTH_RANK = {"must": 3, "never": 3, "never-exceed": 3, "should": 2, "may": 1}


def _conflict_key_for_ops(ops: list[dict]) -> str | None:
    """取条目中优先级最高的冲突键（配色类统一为 color_encoding）。"""
    keys: list[str] = []
    for op in ops or []:
        if not isinstance(op, dict):
            continue
        action = str(op.get("action") or "")
        if not action:
            continue
        if action in _COLOR_ENCODING_ACTIONS:
            keys.append("color_encoding")
        elif action == "set_mark_type":
            keys.append("set_mark_type")
        elif action.startswith("set_font"):
            keys.append("font")
        elif action in ("set_title_text", "set_subtitle", "set_source_note"):
            # 标题/副标题/来源可叠加，勿并成同一冲突键
            keys.append(action)
        elif action == "set_background":
            keys.append("background")
        elif action == "set_legend":
            keys.append("legend")
        elif action == "merge_config":
            # 按 config 顶层键区分（axisX / axisY 可共存，勿整类互斥）
            cfg = op.get("config") if isinstance(op.get("config"), dict) else {}
            top = ".".join(sorted(str(k) for k in cfg.keys())) or "_"
            keys.append(f"merge_config:{top}")
        elif action == "set_size":
            keys.append("set_size")
        else:
            keys.append(action)
    if not keys:
        return None
    # 多键时：配色优先作为代表键（同条 change 通常只改一类）
    if "color_encoding" in keys:
        return "color_encoding"
    if "set_mark_type" in keys:
        return "set_mark_type"
    return keys[0]


def _item_strength_rank(item: dict) -> int:
    return _STRENGTH_RANK.get(str(item.get("strength") or "should"), 1)


def _merge_persona_by_conflict_key(
    candidates: list[dict], adopted: list[dict]
) -> tuple[list[dict], list[dict]]:
    """机构同节点只留一条：adopted（拍3）> candidates（拍2）；同级 strength 高者胜，后写覆盖前写。

    返回 (executable_persona, superseded_as_suggested)。
    """
    # 条目带来源优先级：adopted=1 > candidates=0；同级内顺序靠后优先
    ranked: list[tuple[int, int, int, dict]] = []
    for i, c in enumerate(candidates):
        if c.get("ops") and not c.get("suggested_only"):
            ranked.append((0, _item_strength_rank(c), i, c))
    offset = len(candidates)
    for j, a in enumerate(adopted):
        if a.get("ops") and not a.get("suggested_only"):
            ranked.append((1, _item_strength_rank(a), offset + j, a))

    winners: dict[str, tuple[int, int, int, dict]] = {}
    no_key: list[dict] = []
    for tier, strength, idx, item in ranked:
        key = _conflict_key_for_ops(item.get("ops") or [])
        if key is None:
            no_key.append(item)
            continue
        prev = winners.get(key)
        if prev is None:
            winners[key] = (tier, strength, idx, item)
            continue
        pt, ps, pi, _ = prev
        # 更高 tier（adopted）胜；同 tier 更高 strength；再后写胜
        if tier > pt or (tier == pt and (strength > ps or (strength == ps and idx >= pi))):
            winners[key] = (tier, strength, idx, item)

    winner_ids = {id(v[3]) for v in winners.values()}
    no_key_ids = {id(x) for x in no_key}
    executable: list[dict] = []
    # 稳定顺序：按原相对序输出胜出项，无冲突键项追加在后
    ordered = sorted(winners.values(), key=lambda t: t[2])
    for _t, _s, _i, item in ordered:
        executable.append(item)
    executable.extend(no_key)

    superseded: list[dict] = []
    for _tier, _strength, _idx, item in ranked:
        if id(item) in winner_ids or id(item) in no_key_ids:
            continue
        key = _conflict_key_for_ops(item.get("ops") or []) or "node"
        win = winners.get(key)
        win_id = (win[3].get("rule_id") if win else "?")
        superseded.append(
            {
                **item,
                "ops": [],
                "suggested_only": True,
                "rationale": (
                    f"{item.get('rationale') or ''}（同节点已由更高优先级决策覆盖："
                    f"{win_id}）"
                ).strip(),
            }
        )
    return executable, superseded


def _defer_for_user_lock(item: dict) -> dict:
    return {
        **item,
        "ops": [],
        "suggested_only": True,
        "rationale": (
            f"{item.get('rationale') or ''}（与用户明确改件冲突："
            "保留为建议，已优先执行用户意图）"
        ).strip(),
    }


def _build_execution_plan(
    persona: Persona,
    facts: dict,
    candidates: list[dict],
    adopted: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """拍4编排：用户优先 → 机构同键合并（慢道优先于快道）。

    返回 (executable, suggested, deferred_persona)。
    """
    suggested = [c for c in candidates if c.get("suggested_only")] + [
        a for a in adopted if a.get("suggested_only")
    ]

    user_items = list(facts.get("user_constraint_items") or [])
    user_exec = [c for c in user_items if c.get("ops") and not c.get("suggested_only")]
    user_sug = [c for c in user_items if c.get("suggested_only")]

    if _user_pie_ops(user_exec):
        palette_item = _pie_categorical_palette_item(persona)
        if palette_item and not any(
            o.get("action") == "set_color_range"
            for it in user_exec
            for o in (it.get("ops") or [])
        ):
            user_exec = list(user_exec) + [palette_item]

    locked = _user_locked_actions(user_exec)
    cand_ops = [c for c in candidates if c.get("ops") and not c.get("suggested_only")]
    adop_ops = [a for a in adopted if a.get("ops") and not a.get("suggested_only")]

    deferred_persona: list[dict] = []
    unlocked_cand: list[dict] = []
    unlocked_adop: list[dict] = []
    for item in cand_ops:
        if locked and _ops_hit_lock(item.get("ops") or [], locked):
            deferred_persona.append(_defer_for_user_lock(item))
        else:
            unlocked_cand.append(item)
    for item in adop_ops:
        if locked and _ops_hit_lock(item.get("ops") or [], locked):
            deferred_persona.append(_defer_for_user_lock(item))
        else:
            unlocked_adop.append(item)

    merged, superseded = _merge_persona_by_conflict_key(unlocked_cand, unlocked_adop)
    executable = user_exec + merged
    suggested = user_sug + deferred_persona + superseded + suggested
    return executable, suggested, deferred_persona


def _pie_categorical_palette_item(persona: Persona) -> dict | None:
    """用户改 pie 后补分类色板 range（对齐 IBM categorical sequence）。"""
    colors = persona.resolve_color_list("{palette.categorical}") if hasattr(persona, "resolve_color_list") else []
    if not colors:
        return None
    return {
        "rule_id": "u-color-range-categorical",
        "layer": "user",
        "strength": "should",
        "src": ["user:communication_goal", "persona:palette.categorical"],
        "story_id": "",
        "ops": [{"action": "set_color_range", "colors": colors}],
        "confidence": "high",
        "suggested_only": False,
        "rationale": (
            "饼图/多类别着色使用机构分类色板顺序（非单色 primary）；"
            f"已写入 {len(colors)} 色 scale.range"
        ),
        "detail": "categorical palette for pie slices",
        "focus": "color",
        "kind": "edit",
        "grounding": "persona_token",
        "label": "User color.range (categorical)",
        "rule_text": '{"set":"color.range","to":"{palette.categorical}"}',
    }


def _structure_loss_detail(original: dict, candidate: dict, item: dict | None = None) -> str | None:
    """Return a compact loss report when a candidate silently removes source structure."""
    final = structure_baseline(candidate)
    missing_marks = max(0, int(original.get("unit_count") or 0) - int(final.get("unit_count") or 0))
    missing_annotations = max(
        0, int(original.get("annotation_count") or 0) - int(final.get("annotation_count") or 0)
    )
    missing_channels = sorted(
        set(original.get("encoding_channels") or []) - set(final.get("encoding_channels") or [])
    )
    # 单色规范会有意识地把 field-based color 改成 mark.color；这不是静默结构
    # 丢失。其它动作（尤其 set_mark_type）丢 color 仍必须被拦住。
    actions = {
        str(op.get("action") or "")
        for op in ((item or {}).get("ops") or [])
        if isinstance(op, dict)
    }
    color_only_actions = {"set_mark_color", "highlight_category", "set_color_range", "remove_encoding_channel"}
    removes_only_color = all(
        op.get("action") != "remove_encoding_channel" or op.get("channel") == "color"
        for op in ((item or {}).get("ops") or [])
        if isinstance(op, dict)
    )
    if actions and actions.issubset(color_only_actions) and removes_only_color:
        missing_channels = [ch for ch in missing_channels if ch != "color"]
    if not (missing_marks or missing_annotations or missing_channels):
        return None
    return (
        f"结构保护阻止落地：units -{missing_marks}，annotations -{missing_annotations}，"
        f"channels missing={missing_channels}"
    )


def beat4_compile(
    persona: Persona,
    spec: dict,
    facts: dict,
    candidates: list[dict],
    adopted: list[dict],
    verify_list: list[dict],
    context: dict | None = None,
) -> tuple[dict, list, list, dict]:
    started = time.perf_counter()
    modified = spec
    changes: list[dict] = []

    executable, suggested, deferred_persona = _build_execution_plan(
        persona, facts, candidates, adopted
    )
    original_structure = (
        facts.get("original_structure")
        if isinstance(facts.get("original_structure"), dict)
        else structure_baseline(spec)
    )

    assembly_plan = facts.get("component_assembly_plan") if isinstance(facts.get("component_assembly_plan"), dict) else None
    if assembly_plan and isinstance(assembly_plan.get("op"), dict):
        assembled, report = apply_ops_with_effect(modified, [assembly_plan["op"]])
        if report.changed:
            modified = assembled
            # 后续样式规则应保护重组后的受控结构；文本语义由 assembly metadata 留存。
            original_structure = structure_baseline(modified)
            changes.append(_build_change(persona, {
                "rule_id": assembly_plan["rule_id"], "layer": "L2", "strength": "should",
                "src": ["L2:component-assembly"], "story_id": "", "ops": [assembly_plan["op"]],
                "confidence": "high", "rationale": f"组件重组：{assembly_plan.get('quote') or 'pixel canvas layout'}",
                "detail": "reassemble semantic text and restore native axes", "suggested_only": False,
            }, "applied"))

    n_noop = 0
    for item in executable:
        try:
            next_spec, report = apply_ops_with_effect(modified, item.get("ops") or [])
            if report.changed:
                # Persona 建议绝不可为了改一个样式而删掉 brush、series、annotation
                # 或关键编码。用户明确的图型编辑保留其直通权限；其它情况降级建议。
                # 结构风险只来自会替换/删改语义层的动作。字号、尺寸、轴、色彩等
                # 安全样式操作不会被这一道完整性门误拦。
                risky_actions = {"set_mark_type", "remove_encoding_channel", "remove_value_labels"}
                item_actions = {
                    str(op.get("action") or "")
                    for op in (item.get("ops") or [])
                    if isinstance(op, dict)
                }
                loss = (
                    None
                    if item.get("layer") == "user" or not (item_actions & risky_actions)
                    else _structure_loss_detail(original_structure, next_spec, item)
                )
                if loss:
                    n_noop += 1
                    item = {
                        **item,
                        "rationale": f"{item.get('rationale') or ''}（{loss}）".strip(),
                    }
                    changes.append(_build_change(persona, item, "suggested"))
                    continue
                modified = next_spec
                changes.append(_build_change(persona, item, "applied"))
            else:
                n_noop += 1
                note = "未能写入 spec（无落点或已是目标态）"
                if report.noop_actions:
                    note += f"；noop={','.join(report.noop_actions)}"
                item = {
                    **item,
                    "rationale": f"{item.get('rationale') or ''}（{note}）".strip(),
                }
                changes.append(_build_change(persona, item, "suggested"))
        except Exception as exc:  # noqa: BLE001 — 单条 op 失败降级为建议，不拖垮整体
            item = {
                **item,
                "rationale": f"{item.get('rationale', '')}（编译失败降级为建议：{exc}）".strip("（"),
            }
            changes.append(_build_change(persona, item, "suggested"))

    for item in suggested:
        changes.append(_build_change(persona, item, "suggested"))

    # L1 不变量核验：编译后重跑全部程序化检测器
    invariants = run_invariants(persona, modified, context)
    for v in verify_list:
        inv = next((i for i in invariants if i["rule_id"] == v["rule_id"]), None)
        if inv is not None:
            inv["initially_violated"] = v["violated"]
            inv["resolved_by_compile"] = v["violated"] and inv["ok"]

    # Decision IR 合规：落地后重抽 facts，核对拍1 coloring_mode 是否落实
    coloring_ok = None
    mode = str(facts.get("coloring_mode") or "").strip().lower()
    if mode in COLORING_MODES:
        try:
            facts_after = extract_facts(modified, context)
            coloring_ok = _coloring_mode_satisfied(persona, facts_after, mode)
            invariants.append(
                {
                    "rule_id": "d-coloring-mode",
                    "ok": coloring_ok,
                    "detail": (
                        f"coloring_mode={mode} "
                        + ("落实" if coloring_ok else "未落实（决策与落地不一致）")
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            invariants.append(
                {
                    "rule_id": "d-coloring-mode",
                    "ok": False,
                    "detail": f"coloring_mode 校验失败：{exc}",
                }
            )

    # 修改后重新运行 Chart Audit IR：只对本轮确实触及轴/标签的动作记录效果，
    # 不把未被 persona 选中的问题误报成失败。
    try:
        facts_after = extract_facts(modified, context)
        before_audit = facts.get("chart_audit") if isinstance(facts.get("chart_audit"), dict) else {}
        after_audit = facts_after.get("chart_audit") if isinstance(facts_after.get("chart_audit"), dict) else {}
        touched_layout = any(
            op.get("action") in {"set_axis", "thin_axis_labels", "set_font_sizes", "set_text_style"}
            for item in changes for op in (item.get("ops") or []) if isinstance(op, dict)
        )
        before_axes = before_audit.get("axes") if isinstance(before_audit.get("axes"), dict) else {}
        after_axes = after_audit.get("axes") if isinstance(after_audit.get("axes"), dict) else {}
        if touched_layout and before_axes.get("x_dense"):
            resolved = not bool(after_axes.get("x_dense"))
            invariants.append({
                "rule_id": "audit-x-label-density",
                "ok": resolved,
                "detail": "修改后 x 轴标签密度已改善" if resolved else "修改后 x 轴仍然拥挤，建议降级或继续调整",
            })
    except Exception as exc:  # noqa: BLE001
        invariants.append({"rule_id": "audit-post-compile", "ok": False, "detail": f"图表审计复核失败：{exc}"})

    # 原图结构保留审计：编译不得静默丢失 series、annotation 或关键 encoding。
    try:
        original = facts.get("original_structure") if isinstance(facts.get("original_structure"), dict) else {}
        final = structure_baseline(modified)
        missing_marks = max(0, int(original.get("unit_count") or 0) - int(final.get("unit_count") or 0))
        missing_annotations = max(0, int(original.get("annotation_count") or 0) - int(final.get("annotation_count") or 0))
        missing_channels = sorted(set(original.get("encoding_channels") or []) - set(final.get("encoding_channels") or []))
        if missing_marks or missing_annotations or missing_channels:
            invariants.append({
                "rule_id": "preserve-original-structure",
                "ok": False,
                "detail": (
                    f"原图结构被削减：units -{missing_marks}，annotations -{missing_annotations}，"
                    f"channels missing={missing_channels}"
                ),
            })
        else:
            invariants.append({"rule_id": "preserve-original-structure", "ok": True, "detail": "原图结构元素均保留"})
    except Exception as exc:  # noqa: BLE001
        invariants.append({"rule_id": "preserve-original-structure", "ok": False, "detail": f"结构保留审计失败：{exc}"})

    n_applied = sum(1 for c in changes if c["status"] == "applied")
    n_deferred = len(deferred_persona)
    ok_all = all(i["ok"] for i in invariants) if invariants else True
    summary = (
        f"编译 {n_applied} 项修改"
        + (f"（无 diff 缓议 {n_noop} 项）" if n_noop else "")
        + (f"（用户优先，缓议机构冲突 {n_deferred} 项）" if n_deferred else "")
        + f"；L1 不变量核验{'通过' if ok_all else '存在未解决项'}（{len(invariants)} 项）"
    )
    if coloring_ok is False:
        summary += f"；配色原则 {mode} 未落实"
    trace = _trace(
        4,
        "fast",
        "编译执行与校验",
        started,
        summary,
        applied=[c["rule_id"] for c in changes if c["status"] == "applied"],
        noop_suggested=n_noop,
        user_priority_deferred=[d.get("rule_id") for d in deferred_persona],
        coloring_mode_ok=coloring_ok,
    )
    return modified, changes, invariants, trace
