"""L1 快道检测器与不变量核验。

检测器按 rule id 注册（persona 编译期绑定到可执行检查）；check:llm 或无检
测器的规则由拍2列入升级清单交慢道——"判不了的升级"。verify_only 检测器
只核验不产出 ops（如无障碍对比度），编译后重跑作为 L1 不变量核验。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .actions import apply_ops, compile_then
from .specfacts import extract_facts


@dataclass
class Detection:
    rule_id: str
    violated: bool = False
    applicable: bool = True
    verify_only: bool = False
    ops: list = field(default_factory=list)
    detail: str = ""


DetectorFn = Callable[..., Detection]
DETECTORS: dict[str, DetectorFn] = {}


def register(rule_id: str):
    def deco(fn: DetectorFn):
        DETECTORS[rule_id] = fn
        return fn

    return deco


def detect_rule(persona, rule, spec: dict, facts: dict) -> Detection | None:
    fn = DETECTORS.get(rule.id)
    if fn is not None:
        return fn(persona, spec, facts)

    # Parser Agent 可为自定义 L1 规则附带受控 then。无需预注册 rule id，
    # 只要能编译为现有 ops，就可用“应用前后是否变化”作为通用快道检测。
    then = rule.raw.get("then") if isinstance(rule.raw, dict) else None
    if rule.check == "programmatic" and then:
        compiled = compile_then(persona, then, facts)
        ops = compiled.get("ops") or []
        if ops and not compiled.get("needs"):
            modified = apply_ops(spec, ops)
            violated = modified != spec
            return Detection(
                rule.id,
                violated=violated,
                ops=ops if violated else [],
                detail="自定义结构化规则可执行" if violated else "自定义结构化规则已满足",
            )
    return None


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[float, float, float] | None:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) < 6:
        return None
    try:
        return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def relative_luminance(hex_color: str) -> float | None:
    rgb = _hex_to_rgb(hex_color)
    if rgb is None:
        return None
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(c1: str, c2: str) -> float | None:
    l1, l2 = relative_luminance(c1), relative_luminance(c2)
    if l1 is None or l2 is None:
        return None
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _parse_pt(v) -> int | None:
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        digits = "".join(ch for ch in v if ch.isdigit())
        return int(digits) if digits else None
    return None


def _recolor_primary_ops(persona, facts: dict, primary: str, secondary: list[str]) -> list[dict]:
    """把主序列颜色改为机构主色的通用 ops 组合。

    尊重拍1 coloring_mode：categorical/paired 时保留类别区分并写入色板 range，
    避免「机构色板合规」把组成图收成整图一色。
    """
    ops: list[dict] = []
    mode = str(facts.get("coloring_mode") or "uniform")
    house: list[str] = []
    if hasattr(persona, "resolve_color_list"):
        house = [c for c in (persona.resolve_color_list("{palette.categorical}") or []) if isinstance(c, str)]
    if not house:
        house = [c for c in ([primary] + list(secondary or [])) if isinstance(c, str)]
    ordered = [primary] + [c for c in house if c != primary]

    if mode in ("categorical", "paired") and (
        facts.get("color_field") or facts.get("per_category_coloring") or facts.get("category_field")
    ):
        try:
            n = int(facts.get("category_count") or 0) if facts.get("per_category_coloring") else int(
                facts.get("series_count") or 0
            )
        except (TypeError, ValueError):
            n = 0
        if mode == "paired":
            n = max(n, 2)
        else:
            n = max(n, 3)
        ops.append({"action": "set_color_range", "colors": ordered[: max(n, 2)]})
        return ops

    if mode == "highlight" or (
        facts.get("literal_color_encoding") and facts.get("accent_color")
    ):
        op = {"action": "set_mark_color", "color": primary}
        accent = None
        if secondary:
            accent = secondary[0]
        elif len(ordered) >= 2:
            accent = ordered[1]
        if accent and accent != primary:
            op["accent_color"] = accent
        ops.append(op)
        return ops

    if facts.get("per_category_coloring"):
        # 单序列按类别着色且模式为 uniform → 收敛为统一主色
        ops.append({"action": "remove_encoding_channel", "channel": "color"})
        ops.append({"action": "set_mark_color", "color": primary})
    elif facts.get("color_field"):
        n = facts.get("series_count") or 2
        palette = ordered[: max(int(n) if n else 2, 2)]
        ops.append({"action": "set_color_range", "colors": palette})
    else:
        op: dict = {"action": "set_mark_color", "color": primary}
        # 原图用 value+condition 强调某类时，用辅色改写 condition
        if facts.get("literal_color_encoding") and facts.get("accent_color") and secondary:
            op["accent_color"] = secondary[0]
        ops.append(op)
    return ops


# ---------------------------------------------------------------------------
# BBC L1 检测器
# ---------------------------------------------------------------------------

@register("s-type-hierarchy")
def det_type_hierarchy(persona, spec, facts) -> Detection:
    from .actions import persona_font_family

    sizes_tok = persona.token_index().get("font.size") or {}
    targets = {
        "title": _parse_pt(sizes_tok.get("title")) or 28,
        "subtitle": _parse_pt(sizes_tok.get("subtitle")) or 22,
        "body": _parse_pt(sizes_tok.get("body")) or 18,
        "caption": _parse_pt(sizes_tok.get("caption")) or 14,
    }
    fs = facts.get("font_sizes") or {}
    family = persona_font_family(persona)
    size_violated = fs.get("title") != targets["title"] or fs.get("axis_label") != targets["body"]
    # 根 title / config 字体与机构令牌不一致也算违规（避免 Arial 原图「看起来没改」）
    title_font = None
    title_raw = spec.get("title")
    if isinstance(title_raw, dict) and isinstance(title_raw.get("font"), str):
        title_font = title_raw["font"]
    cfg_font = (spec.get("config") or {}).get("font") if isinstance(spec.get("config"), dict) else None
    fam_violated = bool(family) and (
        (isinstance(title_font, str) and family.split(",")[0].strip().lower() not in title_font.lower())
        or (
            not title_font
            and isinstance(cfg_font, str)
            and family.split(",")[0].strip().lower() not in cfg_font.lower()
        )
        or (not title_font and not cfg_font)
    )
    violated = size_violated or fam_violated
    ops = []
    if violated:
        if family:
            ops.append({"action": "set_font", "family": family})
        ops.append(
            {
                "action": "set_font_sizes",
                "title": targets["title"],
                "subtitle": targets["subtitle"],
                "axis_label": targets["body"],
                "axis_title": targets["body"],
                "legend_label": targets["body"],
            }
        )
    return Detection(
        rule_id="s-type-hierarchy",
        violated=violated,
        ops=ops,
        detail=f"当前字号 {fs}，目标层级 {targets}；family={family}",
    )


@register("s-text-left")
def det_text_left(persona, spec, facts) -> Detection:
    violated = facts.get("title_anchor") != "start"
    ops = [{"action": "set_title_anchor", "anchor": "start"}] if violated else []
    return Detection("s-text-left", violated=violated, ops=ops, detail=f"title_anchor={facts.get('title_anchor')}")


@register("s-source")
def det_source(persona, spec, facts) -> Detection:
    violated = not facts.get("has_source_note")
    ops = []
    if violated:
        caption = _parse_pt((persona.token_index().get("font.size") or {}).get("caption")) or 14
        gray = persona.resolve_color("bbc-gray") or "#333333"
        provider = facts.get("source_provider") or "—"
        ops.append(
            {
                "action": "set_source_note",
                "text": f"Source: {provider}",
                "font_size": caption,
                "color": gray,
                "note": "Add a source attribution line (caption size).",
            }
        )
    return Detection("s-source", violated=violated, ops=ops, detail="缺少来源署名" if violated else "已有来源署名")


@register("s-grid-horizontal")
def det_grid_horizontal(persona, spec, facts) -> Detection:
    grid_color = persona.resolve_color("grid") or "#cbcbcb"
    violated = (not facts.get("grid_y")) or facts.get("grid_y_color") != grid_color
    ops = []
    if violated:
        ops.append(
            {
                "action": "merge_config",
                "config": {"axisY": {"grid": True, "gridColor": grid_color}},
                "note": f"Keep horizontal gridlines only, in {grid_color}.",
            }
        )
    return Detection("s-grid-horizontal", violated=violated, ops=ops, detail=f"grid_y={facts.get('grid_y')} color={facts.get('grid_y_color')}")


@register("s-grid-vertical")
def det_grid_vertical(persona, spec, facts) -> Detection:
    violated = bool(facts.get("grid_x"))
    ops = []
    if violated:
        ops.append(
            {
                "action": "merge_config",
                "config": {"axisX": {"grid": False}},
                "note": "Remove vertical gridlines.",
            }
        )
    return Detection("s-grid-vertical", violated=violated, ops=ops, detail=f"grid_x={facts.get('grid_x')}")


@register("s-legend-top")
def det_legend_top(persona, spec, facts) -> Detection:
    if not facts.get("has_legend"):
        return Detection("s-legend-top", applicable=False, detail="无图例，不适用")
    violated = facts.get("legend_orient") != "top"
    ops = [{"action": "set_legend", "orient": "top"}] if violated else []
    return Detection("s-legend-top", violated=violated, ops=ops, detail=f"legend_orient={facts.get('legend_orient')}")


@register("s-legend-notitle")
def det_legend_notitle(persona, spec, facts) -> Detection:
    if not facts.get("has_legend"):
        return Detection("s-legend-notitle", applicable=False, detail="无图例，不适用")
    violated = facts.get("legend_title") is not None  # None 表示已显式去除
    ops = [{"action": "set_legend", "title": None}] if violated else []
    return Detection("s-legend-notitle", violated=violated, ops=ops, detail=f"legend_title={facts.get('legend_title')}")


@register("s-accessibility")
def det_accessibility(persona, spec, facts) -> Detection:
    """verify_only：核验基色对背景对比度 ≥ 3.0（WCAG 非文本图形参考线）。
    强调色不计入——其与基色以色相区分，单独记录在 facts.accent_color。"""
    bg = facts.get("background") or "#ffffff"
    failing = []
    for c in facts.get("colors_effective") or []:
        ratio = contrast_ratio(c, bg)
        if ratio is not None and ratio < 3.0:
            failing.append(f"{c}({ratio:.1f}:1)")
    return Detection(
        "s-accessibility",
        violated=bool(failing),
        verify_only=True,
        detail=("基色对比度不足: " + ", ".join(failing)) if failing else "基色对比度通过（≥3.0:1）",
    )


# ---------------------------------------------------------------------------
# Economist L1 检测器
# ---------------------------------------------------------------------------

@register("s-palette-blues")
def det_palette_blues(persona, spec, facts) -> Detection:
    chicago = [c for c in (persona.resolve_color("chicago-20"), persona.resolve_color("chicago-30")) if c]
    if not chicago:
        return Detection("s-palette-blues", applicable=False, detail="未找到 chicago 令牌")
    primary_now = (facts.get("colors_effective") or [None])[0]
    violated = primary_now not in chicago
    ops = []
    detail = f"当前主色 {primary_now}，机构主色 {chicago[0]}"
    if violated:
        secondary = [c for c in (persona.resolve_color("hong-kong-45"), persona.resolve_color("hong-kong-55")) if c]
        ops = _recolor_primary_ops(persona, facts, chicago[0], secondary)
    else:
        # 主色已在指南色内，但仍可能未落实 coloring_mode 分配原则
        from .beats import _coloring_mode_satisfied, _ops_for_coloring_mode

        mode = str(facts.get("coloring_mode") or "").strip().lower()
        if mode and not _coloring_mode_satisfied(persona, facts, mode):
            violated = True
            ops = _ops_for_coloring_mode(persona, facts, mode)
            detail = f"{detail}；未落实配色原则 coloring_mode={mode}"
    return Detection("s-palette-blues", violated=violated, ops=ops, detail=detail)


@register("s-color-cap")
def det_color_cap(persona, spec, facts) -> Detection:
    count = facts.get("color_count") or 0
    return Detection(
        "s-color-cap",
        violated=count > 6,
        verify_only=True,
        detail=f"用色 {count} 种（上限 6）",
    )


@register("s-type-scale")
def det_type_scale(persona, spec, facts) -> Detection:
    from .actions import persona_font_family

    steps_raw = persona.token_index().get("font.scale.steps") or {}
    steps = sorted({_parse_pt(v) for v in steps_raw.values() if _parse_pt(v)})
    if not steps:
        return Detection("s-type-scale", applicable=False, detail="未找到音阶令牌")

    def snap(v):
        return min(steps, key=lambda s: abs(s - v)) if isinstance(v, (int, float)) else v

    fs = facts.get("font_sizes") or {}
    if not fs:
        return Detection("s-type-scale", applicable=False, detail="无字号事实")
    snapped = {k: snap(v) for k, v in fs.items()}
    offenders = {k: (fs[k], snapped[k]) for k in fs if fs[k] not in steps}
    family = persona_font_family(persona)
    title_font = None
    title_raw = spec.get("title")
    if isinstance(title_raw, dict) and isinstance(title_raw.get("font"), str):
        title_font = title_raw["font"]
    cfg_font = (spec.get("config") or {}).get("font") if isinstance(spec.get("config"), dict) else None
    fam_missing = bool(family) and not (
        (isinstance(title_font, str) and family.split(",")[0].strip().lower() in title_font.lower())
        or (isinstance(cfg_font, str) and family.split(",")[0].strip().lower() in cfg_font.lower())
    )
    violated = bool(offenders) or fam_missing
    ops = []
    if violated:
        if family and fam_missing:
            ops.append({"action": "set_font", "family": family})
        if offenders:
            ops.append(
                {
                    "action": "set_font_sizes",
                    "title": snapped["title"],
                    "subtitle": snapped["subtitle"],
                    "axis_label": snapped["axis_label"],
                    "axis_title": snapped["axis_title"],
                    "legend_label": snapped["legend_label"],
                    "note": f"Snap font sizes to the Major Second scale: {offenders}.",
                }
            )
        elif family and fam_missing:
            # 仅补字体：字号已在音阶上，仍写入当前字号以刷新 title 对象
            ops.append(
                {
                    "action": "set_font_sizes",
                    "title": fs["title"],
                    "subtitle": fs["subtitle"],
                    "axis_label": fs["axis_label"],
                    "axis_title": fs["axis_title"],
                    "legend_label": fs["legend_label"],
                }
            )
    return Detection(
        "s-type-scale",
        violated=violated,
        ops=ops,
        detail=f"越阶字号 {offenders}" if offenders else f"字号在音阶上；family={family}",
    )


@register("s-leading")
def det_leading(persona, spec, facts) -> Detection:
    return Detection("s-leading", applicable=False, detail="行高倍率适用于文本版式，单图 spec 上下文不适用")


# ---------------------------------------------------------------------------
# 自定义 persona 的通用检测器（Parser Agent 合成规则时引用）
# ---------------------------------------------------------------------------

@register("s-house-palette")
def det_house_palette(persona, spec, facts) -> Detection:
    palette = persona.ui.get("palette") or []
    if not palette:
        return Detection("s-house-palette", applicable=False, detail="无机构色板令牌")
    primary_now = (facts.get("colors_effective") or [None])[0]
    violated = primary_now not in palette
    detail = f"当前主色 {primary_now}，机构色板 {palette[:3]}…"
    if violated:
        ops = _recolor_primary_ops(persona, facts, palette[0], palette[1:])
    else:
        # 颜色已在色板内 ≠ 已按指南序列/角色原则分配
        from .beats import _coloring_mode_satisfied, _ops_for_coloring_mode

        mode = str(facts.get("coloring_mode") or "").strip().lower()
        if mode and not _coloring_mode_satisfied(persona, facts, mode):
            violated = True
            ops = _ops_for_coloring_mode(persona, facts, mode)
            detail = f"{detail}；未落实配色原则 coloring_mode={mode}"
        else:
            ops = []
    return Detection("s-house-palette", violated=violated, ops=ops, detail=detail)


# ---------------------------------------------------------------------------
# L1 不变量核验（拍4编译后重跑）
# ---------------------------------------------------------------------------

def run_invariants(persona, modified_spec: dict, context: dict | None = None) -> list[dict]:
    facts_after = extract_facts(modified_spec, context)
    report = []
    for rule in persona.rules:
        if rule.check != "programmatic":
            continue
        det = detect_rule(persona, rule, modified_spec, facts_after)
        if det is None or not det.applicable:
            continue
        report.append({"rule_id": rule.id, "ok": not det.violated, "detail": det.detail})
    return report
