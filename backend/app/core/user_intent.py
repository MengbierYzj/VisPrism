"""用户自然语言意图理解：归类 → 在三层指南与 action space 内落地。

kind:
- communication: 传播趋向（强调/意图）→ 回填 slots，驱动既有 L2
- edit: 明确改组件 → 受控 ops，优先 persona 令牌接地；冲突 L1 never 则拒绝
- mixed: 拆成子项
- other: 仅留痕
"""
from __future__ import annotations

import re
from typing import Any

from .actions import apply_ops
from .detectors import detect_rule
from .specfacts import extract_facts

EXECUTABLE_MARKS = frozenset(
    {
        "arc",
        "area",
        "bar",
        "circle",
        "line",
        "point",
        "rect",
        "rule",
        "square",
        "text",
        "tick",
        "trail",
    }
)

_CHART_ALIAS_PATTERNS: list[tuple[re.Pattern[str], str, str | None]] = [
    (re.compile(r"simple\s*bars?|grouped\s*bars?|柱状图|条形图"), "bar", None),
    (re.compile(r"\bbars?\b"), "bar", None),
    (re.compile(r"line\s*charts?|\blines?\b|折线(?:图)?"), "line", None),
    (re.compile(r"\bareas?\b|面积图"), "area", None),
    (re.compile(r"scatter\s*plots?|scatterplots?|散点图"), "point", None),
    (re.compile(r"\bpoints?\b"), "point", None),
    (re.compile(r"\bpie\b|饼图"), "pie", "pie"),
    (re.compile(r"\bdonuts?\b|环图"), "arc", None),
    (re.compile(r"heat\s*maps?|heatmaps?|热力(?:图)?"), "rect", None),
]

_SOFT_CHARTS = re.compile(
    r"floating\s*bars?|lollipops?|bullet|meter|gauge|treemap|dumbbell|哑铃",
    re.I,
)

_EDIT_HINT = re.compile(
    r"(?:adjust|change|convert|switch|make|set|use|turn|"
    r"改成|改为|调整为|调整成|换成|变成|改用|使用)",
    re.I,
)

_COMM_HINT = re.compile(
    r"(?:highlight|emphasiz|focus|notice|remember|show\s+the\s+gap|huge\s+gap|"
    r"强调|突出|关注|记住|理解|差距|对比|趋势|传播)",
    re.I,
)

_COLOR_HINT = re.compile(
    r"(?:brand\s*colou?r|primary\s*colou?r|house\s*colou?r|主色|品牌色|机构色|用蓝色|用橙色)",
    re.I,
)

_TITLE_HINT = re.compile(r"(?:title|标题).{0,20}(?:left|左对齐|sentence\s*case)", re.I)

_LEGEND_HINT = re.compile(r"(?:legend|图例).{0,24}(?:top|bottom|left|right|上|下|左|右|去掉标题)", re.I)

ALLOWED_INTENTS = frozenset(
    {"comparison", "trend", "composition", "distribution", "correlation", "part-to-whole"}
)


def _normalize(goal: str) -> str:
    return re.sub(r"\s+", " ", goal.strip())


def _match_chart(text: str) -> tuple[str, str | None, str] | None:
    low = text.lower()
    for pattern, chart, pie_sem in _CHART_ALIAS_PATTERNS:
        m = pattern.search(low)
        if m:
            return chart, pie_sem, m.group(0)
    return None


def _resolve_emphasis_from_goal(goal: str, facts: dict) -> str | None:
    cats = facts.get("categories") or []
    if not isinstance(cats, list):
        return None
    low = goal.lower()
    for c in cats:
        if c is None:
            continue
        name = str(c)
        if name.lower() in low or name in goal:
            return name
    if re.search(r"(?:max|largest|highest|最大|最高|峰值)", goal, re.I):
        maxc = facts.get("max_category") or {}
        if isinstance(maxc, dict) and maxc.get("name") is not None:
            return str(maxc["name"])
    if re.search(r"(?:gap|差距|对比|highlight|emphasiz|突出|强调)", goal, re.I):
        maxc = facts.get("max_category") or {}
        if isinstance(maxc, dict) and maxc.get("name") is not None:
            return str(maxc["name"])
    return None


def _intent_hint_from_goal(goal: str) -> str | None:
    low = goal.lower()
    mapping = [
        (r"trend|over\s+time|趋势|随时间", "trend"),
        (r"compar|差距|对比|versus|vs\b", "comparison"),
        (r"part\s*to\s*whole|占比|构成|composition|share", "composition"),
        (r"correlat|相关", "correlation"),
        (r"distribut|分布", "distribution"),
    ]
    for pat, intent in mapping:
        if re.search(pat, low):
            return intent
    return None


def mock_analyze_goal(goal: str | None, facts: dict | None = None) -> dict[str, Any]:
    """确定性意图分析（mock / live 降级）。"""
    facts = facts or {}
    if not goal or not str(goal).strip():
        return {"kind": "other", "items": [], "summary": ""}
    text = _normalize(str(goal))
    has_edit = bool(_EDIT_HINT.search(text))
    has_comm = bool(_COMM_HINT.search(text))
    chart_hit = _match_chart(text)
    soft = _SOFT_CHARTS.search(text)
    color_hit = _COLOR_HINT.search(text)
    title_hit = _TITLE_HINT.search(text)
    legend_hit = _LEGEND_HINT.search(text)
    edit_signal = has_edit and (chart_hit or soft or color_hit or title_hit or legend_hit)
    # 短句几乎只有图型名也算 edit
    if chart_hit and not has_comm and len(text) < 40:
        edit_signal = True

    items: list[dict[str, Any]] = []

    if has_comm or (not edit_signal and has_comm):
        emph = _resolve_emphasis_from_goal(text, facts)
        ih = _intent_hint_from_goal(text)
        # 强调与传播意图拆成多条，便于各自进入 design decisions
        if emph:
            items.append(
                {
                    "kind": "communication",
                    "focus": "emphasis",
                    "slots": {"emphasis_target": emph},
                    "grounding": "persona_rule",
                    "ops": [],
                    "suggested_only": True,
                    "rationale": f"用户要求强调「{emph}」，交由机构 L2 高亮等规则在指南内响应",
                }
            )
        if ih:
            items.append(
                {
                    "kind": "communication",
                    "focus": "intent",
                    "slots": {"intent": ih},
                    "grounding": "persona_rule",
                    "ops": [],
                    "suggested_only": True,
                    "rationale": f"用户传播意图倾向「{ih}」，用于匹配机构 L2 when.intent",
                }
            )
        if not emph and not ih:
            items.append(
                {
                    "kind": "communication",
                    "focus": "intent",
                    "slots": {},
                    "grounding": "persona_rule",
                    "ops": [],
                    "suggested_only": True,
                    "rationale": "用户表达传播趋向，交由机构 L2 规则在指南内响应",
                }
            )

    if edit_signal or (chart_hit and has_edit):
        if soft and has_edit:
            soft_span = soft.span()
            skip_chart = False
            if chart_hit:
                # floating bar 内的 bar 子串不触发可执行 bar
                low = text.lower()
                for pattern, _c, _p in _CHART_ALIAS_PATTERNS:
                    m = pattern.search(low)
                    if m and m.start() >= soft_span[0] and m.end() <= soft_span[1]:
                        skip_chart = True
                        break
            items.append(
                {
                    "kind": "edit",
                    "focus": "chart.type",
                    "slots": {"chart_type": soft.group(0).lower()},
                    "grounding": "none",
                    "ops": [],
                    "suggested_only": True,
                    "rationale": f"识别到图型「{soft.group(0)}」，超出受控 mark 自动迁移",
                }
            )
            if skip_chart:
                chart_hit = None
        if chart_hit:
            chart, pie_sem, matched = chart_hit
            mark_type = "arc" if pie_sem == "pie" else chart
            if mark_type in EXECUTABLE_MARKS or pie_sem == "pie":
                op: dict[str, Any] = {
                    "action": "set_mark_type",
                    "mark_type": mark_type if pie_sem != "pie" else "arc",
                    "rebuild_unit": True,
                    "category_field": facts.get("category_field"),
                    "value_field": facts.get("value_field"),
                    "category_channel": facts.get("category_channel") or "y",
                }
                if pie_sem == "pie":
                    op["chart_type"] = "pie"
                items.append(
                    {
                        "kind": "edit",
                        "focus": "chart.type",
                        "slots": {"chart_type": chart, "match": matched},
                        "grounding": "action_space",
                        "ops": [op],
                        "suggested_only": False,
                        "rationale": f"用户明确要求改为 {matched}（受控 mark）",
                    }
                )
        if color_hit:
            items.append(
                {
                    "kind": "edit",
                    "focus": "color",
                    "slots": {"color_role": "primary"},
                    "grounding": "persona_token",
                    "ops": [],  # 编译阶段接地
                    "suggested_only": False,
                    "rationale": "用户要求使用机构主色/品牌色",
                }
            )
        if title_hit:
            items.append(
                {
                    "kind": "edit",
                    "focus": "title",
                    "slots": {"anchor": "start"},
                    "grounding": "action_space",
                    "ops": [{"action": "set_title_anchor", "anchor": "start"}],
                    "suggested_only": False,
                    "rationale": "用户要求标题左对齐类调整",
                }
            )
        if legend_hit:
            orient = "top"
            low = text.lower()
            if "bottom" in low or "下" in text:
                orient = "bottom"
            elif "left" in low or "左" in text:
                orient = "left"
            elif "right" in low or "右" in text:
                orient = "right"
            op_l: dict[str, Any] = {"action": "set_legend", "orient": orient}
            if re.search(r"no\s*title|去掉标题|无标题", text, re.I):
                op_l["title"] = None
            items.append(
                {
                    "kind": "edit",
                    "focus": "legend",
                    "slots": {"orient": orient},
                    "grounding": "action_space",
                    "ops": [op_l],
                    "suggested_only": False,
                    "rationale": f"用户要求调整图例（orient={orient}）",
                }
            )

    if not items:
        return {
            "kind": "other",
            "items": [
                {
                    "kind": "other",
                    "focus": "none",
                    "slots": {},
                    "grounding": "none",
                    "ops": [],
                    "suggested_only": True,
                    "rationale": "未能归类为传播强调或可执行改件",
                }
            ],
            "summary": "other",
        }

    kinds = {i["kind"] for i in items}
    if "communication" in kinds and "edit" in kinds:
        top = "mixed"
    elif "edit" in kinds:
        top = "edit"
    elif "communication" in kinds:
        top = "communication"
    else:
        top = "other"
    return {"kind": top, "items": items, "summary": top}


def normalize_live_analysis(raw: Any, facts: dict) -> dict[str, Any]:
    """校验 live LLM 分析结果；非法字段丢弃，禁止自由 hex。"""
    if not isinstance(raw, dict):
        return mock_analyze_goal(facts.get("communication_goal"), facts)
    items_in = raw.get("items") if isinstance(raw.get("items"), list) else []
    items: list[dict[str, Any]] = []
    for it in items_in:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "other")
        if kind not in ("communication", "edit", "other"):
            kind = "other"
        focus = str(it.get("focus") or "none")
        slots = it.get("slots") if isinstance(it.get("slots"), dict) else {}
        # 清洗 slots：intent / emphasis 白名单；禁止 hex 色值
        clean_slots: dict[str, Any] = {}
        if "intent" in slots and str(slots["intent"]) in ALLOWED_INTENTS:
            clean_slots["intent"] = str(slots["intent"])
        if "emphasis_target" in slots and slots["emphasis_target"]:
            clean_slots["emphasis_target"] = str(slots["emphasis_target"])
        if "chart_type" in slots:
            clean_slots["chart_type"] = str(slots["chart_type"]).lower()
        if "color_role" in slots and str(slots["color_role"]) in ("primary", "accent", "canvas"):
            clean_slots["color_role"] = str(slots["color_role"])
        if "anchor" in slots and str(slots["anchor"]) in ("start", "middle", "end"):
            clean_slots["anchor"] = str(slots["anchor"])
        if "orient" in slots and str(slots["orient"]) in ("top", "bottom", "left", "right"):
            clean_slots["orient"] = str(slots["orient"])
        items.append(
            {
                "kind": kind,
                "focus": focus,
                "slots": clean_slots,
                "grounding": str(it.get("grounding") or "none"),
                "ops": [],
                "suggested_only": True,
                "rationale": str(it.get("rationale") or ""),
            }
        )
    if not items:
        return mock_analyze_goal(facts.get("communication_goal"), facts)
    kinds = {i["kind"] for i in items}
    if "communication" in kinds and "edit" in kinds:
        top = "mixed"
    elif "edit" in kinds:
        top = "edit"
    elif "communication" in kinds:
        top = "communication"
    else:
        top = "other"
    return {"kind": top, "items": items, "summary": str(raw.get("summary") or top)}


def _ground_color_op(persona, item: dict) -> dict | None:
    role = (item.get("slots") or {}).get("color_role") or "primary"
    paths = {
        "primary": ["color.primary", "color.bbc-blue", "palette.categorical"],
        "accent": ["color.accent", "color.orange", "color.emphasis"],
        "canvas": ["color.canvas.white", "color.canvas"],
    }
    for path in paths.get(str(role), paths["primary"]):
        color = persona.resolve_color(f"{{{path}}}") if hasattr(persona, "resolve_color") else None
        if not color:
            # 尝试列表首色
            cl = persona.resolve_color_list(f"{{{path}}}") if hasattr(persona, "resolve_color_list") else []
            if cl:
                color = cl[0]
        if isinstance(color, str) and color.startswith("#"):
            return {
                **item,
                "ops": [{"action": "set_mark_color", "color": color}],
                "grounding": "persona_token",
                "suggested_only": False,
                "rationale": item.get("rationale") or f"使用机构令牌 {path}={color}",
            }
    return {
        **item,
        "ops": [],
        "suggested_only": True,
        "grounding": "none",
        "rationale": (item.get("rationale") or "") + "（无可用机构色令牌，仅建议）",
    }


def _ground_chart_op(item: dict, facts: dict) -> dict:
    slots = item.get("slots") or {}
    chart = str(slots.get("chart_type") or "").lower()
    pie_sem = "pie" if chart == "pie" else None
    mark_type = {"pie": "arc"}.get(chart, chart)
    if mark_type not in EXECUTABLE_MARKS and pie_sem != "pie":
        # 再跑别名
        hit = _match_chart(chart) or _match_chart(str(slots.get("match") or ""))
        if not hit:
            return {
                **item,
                "ops": [],
                "suggested_only": True,
                "grounding": "none",
                "rationale": item.get("rationale") or f"图型 {chart} 不可自动执行",
            }
        chart, pie_sem, _m = hit
        mark_type = "arc" if pie_sem == "pie" else chart
    op: dict[str, Any] = {
        "action": "set_mark_type",
        "mark_type": "arc" if pie_sem == "pie" else mark_type,
        "rebuild_unit": True,
        "category_field": facts.get("category_field"),
        "value_field": facts.get("value_field"),
        "category_channel": facts.get("category_channel") or "y",
    }
    if pie_sem == "pie":
        op["chart_type"] = "pie"
    return {
        **item,
        "ops": [op],
        "suggested_only": False,
        "grounding": "action_space",
        "rationale": item.get("rationale") or f"用户明确改型 → {mark_type}",
    }


def compile_intent_items(persona, analysis: dict, facts: dict) -> list[dict]:
    """将分析项编译为带 ops 的条目（颜色接地 persona 令牌）。"""
    out: list[dict] = []
    for item in analysis.get("items") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        focus = item.get("focus")
        if kind == "edit" and focus == "color" and not item.get("ops"):
            out.append(_ground_color_op(persona, item))
        elif kind == "edit" and focus == "chart.type" and not item.get("ops"):
            out.append(_ground_chart_op(item, facts))
        else:
            out.append(dict(item))
    return out


def l1_never_conflicts(persona, spec: dict, ops: list[dict], facts: dict) -> list[str]:
    """若用户 ops 导致 L1 never 规则违规，返回冲突 rule id。"""
    if not ops:
        return []
    try:
        modified = apply_ops(spec, ops)
    except Exception:  # noqa: BLE001
        return ["apply-failed"]
    ctx = {}
    if facts.get("communication_goal"):
        ctx["communication_goal"] = facts["communication_goal"]
    after = extract_facts(modified, ctx)
    for k in ("intent", "emphasis_target", "data_topic", "communication_goal"):
        if facts.get(k) is not None:
            after[k] = facts[k]
    conflicts = []
    for rule in getattr(persona, "rules", []) or []:
        if getattr(rule, "strength", "") != "never":
            continue
        if getattr(rule, "check", "") != "programmatic":
            continue
        det = detect_rule(persona, rule, modified, after)
        if det and det.applicable and det.violated:
            conflicts.append(rule.id)
    return conflicts


def apply_communication_slots(facts: dict, analysis: dict) -> None:
    """communication/mixed：回填 emphasis_target / intent。"""
    for item in analysis.get("items") or []:
        if item.get("kind") != "communication":
            continue
        slots = item.get("slots") or {}
        if slots.get("emphasis_target"):
            facts["emphasis_target"] = slots["emphasis_target"]
        if slots.get("intent") and slots["intent"] in ALLOWED_INTENTS:
            # part-to-whole 与 composition 对齐
            intent = slots["intent"]
            if intent == "part-to-whole":
                intent = "composition"
            facts["intent"] = intent


def analysis_to_pipeline_items(
    persona, analysis: dict, spec: dict, facts: dict
) -> tuple[list[dict], list[dict]]:
    """返回 (pipeline_candidates, rejected_user_items)。

    communication 与 edit 均可进入 changes：传播类无 ops、suggested，用于展示意图如何
    调制机构规则；改件类带 ops 优先执行。同一 goal 可产生多条不同 focus。
    """
    compiled = compile_intent_items(persona, analysis, facts)
    candidates: list[dict] = []
    rejected: list[dict] = []
    idx = 0
    for item in compiled:
        kind = item.get("kind")
        if kind == "other":
            continue
        if kind not in ("communication", "edit"):
            continue
        idx += 1
        focus = str(item.get("focus") or kind).replace("_", "-")
        rid = f"u-{focus}" if idx == 1 else f"u-{focus}-{idx}"
        ops = list(item.get("ops") or [])
        if kind == "communication":
            slots = item.get("slots") or {}
            slot_bits = []
            if slots.get("emphasis_target"):
                slot_bits.append(f"emphasis={slots['emphasis_target']}")
            if slots.get("intent"):
                slot_bits.append(f"intent={slots['intent']}")
            detail = item.get("rationale") or "user communication"
            if slot_bits:
                detail = f"{detail}（{'; '.join(slot_bits)}）"
            candidates.append(
                {
                    "layer": "user",
                    "rule_id": rid,
                    "rule_text": detail,
                    "strength": "should",
                    "story_id": "",
                    "src": ["user:communication_goal"],
                    "derived": False,
                    "ops": [],
                    "confidence": "medium",
                    "rationale": detail,
                    "suggested_only": True,
                    "detail": detail,
                    "focus": item.get("focus"),
                    "kind": kind,
                    "grounding": item.get("grounding") or "persona_rule",
                    "label": f"User {focus}",
                }
            )
            continue
        # edit
        if ops:
            conflicts = l1_never_conflicts(persona, spec, ops, facts)
            if conflicts:
                rejected.append(
                    {
                        "rule_id": rid,
                        "layer": "user",
                        "label": f"User {focus}",
                        "reason": f"与 L1 never 冲突：{', '.join(conflicts)}",
                        "src": ["user:communication_goal"],
                        "story_id": "",
                    }
                )
                continue
        suggested_only = bool(item.get("suggested_only") or not ops)
        candidates.append(
            {
                "layer": "user",
                "rule_id": rid,
                "rule_text": item.get("rationale") or f"user {kind}/{focus}",
                "strength": "must" if ops and not suggested_only else "should",
                "story_id": "",
                "src": ["user:communication_goal"],
                "derived": False,
                "ops": ops,
                "confidence": "high" if ops and not suggested_only else "medium",
                "rationale": item.get("rationale") or "",
                "suggested_only": suggested_only,
                "detail": item.get("rationale") or "",
                "focus": item.get("focus"),
                "kind": kind,
                "grounding": item.get("grounding"),
                "label": f"User {focus}",
            }
        )
    return candidates, rejected


def attach_user_intent(persona, spec: dict, facts: dict, analysis: dict | None = None) -> dict:
    """就地写入 facts 分析与 pipeline items；返回 analysis。"""
    if analysis is None:
        analysis = mock_analyze_goal(facts.get("communication_goal"), facts)
    apply_communication_slots(facts, analysis)
    facts["user_intent_analysis"] = analysis
    items, rejected = analysis_to_pipeline_items(persona, analysis, spec, facts)
    facts["user_constraint_items"] = items
    facts["user_intent_rejected"] = rejected
    return analysis


INTENT_ANALYZE_SYSTEM = (
    "你是可视化顾问的意图分析器。阅读用户自然语言目标与图表事实，"
    "归类为 communication（传播强调/意图）、edit（明确改组件）、other。"
    "可同时输出多条 items；不得发明 hex 颜色或未列出的 action。"
    "slots 仅允许：intent(comparison|trend|composition|distribution|correlation)、"
    "emphasis_target(类别名)、chart_type、color_role(primary|accent|canvas)、"
    "anchor(start|middle|end)、orient(top|bottom|left|right)。"
    '只输出 JSON：{"kind":"communication|edit|mixed|other","summary":"一句中文",'
    '"items":[{"kind":"communication|edit|other","focus":"emphasis|intent|chart.type|color|title|legend|none",'
    '"slots":{},"grounding":"persona_rule|persona_token|action_space|none","rationale":"一句中文"}]}'
)
# 机构专家设定版见 advisor_briefing.intent_analyze_system(briefing)
