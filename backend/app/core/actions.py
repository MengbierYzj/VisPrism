"""快道动作引擎：语义化的 Vega-Lite spec 操作（令牌直注，不经 LLM 转写）。

op 是可序列化 dict：
- 方案里逐条留痕（每处修改附带其 ops）；
- 用户跨机构采纳后由 Composer 确定性重放（/api/design/apply）。

同时提供 L2 then → ops 的编译器 compile_then。
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .view_geometry import (
    apply_paint_color,
    drawn_grid_units,
    geometry_targets,
    is_source_text,
    primary_paint_targets,
    read_paint_color,
    title_text_units,
    walk_annotated_units,
)

DEFAULT_MARK_COLOR = "#4c78a8"  # vega-lite 默认蓝

# 超出单图 spec 可自动执行范围的目标（版式/多图/开放式图型迁移）→ 只能作为建议。
# chart.type 默认仍受此门约束；compile_then 对 set/override + 受控 mark 放行。
# prefer:chart.type 默认 suggested；VIZGUIDE_PREFER_MODE=apply 时与 set 同权。
# grid.horizontal / grid.vertical 已有 Vega-Lite config 编译器，不应被此前缀门拦截。
NON_CHART_TARGET = re.compile(
    r"^(grid\.(?!horizontal$|vertical$|style$)|line-height|chart\.type|color\.palette)"
)

# 机构/自然语言图型名 → Vega-Lite mark.type（含 IBM Recommend 可落地子集）
CHART_TYPE_MARK_ALIASES = {
    "pie": "arc",
    "donut": "arc",
    "scatter": "point",
    "scatterplot": "point",
    "scattorplot": "point",  # IBM 原文拼写
    "heatmap": "rect",
    "heat map": "rect",
    "histogram": "bar",
    "simple bar": "bar",
    "grouped bar": "bar",
    "stacked bar": "bar",
    "floating bar": "bar",
    "lollipop": "tick",
    "bubble": "point",
    "line": "line",
    "area": "area",
    "stacked area": "area",
    "stream": "area",
    "boxplot": "boxplot",
    "box plot": "boxplot",
    "box-plot": "boxplot",
}
# VL 无原生 mark、本轮仅 suggested 的 IBM 推荐图型（文档/编译 note 用）
NON_EXECUTABLE_CHART_TYPES = frozenset(
    {
        "radar",
        "wordcloud",
        "word cloud",
        "bullet",
        "meter",
        "gauge",
        "tree map",
        "treemap",
        "circle pack",
        "parallel coordinates",
        "alluvial diagram",
        "alluvial",
        "network diagram",
        "network",
        "tree diagram",
        "choropleth map",
        "choropleth",
        "chorpleth map",
        "proportional symbol",
        "propotional symbol",
        "connecting lines",
    }
)
EXECUTABLE_MARKS = frozenset(
    {
        "arc",
        "area",
        "bar",
        "boxplot",
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

# 复合视图键：禁止在其根上凭空创建 mark/encoding（否则 VL 编译读 mark.filled 崩溃）
COMPOSITION_KEYS = ("layer", "hconcat", "vconcat", "concat")
# 标注/来源文字 mark：改色与改图型时默认跳过，只动几何主图
ANNOTATION_MARKS = frozenset({"text"})


def deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _is_composition(node: dict) -> bool:
    return isinstance(node, dict) and any(k in node for k in COMPOSITION_KEYS)


def _mark_type(mark: Any) -> str | None:
    if isinstance(mark, str):
        return mark
    if isinstance(mark, dict):
        t = mark.get("type")
        return t if isinstance(t, str) else None
    return None


def _iter_unit_views(node: Any):
    """深度优先产出带 mark 的 unit 视图（不含仅作容器的 layer/concat 父节点）。"""
    if not isinstance(node, dict):
        return
    if "mark" in node:
        yield node
        return
    for key in COMPOSITION_KEYS:
        kids = node.get(key)
        if isinstance(kids, list):
            for kid in kids:
                yield from _iter_unit_views(kid)
    nested = node.get("spec")
    if isinstance(nested, dict):
        yield from _iter_unit_views(nested)


def _ensure_mark_obj(view: dict) -> dict:
    """将某 unit 视图的 mark 归一化为对象并返回引用。绝不在无 mark 的容器上新建。"""
    mark = view.get("mark")
    if isinstance(mark, str):
        view["mark"] = {"type": mark}
    elif isinstance(mark, dict):
        return mark
    else:
        # 仅允许在已是/将是 unit 的节点上创建；复合根禁止
        if _is_composition(view):
            raise ValueError("不能在 layer/concat 复合视图根上创建 mark")
        view["mark"] = {}
    return view["mark"]


def _mark_targets(spec: dict) -> list[dict]:
    """几何目标：主数据优先，排除自绘网格/标题等 chrome（见 view_geometry）。"""
    targets = geometry_targets(spec, include_secondary=True)
    if targets:
        return targets
    units = list(_iter_unit_views(spec))
    if not units:
        return [] if _is_composition(spec) else [spec]
    geom = [u for u in units if _mark_type(u.get("mark")) not in ANNOTATION_MARKS]
    return geom or units


def _paint_targets(spec: dict) -> list[dict]:
    """改色只打主数据几何，不改网格/箭头/注释框。"""
    targets = primary_paint_targets(spec)
    return targets or _mark_targets(spec)


def _encoding_target(spec: dict) -> dict | None:
    """encoding 相关 op 的落点：优先主几何 unit。"""
    for view in _paint_targets(spec):
        if isinstance(view.get("encoding"), dict):
            return view
    for view in _mark_targets(spec):
        if _mark_type(view.get("mark")) in ANNOTATION_MARKS:
            continue
        if isinstance(view.get("encoding"), dict):
            return view
    targets = _mark_targets(spec)
    if targets:
        return targets[0]
    if not _is_composition(spec):
        return spec
    return None


def _mark_obj(spec: dict) -> dict:
    """兼容旧调用：返回主几何 unit 的 mark 对象引用。

    复合视图（vconcat/layer 等）不再在根上创建空 mark，避免
    `Cannot read properties of undefined (reading 'filled')`。
    """
    targets = _paint_targets(spec) or _mark_targets(spec)
    if not targets:
        raise ValueError("spec 中无可写入的 mark 视图")
    return _ensure_mark_obj(targets[0])


def _title_obj(spec: dict) -> dict:
    """title 归一化为对象形式并返回引用。"""
    title = spec.get("title")
    if isinstance(title, str):
        spec["title"] = {"text": title}
    elif not isinstance(title, dict):
        spec["title"] = {"text": ""}
    return spec["title"]


def current_mark_color(spec: dict) -> str:
    """当前主色：优先 encoding.color 字面 value（含 condition 基色），再 mark.fill/color。

    highlight_category 在 set_mark_color 保留 condition 后常已清空 mark.color；
    若此处回退 DEFAULT_MARK_COLOR(#4c78a8)，会出现「机构蓝被盖成 Vega 默认蓝」。
    """
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else None
        if not enc:
            continue
        color = enc.get("color")
        if not isinstance(color, dict) or color.get("field"):
            continue
        val = color.get("value")
        if isinstance(val, str) and val.strip():
            return val.strip()
    for view in _paint_targets(spec):
        mark = view.get("mark")
        if isinstance(mark, dict):
            c = read_paint_color(mark)
            if c:
                return c
    mark = spec.get("mark")
    if isinstance(mark, dict):
        c = read_paint_color(mark)
        if c:
            return c
    return DEFAULT_MARK_COLOR


def _recolor_drawn_grids(spec: dict, color: str) -> None:
    for u in drawn_grid_units(spec):
        mark = u["view"].get("mark")
        if isinstance(mark, dict) and "stroke" in mark:
            mark["stroke"] = color


def _patch_title_text_layers(
    spec: dict, *, font_size: Any = None, family: str | None = None
) -> None:
    for u in title_text_units(spec):
        if u["role"] != "title":
            continue
        mark = _ensure_mark_obj(u["view"])
        if font_size is not None:
            mark["fontSize"] = font_size
        if family:
            mark["font"] = family


def _strip_channel_fonts(spec: dict) -> None:
    """去掉 encoding 通道上的字体字号，避免盖住 config。"""
    font_keys = (
        "labelFontSize",
        "titleFontSize",
        "labelFont",
        "titleFont",
        "labelFontWeight",
        "titleFontWeight",
    )

    def scrub_enc(enc: Any) -> None:
        if not isinstance(enc, dict):
            return
        for ch in enc.values():
            if not isinstance(ch, dict):
                continue
            axis = ch.get("axis")
            if isinstance(axis, dict):
                for k in font_keys:
                    axis.pop(k, None)
            legend = ch.get("legend")
            if isinstance(legend, dict):
                for k in ("labelFontSize", "titleFontSize", "labelFont", "titleFont"):
                    legend.pop(k, None)

    scrub_enc(spec.get("encoding"))
    for view in _iter_unit_views(spec):
        scrub_enc(view.get("encoding"))


def _apply_root_title_font(
    spec: dict, *, font_size: Any = None, family: str | None = None, subtitle_size: Any = None
) -> None:
    if spec.get("title") is None:
        return
    title = _title_obj(spec)
    if font_size is not None:
        title["fontSize"] = font_size
    if subtitle_size is not None:
        title["subtitleFontSize"] = subtitle_size
    if family:
        title["font"] = family
        title["subtitleFont"] = family


def _patch_all_text_marks(
    spec: dict,
    *,
    family: str | None = None,
    title_size: Any = None,
    body_size: Any = None,
) -> None:
    """自绘 text 层同步字体；标题用 title_size，正文字号勿套到 annotation。

    annotation（说明/callout）若被加大到 ≥18，会被误判为 title，进而被
    set_title_text 整批改成同一标题文案。
    """
    assembled = isinstance(spec.get("usermeta"), dict) and bool(spec["usermeta"].get("component_assembly"))
    for u in walk_annotated_units(spec):
        if u.get("mark_type") != "text":
            continue
        mark = u.get("mark_obj")
        if not isinstance(mark, dict):
            mark = _ensure_mark_obj(u["view"])
        if family:
            mark["font"] = family
        # header/footer/plot 注释已在组件重组时按各自区域给定字号；全局层级
        # 只能影响根 title，不能再把 footer 或图内 callout 放大。
        if assembled:
            continue
        role = u.get("role")
        if role == "title" and title_size is not None:
            mark["fontSize"] = title_size
        elif (
            body_size is not None
            and role not in ("title", "annotation", "drawn_axis")
        ):
            mark["fontSize"] = body_size
        elif family and title_size is None and body_size is None:
            pass  # 仅改 family


# 设计系统 CSS 变量 / 嵌套 family 令牌 → 浏览器可解析的字体栈
_CSS_FONT_MAP = {
    "--ds-type-system-serif": "Georgia, 'Times New Roman', Times, serif",
    "--ds-type-system-sans": "Helvetica Neue, Helvetica, Arial, sans-serif",
    "--ds-type-system-sans-serif": "Helvetica Neue, Helvetica, Arial, sans-serif",
    "--ds-type-system-mono": "Consolas, 'Courier New', monospace",
}


def resolve_font_family_value(raw: Any) -> str | None:
    """把 persona 字体令牌收成 VL 可用的 family 字符串。"""
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if s.startswith("--"):
            return _CSS_FONT_MAP.get(s) or "Georgia, 'Times New Roman', Times, serif"
        # 单名字体补常用回退，避免系统缺字时落到页面 CSS（如 DM Sans）
        low = s.lower()
        if low in ("helvetica", "helvetica neue"):
            return "Helvetica Neue, Helvetica, Arial, sans-serif"
        if low in ("arial",):
            return "Arial, Helvetica, sans-serif"
        if low in ("georgia", "times", "times new roman"):
            return "Georgia, 'Times New Roman', Times, serif"
        return s
    if isinstance(raw, dict):
        for key in ("serif", "sans", "sans-serif", "primary", "default", "mono", "body"):
            if key in raw:
                got = resolve_font_family_value(raw[key])
                if got:
                    return got
        for v in raw.values():
            got = resolve_font_family_value(v)
            if got:
                return got
    return None


def persona_font_family(persona) -> str | None:
    """从 persona 令牌取字体；CSS 变量立即展开，普通名字留给 apply_op 规范化。"""
    idx = persona.token_index() if hasattr(persona, "token_index") else {}
    for key in (
        "font.family",
        "font.family.serif",
        "font.family.sans",
        "font.family.primary",
    ):
        raw = idx.get(key)
        if isinstance(raw, str) and raw.strip():
            s = raw.strip()
            if s.startswith("--"):
                return resolve_font_family_value(s)
            return s
        if isinstance(raw, dict):
            got = resolve_font_family_value(raw)
            if got:
                return got
    return None


def _font_config_patch(family: str | None = None, sizes: dict | None = None) -> dict:
    """写入 axis/axisX/axisY/legend/title/text，避免轴向细分 config 残留旧字体。"""
    cfg: dict[str, Any] = {}
    if family:
        axis_font = {"labelFont": family, "titleFont": family}
        cfg.update(
            {
                "font": family,
                "title": {"font": family, "subtitleFont": family},
                "axis": dict(axis_font),
                "axisX": dict(axis_font),
                "axisY": dict(axis_font),
                "legend": {"labelFont": family, "titleFont": family},
                "header": {"labelFont": family, "titleFont": family},
                "text": {"font": family},
            }
        )
    if sizes:
        if sizes.get("title") is not None:
            cfg.setdefault("title", {})["fontSize"] = sizes["title"]
        if sizes.get("subtitle") is not None:
            cfg.setdefault("title", {})["subtitleFontSize"] = sizes["subtitle"]
        if sizes.get("axis_label") is not None:
            for key in ("axis", "axisX", "axisY"):
                cfg.setdefault(key, {})["labelFontSize"] = sizes["axis_label"]
        if sizes.get("axis_title") is not None:
            for key in ("axis", "axisX", "axisY"):
                cfg.setdefault(key, {})["titleFontSize"] = sizes["axis_title"]
        if sizes.get("legend_label") is not None:
            cfg.setdefault("legend", {})["labelFontSize"] = sizes["legend_label"]
        if sizes.get("axis_label") is not None:
            cfg.setdefault("text", {})["fontSize"] = sizes["axis_label"]
    return cfg


def _normalize_chart_type_key(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def _to_sentence_case(text: str) -> str:
    """启发式 sentence case：首字母大写，其余单词小写（保留短缩写）。"""
    # 多行标题先拼成一句再处理
    if isinstance(text, list):
        text = " ".join(str(x) for x in text)
    text = re.sub(r"\s+", " ", str(text or "").replace("\n", " ")).strip()
    parts = re.split(r"(\s+)", text)
    out: list[str] = []
    word_i = 0
    for p in parts:
        if not p or p.isspace():
            out.append(p)
            continue
        # 保留 U.S. / BBC 等短全大写
        core = p.strip("'\"“”‘’")
        if word_i == 0:
            out.append(p[:1].upper() + p[1:].lower() if len(p) > 1 else p.upper())
        elif len(core) <= 3 and core.isupper():
            out.append(p)
        else:
            out.append(p.lower())
        word_i += 1
    return "".join(out)


def _concise_title(text: str, *, max_chars: int = 72, max_words: int = 12) -> str | None:
    """过长标题截到首句/首分句；已够短则返回 None。"""
    if isinstance(text, list):
        text = " ".join(str(x) for x in text)
    t = re.sub(r"\s+", " ", str(text or "").strip())
    if not t:
        return None
    words = t.split(" ")
    if len(t) <= max_chars and len(words) <= max_words:
        return None
    for sep in (". ", " — ", " – ", " - ", ": ", "；", "。"):
        if sep in t:
            head = t.split(sep, 1)[0].strip()
            if 8 <= len(head) < len(t):
                return head
    return " ".join(words[:max_words]).rstrip(",;:")


def _normalize_plain_text(text: Any) -> str:
    if isinstance(text, list):
        return re.sub(r"\s+", " ", " ".join(str(x).strip() for x in text if str(x).strip())).strip()
    return re.sub(r"\s+", " ", str(text or "").replace("\n", " ")).strip()


def _is_generic_title(title: str, facts: dict) -> bool:
    """名词性/字段名式标题（非陈述要点）→ 需要 descriptive 改写。"""
    t = title.lower().strip()
    if not t:
        return True
    claim_markers = (
        "say", "wrong", "rose", "fell", "surge", "drop", "lead", "leads", "most",
        "least", "vs", "versus", "how", "why", "percent", "%", "one in", "out of",
        "hit", "reach", "fall", "grow", "decline",
    )
    if any(m in t for m in claim_markers):
        return False
    for f in (facts.get("category_field"), facts.get("value_field")):
        if f and t == str(f).lower().replace("_", " "):
            return True
    # 短名词短语
    return len(t.split()) <= 6


def _descriptive_title_ops(facts: dict) -> list[dict]:
    """BBC 式「标题陈述要点、副标题补语境」的可执行启发式。"""
    ops: list[dict] = []
    title = _normalize_plain_text(facts.get("title_text"))
    subtitle = _normalize_plain_text(facts.get("subtitle"))
    if not title:
        return ops

    # 副标题复述标题开头 → 去掉重复前缀（保留 Source 行）
    if subtitle and subtitle.lower().startswith(title.lower()):
        rest = subtitle[len(title) :].lstrip(" .:—–-")
        # "Title is measured as…" → "Measured as…"（去掉系动词残片）
        rest = re.sub(
            r"^(is|are|was|were|has been|have been)\s+",
            "",
            rest,
            flags=re.IGNORECASE,
        ).strip()
        if rest and rest.lower() != subtitle.lower():
            rest = rest[0].upper() + rest[1:]
            ops.append(
                {"action": "set_subtitle", "text": rest, "preserve_source": True}
            )
            subtitle = rest

    # 过长 → 截短
    concise = _concise_title(title)
    if concise and concise != title:
        ops.append({"action": "set_title_text", "text": _to_sentence_case(concise)})
        return ops

    # 泛化标题 + 极值类别 → 改成要点式标题；原标题落到副标题（若无副标题）
    maxc = facts.get("max_category") if isinstance(facts.get("max_category"), dict) else {}
    if _is_generic_title(title, facts) and maxc.get("name"):
        name = str(maxc["name"])
        val = maxc.get("value")
        vf = str(facts.get("value_field") or "").lower()
        mark = str(facts.get("mark_type") or "")
        chinese = any("\u4e00" <= ch <= "\u9fff" for ch in title + name)
        if chinese:
            new_t = f"{name}居首" + (f"（{val:g}）" if isinstance(val, (int, float)) else "")
        elif "share" in vf or "percent" in vf or "%" in title:
            new_t = f"{name} tops the list" + (f" at {val:g}%" if isinstance(val, (int, float)) else "")
            new_t = _to_sentence_case(new_t)
        elif mark in ("line", "area", "trail"):
            new_t = _to_sentence_case(f"{name} leads in {title.lower()}")
        else:
            new_t = _to_sentence_case(
                f"{name} leads" + (f" ({val:g})" if isinstance(val, (int, float)) else "")
            )
        if new_t and new_t.lower() != title.lower():
            ops.append({"action": "set_title_text", "text": new_t})
            if not subtitle:
                ops.append(
                    {"action": "set_subtitle", "text": title, "preserve_source": True}
                )
    return ops


def _subtitle_lines(subtitle: Any) -> list[str]:
    if subtitle is None:
        return []
    if isinstance(subtitle, list):
        return [str(x).strip() for x in subtitle if str(x).strip()]
    s = str(subtitle).strip()
    if not s:
        return []
    # 保留显式换行
    if "\n" in s:
        return [ln.strip() for ln in s.splitlines() if ln.strip()]
    return [s]


def _format_source_note(provider_or_note: str) -> str:
    t = (provider_or_note or "").strip()
    if not t:
        return "Source: —"
    low = t.lower()
    if low.startswith("source") or t.startswith("来源"):
        return t
    return f"Source: {t}"


def _escape(v: Any) -> str:
    return str(v).replace("\\", "\\\\").replace("'", "\\'")


def _highlight_condition_test(field: Any, value: Any) -> str:
    """生成 VL filter 表达式；数值类用 ==，避免 year:1995 对不上 '1995'。

    JS 中 ``1995 == '1995'`` 为 true，故数字字面量可同时匹配 number/string 数据。
    """
    f = _escape(field)
    if isinstance(value, bool):
        return f"datum['{f}'] === {'true' if value else 'false'}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"datum['{f}'] == {value}"
    if isinstance(value, float):
        return f"datum['{f}'] == {value}"
    if isinstance(value, str):
        s = value.strip()
        if re.fullmatch(r"-?\d+", s):
            return f"datum['{f}'] == {s}"
        if re.fullmatch(r"-?\d+\.\d+", s):
            return f"datum['{f}'] == {s}"
        return f"datum['{f}'] === '{_escape(s)}'"
    return f"datum['{f}'] === '{_escape(value)}'"


def _find_data(spec: dict) -> dict | None:
    if isinstance(spec.get("data"), dict):
        return spec["data"]
    for view in _iter_unit_views(spec):
        if isinstance(view.get("data"), dict):
            return view["data"]
    for key in COMPOSITION_KEYS:
        kids = spec.get(key)
        if not isinstance(kids, list):
            continue
        for kid in kids:
            if isinstance(kid, dict) and isinstance(kid.get("data"), dict):
                return kid["data"]
    return None


def _unit_encoding_for_mark(op: dict) -> dict[str, Any]:
    """按目标 mark 与字段事实生成单 unit encoding。"""
    mark_type = op.get("mark_type") or "bar"
    chart = _normalize_chart_type_key(op.get("chart_type") or "")
    category_field = op.get("category_field")
    value_field = op.get("value_field")
    color_field = op.get("color_field")

    if chart in ("pie", "donut") or mark_type == "arc":
        enc: dict[str, Any] = {}
        if category_field and value_field:
            enc["theta"] = {"field": value_field, "type": "quantitative"}
            enc["color"] = {"field": category_field, "type": "nominal"}
        return enc

    if chart == "histogram" and value_field:
        return {
            "x": {"field": value_field, "type": "quantitative", "bin": True},
            "y": {"aggregate": "count", "type": "quantitative"},
        }

    if mark_type == "boxplot" and category_field and value_field:
        return {
            "x": {"field": category_field, "type": "nominal"},
            "y": {"field": value_field, "type": "quantitative"},
        }

    if (chart == "heatmap" or mark_type == "rect") and category_field and value_field:
        # 双分类优先；否则 x=类别 y=定量色
        if color_field and color_field != category_field:
            return {
                "x": {"field": category_field, "type": "nominal"},
                "y": {"field": color_field, "type": "nominal"},
                "color": {"field": value_field, "type": "quantitative"},
            }
        return {
            "x": {"field": category_field, "type": "nominal"},
            "y": {"field": value_field, "type": "quantitative"},
            "color": {"field": value_field, "type": "quantitative"},
        }

    if not (category_field and value_field):
        return {}

    lineish = mark_type in ("line", "area", "point", "circle", "trail", "tick")
    channel = op.get("category_channel") or ("x" if lineish else "y")
    if channel == "y":
        enc = {
            "y": {"field": category_field, "type": "nominal"},
            "x": {"field": value_field, "type": "quantitative"},
        }
    else:
        enc = {
            "x": {"field": category_field, "type": "nominal"},
            "y": {"field": value_field, "type": "quantitative"},
        }
    if chart == "bubble" or op.get("size_from_value"):
        enc["size"] = {"field": value_field, "type": "quantitative"}
    if "stacked" in chart and color_field:
        enc["color"] = {"field": color_field, "type": "nominal"}
    elif chart in ("stacked bar", "stacked area", "stream") and not color_field:
        # 无系列字段时仍输出 mark；stack 由 VL 默认处理单系列
        pass
    return enc


def _make_unit_view(op: dict, data: dict | None, width: Any = None, height: Any = None) -> dict:
    mark_type = op.get("mark_type") or "bar"
    chart = _normalize_chart_type_key(op.get("chart_type") or "")
    mark: dict[str, Any] = {"type": mark_type}
    if chart == "donut" or (mark_type == "arc" and chart == "donut"):
        mark["type"] = "arc"
        mark["innerRadius"] = 50
    elif mark_type == "arc" and chart == "pie":
        mark.pop("innerRadius", None)
    unit: dict[str, Any] = {
        "mark": mark,
        "encoding": _unit_encoding_for_mark(op),
    }
    if data is not None:
        unit["data"] = data
    if width is not None:
        unit["width"] = width
    if height is not None:
        unit["height"] = height
    return unit


def _primary_geom_child_index(kids: list) -> int | None:
    """vconcat/hconcat 中首个含几何 mark 的子视图下标（跳过纯 text 来源层）。"""
    for i, kid in enumerate(kids):
        if not isinstance(kid, dict):
            continue
        targets = _mark_targets(kid)
        if any(_mark_type(t.get("mark")) not in ANNOTATION_MARKS for t in targets):
            return i
        # 子节点本身是 layer/unit 容器但 _mark_targets 已覆盖；无几何则跳过
        if "mark" in kid and _mark_type(kid.get("mark")) not in ANNOTATION_MARKS:
            return i
    return None


def _rebuild_unit_mark(spec: dict, op: dict) -> None:
    """将 layer 多 mark 或 concat 主图折叠为单 mark unit（chart.type / 用户改型）。

    - 根为 layer：去掉叠加层，写成根级 unit；
    - 根为 vconcat/hconcat：只替换几何主图子节点，保留 Source 等 text 兄弟层。
    """
    mark_type = op.get("mark_type") or "bar"
    data = _find_data(spec)
    width = spec.get("width")
    height = spec.get("height")
    for view in _mark_targets(spec):
        if width is None and isinstance(view.get("width"), (int, float)):
            width = view["width"]
        if height is None and isinstance(view.get("height"), (int, float)):
            height = view["height"]

    for key in ("vconcat", "hconcat", "concat"):
        kids = spec.get(key)
        if not isinstance(kids, list) or not kids:
            continue
        idx = _primary_geom_child_index(kids)
        if idx is None:
            continue
        child = kids[idx]
        child_data = child.get("data") if isinstance(child, dict) and isinstance(child.get("data"), dict) else data
        cw = child.get("width") if isinstance(child, dict) else None
        ch = child.get("height") if isinstance(child, dict) else None
        kids[idx] = _make_unit_view(
            {**op, "mark_type": mark_type},
            child_data,
            cw if cw is not None else None,
            ch if ch is not None else None,
        )
        return

    for key in COMPOSITION_KEYS:
        spec.pop(key, None)
    spec.pop("encoding", None)
    spec.pop("mark", None)
    unit = _make_unit_view(op, data, width, height)
    # 把 unit 字段写回根（保留根级 schema/description 等）
    for k, v in unit.items():
        spec[k] = v


def _iter_encoding_views(spec: dict) -> list[dict]:
    """所有可能带 encoding 的视图（根 + unit）。"""
    views: list[dict] = []
    if isinstance(spec.get("encoding"), dict) or "mark" in spec:
        views.append(spec)
    for view in _iter_unit_views(spec):
        if view is not spec:
            views.append(view)
    return views


def _recolor_or_clear_literal_color(
    spec: dict, primary: str, accent: str | None = None
) -> None:
    """encoding.color 的 value/condition（无 field）会盖住 mark.color。

    - 有 accent：改写 value=主色、condition.value=强调色（保留强调结构）
    - 无 accent 但已有 condition：只换基色 value，**保留** condition（避免末年/峰值强调被抹成单色）
    - 纯 value、无 condition：删除该 color 通道，交给 mark.color
    """
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        color = enc.get("color")
        if not isinstance(color, dict) or color.get("field"):
            continue
        cond = color.get("condition")
        has_cond = isinstance(cond, dict) and ("test" in cond or "value" in cond)
        if has_cond:
            color["value"] = primary
            cond = dict(cond)
            if accent:
                cond["value"] = accent
            # 无 accent 时保留原 condition.value（语义强调色）
            color["condition"] = cond
            enc["color"] = color
            mark = view.get("mark")
            if isinstance(mark, dict):
                mark.pop("color", None)
                mark.pop("fill", None)
        else:
            enc.pop("color", None)


def _view_data_values(view: dict) -> list:
    data = view.get("data") if isinstance(view.get("data"), dict) else None
    if isinstance(data, dict) and isinstance(data.get("values"), list):
        return data["values"]
    return []


def _field_values_look_like_hex(view: dict, field: str) -> bool:
    """color 通道绑的是数据里的 hex 列（identity），而非类别名。"""
    vals = []
    for row in _view_data_values(view)[:24]:
        if isinstance(row, dict) and field in row:
            vals.append(row.get(field))
    if not vals:
        return field.lower() in ("color", "colour", "fill", "hex", "colourcode")
    hexish = 0
    for v in vals:
        if isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{3,8}", v.strip()):
            hexish += 1
    return hexish >= max(1, len(vals) // 2)


def _retarget_literal_color_field(view: dict, color_enc: dict) -> None:
    """Color='#hex' 列 → 改绑 Category 等名义字段，以便 scale.range 生效。"""
    field = color_enc.get("field")
    if not isinstance(field, str):
        return
    looks_hex = _field_values_look_like_hex(view, field) or field.lower() in (
        "color",
        "colour",
        "fill",
        "hex",
        "colourcode",
    )
    if not looks_hex:
        return
    rows = _view_data_values(view)
    keys: set[str] = set()
    for row in rows[:8]:
        if isinstance(row, dict):
            keys.update(str(k) for k in row.keys())
    for cand in ("Category", "category", "Name", "name", "label", "type", "Type", "series"):
        if cand in keys and cand != field:
            color_enc["field"] = cand
            color_enc["type"] = "nominal"
            return
    # layer 共享父 data、本地无 values 时：Color → Category 惯例
    if field.lower() == "color":
        color_enc["field"] = "Category"
        color_enc["type"] = "nominal"


def _color_encoding_views(spec: dict) -> list[dict]:
    """所有带 encoding.color.field 的 unit（含 vconcat/layer 多环）。"""
    out: list[dict] = []
    seen: set[int] = set()
    for view in list(_paint_targets(spec)) + list(_iter_unit_views(spec)):
        if not isinstance(view, dict):
            continue
        vid = id(view)
        if vid in seen:
            continue
        seen.add(vid)
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        color = enc.get("color")
        if isinstance(color, dict) and isinstance(color.get("field"), str) and color["field"]:
            out.append(view)
    return out


def _apply_color_range_to_view(view: dict, colors: list[str]) -> bool:
    """写入单视图 color.scale.range；处理 scale:null 与 hex 列。"""
    enc = view.setdefault("encoding", {})
    color = enc.get("color")
    if not isinstance(color, dict) or not color.get("field"):
        return False
    _retarget_literal_color_field(view, color)
    # scale: null 时 setdefault 无效，必须覆盖
    scale = color.get("scale")
    if not isinstance(scale, dict):
        color["scale"] = {"range": list(colors)}
    else:
        scale["range"] = list(colors)
    return True


def _paint_series_colors(spec: dict, colors: list[str]) -> bool:
    """无 color 通道时：按主几何层依次着机构色（Berlin 双 area 等）。"""
    if not colors:
        return False
    targets = _paint_targets(spec)
    if not targets:
        return False
    changed = False
    for i, view in enumerate(targets):
        apply_paint_color(_ensure_mark_obj(view), colors[i % len(colors)])
        changed = True
    return changed


def _remove_value_label_layers(spec: dict) -> bool:
    """移除绑在主几何数据上的柱上/点上数值 text 层；保留像素画布 callout/品牌字。"""
    from .view_geometry import (
        COMPOSITION_KEYS,
        is_per_mark_value_label,
        primary_encoding_fields,
        walk_annotated_units,
    )

    units = walk_annotated_units(spec)
    primary_fields = primary_encoding_fields(units)
    drop_ids: set[int] = set()
    for u in units:
        if is_per_mark_value_label(u, primary_fields):
            drop_ids.add(id(u["view"]))

    if not drop_ids:
        return False

    def prune(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for key in COMPOSITION_KEYS:
            kids = node.get(key)
            if isinstance(kids, list):
                node[key] = [k for k in kids if id(k) not in drop_ids]
                for k in node[key]:
                    prune(k)
        nested = node.get("spec")
        if isinstance(nested, dict):
            prune(nested)

    prune(spec)
    return True


def _subsample_axis_values(values: list, max_ticks: int) -> list:
    """均匀保留首尾与中间刻度，目标不超过 max_ticks。"""
    n = len(values)
    if n <= max_ticks:
        return list(values)
    if max_ticks <= 2:
        return [values[0], values[-1]]
    # 等间隔下标（含 0 与 n-1）
    idxs = sorted(
        {
            int(round(i * (n - 1) / (max_ticks - 1)))
            for i in range(max_ticks)
        }
    )
    return [values[i] for i in idxs]


def _axis_tick_list(axis: dict) -> list | None:
    vals = axis.get("values")
    return vals if isinstance(vals, list) else None


def _x_axis_still_crowded(spec: dict) -> bool:
    """密轴/长日期标签：轴字号不宜过大（与是否已倾斜无关）。"""
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else {}
        x = enc.get("x") if isinstance(enc.get("x"), dict) else {}
        axis = x.get("axis") if isinstance(x.get("axis"), dict) else {}
        vals = _axis_tick_list(axis)
        n = len(vals) if vals is not None else 0
        has_expr = isinstance(axis.get("labelExpr"), str) and bool(axis["labelExpr"].strip())
        if has_expr and n >= 5:
            return True
        if n >= 6:
            return True
    return False


def _thin_axis_labels(spec: dict, channel: str = "x", max_ticks: int = 8) -> bool:
    """稀疏指定轴的 axis.values，并处理水平长标签挤叠；不碰柱上数值层。"""
    ch_key = channel if channel in ("x", "y") else "x"
    changed = False
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        ch = enc.get(ch_key)
        if not isinstance(ch, dict):
            continue
        axis = ch.get("axis")
        if axis is False:
            continue
        if not isinstance(axis, dict):
            axis = {}
            ch["axis"] = axis
        vals = _axis_tick_list(axis)
        # ordinal/nominal 轴通常没有显式 axis.values。此时从 inline data 的字段域
        # 构造刻度，否则 L3 的「稀疏标签」会静默 no-op（如年度柱图）。
        if vals is None and str(ch.get("type") or "").lower() in ("ordinal", "nominal"):
            field = ch.get("field")
            if isinstance(field, str) and field:
                domain: list[Any] = []
                datasets: list[Any] = [spec.get("data"), view.get("data")]
                for data in datasets:
                    values = data.get("values") if isinstance(data, dict) else None
                    if not isinstance(values, list):
                        continue
                    for row in values:
                        value = row.get(field) if isinstance(row, dict) else None
                        if value is not None and value not in domain:
                            domain.append(value)
                if len(domain) > max_ticks:
                    vals = domain
        if vals is not None and len(vals) > max_ticks:
            new_vals = _subsample_axis_values(vals, max_ticks)
            if new_vals != vals:
                axis["values"] = new_vals
                changed = True
        cur = _axis_tick_list(axis)
        n_cur = len(cur) if cur is not None else 0
        has_expr = isinstance(axis.get("labelExpr"), str) and bool(axis["labelExpr"].strip())
        # 密轴或刚稀疏：间距 / overlap / 倾斜（仅稀疏不够时，长日期水平字仍会撞）
        if (cur is not None and n_cur >= 6) or (has_expr and n_cur >= 5):
            pad = axis.get("labelPadding")
            try:
                pad_n = float(pad) if pad is not None else 0.0
            except (TypeError, ValueError):
                pad_n = 0.0
            if pad_n < 12:
                axis["labelPadding"] = 12
                changed = True
            if axis.get("labelOverlap") is None:
                axis["labelOverlap"] = True
                changed = True
            if ch_key == "x" and axis.get("labelAngle") in (None, 0, 0.0):
                axis["labelAngle"] = -35
                axis["labelAlign"] = "right"
                axis["labelBaseline"] = "middle"
                changed = True
    # 机构字号若把轴标抬到 18px，会抵消稀疏效果 → 密轴时封顶
    if ch_key == "x" and _x_axis_still_crowded(spec):
        cfg = spec.setdefault("config", {})
        if not isinstance(cfg, dict):
            return changed
        for key in ("axis", "axisX"):
            block = cfg.get(key)
            if not isinstance(block, dict):
                continue
            fs = block.get("labelFontSize")
            try:
                fs_n = float(fs) if fs is not None else None
            except (TypeError, ValueError):
                fs_n = None
            if fs_n is not None and fs_n > 13:
                block["labelFontSize"] = 13
                changed = True
    return changed


def _set_axis(spec: dict, channel: str, axis_patch: dict | None = None, scale_patch: dict | None = None) -> bool:
    """受控轴样式修改：只允许安全的 Vega-Lite axis/scale 字段。"""
    ch_key = channel if channel in ("x", "y") else "x"
    axis_allowed = {"grid", "gridColor", "gridDash", "gridWidth", "labelAngle", "labelAlign", "labelBaseline", "labelPadding", "labelOverlap", "tickCount", "values", "format", "title", "titlePadding", "titleAngle", "domain", "ticks"}
    scale_allowed = {"zero", "domainMin", "domainMax", "nice", "padding", "paddingInner", "paddingOuter"}
    changed = False
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else {}
        ch = enc.get(ch_key) if isinstance(enc, dict) else None
        if not isinstance(ch, dict):
            continue
        if isinstance(axis_patch, dict):
            axis = ch.get("axis")
            if axis is False:
                continue
            if not isinstance(axis, dict):
                axis = {}
                ch["axis"] = axis
            for key, value in axis_patch.items():
                if key in axis_allowed and axis.get(key) != value:
                    axis[key] = value
                    changed = True
        if isinstance(scale_patch, dict):
            scale = ch.get("scale")
            if scale is False:
                continue
            if not isinstance(scale, dict):
                scale = {}
                ch["scale"] = scale
            for key, value in scale_patch.items():
                if key in scale_allowed and scale.get(key) != value:
                    scale[key] = value
                    changed = True
    return changed


def _set_mark_style(spec: dict, style: dict) -> bool:
    """对主数据 marks 应用受控视觉样式，避免影响 text/annotation 层。"""
    allowed = {
        "opacity", "fillOpacity", "strokeOpacity", "cornerRadius", "cornerRadiusEnd",
        "strokeWidth", "strokeDash", "strokeCap", "strokeJoin", "filled", "fill",
        "stroke", "size", "shape", "interpolate", "tension", "point", "line",
        "binSpacing", "discreteBandSize", "continuousBandSize",
    }
    changed = False
    for view in _paint_targets(spec):
        mark = _ensure_mark_obj(view)
        for key, value in style.items():
            if key in allowed and mark.get(key) != value:
                mark[key] = value
                changed = True
    return changed


def _set_text_style(spec: dict, style: dict) -> bool:
    """对 text marks 的可读性属性做受控修改；不改文案、字段或位置编码。"""
    allowed = {"fontSize", "fontWeight", "opacity", "align", "baseline", "angle", "dx", "dy"}
    changed = False
    for view in _iter_unit_views(spec):
        mark = view.get("mark")
        mark_type = mark.get("type") if isinstance(mark, dict) else mark
        if mark_type != "text":
            continue
        obj = _ensure_mark_obj(view)
        for key, value in style.items():
            if key in allowed and obj.get(key) != value:
                obj[key] = value
                changed = True
    return changed


def _set_encoding_style(spec: dict, channel: str, patch: dict) -> bool:
    """Set safe visual encoding properties (shape/size/order/tooltip) on existing channels."""
    allowed = {"field", "type", "aggregate", "bin", "sort", "scale", "legend", "title", "condition"}
    changed = False
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else None
        if not isinstance(enc, dict):
            continue
        current = enc.get(channel)
        if current is None:
            current = {}
            enc[channel] = current
        if not isinstance(current, dict):
            continue
        for key, value in patch.items():
            if key in allowed and current.get(key) != value:
                current[key] = value
                changed = True
    return changed


def _slim_channel(ch: dict, keep: tuple = ("field", "type", "aggregate", "sort", "timeUnit")) -> dict:
    """复制通道定义的骨架字段（不带 axis/scale/title，标注层与主层共享 scale）。"""
    return {k: ch[k] for k in keep if k in ch}


def _sort_categories(spec: dict, order: str = "desc") -> bool:
    """类别轴按数值大小排序（nominal/ordinal 才动，时间轴不排）。"""
    desc = order != "asc"
    changed = False
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        for cat_key, val_key in (("x", "y"), ("y", "x")):
            cat, val = enc.get(cat_key), enc.get(val_key)
            if not (isinstance(cat, dict) and cat.get("field")):
                continue
            if str(cat.get("type") or "") not in ("nominal", "ordinal"):
                continue
            if not (isinstance(val, dict) and str(val.get("type") or "") == "quantitative"):
                continue
            want = ("-" if desc else "") + val_key
            if cat.get("sort") != want:
                cat["sort"] = want
                changed = True
    return changed


def _set_orientation_horizontal(spec: dict) -> bool:
    """竖向条形图转横条：x(类别) ↔ y(数值) 互换，sort 轴引用同步翻转。"""
    if not any(_mark_type(v.get("mark")) == "bar" for v in _mark_targets(spec)):
        return False
    changed = False
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        x, y = enc.get("x"), enc.get("y")
        if not (isinstance(x, dict) and isinstance(y, dict)):
            continue
        if str(x.get("type") or "") not in ("nominal", "ordinal") or str(y.get("type") or "") != "quantitative":
            continue
        enc["x"], enc["y"] = y, x
        for ch in (enc["x"], enc["y"]):
            sort = ch.get("sort")
            if isinstance(sort, str) and sort.lstrip("-") in ("x", "y"):
                flipped = {"x": "y", "y": "x"}[sort.lstrip("-")]
                ch["sort"] = ("-" if sort.startswith("-") else "") + flipped
        # 类别轴到了 y，倾斜标签不再必要
        cat_axis = enc["y"].get("axis")
        if isinstance(cat_axis, dict):
            cat_axis.pop("labelAngle", None)
        changed = True
    return changed


def _value_label_host(spec: dict) -> tuple[dict | None, dict]:
    """找承载数值标注的 bar unit 及其有效 encoding（根共享通道并入）。"""
    for view in _iter_encoding_views(spec):
        if _mark_type(view.get("mark")) != "bar":
            continue
        enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else {}
        if view is not spec and isinstance(spec.get("encoding"), dict):
            enc = {**spec["encoding"], **enc}
        return view, enc
    return None, {}


def _append_sibling_layer(spec: dict, host: dict, layer_view: dict) -> bool:
    """把新层挂到 host 旁边：根 unit 先包成 layer；仅支持根级 layer 列表。"""
    if host is spec and "layer" not in spec:
        unit = {}
        for key in ("mark", "encoding"):
            if key in spec:
                unit[key] = spec.pop(key)
        spec["layer"] = [unit, layer_view]
        return True
    layer = spec.get("layer")
    if isinstance(layer, list) and any(k is host for k in layer):
        layer.append(layer_view)
        return True
    return False


def _add_value_labels(spec: dict, fmt: str | None = None) -> bool:
    """给单系列 bar 加数值标注层；多系列/已有标注/嵌套复合视图不动。"""
    from .view_geometry import (
        is_per_mark_value_label,
        primary_encoding_fields,
        walk_annotated_units,
    )

    units = walk_annotated_units(spec)
    primary_fields = primary_encoding_fields(units)
    if any(is_per_mark_value_label(u, primary_fields) for u in units):
        return False

    host, enc = _value_label_host(spec)
    if host is None:
        return False
    x, y = enc.get("x"), enc.get("y")
    if not (isinstance(x, dict) and isinstance(y, dict)):
        return False
    if str(x.get("type") or "") in ("nominal", "ordinal") and str(y.get("type") or "") == "quantitative":
        cat_key, val_key, cat, val = "x", "y", x, y
        mark = {"type": "text", "baseline": "bottom", "dy": -4}
    elif str(y.get("type") or "") in ("nominal", "ordinal") and str(x.get("type") or "") == "quantitative":
        cat_key, val_key, cat, val = "y", "x", y, x
        mark = {"type": "text", "align": "left", "dx": 4, "baseline": "middle"}
    else:
        return False
    color = enc.get("color")
    if isinstance(color, dict) and color.get("field") and color["field"] != cat.get("field"):
        return False  # 分组/堆叠多系列：标注会互相压盖

    text_ch: dict = {"field": val.get("field"), "type": "quantitative"}
    if val.get("aggregate"):
        text_ch["aggregate"] = val["aggregate"]
    if fmt:
        text_ch["format"] = fmt
    label_layer = {
        "mark": mark,
        "encoding": {
            cat_key: _slim_channel(cat),
            val_key: _slim_channel(val, keep=("field", "type", "aggregate", "timeUnit")),
            "text": text_ch,
        },
    }
    return _append_sibling_layer(spec, host, label_layer)


def _direct_label(spec: dict) -> bool:
    """图例改直接标注：冗余图例（color=类别轴字段）直接摘除；多系列 line 加线端系列名。"""
    changed = False
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        color = enc.get("color")
        if not (isinstance(color, dict) and color.get("field")):
            continue
        cat_field = None
        for ch_key in ("x", "y", "theta"):
            ch = enc.get(ch_key)
            if isinstance(ch, dict) and ch.get("field") and str(ch.get("type") or "") in ("nominal", "ordinal"):
                cat_field = ch["field"]
                break
        if cat_field and color["field"] == cat_field:
            # 类别已由轴标出，图例是冗余信道（键缺省=VL 默认显示，也要显式置 null）
            if "legend" not in color or color["legend"] is not None:
                color["legend"] = None
                changed = True
            continue
        mark_t = _mark_type(view.get("mark")) or _mark_type(spec.get("mark"))
        x, y = enc.get("x"), enc.get("y")
        if (
            mark_t == "line"
            and isinstance(x, dict) and x.get("field")
            and isinstance(y, dict) and y.get("field")
            and str(y.get("type") or "") == "quantitative"
        ):
            xf = x["field"]
            label_layer = {
                "mark": {"type": "text", "align": "left", "dx": 6},
                "encoding": {
                    "x": {"aggregate": "max", "field": xf, "type": x.get("type") or "temporal"},
                    "y": {"aggregate": {"argmax": xf}, "field": y["field"], "type": "quantitative"},
                    "color": {"field": color["field"], "type": color.get("type") or "nominal", "legend": None},
                    "text": {"field": color["field"], "type": "nominal"},
                },
            }
            if _append_sibling_layer(spec, view, label_layer):
                if "legend" not in color or color["legend"] is not None:
                    color["legend"] = None
                changed = True
    return changed


def _set_quant_axis_scale(spec: dict, scale_patch: dict) -> bool:
    """把 scale 补丁打到数值(quantitative)通道——竖图在 y、横图在 x，不猜死通道。"""
    changed = False
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        for ch_key in ("x", "y"):
            ch = enc.get(ch_key)
            if not (isinstance(ch, dict) and str(ch.get("type") or "") == "quantitative"):
                continue
            scale = ch.get("scale")
            if scale is False:
                continue
            if not isinstance(scale, dict):
                scale = {}
                ch["scale"] = scale
            for key, value in scale_patch.items():
                if scale.get(key) != value:
                    scale[key] = value
                    changed = True
    return changed


def _set_band_padding(spec: dict, inner: float | None, outer: float | None) -> bool:
    """条形图带宽节奏：paddingInner/Outer 写到类别(band)通道的 scale 上。"""
    if not any(_mark_type(v.get("mark")) == "bar" for v in _mark_targets(spec)):
        return False
    patch: dict = {}
    if inner is not None:
        patch["paddingInner"] = round(max(0.0, min(float(inner), 0.9)), 3)
    if outer is not None:
        patch["paddingOuter"] = round(max(0.0, min(float(outer), 0.9)), 3)
    if not patch:
        return False
    changed = False
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        for cat_key, val_key in (("x", "y"), ("y", "x")):
            cat, val = enc.get(cat_key), enc.get(val_key)
            if not (isinstance(cat, dict) and cat.get("field")):
                continue
            if str(cat.get("type") or "") not in ("nominal", "ordinal"):
                continue
            if not (isinstance(val, dict) and str(val.get("type") or "") == "quantitative"):
                continue
            scale = cat.get("scale")
            if scale is False:
                continue
            if not isinstance(scale, dict):
                scale = {}
                cat["scale"] = scale
            for key, value in patch.items():
                if scale.get(key) != value:
                    scale[key] = value
                    changed = True
    return changed


_GRID_DASH: dict[str, list[int] | None] = {"dotted": [1, 3], "dashed": [5, 4], "solid": None}


def _set_grid_style(
    spec: dict, style: str | None, color: str | None = None, opacity: float | None = None
) -> bool:
    """网格线样式（点线/虚线/实线）与轻重落到数值轴的 grid；显式关网格的轴不动。"""
    dash = _GRID_DASH.get(style) if style in _GRID_DASH else "__skip__"
    if dash == "__skip__" and color is None and opacity is None:
        return False
    changed = False
    for view in _iter_encoding_views(spec):
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        for ch_key in ("x", "y"):
            ch = enc.get(ch_key)
            if not (isinstance(ch, dict) and str(ch.get("type") or "") == "quantitative"):
                continue
            axis = ch.get("axis")
            if axis is False or (isinstance(axis, dict) and axis.get("grid") is False):
                continue
            if not isinstance(axis, dict):
                axis = {}
                ch["axis"] = axis
            if dash != "__skip__":
                if dash is None:
                    if "gridDash" in axis:
                        axis.pop("gridDash")
                        changed = True
                elif axis.get("gridDash") != dash:
                    axis["gridDash"] = dash
                    changed = True
            if color and axis.get("gridColor") != color:
                axis["gridColor"] = color
                changed = True
            if opacity is not None:
                try:
                    val = round(max(0.0, min(float(opacity), 1.0)), 3)
                except (TypeError, ValueError):
                    val = None
                if val is not None and axis.get("gridOpacity") != val:
                    axis["gridOpacity"] = val
                    changed = True
    return changed


def apply_op(spec: dict, op: dict) -> None:
    """原地执行单个 op（spec 已是深拷贝）。未知 action 抛错。"""
    action = op.get("action")

    if action == "reassemble_components":
        from .component_assembler import reassemble_components
        reassemble_components(spec, str(op.get("profile") or "editorial"), op.get("placements") if isinstance(op.get("placements"), list) else None)
        return

    # A layered Vega-Lite export can mix native, scale-bound axes with text placed
    # in absolute pixels.  Changing root dimensions or root padding moves only the
    # former coordinate system.  Such a transform is valid only after a layout
    # migration (reassemble_components); otherwise it must be treated as a no-op.
    # This is a structural invariant, not a persona-specific exception.
    fixed_layout = False
    if action in {"set_size", "merge_config", "set_orientation"}:
        try:
            from .component_assembler import build_component_ir
            fixed_layout = bool(build_component_ir(spec).get("pixel_positioned_text"))
        except Exception:
            fixed_layout = False

    if action == "set_mark_color":
        primary = op["color"]
        accent = op.get("accent_color") if isinstance(op.get("accent_color"), str) else None
        # 字面 value/condition 会盖住 mark.color，先改写或清除
        _recolor_or_clear_literal_color(spec, primary, accent)
        targets = _paint_targets(spec)
        if not targets:
            return
        # 若仍保留 encoding.color（强调结构），勿再写 mark.color
        still_literal = False
        for view in _iter_encoding_views(spec):
            color = (view.get("encoding") or {}).get("color") if isinstance(view.get("encoding"), dict) else None
            if isinstance(color, dict) and not color.get("field") and (
                "value" in color or "condition" in color
            ):
                still_literal = True
                break
        if still_literal:
            return
        for view in targets:
            apply_paint_color(_ensure_mark_obj(view), primary)

    elif action == "set_mark_type":
        targets = _mark_targets(spec)
        chart = _normalize_chart_type_key(op.get("chart_type") or "")
        # 同主图型不是“把第一个 layer 改成该类型”的命令。组合图中的第一个
        # layer 常是 brush/background rect；此类请求应完全 idempotent。
        if _same_primary_mark_type(spec, op):
            return
        # 显式 rebuild_unit，或复合多几何层且已带字段 → 折叠为单 unit
        if _should_rebuild_mark_type(spec, op, targets):
            _rebuild_unit_mark(spec, op)
            return
        if not targets:
            return
        view = targets[0]
        mark = _ensure_mark_obj(view)
        mark["type"] = op["mark_type"]
        if chart == "donut" or (op["mark_type"] == "arc" and chart == "donut"):
            mark["type"] = "arc"
            mark["innerRadius"] = mark.get("innerRadius") or 50
        if chart in ("pie", "donut") or op["mark_type"] == "arc":
            # Vega-Lite 没有 pie mark；饼图是 arc + theta/color 编码。
            enc = view.setdefault("encoding", {})
            category_field = op.get("category_field")
            value_field = op.get("value_field")
            if category_field and value_field:
                for channel in ("x", "y", "x2", "y2", "size", "shape"):
                    enc.pop(channel, None)
                enc["theta"] = {"field": value_field, "type": "quantitative"}
                enc["color"] = {"field": category_field, "type": "nominal"}
        if chart == "bubble" and op.get("value_field"):
            enc = view.setdefault("encoding", {})
            enc["size"] = {"field": op["value_field"], "type": "quantitative"}

    elif action == "remove_encoding_channel":
        view = _encoding_target(spec)
        enc = view.get("encoding") if isinstance(view, dict) else None
        if isinstance(enc, dict):
            enc.pop(op["channel"], None)

    elif action == "set_color_range":
        colors = [c for c in (op.get("colors") or []) if isinstance(c, str)]
        if not colors:
            return
        views = _color_encoding_views(spec)
        touched = False
        for view in views:
            if _apply_color_range_to_view(view, colors):
                touched = True
        if touched:
            # 多类别着色由 encoding 驱动，清除几何 mark.color/fill 避免与色板抢优先级
            for target in _paint_targets(spec):
                mark = target.get("mark")
                if isinstance(mark, dict):
                    mark.pop("color", None)
                    mark.pop("fill", None)
        else:
            # Berlin 等：双序列 layer 无 color 通道 → 按层着机构色
            _paint_series_colors(spec, colors)

    elif action == "highlight_category":
        # category_condition：字面 condition 或单序列类别高亮。
        # 多序列 color.field（scale.domain>=2）须走 set_color_range，此处拒绝改写以免打断连线。
        view = _encoding_target(spec)
        if view is None:
            return
        for cand in _iter_encoding_views(spec):
            cenc = cand.get("encoding") if isinstance(cand.get("encoding"), dict) else None
            color0 = cenc.get("color") if isinstance(cenc, dict) else None
            if not isinstance(color0, dict) or not color0.get("field"):
                continue
            scale0 = color0.get("scale") if isinstance(color0.get("scale"), dict) else {}
            domain0 = scale0.get("domain") if isinstance(scale0.get("domain"), list) else []
            if len(domain0) >= 2:
                return
        base = op.get("base_color") if isinstance(op.get("base_color"), str) else None
        if not base:
            base = current_mark_color(spec)
        field = op.get("field")
        value = op.get("value")
        enc = view.setdefault("encoding", {})
        existing = enc.get("color") if isinstance(enc.get("color"), dict) else None
        keep_test = None
        if existing and not existing.get("field"):
            cond0 = existing.get("condition")
            if (
                isinstance(cond0, dict)
                and isinstance(cond0.get("test"), str)
                and cond0["test"].strip()
            ):
                keep_test = cond0["test"]
        if keep_test:
            enc["color"] = {
                "condition": {"test": keep_test, "value": op["color"]},
                "value": base,
            }
        else:
            enc["color"] = {
                "condition": {
                    "test": _highlight_condition_test(field, value),
                    "value": op["color"],
                },
                "value": base,
            }
        for target in _paint_targets(spec):
            mark = target.get("mark")
            if isinstance(mark, dict):
                mark.pop("color", None)
                mark.pop("fill", None)

    elif action == "set_legend":
        # 遍历全部带 color.field 的图例（含独立 scale 多 layer）
        touched = 0
        views = list(_iter_unit_views(spec))
        if isinstance(spec.get("encoding"), dict):
            views = [spec] + views
        for view in views:
            enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else None
            if not isinstance(enc, dict):
                continue
            color = enc.get("color")
            if not isinstance(color, dict) or not color.get("field"):
                continue
            legend = color.get("legend")
            if legend is None and "legend" in color:
                continue  # 显式 legend:null
            if not isinstance(legend, dict):
                legend = {}
            if "orient" in op:
                legend["orient"] = op["orient"]
                legend.pop("legendX", None)
                legend.pop("legendY", None)
            if "title" in op:
                legend["title"] = op["title"]
            for key in ("labelColor", "titleColor", "labelFontSize", "titleFontSize", "symbolSize", "columns", "direction"):
                if key in op:
                    legend[key] = op[key]
            color["legend"] = legend
            touched += 1
        if touched == 0:
            view = _encoding_target(spec)
            enc = view.get("encoding") if isinstance(view, dict) else None
            color = enc.get("color") if isinstance(enc, dict) else None
            if isinstance(color, dict) and color.get("field"):
                legend = color.get("legend")
                if legend is None and "legend" in color:
                    return
                if not isinstance(legend, dict):
                    legend = {}
                if "orient" in op:
                    legend["orient"] = op["orient"]
                    legend.pop("legendX", None)
                    legend.pop("legendY", None)
                if "title" in op:
                    legend["title"] = op["title"]
                for key in ("labelColor", "titleColor", "labelFontSize", "titleFontSize", "symbolSize", "columns", "direction"):
                    if key in op:
                        legend[key] = op[key]
                color["legend"] = legend

    elif action == "merge_config":
        cfg_in = op["config"]
        if (isinstance(spec.get("usermeta"), dict) and spec["usermeta"].get("component_assembly")) or fixed_layout:
            # 未迁移的绝对文字也不能用根 padding 改变绘图区原点；已分区图同理。
            cfg_in = {k: v for k, v in cfg_in.items() if k != "padding"}
            if not cfg_in:
                return
        cfg = copy.deepcopy(cfg_in)
        deep_merge(spec.setdefault("config", {}), cfg)
        # 自绘网格：同步 stroke，否则只改 axis config 不可见
        axis_y = cfg.get("axisY") if isinstance(cfg.get("axisY"), dict) else {}
        if isinstance(axis_y.get("gridColor"), str):
            _recolor_drawn_grids(spec, axis_y["gridColor"])

    elif action == "set_size":
        if (isinstance(spec.get("usermeta"), dict) and spec["usermeta"].get("component_assembly")) or fixed_layout:
            return
        # 导出式复合图宽高在根上；避免给每层装饰 unit 写尺寸
        if op.get("width"):
            spec["width"] = op["width"]
        if op.get("height"):
            spec["height"] = op["height"]

    elif action == "set_background":
        spec["background"] = op["color"]

    elif action == "set_title_anchor":
        if spec.get("title") is not None:
            _title_obj(spec)["anchor"] = op.get("anchor", "start")
        deep_merge(spec.setdefault("config", {}), {"title": {"anchor": op.get("anchor", "start")}})

    elif action == "set_subtitle":
        title = _title_obj(spec)
        if op.get("preserve_source"):
            # 写入语境副标题时保留已有 Source 行
            existing = _subtitle_lines(title.get("subtitle"))
            source_lines = [ln for ln in existing if is_source_text(ln)]
            context = str(op.get("text") or "").strip()
            lines = ([context] if context else []) + source_lines
            title["subtitle"] = lines if len(lines) > 1 else (lines[0] if lines else context)
        else:
            title["subtitle"] = op["text"]
        if op.get("font_size"):
            title["subtitleFontSize"] = op["font_size"]
        if op.get("color"):
            title["subtitleColor"] = op["color"]

    elif action == "set_source_note":
        # 追加/替换来源行，不覆盖描述性副标题
        note = _format_source_note(str(op.get("text") or ""))
        title = _title_obj(spec)
        lines = [ln for ln in _subtitle_lines(title.get("subtitle")) if not is_source_text(ln)]
        lines.append(note)
        title["subtitle"] = lines if len(lines) > 1 else lines[0]
        if op.get("font_size") is not None and len(lines) == 1:
            # 仅来源一行时可把副标题字级收成 caption
            title["subtitleFontSize"] = op["font_size"]
        if op.get("color"):
            title["subtitleColor"] = op["color"]

    elif action == "set_title_text":
        text = op.get("text")
        if text is None:
            return
        if isinstance(text, list):
            text = " ".join(str(x) for x in text)
        text = str(text)
        # 根 title（重建后 chrome 标题多落在此）
        title = _title_obj(spec)
        old = title.get("text")
        old_s = str(old).strip() if isinstance(old, str) and str(old).strip() else ""
        title["text"] = text
        # 仅同步「文案已是旧标题」的自绘 title 层；勿把 annotation/说明行改成标题
        synced = 0
        for u in title_text_units(spec):
            if u["role"] != "title":
                continue
            mark = _ensure_mark_obj(u["view"])
            prev = mark.get("text")
            if isinstance(prev, str) and old_s and prev.strip() == old_s:
                mark["text"] = text
                synced += 1
        if synced == 0 and not old_s:
            # 无根标题历史：只改字号最大的一个 title 层
            cands = [u for u in title_text_units(spec) if u.get("role") == "title"]
            if cands:
                best = max(
                    cands,
                    key=lambda u: float(
                        ((u.get("mark_obj") or {}) if isinstance(u.get("mark_obj"), dict) else {}).get(
                            "fontSize"
                        )
                        or (
                            (u["view"].get("mark") or {}).get("fontSize")
                            if isinstance(u["view"].get("mark"), dict)
                            else 0
                        )
                        or 0
                    ),
                )
                _ensure_mark_obj(best["view"])["text"] = text

    elif action == "set_font":
        fam = resolve_font_family_value(op.get("family")) or str(op.get("family") or "").strip()
        if not fam:
            return
        _strip_channel_fonts(spec)
        deep_merge(spec.setdefault("config", {}), _font_config_patch(family=fam))
        _apply_root_title_font(spec, family=fam)
        _patch_title_text_layers(spec, family=fam)
        _patch_all_text_marks(spec, family=fam)

    elif action == "remove_value_labels":
        # 密集柱上数字重叠：去掉 field-bound text 标签层（不删标题/来源）
        _remove_value_label_layers(spec)

    elif action == "thin_axis_labels":
        # 密轴刻度：稀疏 values / 加大 labelPadding（不碰柱上数值层）
        channel = op.get("channel") if isinstance(op.get("channel"), str) else "x"
        try:
            max_ticks = int(op.get("max_ticks") or 8)
        except (TypeError, ValueError):
            max_ticks = 8
        max_ticks = max(3, min(max_ticks, 16))
        _thin_axis_labels(spec, channel=channel, max_ticks=max_ticks)

    elif action == "set_axis":
        channel = op.get("channel") if isinstance(op.get("channel"), str) else "x"
        _set_axis(
            spec,
            channel,
            axis_patch=op.get("axis") if isinstance(op.get("axis"), dict) else None,
            scale_patch=op.get("scale") if isinstance(op.get("scale"), dict) else None,
        )

    elif action == "set_mark_style":
        _set_mark_style(spec, op.get("style") if isinstance(op.get("style"), dict) else {})

    elif action == "set_text_style":
        _set_text_style(spec, op.get("style") if isinstance(op.get("style"), dict) else {})

    elif action == "set_encoding_style":
        channel = str(op.get("channel") or "shape")
        _set_encoding_style(spec, channel, op.get("style") if isinstance(op.get("style"), dict) else {})

    elif action == "sort_categories":
        order = "asc" if str(op.get("order") or "desc").lower().startswith("asc") else "desc"
        _sort_categories(spec, order)

    elif action == "set_orientation":
        # 像素定位文字的导出图翻转会错位，保持不动（同 set_size 的结构不变量）
        if str(op.get("to") or "horizontal").lower() == "horizontal" and not fixed_layout:
            _set_orientation_horizontal(spec)

    elif action == "add_value_labels":
        _add_value_labels(spec, op.get("format") if isinstance(op.get("format"), str) else None)

    elif action == "direct_label":
        _direct_label(spec)

    elif action == "set_axis_zero":
        _set_quant_axis_scale(spec, {"zero": True})

    elif action == "set_grid_style":
        _set_grid_style(
            spec,
            str(op["style"]).lower() if isinstance(op.get("style"), str) else None,
            op.get("color") if isinstance(op.get("color"), str) else None,
            op.get("opacity"),
        )

    elif action == "set_band_padding":
        _set_band_padding(spec, op.get("inner"), op.get("outer"))

    elif action == "normalize_axis_title_layout":
        from .layout_audit import normalize_axis_title_layout

        normalize_axis_title_layout(spec)

    elif action == "set_font_sizes":
        _strip_channel_fonts(spec)
        assembled = isinstance(spec.get("usermeta"), dict) and bool(spec["usermeta"].get("component_assembly"))
        axis_label = op.get("axis_label")
        # 密轴水平长标签时，机构轴字号（如 BBC 18）会重新制造重叠
        if axis_label is not None and _x_axis_still_crowded(spec):
            try:
                if float(axis_label) > 13:
                    axis_label = 13
            except (TypeError, ValueError):
                pass
        sizes = {
            "title": op.get("title"),
            # A component compiler owns header/footer sizing.  A generic L1
            # subtitle token must not invalidate its measured wrapping geometry.
            "subtitle": None if assembled else op.get("subtitle"),
            "axis_label": axis_label,
            "axis_title": op.get("axis_title"),
            "legend_label": op.get("legend_label"),
        }
        deep_merge(spec.setdefault("config", {}), _font_config_patch(sizes=sizes))
        if op.get("title") is not None or op.get("subtitle") is not None:
            _apply_root_title_font(
                spec,
                font_size=op.get("title"),
                subtitle_size=None if assembled else op.get("subtitle"),
            )
        if op.get("title") is not None:
            _patch_title_text_layers(spec, font_size=op["title"])
        _patch_all_text_marks(
            spec,
            title_size=op.get("title"),
            body_size=op.get("subtitle") or op.get("axis_label"),
        )

    else:
        raise ValueError(f"未知 action: {action}")


def _spec_fingerprint(spec: dict) -> str:
    """稳定序列化，用于判定 apply 是否真改写了 spec。"""
    return json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass
class EffectReport:
    """单次 apply_ops 的落地效果（拍4 / Composer 共用）。"""

    changed: bool
    noop_actions: list[str] = field(default_factory=list)
    applied_actions: list[str] = field(default_factory=list)


def apply_ops_with_effect(spec: dict, ops: list[dict]) -> tuple[dict, EffectReport]:
    """深拷贝后逐条 apply_op；按前后 fingerprint 判定是否生效。

    不改变各 apply_op 分支语义；静默 no-op 表现为 changed=False。
    """
    before_all = _spec_fingerprint(spec)
    out = copy.deepcopy(spec)
    noop_actions: list[str] = []
    applied_actions: list[str] = []
    for op in ops or []:
        if not isinstance(op, dict):
            continue
        action = str(op.get("action") or "unknown")
        before = _spec_fingerprint(out)
        apply_op(out, op)
        after = _spec_fingerprint(out)
        if before == after:
            noop_actions.append(action)
        else:
            applied_actions.append(action)
    changed = before_all != _spec_fingerprint(out)
    return out, EffectReport(
        changed=changed, noop_actions=noop_actions, applied_actions=applied_actions
    )


def apply_ops(spec: dict, ops: list[dict]) -> dict:
    out, _report = apply_ops_with_effect(spec, ops)
    return out


def describe_op(op: dict) -> str:
    """op → 英文祈使句（前端 prompt 组装语言）。"""
    a = op.get("action")
    if op.get("note"):
        return str(op["note"])
    if a == "set_mark_color":
        return f"Set all marks to {op['color']}."
    if a == "set_mark_type":
        chart_type = op.get("chart_type") or op["mark_type"]
        return f"Change the chart type to {chart_type}."
    if a == "remove_encoding_channel":
        return f"Remove the {op['channel']} encoding."
    if a == "set_color_range":
        return f"Use the palette {', '.join(op['colors'])}."
    if a == "highlight_category":
        return f"Highlight '{op['value']}' in {op['color']} and render the rest in the base color."
    if a == "set_legend":
        parts = []
        if op.get("orient"):
            parts.append(f"move the legend to {op['orient']}")
        if "title" in op and op["title"] is None:
            parts.append("remove the legend title")
        return ("; ".join(parts) + ".").capitalize() if parts else "Adjust the legend."
    if a == "merge_config":
        return "Apply the config adjustments."
    if a == "set_size":
        return f"Resize the chart to {op.get('width')}x{op.get('height')}px."
    if a == "set_background":
        return f"Set the chart background to {op['color']}."
    if a == "set_title_anchor":
        return "Left-align the title block."
    if a == "set_title_text":
        return f"Set the title to \"{op.get('text')}\"."
    if a == "set_subtitle":
        return f"Add the subtitle line \"{op['text']}\"."
    if a == "set_source_note":
        return f"Add source attribution: {op.get('text')}."
    if a == "set_font":
        return f"Use the {op['family']} font family."
    if a == "set_font_sizes":
        kv = ", ".join(f"{k}={v}" for k, v in op.items() if k not in ("action", "note") and v)
        return f"Set font sizes ({kv})."
    if a == "remove_value_labels":
        return "Remove per-mark value label text layers to reduce overlap."
    if a == "thin_axis_labels":
        ch = op.get("channel") or "x"
        return f"Thin dense {ch}-axis tick labels to reduce crowding."
    if a == "set_axis":
        ch = op.get("channel") or "x"
        return f"Adjust safe {ch}-axis ticks, labels, grid, or scale settings."
    if a == "set_mark_style":
        return "Adjust safe primary-mark styling."
    if a == "set_text_style":
        return "Adjust safe text and annotation styling."
    if a == "set_encoding_style":
        return f"Adjust the {op.get('channel', 'visual')} encoding and its legend or scale."
    if a == "normalize_axis_title_layout":
        return "Normalize axis title layout (drop brittle absolute offsets / orphaned horizontal y titles)."
    if a == "sort_categories":
        return f"Sort categories by value, {'ascending' if op.get('order') == 'asc' else 'descending'}."
    if a == "set_orientation":
        return "Flip the bar chart to horizontal bars (categories on the y-axis)."
    if a == "add_value_labels":
        return "Label each bar with its value directly on the chart."
    if a == "direct_label":
        return "Drop the legend and label series/categories directly on the chart."
    if a == "set_axis_zero":
        return "Start the value axis at zero."
    if a == "set_grid_style":
        return f"Use {op.get('style', 'dotted')} gridlines."
    if a == "set_band_padding":
        return "Tune bar width versus gap rhythm (band padding)."
    if a == "compose_component":
        comp = op.get("component") or "component"
        paths = [p for p in (op.get("spec_paths") or []) if isinstance(p, str)]
        if paths:
            return f"Apply this institution's {comp} treatment ({len(paths)} properties)."
        return f"Apply this institution's {comp} treatment."
    return str(a)


def describe_ops(ops: list[dict]) -> str:
    return " ".join(describe_op(op) for op in ops)


def _prefer_applies(verb: str) -> bool:
    """prefer 是否与 set 同权执行：非 prefer 动词恒 True；prefer 仅在 prefer_mode=apply。"""
    if verb != "prefer":
        return True
    from app.config import settings

    return settings.prefer_mode == "apply"


def _pack_set_mark_type_op(
    mark_type: str,
    facts: dict,
    *,
    chart_type: str | None = None,
) -> dict[str, Any]:
    """打包 set_mark_type；有类别/数值字段时附带 rebuild_unit（复合 layer 折叠）。"""
    chart = _normalize_chart_type_key(chart_type or "")
    lineish = mark_type in ("line", "area", "point", "circle", "trail", "tick")
    # histogram 只需数值字段；其余改型优先带齐 category+value
    need_pair = chart != "histogram"
    op: dict[str, Any] = {"action": "set_mark_type", "mark_type": mark_type}
    if chart:
        op["chart_type"] = chart
    cat = facts.get("category_field")
    val = facts.get("value_field")
    color_f = facts.get("color_field")
    if color_f:
        op["color_field"] = color_f
    if chart == "bubble":
        op["size_from_value"] = True
    if chart == "histogram" and val:
        op.update({"rebuild_unit": True, "value_field": val})
        return op
    if cat and val:
        op.update(
            {
                "rebuild_unit": True,
                "category_field": cat,
                "value_field": val,
                "category_channel": facts.get("category_channel")
                or ("x" if lineish else "y"),
            }
        )
    if chart in ("pie", "donut"):
        if cat:
            op["category_field"] = cat
        if val:
            op["value_field"] = val
        if cat and val:
            op["rebuild_unit"] = True
    elif need_pair and mark_type == "boxplot" and cat and val:
        op["rebuild_unit"] = True
    return op


def _should_rebuild_mark_type(spec: dict, op: dict, targets: list[dict]) -> bool:
    """显式 rebuild_unit，或复合多几何层且 op 已带字段时兜底折叠。

    单 unit 上连续改型（如 user pie → persona line）也必须重建 encoding，
    否则会出现 mark=line 却残留 theta/color 的不可渲染组合。
    """
    target_type = str(op.get("mark_type") or "").lower()
    # 组合图常带 brush rect、reference rule 等辅助层。若主数据几何已经是
    # 目标类型，绝不能因为这些辅助层不同就把整个图折叠为一个 unit。
    primary_types = {
        str(_mark_type(view.get("mark")) or "").lower()
        for view in primary_paint_targets(spec)
        if _mark_type(view.get("mark")) not in ANNOTATION_MARKS
    }
    if target_type and primary_types and primary_types == {target_type}:
        return False
    current_types = {
        str(_mark_type(t.get("mark")) or "").lower()
        for t in targets
        if _mark_type(t.get("mark")) not in ANNOTATION_MARKS
    }
    # Same-type requests are style/idempotence operations, never permission to
    # flatten vconcat/layer or discard detail, tooltip, dash, and annotation layers.
    if target_type and current_types and current_types == {target_type}:
        return False
    multi = _is_composition(spec) or len(targets) != 1
    has_fields = bool(op.get("category_field") and op.get("value_field"))
    if op.get("rebuild_unit") and has_fields:
        return True
    if op.get("rebuild_unit") and (multi or not targets):
        return True
    if multi and has_fields:
        return True
    return False


def _same_primary_mark_type(spec: dict, op: dict) -> bool:
    target_type = str(op.get("mark_type") or "").lower()
    if not target_type:
        return False
    primary_types = {
        str(_mark_type(view.get("mark")) or "").lower()
        for view in primary_paint_targets(spec)
        if _mark_type(view.get("mark")) not in ANNOTATION_MARKS
    }
    return bool(primary_types) and primary_types == {target_type}


# ---------------------------------------------------------------------------
# L2 then → ops 编译
# ---------------------------------------------------------------------------

def _parse_size(to: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\d+", str(to))
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    return None, None


def _parse_number(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def compile_then(persona, then: Any, facts: dict) -> dict:
    """把 L2 的 then 编译为 ops。

    返回 {ops, needs, renderable, any_of, note}：
    - needs=["emphasis_target"]：需要慢道语义槽位才能落地（快道升级）；
    - renderable=False：目标超出单图 spec（版式/图型迁移/语义色板），只能作为建议；
    - any_of：策略候选，交慢道择一。
    """
    out = {"ops": [], "needs": [], "renderable": True, "any_of": None, "note": ""}
    if not isinstance(then, dict):
        out["renderable"] = False
        out["note"] = str(then) if then else ""
        return out

    if "any-of" in then:
        out["any_of"] = [str(s) for s in then["any-of"]]
        return out

    if "enforce" in then or "round" in then:
        out["renderable"] = False
        out["note"] = str(then.get("enforce") or then.get("round"))
        return out

    verb = next((v for v in ("set", "prefer", "override") if v in then), None)
    if verb is None:
        out["renderable"] = False
        return out
    target = then[verb]
    to = then.get("to")

    # set 直接挂 {path: value} 字典的形式（如 grid.gap）
    if isinstance(target, dict):
        if any(NON_CHART_TARGET.match(str(k)) for k in target):
            out["renderable"] = False
            out["note"] = "; ".join(f"{k}: {v}" for k, v in target.items())
            return out
        out["renderable"] = False
        return out

    target = str(target)
    if target == "chart.type":
        chart_type = _normalize_chart_type_key(to)
        mark_type = CHART_TYPE_MARK_ALIASES.get(chart_type, chart_type)
        from app.config import settings

        # Persona 不能在锁定模式下自动改图型。该门必须同时覆盖 set、prefer、
        # override，避免 parser 中的强措辞绕过“禁止改图型”模式。
        if not settings.advisor_chart_type_changes_enabled:
            out["renderable"] = False
            out["note"] = f"{verb} chart.type → {to}（机构图型改动当前锁定，仅建议）"
            return out
        # 开放模式下：prefer 仍受 prefer_mode 控制；set/override 可执行。
        prefer_ok = _prefer_applies(verb)
        can_execute = prefer_ok and mark_type in EXECUTABLE_MARKS
        if can_execute:
            op = _pack_set_mark_type_op(mark_type, facts, chart_type=chart_type)
            out["ops"].append(op)
            if verb == "prefer":
                out["note"] = f"prefer chart.type → {to} (apply mode)"
        else:
            out["renderable"] = False
            note = f"{verb} chart.type → {to}"
            if chart_type in NON_EXECUTABLE_CHART_TYPES or mark_type not in EXECUTABLE_MARKS:
                note += "（VL 无原生 mark / 本轮仅建议）"
            out["note"] = note
        return out

    def _resolve_style(style: dict) -> dict:
        resolved = {}
        for key, value in style.items():
            if isinstance(value, str):
                color = persona.resolve_color(value)
                resolved[key] = color or value
            else:
                resolved[key] = value
        return resolved

    if NON_CHART_TARGET.match(target):
        out["renderable"] = False
        out["note"] = f"{verb} {target} → {to}"
        return out

    if target == "mark.color":
        color = persona.resolve_color(to)
        if not color:
            out["renderable"] = False
            return out
        mode = str(facts.get("coloring_mode") or "uniform")
        # 仅在「应收束为单色」时去掉类别 color；categorical/paired 由慢道改走 color.range
        if facts.get("per_category_coloring") and mode not in ("categorical", "paired"):
            out["ops"].append({"action": "remove_encoding_channel", "channel": "color"})
        op: dict[str, Any] = {"action": "set_mark_color", "color": color}
        # 字面 value/condition 着色：尽量用色板第二色保留强调条
        if facts.get("literal_color_encoding") and facts.get("accent_color"):
            palette = persona.resolve_color_list("{palette.categorical}") or []
            accent = next((c for c in palette if isinstance(c, str) and c != color), None)
            if not accent:
                for key in ("bbc-orange", "color.bbc-orange", "hong-kong", "color.accent"):
                    accent = persona.resolve_color(key) or persona.resolve_color(f"{{{key}}}")
                    if accent and accent != color:
                        break
            if accent:
                op["accent_color"] = accent
        out["ops"].append(op)

    elif target == "color.range":
        colors = persona.resolve_color_list(to)
        if not colors:
            out["renderable"] = False
            return out
        # 类别/系列身份靠 color 区分时写入 range；无 color 通道才退化为单色
        if (
            facts.get("color_field")
            or facts.get("per_category_coloring")
            or str(facts.get("coloring_mode") or "") in ("categorical", "paired")
        ):
            out["ops"].append({"action": "set_color_range", "colors": colors})
        else:
            out["ops"].append({"action": "set_mark_color", "color": colors[0]})
            if facts.get("literal_color_encoding") and len(colors) >= 2:
                out["ops"][-1]["accent_color"] = colors[1]

    elif target == "emphasized-mark.color":
        color = persona.resolve_color(to)
        if not color:
            out["renderable"] = False
            return out
        base = (
            persona.resolve_color("{color.primary}")
            or persona.resolve_color("{color.bbc-blue}")
            or (persona.resolve_color_list("{palette.categorical}") or [None])[0]
        )
        ops, needs = build_emphasis_ops(persona, facts, accent=color, base=base)
        if not ops:
            out["renderable"] = False
            out["note"] = "emphasis binding missing domain/mechanism"
            return out
        out["ops"].extend(ops)
        out["needs"].extend(needs)

    elif target in ("mark.style", "bar.style", "line.style", "point.style", "area.style"):
        style = _resolve_style(to) if isinstance(to, dict) else {}
        # Guide prose commonly names these as bar/line/point properties. Keep the
        # operation broad but bounded by _set_mark_style's Vega-Lite whitelist.
        if style:
            out["ops"].append({"action": "set_mark_style", "style": style})
        else:
            out["renderable"] = False

    elif target.startswith("mark."):
        prop = target.split(".", 1)[1]
        aliases = {
            "opacity": "opacity", "fillOpacity": "fillOpacity", "strokeOpacity": "strokeOpacity",
            "strokeWidth": "strokeWidth", "strokeDash": "strokeDash", "cornerRadius": "cornerRadius",
            "filled": "filled", "shape": "shape", "size": "size", "interpolate": "interpolate",
            "point": "point", "line": "line",
        }
        if prop in aliases:
            value = persona.resolve_color(to) if isinstance(to, str) else to
            out["ops"].append({"action": "set_mark_style", "style": {aliases[prop]: value or to}})
        else:
            out["renderable"] = False

    elif target in ("axis.x", "axis.y"):
        channel = target[-1]
        patch = to if isinstance(to, dict) else {}
        axis_patch = patch.get("axis", patch)
        scale_patch = patch.get("scale") if isinstance(patch, dict) else None
        if isinstance(axis_patch, dict) or isinstance(scale_patch, dict):
            out["ops"].append({"action": "set_axis", "channel": channel,
                               "axis": axis_patch if isinstance(axis_patch, dict) else {},
                               "scale": scale_patch if isinstance(scale_patch, dict) else {}})
        else:
            out["renderable"] = False

    elif target in ("encoding.shape", "encoding.size"):
        channel = target.split(".", 1)[1]
        patch = to if isinstance(to, dict) else {"field": to}
        if patch:
            out["ops"].append({"action": "set_encoding_style", "channel": channel, "style": patch})
        else:
            out["renderable"] = False

    elif target in ("annotation.style", "text.style"):
        style = _resolve_style(to) if isinstance(to, dict) else {}
        if style:
            out["ops"].append({"action": "set_text_style", "style": style})
        else:
            out["renderable"] = False

    elif target == "supporting-mark.color":
        # 需要"辅助序列"证据，当前事实通道无此语义 → 建议
        out["renderable"] = False
        out["note"] = f"supporting series → {to}"

    elif target == "chart.size":
        w, h = _parse_size(to)
        if w and h:
            out["ops"].append({"action": "set_size", "width": w, "height": h})
        else:
            out["renderable"] = False

    elif target in ("chart.background", "background"):
        color = persona.resolve_color(to)
        if color:
            out["ops"].append({"action": "set_background", "color": color})
        else:
            out["renderable"] = False

    elif target == "font.family":
        resolved = persona.resolve_token(to)
        family: str | None = None
        if isinstance(resolved, str) and resolved.strip():
            family = resolved.strip()
            if family.startswith("--"):
                family = resolve_font_family_value(family)
        elif isinstance(resolved, dict):
            family = resolve_font_family_value(resolved)
        if not family:
            family = persona_font_family(persona)
        if family:
            out["ops"].append({"action": "set_font", "family": family})
        else:
            out["renderable"] = False

    elif target == "font.sizes":
        if not isinstance(to, dict):
            out["renderable"] = False
        else:
            size_op: dict = {"action": "set_font_sizes"}
            aliases = {
                "title": "title",
                "subtitle": "subtitle",
                "body": "axis_label",
                "axis": "axis_label",
                "axis_label": "axis_label",
                "axis_title": "axis_title",
                "legend": "legend_label",
                "legend_label": "legend_label",
            }
            for raw_key, raw_value in to.items():
                key = aliases.get(str(raw_key))
                number = _parse_number(persona.resolve_token(raw_value))
                if key and number:
                    size_op[key] = number
            if len(size_op) > 1:
                out["ops"].append(size_op)
            else:
                out["renderable"] = False

    elif target == "title.anchor":
        anchor = str(to or "").strip()
        if anchor in ("start", "middle", "end"):
            out["ops"].append({"action": "set_title_anchor", "anchor": anchor})
        else:
            out["renderable"] = False

    elif target == "legend.orient":
        orient = str(to or "").strip()
        if orient:
            out["ops"].append({"action": "set_legend", "orient": orient})
        else:
            out["renderable"] = False

    elif target == "legend.title":
        out["ops"].append({"action": "set_legend", "title": to})

    elif target == "legend.style":
        style = to if isinstance(to, dict) else {}
        allowed = {"orient", "title", "labelColor", "titleColor", "labelFontSize", "titleFontSize", "symbolSize", "columns", "direction"}
        op = {"action": "set_legend", **{k: v for k, v in style.items() if k in allowed}}
        if len(op) > 1:
            out["ops"].append(op)
        else:
            out["renderable"] = False

    elif target == "grid.horizontal":
        color = persona.resolve_color(to)
        if color:
            out["ops"].append(
                {
                    "action": "merge_config",
                    "config": {"axisY": {"grid": True, "gridColor": color}},
                }
            )
        else:
            out["renderable"] = False

    elif target == "grid.vertical":
        enabled = bool(to)
        out["ops"].append(
            {"action": "merge_config", "config": {"axisX": {"grid": enabled}}}
        )

    elif target == "axis.zero":
        if to is True or str(to or "").strip().lower() in ("on", "true", "yes", "zero", "0"):
            out["ops"].append({"action": "set_axis_zero"})
        else:
            out["renderable"] = False

    elif target == "grid.style":
        style = str(to or "").strip().lower()
        if style in _GRID_DASH:
            op: dict[str, Any] = {"action": "set_grid_style", "style": style}
            grid_color = persona.resolve_color("grid")
            if grid_color:
                op["color"] = grid_color
            out["ops"].append(op)
        else:
            out["renderable"] = False
            out["note"] = f"grid style → {to}"

    elif target in ("labels.values", "data.labels"):
        if str(facts.get("mark_type") or "") == "bar":
            op = {"action": "add_value_labels"}
            if isinstance(to, str) and to.strip().lower() not in ("on", "true", "yes"):
                op["format"] = to.strip()  # then.to 可直接携带 d3 数字格式
            out["ops"].append(op)
        else:
            out["renderable"] = False
            out["note"] = "value labels compile for bar marks only (for now)"

    elif target in ("labels.direct", "legend.direct"):
        if facts.get("has_legend") or facts.get("color_field"):
            out["ops"].append({"action": "direct_label"})
        else:
            out["renderable"] = False
            out["note"] = "no legend/series to direct-label"

    elif target in ("sort.categories", "category.order"):
        if facts.get("category_field") and str(facts.get("mark_type") or "") in ("bar", "tick"):
            order = "asc" if str(to or "").strip().lower().startswith("asc") else "desc"
            out["ops"].append({"action": "sort_categories", "order": order})
        else:
            out["renderable"] = False
            out["note"] = "no categorical axis to sort"

    elif target == "orientation":
        if str(to or "").strip().lower() == "horizontal" and str(facts.get("mark_type") or "") == "bar":
            out["ops"].append({"action": "set_orientation", "to": "horizontal"})
        else:
            out["renderable"] = False
            out["note"] = f"orientation → {to}"

    elif target == "bar.spacing":
        if str(facts.get("mark_type") or "") != "bar":
            out["renderable"] = False
            out["note"] = "band padding applies to bar charts only"
        elif isinstance(to, dict):
            op = {"action": "set_band_padding"}
            if to.get("inner") is not None:
                op["inner"] = to["inner"]
            if to.get("outer") is not None:
                op["outer"] = to["outer"]
            out["ops"].append(op)
        elif str(to or "").strip().lower() in ("bars-2x-gap", "2x-gap"):
            # 柱宽 ≈ 2×间隙 → gap/(bar+gap)=1/3
            out["ops"].append({"action": "set_band_padding", "inner": 0.33, "outer": 0.17})
        else:
            out["renderable"] = False
            out["note"] = f"bar spacing → {to}"

    elif target == "axis.tick-density":
        max_ticks = _parse_number(to)
        if max_ticks:
            out["ops"].append({"action": "thin_axis_labels", "channel": "x", "max_ticks": int(max_ticks)})
        else:
            out["renderable"] = False

    elif target == "axis.label-angle":
        if to in (0, "0") or str(to or "").strip().lower() == "horizontal":
            out["ops"].append({"action": "set_axis", "channel": "x", "axis": {"labelAngle": 0}})
        else:
            out["renderable"] = False
            out["note"] = f"axis label angle → {to}"

    elif target == "source.required":
        if bool(to):
            caption_size = _parse_number(
                persona.token_index().get("font.size.caption")
                or persona.token_index().get("font.size.axis_label")
                or 14
            ) or 14
            text_color = (
                persona.resolve_color("text")
                or persona.resolve_color("grid")
                or "#333333"
            )
            out["ops"].append(
                {
                    "action": "set_source_note",
                    "text": "Source: —",
                    "font_size": caption_size,
                    "color": text_color,
                    "note": "Add a Source: attribution; replace — with the provider.",
                }
            )
        else:
            out["renderable"] = False

    else:
        out["renderable"] = False
        out["note"] = f"{verb} {target} → {to}"

    return out


def _series_range_with_emphasis(
    domain: list[Any],
    emphasize: Any,
    accent: str,
    palette: list[str],
) -> list[str]:
    """按 domain 顺序着色：强调项用 accent，其余按机构色板轮转（跳过与 accent 相同）。"""
    if not domain:
        return []
    rest = [c for c in palette if isinstance(c, str) and c != accent]
    if not rest:
        rest = [c for c in palette if isinstance(c, str)] or [accent]
    out: list[str] = []
    j = 0
    emp = str(emphasize).strip() if emphasize is not None else ""
    for d in domain:
        if emp and str(d).strip() == emp:
            out.append(accent)
        else:
            out.append(rest[j % len(rest)])
            j += 1
    return out


def build_emphasis_ops(
    persona: Any,
    facts: dict,
    *,
    accent: str,
    base: str | None = None,
) -> tuple[list[dict], list[str]]:
    """按 Decision IR 的 emphasis_mechanism 编译强调 ops（不发明 hex）。"""
    from .decision_ir import infer_color_structure, infer_emphasis_binding

    local = dict(facts)
    if not local.get("emphasis_mechanism") or not local.get("emphasis_field"):
        bind = infer_emphasis_binding(
            local,
            emphasis_target=local.get("emphasis_target"),
            color_structure=infer_color_structure(local),
        )
        local.update({k: v for k, v in bind.items() if v is not None})

    mech = local.get("emphasis_mechanism")
    field = local.get("emphasis_field")
    value = local.get("emphasis_target")
    palette = []
    if hasattr(persona, "resolve_color_list"):
        palette = [c for c in (persona.resolve_color_list("{palette.categorical}") or []) if isinstance(c, str)]
    if not palette and hasattr(persona, "ui"):
        palette = [c for c in ((persona.ui or {}).get("palette") or []) if isinstance(c, str)]
    primary = (
        base
        or (hasattr(persona, "resolve_color") and persona.resolve_color("{color.primary}"))
        or (palette[0] if palette else None)
    )

    if mech == "series_scale":
        domain = list(local.get("series_values") or [])
        needs = [] if value is not None else ["emphasis_target"]
        if not domain:
            return [], needs or ["emphasis_target"]
        if value is None:
            return [
                {
                    "action": "set_color_range",
                    "colors": [],
                    "_emphasis_fill": {
                        "kind": "series_scale",
                        "accent": accent,
                        "domain": domain,
                        "palette": palette,
                    },
                }
            ], ["emphasis_target"]
        colors = _series_range_with_emphasis(domain, value, accent, palette or [accent, primary or accent])
        return [{"action": "set_color_range", "colors": colors}], []

    if mech == "literal_condition":
        op: dict[str, Any] = {
            "action": "set_mark_color",
            "color": primary or accent,
            "accent_color": accent,
        }
        return [op], []

    # category_condition
    needs = [] if value is not None else ["emphasis_target"]
    return [
        {
            "action": "highlight_category",
            "field": field,
            "value": value,
            "color": accent,
            "base_color": primary,
        }
    ], needs


def fill_emphasis_ops(ops: list[dict], facts: dict, target: Any = None) -> list[dict]:
    """填充/改写强调占位 ops（拍3/拍4 在 emphasis_target 就绪后调用）。"""
    value = target if target is not None else facts.get("emphasis_target")
    filled: list[dict] = []
    for op in ops:
        meta = op.get("_emphasis_fill") if isinstance(op, dict) else None
        if isinstance(meta, dict) and meta.get("kind") == "series_scale":
            if value is None:
                continue
            domain = list(meta.get("domain") or facts.get("series_values") or [])
            accent = meta.get("accent") or op.get("accent_color")
            palette = list(meta.get("palette") or [])
            if not isinstance(accent, str):
                continue
            colors = _series_range_with_emphasis(domain, value, accent, palette or [accent])
            filled.append({"action": "set_color_range", "colors": colors})
            continue
        if isinstance(op, dict) and op.get("action") == "highlight_category":
            field = facts.get("emphasis_field") or op.get("field")
            filled.append({**op, "value": value, "field": field})
            continue
        filled.append(op)
    return filled


def compile_strategy(persona, strategy: str, facts: dict) -> dict:
    """any-of 策略文本 → ops（慢道择一后调用）。可执行的策略：单一强色高亮。"""
    out = {"ops": [], "needs": [], "renderable": True, "note": strategy}
    if "高亮" in strategy or "强色" in strategy or "highlight" in strategy.lower():
        strong = persona.ui.get("brand_color") or (persona.ui.get("palette") or [None])[0]
        if strong:
            base = (
                persona.resolve_color("{color.primary}")
                or (persona.resolve_color_list("{palette.categorical}") or [None])[0]
            )
            ops, needs = build_emphasis_ops(persona, facts, accent=strong, base=base)
            if not ops:
                out["renderable"] = False
                return out
            out["ops"] = ops
            out["needs"] = needs
            return out
    out["renderable"] = False
    return out
