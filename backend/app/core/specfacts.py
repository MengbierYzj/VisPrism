"""快道事实提取：从 Vega-Lite spec 程序化提取设计状态事实。

产出供 L2 条件求值与 L1 检测器使用。语义槽位（data_topic / intent /
emphasis_target / summary）留空，由慢道拍1（读图立意）填充——快道只
提取可程序判定的事实，不做语义猜测。

复合图：主几何打分 + 祖先 encoding 合并 + 自绘网格/标题 text 识别
（见 view_geometry）。
"""
from __future__ import annotations

import re
from typing import Any

from .layout_audit import build_layout_slice
from .view_geometry import (
    chrome_digest_for_llm,
    drawn_grid_units,
    is_per_mark_value_label,
    mark_type_of,
    primary_encoding_fields,
    read_paint_color,
    resolve_primary_unit,
    source_text_units,
    title_text_units,
    unit_text_content,
    walk_annotated_units,
)

# vega-lite 默认 categorical 配色（tableau10），用于估计未显式指定颜色时的用色
VEGA_CATEGORY_SCHEME = [
    "#4c78a8", "#f58518", "#e45756", "#72b7b2", "#54a24b",
    "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac",
]
# vega-lite 默认字号（px），作为未显式配置时的事实基线
DEFAULT_FONT_SIZES = {"title": 13, "subtitle": 11, "axis_label": 10, "axis_title": 11, "legend_label": 10}
DEFAULT_GRID_COLOR = "#ddd"


def _channel(enc: dict, name: str) -> dict:
    v = enc.get(name)
    return v if isinstance(v, dict) else {}


def _is_cat(ch: dict) -> bool:
    return ch.get("type") in ("nominal", "ordinal")


def _is_quant(ch: dict) -> bool:
    return ch.get("type") in ("quantitative", "temporal")


def validate_spec(spec: Any) -> list[str]:
    """轻量校验：不是完整 schema 校验，只保证管线可处理。"""
    errors = []
    if not isinstance(spec, dict):
        return ["spec 必须是 JSON 对象"]
    if not any(k in spec for k in ("mark", "layer", "hconcat", "vconcat", "facet", "spec", "concat")):
        errors.append("spec 缺少 mark/layer/concat 等视图定义")
    return errors


# 兼容旧导入名
_ANNOTATION_MARKS = frozenset({"text"})
_COMPOSITION_KEYS = ("layer", "hconcat", "vconcat", "concat")


def _mark_type_of(mark: Any) -> str | None:
    return mark_type_of(mark)


def _walk_unit_views(node: Any, inherited: dict | None = None):
    """兼容旧接口：产出 (unit_view, inherited_props)。"""
    if not isinstance(node, dict):
        return
    for u in walk_annotated_units(node):
        yield u["view"], u["inherited"]


def _resolve_view_for_facts(spec: dict) -> tuple[dict, dict, dict, dict]:
    """解析主几何：返回 (effective_view, inherited, root, primary_meta)。"""
    primary = resolve_primary_unit(spec)
    if not primary:
        return spec, {}, spec, {}
    view = primary["view"]
    inh = primary["inherited"]
    effective = dict(view)
    effective["encoding"] = primary["encoding"]
    if "data" not in effective and "data" in inh:
        effective["data"] = inh["data"]
    if "width" not in effective and "width" in inh:
        effective["width"] = inh["width"]
    if "height" not in effective and "height" in inh:
        effective["height"] = inh["height"]
    return effective, inh, spec, primary


def _has_source(t: Any) -> bool:
    if not t:
        return False
    joined = " ".join(t) if isinstance(t, list) else str(t)
    return "source" in joined.lower() or "来源" in joined


_CALC_BINOP = re.compile(
    r"^datum\.([A-Za-z_][\w]*)\s*([*/+-])\s*(-?\d+(?:\.\d+)?)\s*$"
)
_CALC_FIELD = re.compile(r"^datum\.([A-Za-z_][\w]*)\s*$")


def _eval_simple_calculate(expr: str, row: dict) -> Any:
    """仅支持极值事实所需的简单 calculate，避免引入完整表达式引擎。"""
    e = (expr or "").strip()
    m = _CALC_BINOP.match(e)
    if m:
        field, op, num_s = m.group(1), m.group(2), m.group(3)
        left = row.get(field)
        if not isinstance(left, (int, float)):
            return None
        num = float(num_s)
        if op == "+":
            return left + num
        if op == "-":
            return left - num
        if op == "*":
            return left * num
        if op == "/":
            return left / num if num != 0 else None
        return None
    m2 = _CALC_FIELD.match(e)
    if m2:
        return row.get(m2.group(1))
    return None


def _materialize_calculate_rows(
    rows: list | None, transforms: list | None
) -> list | None:
    """对 rows 物化 calculate 派生列；故意跳过 filter，以免只剩标注年份行。"""
    if not isinstance(rows, list) or not rows:
        return rows
    if not isinstance(transforms, list) or not transforms:
        return rows
    calcs = [
        t
        for t in transforms
        if isinstance(t, dict)
        and isinstance(t.get("calculate"), str)
        and isinstance(t.get("as"), str)
        and t["as"]
    ]
    if not calcs:
        return rows
    out: list = []
    for r in rows:
        if not isinstance(r, dict):
            out.append(r)
            continue
        nr = dict(r)
        for t in calcs:
            alias = t["as"]
            if alias in nr and isinstance(nr[alias], (int, float)):
                continue
            val = _eval_simple_calculate(t["calculate"], nr)
            if val is not None:
                nr[alias] = val
        out.append(nr)
    return out


def structure_baseline(spec: dict) -> dict:
    """Compact loss-detection baseline for the original chart structure."""
    units = walk_annotated_units(spec)
    marks = []
    channels = set()
    for u in units:
        if u.get("mark_type"):
            marks.append(str(u.get("mark_type")))
        view = u.get("view") if isinstance(u.get("view"), dict) else {}
        enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else {}
        channels.update(str(k) for k in enc)
    return {
        "root_composition": next((k for k in ("vconcat", "hconcat", "concat", "layer") if k in spec), "unit"),
        "unit_count": len(units),
        "mark_types": marks,
        "encoding_channels": sorted(channels),
        "annotation_count": sum(1 for u in units if u.get("role") in ("annotation", "source", "title")),
    }


def extract_facts(spec: dict, context: dict | None = None) -> dict:
    context = context or {}
    view, _inh, root, primary = _resolve_view_for_facts(spec)
    enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else {}
    config = root.get("config") if isinstance(root.get("config"), dict) else {}

    mark = view.get("mark")
    mark_type = mark if isinstance(mark, str) else (mark or {}).get("type") if isinstance(mark, dict) else None
    mark_obj = mark if isinstance(mark, dict) else {}

    parent_enc = primary.get("parent_encoding") if isinstance(primary.get("parent_encoding"), dict) else {}

    def _prefer_channel(name: str) -> dict:
        """子层 transform 字段（如 step）不在 data 时，回退祖先通道。"""
        ch = _channel(enc, name)
        pch = _channel(parent_enc, name)
        data_probe = view.get("data") if isinstance(view.get("data"), dict) else {}
        probe_rows = data_probe.get("values") if isinstance(data_probe.get("values"), list) else None
        f = ch.get("field")
        if probe_rows and isinstance(f, str):
            if any(isinstance(r, dict) and f in r for r in probe_rows[:5]):
                return ch
            pf = pch.get("field")
            if isinstance(pf, str) and any(
                isinstance(r, dict) and pf in r for r in probe_rows[:5]
            ):
                return pch
        # 无 data 探针时：父有 field、子像中间量 → 偏父
        if pch.get("field") and ch.get("field") and ch.get("field") != pch.get("field"):
            if not _is_cat(ch) and _is_quant(ch) and (_is_quant(pch) or _is_cat(pch)):
                return pch
        return ch or pch

    x, y, color = _prefer_channel("x"), _prefer_channel("y"), _channel(enc, "color")
    if not color.get("field"):
        color = _channel(parent_enc, "color") or color

    # —— 类别轴 / 数值轴 ——
    category_channel = "x" if _is_cat(x) else ("y" if _is_cat(y) else None)
    category_field = (x if category_channel == "x" else y).get("field") if category_channel else None
    value_field = y.get("field") if y.get("type") == "quantitative" else (
        x.get("field") if x.get("type") == "quantitative" else None
    )
    # 双定量轴（如 Year + Cases）：优先 y 为数值，x 作时间/类别角色
    if category_field is None and _is_quant(x) and _is_quant(y):
        xf, yf = x.get("field"), y.get("field")
        if isinstance(xf, str) and isinstance(yf, str):
            category_field = xf
            category_channel = "x"
            value_field = yf

    data = view.get("data") if isinstance(view.get("data"), dict) else {}
    rows = data.get("values") if isinstance(data.get("values"), list) else None
    # 主几何 encoding 常引用 calculate 派生字段（如 Production_M）
    transforms = None
    if isinstance(primary.get("inherited"), dict):
        transforms = primary["inherited"].get("transform")
    if not transforms and isinstance(view.get("transform"), list):
        transforms = view.get("transform")
    rows = _materialize_calculate_rows(rows, transforms)

    def distinct(field_name):
        if rows is None or not field_name:
            return None
        seen, out = set(), []
        for r in rows:
            if isinstance(r, dict) and field_name in r and r[field_name] not in seen:
                seen.add(r[field_name])
                out.append(r[field_name])
        return out

    categories = distinct(category_field)
    category_count = len(categories) if categories is not None else None

    # —— 序列语义：color 字段与类别轴同字段 = 单序列按类别着色 ——
    color_field = color.get("field")
    # 无 field 的 value/condition 字面着色（强调条等）会盖住 mark.color
    literal_color_encoding = (not color_field) and isinstance(color, dict) and (
        "value" in color or "condition" in color
    )
    per_category_coloring = bool(color_field) and color_field == category_field
    if not color_field:
        series_count = 1
        series_values = []
    elif per_category_coloring:
        series_count = 1
        series_values = categories or []
    else:
        series_values = distinct(color_field)
        series_count = len(series_values) if series_values is not None else None

    # 多 primary area/line 无 color 通道时，用主几何层数估计系列
    units = walk_annotated_units(root)
    primaries = [u for u in units if u["role"] == "primary_data"]
    if not color_field and len(primaries) >= 2:
        series_count = len(primaries)

    # —— 用色事实 ——（含 fill/stroke；condition/value 形态）
    mark_color = read_paint_color(mark_obj)
    scale = color.get("scale") if isinstance(color.get("scale"), dict) else {}
    scale_range = scale.get("range") if isinstance(scale.get("range"), list) else None
    color_value = color.get("value") if isinstance(color.get("value"), str) else None
    cond = color.get("condition") if isinstance(color.get("condition"), dict) else {}
    accent_color = cond.get("value") if isinstance(cond.get("value"), str) else None
    if color_value or accent_color:
        colors_effective = [c for c in (color_value,) if c] or [mark_color or VEGA_CATEGORY_SCHEME[0]]
        color_source = "value"
    elif mark_color and not color_field:
        colors_effective, color_source = [mark_color], "mark"
        paints = []
        for u in primaries:
            c = read_paint_color(u.get("mark_obj") or {})
            if c and c not in paints:
                paints.append(c)
        if len(paints) >= 2:
            colors_effective = paints
            color_source = "mark-layers"
    elif scale_range:
        colors_effective, color_source = [c for c in scale_range if isinstance(c, str)], "scale"
    elif color_field:
        n = category_count if per_category_coloring else (series_count or 0)
        colors_effective = VEGA_CATEGORY_SCHEME[: max(n or 0, 1)]
        color_source = "scheme-default"
    else:
        colors_effective, color_source = [VEGA_CATEGORY_SCHEME[0]], "vega-default"
    color_count = len(colors_effective) + (1 if accent_color else 0)

    # —— 图例 ——
    has_legend = bool(color_field) and color.get("legend", {}) is not None
    legend_cfg = color.get("legend") if isinstance(color.get("legend"), dict) else {}
    legend_orient = legend_cfg.get("orient")
    legend_title = legend_cfg.get("title", "__default__")

    # —— 标题（根 title 或自绘 text 层）——
    title_raw = root.get("title")
    title_from_text_layer = False
    if isinstance(title_raw, dict):
        title_text = title_raw.get("text")
        subtitle = title_raw.get("subtitle")
        title_anchor = title_raw.get("anchor")
    else:
        title_text = title_raw if isinstance(title_raw, str) else None
        subtitle = None
        title_anchor = None
    if title_anchor is None:
        title_anchor = (config.get("title") or {}).get("anchor") if isinstance(config.get("title"), dict) else None

    # 多行 title/subtitle 归一为可读字符串（事实与改写用）
    if isinstance(title_text, list):
        title_text = " ".join(str(x).strip() for x in title_text if str(x).strip())
    if isinstance(subtitle, list):
        subtitle = "\n".join(str(x).strip() for x in subtitle if str(x).strip())

    if not title_text:
        titles = title_text_units(root)
        title_roles = [u for u in titles if u["role"] == "title"]
        pick = title_roles[0] if title_roles else (titles[0] if titles else None)
        if pick:
            blob = unit_text_content(pick)
            if blob:
                title_text = blob
                title_from_text_layer = True
            subs = [u for u in titles if u["role"] == "subtitle"]
            if not subtitle and subs:
                bits = [unit_text_content(u) for u in subs[:4]]
                bits = [b for b in bits if b]
                if bits:
                    subtitle = " ".join(bits)

    source_provider: str | None = None
    has_source_note = False

    def _remember_source(blob: Any) -> None:
        nonlocal source_provider, has_source_note
        if not isinstance(blob, str) or not blob.strip():
            return
        if not _has_source(blob):
            return
        has_source_note = True
        # Source: YouGov / 来源：xxx
        m = re.search(r"(?:source|来源)\s*[:：]\s*([^\n|;]+)", blob, flags=re.I)
        if m and not source_provider:
            source_provider = m.group(1).strip().rstrip(".")

    _remember_source(subtitle if isinstance(subtitle, str) else None)
    _remember_source(title_text if isinstance(title_text, str) else None)
    if isinstance(root.get("description"), str):
        _remember_source(root["description"])
    for u in source_text_units(root):
        _remember_source(unit_text_content(u))
    if not has_source_note:
        for u in units:
            if u["mark_type"] != "text":
                continue
            _remember_source(unit_text_content(u))
            if has_source_note:
                break

    # —— 网格：标准 axis + 自绘 rule ——
    def _grid(ch: dict, axis_key: str) -> tuple[bool, str]:
        axis = ch.get("axis") if isinstance(ch.get("axis"), dict) else {}
        cfg_axis = config.get(axis_key) if isinstance(config.get(axis_key), dict) else {}
        default_on = _is_quant(ch)
        on = axis.get("grid", cfg_axis.get("grid", default_on))
        color_v = axis.get("gridColor", cfg_axis.get("gridColor", DEFAULT_GRID_COLOR))
        return bool(on) if ch else False, color_v

    grid_x, grid_x_color = _grid(x, "axisX")
    grid_y, grid_y_color = _grid(y, "axisY")
    grids = drawn_grid_units(root)
    has_drawn_grid = bool(grids)
    drawn_grid_color = None
    if grids:
        stroke = (grids[0].get("mark_obj") or {}).get("stroke")
        if isinstance(stroke, str):
            drawn_grid_color = stroke
        grid_y = True
        if drawn_grid_color:
            grid_y_color = drawn_grid_color

    # —— 字号 ——
    cfg_title = config.get("title") if isinstance(config.get("title"), dict) else {}
    cfg_axis = config.get("axis") if isinstance(config.get("axis"), dict) else {}
    cfg_legend = config.get("legend") if isinstance(config.get("legend"), dict) else {}
    font_sizes = {
        "title": cfg_title.get("fontSize", DEFAULT_FONT_SIZES["title"]),
        "subtitle": cfg_title.get("subtitleFontSize", DEFAULT_FONT_SIZES["subtitle"]),
        "axis_label": cfg_axis.get("labelFontSize", DEFAULT_FONT_SIZES["axis_label"]),
        "axis_title": cfg_axis.get("titleFontSize", DEFAULT_FONT_SIZES["axis_title"]),
        "legend_label": cfg_legend.get("labelFontSize", DEFAULT_FONT_SIZES["legend_label"]),
    }
    for u in title_text_units(root):
        if u["role"] != "title":
            continue
        fs = (u.get("mark_obj") or {}).get("fontSize")
        if isinstance(fs, (int, float)):
            font_sizes["title"] = fs
            break
    font_family = config.get("font")

    # —— 极值 ——
    max_category = min_category = None
    data_range_ratio = None
    if rows is not None and category_field and value_field:
        best, worst = None, None
        for r in rows:
            if not isinstance(r, dict):
                continue
            v = r.get(value_field)
            if not isinstance(v, (int, float)):
                continue
            if best is None or v > best[1]:
                best = (r.get(category_field), v)
            if worst is None or v < worst[1]:
                worst = (r.get(category_field), v)
        if best:
            max_category = {"name": best[0], "value": best[1]}
        if worst:
            min_category = {"name": worst[0], "value": worst[1]}
        if best and worst and worst[1] > 0:
            data_range_ratio = best[1] / worst[1]

    # 多序列（color 编码系列）：用系列峰值作为要点标题的主体
    if (
        rows is not None
        and color_field
        and value_field
        and color_field != category_field
    ):
        series_best: dict[Any, float] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            key = r.get(color_field)
            v = r.get(value_field)
            if key is None or not isinstance(v, (int, float)):
                continue
            prev = series_best.get(key)
            if prev is None or v > prev:
                series_best[key] = v
        if series_best:
            top_name, top_val = max(series_best.items(), key=lambda kv: kv[1])
            max_category = {"name": top_name, "value": top_val}
            bot_name, bot_val = min(series_best.items(), key=lambda kv: kv[1])
            min_category = {"name": bot_name, "value": bot_val}
            if bot_val > 0:
                data_range_ratio = top_val / bot_val

    width = view.get("width") if isinstance(view.get("width"), (int, float)) else None
    height = view.get("height") if isinstance(view.get("height"), (int, float)) else None
    if width is None and isinstance(root.get("width"), (int, float)):
        width = root["width"]
    if height is None and isinstance(root.get("height"), (int, float)):
        height = root["height"]

    # —— 轴标签密度 / 柱上数值层（供视觉审图分流，非像素启发式）——
    def _axis_tick_count(ch: dict) -> int | None:
        if not isinstance(ch, dict):
            return None
        axis = ch.get("axis") if isinstance(ch.get("axis"), dict) else {}
        vals = axis.get("values")
        if isinstance(vals, list) and vals:
            return len(vals)
        return None

    axis_x_tick_count = _axis_tick_count(x)
    if axis_x_tick_count is None and category_channel == "x" and category_count:
        axis_x_tick_count = category_count
    axis_y_tick_count = _axis_tick_count(y)
    w_px = float(width or context.get("viewport_px") or 640)
    tick_n = int(axis_x_tick_count or 0)
    cat_n = int(category_count or 0)
    # 刻度过多，或类别远超可用像素宽度 → 密轴（COVID 周标签标签一类）
    # 显式 axis.values 是最终可见刻度；不能因为底层 data domain 很大而继续
    # 报告拥挤（例如 318 个日期只显示 8 个 landmark ticks）。
    explicit_ticks = axis_x_tick_count is not None and isinstance(
        (x.get("axis") if isinstance(x, dict) else None), dict
    ) and isinstance((x.get("axis") or {}).get("values"), list)
    axis_x_dense = bool(
        tick_n >= 10
        or (cat_n >= 24 and not explicit_ticks)
        or (tick_n >= 8 and w_px > 0 and (w_px / max(tick_n, 1)) < 56)
    )
    # 仅「共享主几何数据的柱上/点上数值」；像素画布自有 data 标注不算
    primary_fields = primary_encoding_fields(units)
    has_value_labels = any(is_per_mark_value_label(u, primary_fields) for u in units)

    layer_roles = [
        {
            "index": u["index"],
            "mark_type": u["mark_type"],
            "role": u["role"],
            "score": u["score"],
        }
        for u in units
    ]

    base = {
        "mark_type": mark_type,
        "is_single_view": isinstance(mark, (str, dict)) and bool(enc) and "layer" not in root,
        "category_channel": category_channel,
        "category_field": category_field,
        "value_field": value_field,
        "categories": categories,
        "category_count": category_count,
        "color_field": color_field,
        "per_category_coloring": per_category_coloring,
        "literal_color_encoding": literal_color_encoding,
        "series_count": series_count,
        "series_values": series_values,
        "colors_effective": colors_effective,
        "accent_color": accent_color,
        "color_source": color_source,
        "color_count": color_count,
        "background": root.get("background"),
        "has_legend": has_legend,
        "legend_orient": legend_orient,
        "legend_title": legend_title,
        "title_text": title_text,
        "has_title": bool(title_text),
        "title_from_text_layer": title_from_text_layer,
        "subtitle": subtitle,
        "title_anchor": title_anchor,
        "has_source_note": has_source_note,
        "source_provider": source_provider,
        "grid_x": grid_x,
        "grid_x_color": grid_x_color,
        "grid_y": grid_y,
        "grid_y_color": grid_y_color,
        "has_drawn_grid": has_drawn_grid,
        "drawn_grid_color": drawn_grid_color,
        "font_sizes": font_sizes,
        "font_family": font_family,
        "unit_count": len(units),
        "primary_unit_index": primary.get("index") if primary else None,
        "primary_unit_role": primary.get("role") if primary else None,
        "layer_roles": layer_roles,
        "chrome_layers": chrome_digest_for_llm(root),
        "row_count": len(rows) if rows is not None else None,
        "max_category": max_category,
        "min_category": min_category,
        "data_range_ratio": data_range_ratio,
        "width": width,
        "height": height,
        "axis_x_tick_count": axis_x_tick_count,
        "axis_y_tick_count": axis_y_tick_count,
        "axis_x_dense": axis_x_dense,
        "has_value_labels": has_value_labels,
        "medium": context.get("medium", "digital"),
        "viewport_px": context.get("viewport_px") or width or 640,
        "communication_goal": context.get("communication_goal"),
        "data_topic": None,
        "intent": None,
        "emphasis_target": None,
        "summary": None,
    }
    # 布局 IR：轴朝向/绝对键等程序可检问题（供拍2/拍3，不靠看图）
    layout_slice = build_layout_slice(root, base)
    base["layout_slice"] = layout_slice
    base["layout_flags"] = list(layout_slice.get("flags") or [])
    # Chart Audit IR：在不改变拍1职责的前提下，把可观察的视觉问题结构化，
    # 供拍2检测与拍3语义裁决共同使用，而不是只依赖颜色/字体规则。
    y_scale = y.get("scale") if isinstance(y.get("scale"), dict) else {}
    x_axis = x.get("axis") if isinstance(x.get("axis"), dict) else {}
    y_axis = y.get("axis") if isinstance(y.get("axis"), dict) else {}

    def _title_case_style(text: str) -> str:
        """观察到的标题大小写：title_case / sentence_case / all_caps / unknown。"""
        t = re.sub(r"\s+", " ", str(text or "")).strip()
        words = [w for w in t.split(" ") if any(ch.isalpha() for ch in w)]
        if not words:
            return "unknown"
        if t.isupper():
            return "all_caps"
        tail = words[1:]
        if not tail:
            return "sentence_case"
        # 次词起、长词首字母大写占多数 → Title Case（容忍少量专有名词）
        caps = [w for w in tail if w[:1].isupper() and len(w) >= 4]
        lowers = [w for w in tail if w[:1].islower()]
        if len(caps) >= 2 and len(caps) >= len(lowers):
            return "title_case"
        return "sentence_case"

    mark_props = mark_obj
    annotation_count = sum(1 for u in units if u.get("role") in ("annotation", "source"))
    line_like = str(mark_type or "").lower() in ("line", "trail", "area")
    # 标题形态的程序化信号：大小写风格 + 是否话题标签式标题（拍3 据此裁决，不靠模型目测）
    from .actions import _is_generic_title, _normalize_plain_text  # 局部导入避免环依赖

    title_plain = _normalize_plain_text(title_text)
    audit = {
        "hierarchy": {
            "title_present": bool(title_text),
            "subtitle_present": bool(subtitle),
            "title_style": _title_case_style(title_plain),
            "title_generic_topic_label": bool(title_plain) and _is_generic_title(title_plain, base),
            "source_present": has_source_note,
        },
        "axes": {
            "x_tick_count": axis_x_tick_count,
            "y_tick_count": axis_y_tick_count,
            "x_dense": axis_x_dense,
            "y_zero": y_scale.get("zero") if y_scale else None,
            "x_grid": grid_x,
            "y_grid": grid_y,
            "x_label_angle": x_axis.get("labelAngle"),
            "y_label_angle": y_axis.get("labelAngle"),
            "layout_flags": list(layout_slice.get("flags") or []),
        },
        "marks": {
            "type": mark_type,
            "line_like": line_like,
            "opacity": mark_props.get("opacity"),
            "stroke_width": mark_props.get("strokeWidth"),
            "corner_radius": mark_props.get("cornerRadius"),
            "filled": mark_props.get("filled"),
            "has_point_markers": bool(mark_props.get("point")) if line_like else False,
        },
        "labels": {
            "value_labels_present": has_value_labels,
            "axis_labels_dense": axis_x_dense,
            "annotation_count": annotation_count,
        },
        "legend": {
            "present": has_legend,
            "redundant_risk": bool(has_legend and per_category_coloring and category_count and category_count > 12),
            "orient": legend_orient,
        },
        "accessibility": {
            "color_only_encoding": bool(color_field and not any((u.get("mark_obj") or {}).get("shape") for u in units)),
            "has_text_labels": has_value_labels or annotation_count > 0,
        },
    }
    base["chart_audit"] = audit
    return base
