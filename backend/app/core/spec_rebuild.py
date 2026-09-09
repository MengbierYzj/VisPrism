"""拍前 intake：从上传 Vega-Lite 抽取语义组件，再 emit 干净可改写的工作副本。

原则：**尽量不丢图层内容**。剥除绝对图例/轴坐标与自绘假轴，保留主几何、
overlay、annotation 标注、grid、环图中心合计等；title/source 提升到根 title。

入口：`rebuild_spec_for_advisor`（同步/启发式）与
`rebuild_spec_for_advisor_async`（live 优先 LLM 层角色裁决）。
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any

from .layout_audit import ABS_AXIS_KEYS, ABS_LEGEND_KEYS, clean_axis_layout
from .view_geometry import (
    apply_role_overrides,
    is_source_text,
    refine_drawn_axis_roles,
    unit_text_content,
    units_digest_for_llm,
    walk_annotated_units,
)

_DEFAULT_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"

# 兼容旧名（测试/外部若引用）
_ABS_AXIS_KEYS = ABS_AXIS_KEYS
_ABS_LEGEND_KEYS = ABS_LEGEND_KEYS

# mark 保留的语义属性（非像素装饰）
_MARK_KEEP = (
    "type",
    "filled",
    "fill",
    "fillOpacity",
    "stroke",
    "strokeWidth",
    "strokeDash",
    "strokeCap",
    "strokeJoin",
    "opacity",
    "size",
    "thickness",
    "width",
    "height",
    "orient",
    "interpolate",
    "point",
    "tooltip",
    "clip",
    "cornerRadius",
    "bandSize",
    # 极坐标 / 饼环
    "innerRadius",
    "outerRadius",
    "padAngle",
    "theta",
    "theta2",
    "radius",
    "radius2",
    # 中心合计 / 遮罩色（环图）
    "color",
    # 中心 text 语义排版（非绝对像素框）
    "font",
    "fontSize",
    "fontWeight",
    "fontStyle",
    "dy",
    "dx",
    "align",
    "baseline",
    "angle",
    "limit",
    "text",
)

# 拍前保留的图层（默认保守：annotation/grid 也保留）
_KEEP_LAYER_ROLES = frozenset(
    {"primary_data", "secondary_data", "annotation", "grid"}
)
# 文案提升到根 title 后不再留 text 层（避免双标题）
_LIFT_CHROME_ROLES = frozenset({"title", "subtitle", "source"})
# 唯一默认丢弃：自绘轴（与 VL 默认轴冲突）
_DROP_ROLES = frozenset({"drawn_axis"})
# 兼容旧名
_DATA_ROLES = _KEEP_LAYER_ROLES
_CHROME_ROLES = _LIFT_CHROME_ROLES | _DROP_ROLES


def _clean_axis(axis: Any, *, channel: str | None = None) -> dict | None | bool:
    return clean_axis_layout(axis, channel=channel)


def _clean_channel(ch: Any, *, channel: str | None = None) -> dict | None:
    if not isinstance(ch, dict):
        return None
    out: dict[str, Any] = {}
    for k, v in ch.items():
        if k == "axis":
            # Datawrapper 常用 axis:null（自绘轴）；丢掉后交给 VL 默认轴，避免无刻度
            if v is None:
                continue
            cleaned = _clean_axis(v, channel=channel)
            if cleaned is not None:
                out["axis"] = cleaned
            continue
        if k == "legend":
            continue  # legend 单独重建
        out[k] = copy.deepcopy(v)
    return out


def _clean_encoding(enc: dict | None) -> dict:
    if not isinstance(enc, dict):
        return {}
    out: dict[str, Any] = {}
    for name, ch in enc.items():
        cleaned = _clean_channel(ch, channel=name)
        if cleaned is not None:
            out[name] = cleaned
    return out


def _clean_mark(mark: Any) -> dict:
    if isinstance(mark, str):
        return {"type": mark}
    if not isinstance(mark, dict):
        return {"type": "point"}
    out = {k: copy.deepcopy(v) for k, v in mark.items() if k in _MARK_KEEP}
    if "type" not in out:
        out["type"] = "point"
    # 有 encoding.color 时勿保留 mark.color（emit 层再清）
    return out


def _legend_semantics(legend: Any, scale: Any) -> dict[str, Any]:
    """抽出可重建的图例语义（无绝对坐标）。"""
    sem: dict[str, Any] = {"title": None, "orient": "top"}
    if isinstance(legend, dict):
        if "title" in legend:
            sem["title"] = legend.get("title")
        orient = legend.get("orient")
        if isinstance(orient, str) and orient.strip().lower() not in ("", "none"):
            sem["orient"] = orient.strip().lower()
        for k in ("direction", "symbolType", "symbolSize", "symbolStrokeWidth", "symbolDash"):
            if k in legend:
                sem[k] = copy.deepcopy(legend[k])
    if isinstance(scale, dict):
        if isinstance(scale.get("domain"), list):
            sem["scale_domain"] = copy.deepcopy(scale["domain"])
        if isinstance(scale.get("range"), list):
            sem["scale_range"] = copy.deepcopy(scale["range"])
    return sem


def _title_from_root(spec: dict) -> tuple[str | None, str | None, str | None]:
    raw = spec.get("title")
    if isinstance(raw, str):
        return raw, None, None
    if isinstance(raw, dict):
        text = raw.get("text")
        if isinstance(text, list):
            text = " ".join(str(x) for x in text)
        sub = raw.get("subtitle")
        if isinstance(sub, list):
            sub = " ".join(str(x) for x in sub)
        anchor = raw.get("anchor") if isinstance(raw.get("anchor"), str) else None
        return (
            text if isinstance(text, str) else None,
            sub if isinstance(sub, str) else None,
            anchor,
        )
    return None, None, None


def _is_simple_unit(spec: dict) -> bool:
    """无 layer/concat 的标准 unit：近似 no-op。"""
    if any(k in spec for k in ("layer", "hconcat", "vconcat", "concat", "facet", "repeat")):
        return False
    return "mark" in spec


def _channel_value_only(ch: Any) -> bool:
    return isinstance(ch, dict) and not ch.get("field") and "value" in ch


def _extract_pixel_position(enc: dict | None) -> dict[str, Any] | None:
    """encoding 上 x/y 仅有 value、无 field → 导出器像素定位（非数据域）。

    若仍放在 encoding 里，会走共享定量比例尺（如 y=336 被当成接近 0 的数据），
    底注会叠在图内；应改写到 mark.x / mark.y。
    """
    if not isinstance(enc, dict):
        return None
    x_ch, y_ch = enc.get("x"), enc.get("y")
    if isinstance(x_ch, dict) and x_ch.get("field"):
        return None
    if isinstance(y_ch, dict) and y_ch.get("field"):
        return None
    out: dict[str, Any] = {}
    if _channel_value_only(x_ch):
        out["x"] = x_ch["value"]
    if _channel_value_only(y_ch):
        out["y"] = y_ch["value"]
    return out or None


def _apply_pixel_position_to_layer_ir(layer_ir: dict[str, Any]) -> None:
    """保留 Datawrapper 的像素定位 ``encoding.value`` 原值。

    Vega-Lite 对没有 field 的 position value 直接作为视图像素坐标编译。不得写入
    非标准 ``mark.x/y``，也不得把像素值反算为数据值，否则文字会被送到画布外。
    """
    return


def _numeric_domain(channel: Any) -> tuple[float, float] | None:
    if not isinstance(channel, dict):
        return None
    scale = channel.get("scale") if isinstance(channel.get("scale"), dict) else {}
    domain = scale.get("domain")
    if not isinstance(domain, list) or len(domain) != 2:
        return None
    try:
        lo, hi = float(domain[0]), float(domain[1])
    except (TypeError, ValueError):
        return None
    return (lo, hi) if lo != hi else None


def _pixel_to_data(value: Any, domain: tuple[float, float] | None, span: Any, *, reverse: bool) -> Any:
    if domain is None or not isinstance(span, (int, float)) or float(span) <= 0:
        return value
    if not isinstance(value, (int, float)):
        return value
    lo, hi = domain
    ratio = float(value) / float(span)
    if reverse:
        ratio = 1.0 - ratio
    return lo + ratio * (hi - lo)


def _is_outside_domain(value: Any, domain: tuple[float, float] | None) -> bool:
    if not isinstance(value, (int, float)) or domain is None:
        return False
    lo, hi = domain
    return float(value) < min(lo, hi) or float(value) > max(lo, hi)


def _normalize_pixel_coordinates(ir: dict[str, Any]) -> int:
    """兼容旧审计字段；value-only x/y 是像素坐标，必须原样输出。"""
    return 0


def _make_annotation_backplates_transparent(ir: dict[str, Any]) -> int:
    """同色 annotation rect 是 Datawrapper 文字遮罩，重建后改为透明。"""
    bg = str(ir.get("background") or "#ffffff").strip().lower()
    changed = 0
    for layer in ir.get("layers") or []:
        if not isinstance(layer, dict) or layer.get("role") != "annotation":
            continue
        mark = layer.get("mark") if isinstance(layer.get("mark"), dict) else {}
        if str(mark.get("type") or "").lower() != "rect":
            continue
        fill = str(mark.get("fill") or mark.get("color") or "").strip().lower()
        if fill and fill == bg:
            mark["fill"] = "transparent"
            mark.pop("color", None)
            changed += 1
    return changed


def _normalize_padding(raw: Any) -> dict[str, float] | None:
    if isinstance(raw, (int, float)):
        v = float(raw)
        return {"top": v, "right": v, "bottom": v, "left": v}
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    for k in ("top", "right", "bottom", "left"):
        if isinstance(raw.get(k), (int, float)):
            out[k] = float(raw[k])
    return out or None


def _layout_padding_for_emit(ir: dict[str, Any]) -> dict[str, float]:
    """保留原稿边距；丢掉自绘轴后为 VL 默认轴留底边。"""
    pad = _normalize_padding(ir.get("padding")) or {
        "top": 12.0,
        "right": 12.0,
        "bottom": 12.0,
        "left": 12.0,
    }
    if int(ir.get("dropped_drawn_axis") or 0) > 0:
        pad["bottom"] = max(pad["bottom"], 48.0)
    # 像素 annotation 的负 y 标题依赖原稿顶部 padding；压缩它会令 autosize: none
    # 的画布裁字。普通重建图仍可收紧过大的标题区。
    if (
        ir.get("title_text")
        and pad.get("top", 0) > 80
        and not int(ir.get("pixel_position_layers") or 0)
        and not (
            isinstance(ir.get("autosize"), dict)
            and str(ir["autosize"].get("type") or "").lower() == "none"
        )
    ):
        pad["top"] = max(48.0, pad["top"] * 0.5)
    return pad


def _needs_rebuild(spec: dict, units: list[dict]) -> bool:
    if not _is_simple_unit(spec):
        # 复合图：有 chrome / 绝对图例 / 绝对轴 → 重建
        for u in units:
            if u["role"] in _CHROME_ROLES:
                return True
            leg = (u.get("encoding") or {}).get("color")
            if isinstance(leg, dict):
                legend = leg.get("legend")
                if isinstance(legend, dict) and (
                    legend.get("orient") == "none"
                    or "legendX" in legend
                    or "legendY" in legend
                ):
                    return True
        # 根 encoding 轴绝对键
        root_enc = spec.get("encoding") if isinstance(spec.get("encoding"), dict) else {}
        for ch in root_enc.values():
            if isinstance(ch, dict) and isinstance(ch.get("axis"), dict):
                if any(k in ch["axis"] for k in _ABS_AXIS_KEYS):
                    return True
        # layer 且存在数据层 → 仍重建以统一 legend/title
        if "layer" in spec and any(u["role"] in _DATA_ROLES for u in units):
            return True
        return False
    # 简单 unit：绝对图例 / 通道级字体字号（会盖住 config）→ 重建剥除
    enc = spec.get("encoding") if isinstance(spec.get("encoding"), dict) else {}
    color = enc.get("color") if isinstance(enc.get("color"), dict) else {}
    legend = color.get("legend") if isinstance(color.get("legend"), dict) else {}
    if legend.get("orient") == "none" or "legendX" in legend or "legendY" in legend:
        return True
    for ch in enc.values():
        if isinstance(ch, dict) and isinstance(ch.get("axis"), dict):
            if any(k in ch["axis"] for k in _ABS_AXIS_KEYS):
                return True
        if isinstance(ch, dict) and isinstance(ch.get("legend"), dict):
            leg = ch["legend"]
            if any(k in leg for k in ("labelFontSize", "titleFontSize", "labelFont", "titleFont")):
                return True
            if any(k in leg for k in _ABS_LEGEND_KEYS):
                return True
    return False


def extract_chart_ir(
    spec: dict, units: list[dict[str, Any]] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """抽取 ChartIR + 抽取报告碎片。

    units 可传入已应用 LLM/启发式角色覆盖的注解列表；默认重新 walk。
    """
    if not isinstance(spec, dict):
        return {}, {"ok": False, "note": "spec 非对象"}

    units = units if units is not None else walk_annotated_units(spec)
    title_text, subtitle, title_anchor = _title_from_root(spec)
    source_note: str | None = None
    if isinstance(subtitle, str) and (
        "source" in subtitle.lower() or "来源" in subtitle
    ):
        source_note = subtitle

    for u in units:
        if u["role"] == "title" and not title_text:
            blob = unit_text_content(u)
            if blob:
                title_text = blob
        if u["role"] == "source":
            blob = unit_text_content(u)
            if blob:
                source_note = blob
        if u["role"] == "subtitle" and not subtitle:
            blob = unit_text_content(u)
            if blob:
                subtitle = blob

    data_layers: list[dict[str, Any]] = []
    pixel_layers = 0
    for u in units:
        role = u.get("role")
        if role in _DROP_ROLES or role in _LIFT_CHROME_ROLES:
            continue
        if role not in _KEEP_LAYER_ROLES:
            # 未知角色：保守保留，避免拍前静默丢层
            pass
        view = u["view"]
        # 层本地 encoding（子覆盖父后的有效编码），再拆本地相对父的增量：
        # emit 时根放 shared，层放 layer-local（view 自带 encoding）
        local_enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else {}
        parent_enc = u.get("parent_encoding") if isinstance(u.get("parent_encoding"), dict) else {}
        effective = u.get("encoding") if isinstance(u.get("encoding"), dict) else {}

        color_ch = effective.get("color") if isinstance(effective.get("color"), dict) else {}
        legend_raw = color_ch.get("legend")
        scale_raw = color_ch.get("scale") if isinstance(color_ch.get("scale"), dict) else {}
        legend_sem = None
        if color_ch.get("field") and legend_raw is not False and legend_raw is not None:
            legend_sem = _legend_semantics(legend_raw, scale_raw)
        elif color_ch.get("field") and "legend" not in color_ch:
            legend_sem = _legend_semantics({}, scale_raw)

        layer_ir: dict[str, Any] = {
            "role": u["role"],
            "mark": _clean_mark(view.get("mark")),
            "encoding": _clean_encoding(local_enc),
            "transform": None,
            "description": view.get("description")
            if isinstance(view.get("description"), str)
            else None,
            "legend": legend_sem,
            "color_field": color_ch.get("field"),
            "color_type": color_ch.get("type") or "nominal",
            "color_scale": copy.deepcopy(scale_raw) if scale_raw else None,
        }
        # 合并祖先 transform + 本层 transform（父层 calculate 字段常被 encoding 引用）
        # 自有 data 的 overlay（中心合计/遮罩）不得继承主表 filter，否则少行标注被滤空
        transforms: list = []
        inh = u.get("inherited") if isinstance(u.get("inherited"), dict) else {}
        has_own_data = isinstance(view.get("data"), dict)
        if has_own_data:
            if isinstance(view.get("transform"), list):
                transforms.extend(copy.deepcopy(view["transform"]))
        else:
            inh_tf = inh.get("transform")
            if isinstance(inh_tf, list):
                transforms.extend(copy.deepcopy(inh_tf))
            elif isinstance(view.get("transform"), list):
                # inherited 未带 transform 时退回本层（兼容旧 walk）
                transforms.extend(copy.deepcopy(view["transform"]))
        # 若 inherited 已含本层（mark 节点自身 transform 已并入 inh），勿重复
        # walk 在进入 mark 时把 node.transform 并入 inh，故上面 inh_tf 已完整
        if transforms:
            layer_ir["transform"] = transforms
        # 层自有 data（中心标注/孔洞常见）
        if has_own_data:
            layer_ir["data"] = copy.deepcopy(view["data"])
        # 纯 value 定位 → 像素 mark，避免共享定量轴把底注吸到 y≈0
        before = bool(layer_ir.get("pixel_position"))
        _apply_pixel_position_to_layer_ir(layer_ir)
        if layer_ir.get("pixel_position") and not before:
            pixel_layers += 1
        data_layers.append(layer_ir)

    # 共享 encoding：优先根 encoding，否则用主几何 parent
    shared = spec.get("encoding") if isinstance(spec.get("encoding"), dict) else {}
    if not shared and data_layers:
        primaries = [u for u in units if u["role"] == "primary_data"]
        pick = primaries[0] if primaries else (units[0] if units else None)
        if pick:
            shared = pick.get("parent_encoding") or {}
    shared_clean = _clean_encoding(shared)

    # 推断统一 legend orient
    orients = [
        (ly.get("legend") or {}).get("orient")
        for ly in data_layers
        if isinstance(ly.get("legend"), dict)
    ]
    orients = [o for o in orients if isinstance(o, str) and o not in ("", "none")]
    shared_orient = Counter(orients).most_common(1)[0][0] if orients else "top"
    for ly in data_layers:
        if isinstance(ly.get("legend"), dict):
            ly["legend"]["orient"] = shared_orient

    n_color_legends = sum(1 for ly in data_layers if ly.get("legend"))
    resolve = None
    if n_color_legends >= 2:
        resolve = {"scale": {"color": "independent"}}

    root_data = spec.get("data") if isinstance(spec.get("data"), dict) else None
    if root_data is None:
        for u in units:
            if u["role"] == "primary_data":
                inh = u.get("inherited") or {}
                if isinstance(inh.get("data"), dict):
                    root_data = copy.deepcopy(inh["data"])
                    break

    # 尺寸常在 vconcat 子图而非根上；取主几何继承宽高
    width = spec.get("width") if isinstance(spec.get("width"), (int, float)) else None
    height = spec.get("height") if isinstance(spec.get("height"), (int, float)) else None
    for u in units:
        if u["role"] != "primary_data":
            continue
        inh = u.get("inherited") if isinstance(u.get("inherited"), dict) else {}
        if width is None and isinstance(inh.get("width"), (int, float)):
            width = inh["width"]
        if height is None and isinstance(inh.get("height"), (int, float)):
            height = inh["height"]
        break

    ir: dict[str, Any] = {
        "schema": spec.get("$schema") or _DEFAULT_SCHEMA,
        "width": width,
        "height": height,
        "autosize": copy.deepcopy(spec.get("autosize"))
        if isinstance(spec.get("autosize"), (str, dict))
        else None,
        "background": spec.get("background"),
        "padding": _normalize_padding(spec.get("padding")),
        "data": copy.deepcopy(root_data) if root_data else None,
        "title_text": title_text,
        "subtitle": subtitle if subtitle and subtitle != source_note else None,
        "source": source_note,
        "title_anchor": title_anchor or "start",
        "shared_encoding": shared_clean,
        "layers": data_layers,
        "resolve": resolve,
        "simple_unit": _is_simple_unit(spec),
        "had_chrome": any(
            u["role"] in (_LIFT_CHROME_ROLES | _DROP_ROLES) for u in units
        ),
        "unit_count": len(units),
        "kept_layers": len(data_layers),
        "dropped_chrome": sum(
            1 for u in units if u["role"] in (_LIFT_CHROME_ROLES | _DROP_ROLES)
        ),
        "dropped_drawn_axis": sum(1 for u in units if u["role"] == "drawn_axis"),
        "pixel_position_layers": pixel_layers,
    }
    # Datawrapper 把 annotation 的画布像素写进 encoding.value；统一换算后仍使用
    # 合法 VL encoding，且原稿同背景的文字遮罩改为透明。
    pixel_coordinate_layers = _normalize_pixel_coordinates(ir)
    transparent_backplates = _make_annotation_backplates_transparent(ir)
    meta = {
        "unit_count": len(units),
        "kept_layers": len(data_layers),
        "dropped_chrome": ir["dropped_chrome"],
        "dropped_drawn_axis": ir["dropped_drawn_axis"],
        "pixel_position_layers": pixel_layers,
        "pixel_coordinate_layers": pixel_coordinate_layers,
        "transparent_annotation_backplates": transparent_backplates,
        "shared_legend_orient": shared_orient,
    }
    return ir, meta


def emit_clean_spec(ir: dict[str, Any]) -> dict:
    """由 ChartIR 生成干净 Vega-Lite。"""
    layers_ir = ir.get("layers") or []
    if not layers_ir:
        # 无数据层：退回最小空壳（不应常见）
        out: dict[str, Any] = {"$schema": ir.get("schema") or _DEFAULT_SCHEMA}
        if ir.get("data"):
            out["data"] = ir["data"]
        return out

    out = {"$schema": ir.get("schema") or _DEFAULT_SCHEMA}
    if ir.get("width") is not None:
        out["width"] = ir["width"]
    if ir.get("height") is not None:
        out["height"] = ir["height"]
    # Datawrapper 的绝对文字位于既定 padding 中。若遗漏 autosize:none，VL 默认
    # pad 会为这些外部 mark 无限加边距，视觉上把主图压得很小。
    if ir.get("autosize") is not None:
        out["autosize"] = copy.deepcopy(ir["autosize"])
    if ir.get("background") is not None:
        out["background"] = ir["background"]
    # 保留原稿边距；为 VL 轴与底部说明留空（勿一律压成 12）
    out["padding"] = _layout_padding_for_emit(ir)

    title_obj: dict[str, Any] = {}
    if ir.get("title_text"):
        title_obj["text"] = ir["title_text"]
        title_obj["anchor"] = ir.get("title_anchor") or "start"
    # 副标题与来源并存：不要用来源覆盖描述性副标题
    sub_lines: list[str] = []
    raw_sub = ir.get("subtitle")
    if isinstance(raw_sub, list):
        sub_lines.extend(str(x).strip() for x in raw_sub if str(x).strip())
    elif isinstance(raw_sub, str) and raw_sub.strip():
        sub_lines.append(raw_sub.strip())
    src = ir.get("source")
    if isinstance(src, str) and src.strip():
        if not any(is_source_text(l) for l in sub_lines):
            sub_lines.append(src.strip())
    if sub_lines:
        title_obj["subtitle"] = sub_lines if len(sub_lines) > 1 else sub_lines[0]
    if title_obj:
        out["title"] = title_obj

    if ir.get("data"):
        out["data"] = ir["data"]

    shared = ir.get("shared_encoding") or {}
    if shared:
        out["encoding"] = copy.deepcopy(shared)

    if ir.get("resolve"):
        out["resolve"] = copy.deepcopy(ir["resolve"])

    # 单层且无共享冲突 → 可 flatten 为 unit；多数据层用 layer
    plot_layers: list[dict] = []
    below_layers: list[dict] = []
    plot_h = float(ir["height"]) if isinstance(ir.get("height"), (int, float)) else None

    for ly in layers_ir:
        layer: dict[str, Any] = {}
        if ly.get("description"):
            layer["description"] = ly["description"]
        if ly.get("transform"):
            layer["transform"] = copy.deepcopy(ly["transform"])
        if ly.get("data"):
            layer["data"] = copy.deepcopy(ly["data"])
        layer["mark"] = copy.deepcopy(ly.get("mark") or {"type": "point"})
        enc = copy.deepcopy(ly.get("encoding") or {})
        # 挂回 color + 干净 legend
        if ly.get("color_field"):
            color: dict[str, Any] = {
                "field": ly["color_field"],
                "type": ly.get("color_type") or "nominal",
            }
            scale = ly.get("color_scale")
            if isinstance(scale, dict) and scale:
                color["scale"] = copy.deepcopy(scale)
            leg = ly.get("legend")
            if isinstance(leg, dict):
                legend_out: dict[str, Any] = {
                    "title": leg.get("title", None),
                    "orient": leg.get("orient") or "top",
                }
                for k in (
                    "direction",
                    "symbolType",
                    "symbolSize",
                    "symbolStrokeWidth",
                    "symbolDash",
                ):
                    if k in leg:
                        legend_out[k] = copy.deepcopy(leg[k])
                color["legend"] = legend_out
            enc["color"] = color
            # encoding 驱动色时去掉 mark.color
            if isinstance(layer["mark"], dict):
                layer["mark"].pop("color", None)
        layer["encoding"] = enc

        # 像素 y 超出绘图高度 → 下方条带（真正在图底，而非数据域贴 y=0）
        py = ly.get("pixel_y")
        if (
            ly.get("pixel_position")
            and plot_h is not None
            and isinstance(py, (int, float))
            and float(py) >= plot_h - 1
        ):
            mark = layer["mark"] if isinstance(layer["mark"], dict) else {}
            mark = dict(mark)
            mark["y"] = float(py) - plot_h + 12.0
            # 下条带不再使用共享数据坐标
            mark.pop("x", None)
            if isinstance(layer.get("encoding"), dict):
                layer["encoding"] = {
                    k: v
                    for k, v in layer["encoding"].items()
                    if k not in ("x", "y", "theta", "latitude", "longitude")
                }
            # 左对齐底注
            if "x" not in mark:
                mark["x"] = 0
            mark.setdefault("align", "left")
            mark.setdefault("baseline", "top")
            layer["mark"] = mark
            below_layers.append(layer)
        else:
            plot_layers.append(layer)

    def _attach_layers(target: dict, layers: list[dict]) -> None:
        if len(layers) == 1 and not target.get("encoding"):
            only = layers[0]
            for k in ("transform", "mark", "encoding", "data", "description"):
                if k in only:
                    target[k] = only[k]
        elif len(layers) == 1:
            target["layer"] = [layers[0]]
        else:
            target["layer"] = layers

    if below_layers and plot_layers:
        # 主图保持原稿高度；底注在独立下条带
        plot_unit: dict[str, Any] = {
            "$schema": out.get("$schema") or _DEFAULT_SCHEMA,
        }
        if ir.get("width") is not None:
            plot_unit["width"] = ir["width"]
        if ir.get("height") is not None:
            plot_unit["height"] = ir["height"]
        if ir.get("data"):
            plot_unit["data"] = copy.deepcopy(ir["data"])
        if out.get("encoding"):
            plot_unit["encoding"] = out.pop("encoding")
        if ir.get("resolve"):
            plot_unit["resolve"] = out.pop("resolve", copy.deepcopy(ir["resolve"]))
        _attach_layers(plot_unit, plot_layers)

        max_local_y = 28.0
        for ly in below_layers:
            m = ly.get("mark") if isinstance(ly.get("mark"), dict) else {}
            try:
                max_local_y = max(max_local_y, float(m.get("y") or 0) + 22.0)
            except (TypeError, ValueError):
                pass
        foot_unit: dict[str, Any] = {
            "width": ir.get("width"),
            "height": max_local_y,
            "layer": below_layers,
        }
        # 根只保留标题/背景/边距 + vconcat
        for k in ("width", "height", "data", "encoding", "resolve", "layer", "mark", "transform"):
            out.pop(k, None)
        out["vconcat"] = [plot_unit, foot_unit]
        out["spacing"] = 8
    elif len(plot_layers) == 1 and not out.get("encoding"):
        only = plot_layers[0]
        for k in ("transform", "mark", "encoding", "data", "description"):
            if k in only:
                out[k] = only[k]
    elif len(plot_layers) == 1:
        out["layer"] = [plot_layers[0]]
    else:
        out["layer"] = plot_layers if plot_layers else below_layers

    out["config"] = {"view": {"stroke": "transparent"}}
    return out


def _should_llm_role_pass(units: list[dict]) -> bool:
    """复合导出图：优先交给 LLM 做角色理解（而非仅机械阈值）。"""
    if len(units) >= 3:
        return True
    if any(u.get("mark_type") == "text" for u in units):
        return True
    for u in units:
        if u.get("mark_type") != "text":
            continue
        enc = u.get("encoding") or {}
        x = enc.get("x") if isinstance(enc.get("x"), dict) else {}
        y = enc.get("y") if isinstance(enc.get("y"), dict) else {}
        text_f = isinstance((enc.get("text") or {}).get("field"), str) if isinstance(
            enc.get("text"), dict
        ) else False
        if text_f and (
            (x.get("field") and y.get("value") is not None)
            or (y.get("field") and x.get("value") is not None)
        ):
            return True
    return any(u.get("role") in ("title", "source", "grid", "subtitle") for u in units)


def _restore_chrome_from_original(original: dict, working: dict) -> dict:
    """emit 丢字时从原稿回填 title/subtitle/source（可审计保底）。"""
    if not isinstance(original, dict) or not isinstance(working, dict):
        return working
    out = working
    src_title = original.get("title")
    dst_title = out.get("title")
    src_text = None
    src_sub = None
    if isinstance(src_title, str) and src_title.strip():
        src_text = src_title.strip()
    elif isinstance(src_title, dict):
        if isinstance(src_title.get("text"), str) and src_title["text"].strip():
            src_text = src_title["text"].strip()
        src_sub = src_title.get("subtitle")

    need = False
    if src_text:
        if not isinstance(dst_title, dict) or not str(dst_title.get("text") or "").strip():
            need = True
    if src_sub is not None:
        if not isinstance(dst_title, dict) or dst_title.get("subtitle") in (None, "", []):
            need = True
    if not need:
        return out

    out = copy.deepcopy(working)
    title_obj = out.get("title") if isinstance(out.get("title"), dict) else {}
    title_obj = dict(title_obj)
    if src_text and not str(title_obj.get("text") or "").strip():
        title_obj["text"] = src_text
        title_obj.setdefault("anchor", "start")
    if src_sub is not None and title_obj.get("subtitle") in (None, "", []):
        title_obj["subtitle"] = copy.deepcopy(src_sub)
    if title_obj.get("text") or title_obj.get("subtitle") is not None:
        out["title"] = title_obj
    return out



async def classify_layer_roles_llm(units: list[dict], llm) -> list[dict]:
    """调用 LLM 产出 role overrides。"""
    from .advisor_briefing import chrome_roles_system

    digest = units_digest_for_llm(units)
    if not digest:
        return []
    raw = await llm.chat_json(
        chrome_roles_system(),
        json.dumps(
            {
                "layers": digest,
                "instruction": (
                    "Correct heuristic roles before rebuild. "
                    "Prefer keeping layers. Only mark true drawn-axis tick labels "
                    "as drawn_axis (they will be dropped). Keep callouts/annotations."
                ),
            },
            ensure_ascii=False,
        ),
    )
    overrides = raw.get("overrides") if isinstance(raw, dict) else None
    if not isinstance(overrides, list):
        return []
    # 只保留合法项
    out = []
    for item in overrides:
        if not isinstance(item, dict):
            continue
        if "index" not in item or "role" not in item:
            continue
        out.append(
            {
                "index": item["index"],
                "role": item["role"],
                "rationale": str(item.get("rationale") or "")[:200],
            }
        )
    return out


def _emit_from_units(spec: dict, units: list[dict], *, role_meta: dict) -> tuple[dict, dict]:
    """在已裁决 units 上 extract→emit。"""
    ir, meta = extract_chart_ir(spec, units=units)
    if not ir.get("layers"):
        return copy.deepcopy(spec), {
            "changed": False,
            "mode": "fallback_copy",
            "actions": [],
            "note": "无主数据层，保留原稿拷贝",
            **meta,
            **role_meta,
        }

    working = emit_clean_spec(ir)
    title_before = working.get("title")
    working = _restore_chrome_from_original(spec, working)
    chrome_restored = working.get("title") != title_before
    actions = [
        f"extract_layers={meta.get('kept_layers')}",
        f"drop_chrome={meta.get('dropped_chrome')}",
        f"legend_orient={meta.get('shared_legend_orient')}",
    ]
    if chrome_restored:
        actions.append("restore_title_chrome")
    if role_meta.get("role_source"):
        actions.append(f"roles={role_meta['role_source']}")
    return working, {
        "changed": True,
        "mode": "extract_emit",
        "actions": actions,
        "note": "抽组件重建：尽量保留图层；仅丢自绘轴；title/source 提升到根",
        "chrome_restored": chrome_restored,
        **meta,
        **role_meta,
    }


def rebuild_spec_for_advisor(spec: dict) -> tuple[dict, dict]:
    """同步拍前 intake（测试/无 LLM）：启发式回退裁决自绘轴后 rebuild。"""
    if not isinstance(spec, dict):
        return {}, {"changed": False, "mode": "invalid", "actions": [], "note": "spec 非对象"}

    units = walk_annotated_units(spec)
    if not _needs_rebuild(spec, units):
        return copy.deepcopy(spec), {
            "changed": False,
            "mode": "passthrough",
            "actions": [],
            "note": "标准 unit/已干净，跳过重建",
        }

    axis_ov = refine_drawn_axis_roles(units)
    return _emit_from_units(
        spec,
        units,
        role_meta={
            "role_source": "heuristic",
            "role_overrides": axis_ov,
        },
    )


def _axis_field_context(spec: dict) -> dict[str, list[str]]:
    """收集重建后默认轴涉及的字段名，供 LLM 仅做自然语言化。"""
    found: dict[str, list[str]] = {"x": [], "y": []}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            enc = node.get("encoding")
            if isinstance(enc, dict):
                for channel in ("x", "y"):
                    item = enc.get(channel)
                    field = item.get("field") if isinstance(item, dict) else None
                    if isinstance(field, str) and field and field not in found[channel]:
                        found[channel].append(field)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(spec)
    return found


def _set_axis_titles(spec: dict, titles: dict[str, str | None]) -> None:
    """为所有数据轴设置标题；None 显式阻止 Vega 自动显示字段名。"""
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            enc = node.get("encoding")
            if isinstance(enc, dict):
                for channel in ("x", "y"):
                    item = enc.get(channel)
                    if not isinstance(item, dict) or not item.get("field"):
                        continue
                    axis = item.get("axis")
                    if axis is False:
                        continue
                    if not isinstance(axis, dict):
                        axis = {}
                        item["axis"] = axis
                    axis["title"] = titles.get(channel)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(spec)


async def _naturalize_rebuilt_axis_titles(spec: dict, llm: Any) -> str:
    """LLM 只补缺失的自然语言轴标题，失败则隐藏自动字段标题。"""
    fields = _axis_field_context(spec)
    # 默认安全态：不让 Vega 把字段/多个字段拼成生硬标题。
    _set_axis_titles(spec, {"x": None, "y": None})
    if not fields["x"] and not fields["y"]:
        return "hidden_no_fields"
    if llm is None or getattr(llm, "mode", None) != "live":
        return "hidden_no_live_llm"
    system = (
        "You write concise chart axis titles. Use only the supplied field names; "
        "you may add grammatical connectors but must not invent facts, units, dates, "
        "or comma-separated field lists. Return JSON only: "
        '{"x_title":"... or null","y_title":"... or null"}. '
        "A title must be at most 60 characters."
    )
    try:
        raw = await llm.chat_json(
            system,
            json.dumps({"x_fields": fields["x"], "y_fields": fields["y"]}),
        )
    except Exception:  # noqa: BLE001 — 默认隐藏比错误文字安全
        return "hidden_llm_failed"
    if not isinstance(raw, dict):
        return "hidden_invalid_llm"
    titles: dict[str, str | None] = {}
    for channel, key in (("x", "x_title"), ("y", "y_title")):
        value = raw.get(key)
        if isinstance(value, str):
            clean = " ".join(value.split()).strip()
            # 禁止模型返回字段清单或空文字；字段名本身也不构成自然语言标题。
            if 2 <= len(clean) <= 60 and "," not in clean:
                titles[channel] = clean
                continue
        titles[channel] = None
    _set_axis_titles(spec, titles)
    return "llm" if any(titles.values()) else "hidden_invalid_titles"


async def rebuild_spec_for_advisor_async(spec: dict, llm=None) -> tuple[dict, dict]:
    """拍前 intake（live 优先 LLM 层角色裁决，再 extract→emit）。"""
    if not isinstance(spec, dict):
        return {}, {"changed": False, "mode": "invalid", "actions": [], "note": "spec 非对象"}

    units = walk_annotated_units(spec)
    if not _needs_rebuild(spec, units):
        return copy.deepcopy(spec), {
            "changed": False,
            "mode": "passthrough",
            "actions": [],
            "note": "标准 unit/已干净，跳过重建",
        }

    role_source = "heuristic"
    overrides: list[dict] = []
    use_llm = (
        llm is not None
        and getattr(llm, "mode", None) == "live"
        and _should_llm_role_pass(units)
    )
    if use_llm:
        try:
            overrides = await classify_layer_roles_llm(units, llm)
            if overrides:
                apply_role_overrides(units, overrides)
                role_source = "llm"
            else:
                # LLM 认为启发式已对：仍跑自绘轴安全网，避免 Berlin 类假轴漏网
                axis_ov = refine_drawn_axis_roles(units)
                overrides = axis_ov
                role_source = "llm_empty+heuristic" if axis_ov else "llm_confirm"
        except Exception as exc:  # noqa: BLE001 — 降级启发式，不阻断管线
            axis_ov = refine_drawn_axis_roles(units)
            overrides = axis_ov
            role_source = f"llm_fallback_heuristic:{type(exc).__name__}"
    else:
        overrides = refine_drawn_axis_roles(units)
        role_source = "heuristic"

    working, report = _emit_from_units(
        spec,
        units,
        role_meta={
            "role_source": role_source,
            "role_overrides": overrides,
        },
    )
    if int(report.get("dropped_drawn_axis") or 0) > 0:
        report["axis_title_source"] = await _naturalize_rebuilt_axis_titles(working, llm)
    return working, report
