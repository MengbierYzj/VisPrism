"""复合视图主几何打分、祖先 encoding 合并、chrome（网格/标题 text）识别。

供 specfacts（事实）与 actions（ops 落点）共用，避免 Datawrapper 式
layer 导出图误选 rule 网格、改不到 fill/stroke。
"""
from __future__ import annotations

import copy
from typing import Any

COMPOSITION_KEYS = ("layer", "hconcat", "vconcat", "concat")

# 主数据几何优先；装饰/网格降权
_MARK_BASE_SCORE: dict[str, int] = {
    "bar": 100,
    "area": 95,
    "line": 90,
    "arc": 88,
    "trail": 85,
    "point": 70,
    "circle": 70,
    "square": 65,
    "tick": 45,
    "rect": 30,
    "rule": 12,
    "text": -40,
}

_PRIMARY_MARKS = frozenset(
    {"bar", "area", "line", "arc", "trail", "point", "circle", "square"}
)
_STROKE_MARKS = frozenset({"rule", "line", "trail", "tick"})


def mark_type_of(mark: Any) -> str | None:
    if isinstance(mark, str):
        return mark
    if isinstance(mark, dict):
        t = mark.get("type")
        return t if isinstance(t, str) else None
    return None


def merge_encoding(parent: dict | None, child: dict | None) -> dict:
    """VL layer 语义：子通道覆盖父通道。"""
    out: dict = dict(parent or {})
    for k, v in (child or {}).items():
        out[k] = v
    return out


def _row_count(data: Any) -> int:
    if isinstance(data, dict) and isinstance(data.get("values"), list):
        return len(data["values"])
    return 0


def _channel(enc: dict, name: str) -> dict:
    v = enc.get(name)
    return v if isinstance(v, dict) else {}


def _has_field_channel(enc: dict, *names: str) -> bool:
    for n in names:
        ch = _channel(enc, n)
        if isinstance(ch.get("field"), str) and ch["field"]:
            return True
    return False


def _mark_text_blob(mark: Any) -> str:
    if not isinstance(mark, dict):
        return ""
    t = mark.get("text")
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        return " ".join(str(x) for x in t)
    return ""


def _data_text_blob(data: Any, enc: dict) -> str:
    """从 data.values + encoding.text.field 读文案（Source 层常见）。"""
    text_ch = enc.get("text") if isinstance(enc.get("text"), dict) else {}
    field = text_ch.get("field")
    if not isinstance(field, str) or not field:
        return ""
    if not isinstance(data, dict):
        return ""
    vals = data.get("values")
    if not isinstance(vals, list):
        return ""
    bits: list[str] = []
    for row in vals[:6]:
        if isinstance(row, dict) and row.get(field) is not None:
            bits.append(str(row[field]))
    return "\n".join(bits)


def is_source_text(s: str) -> bool:
    low = (s or "").lower()
    return "source" in low or "来源" in low


def _is_source_text(s: str) -> bool:
    """兼容旧名。"""
    return is_source_text(s)


def unit_text_content(unit: dict[str, Any]) -> str:
    """单元可见文案：mark.text 或 data.values[text.field]。"""
    mark_obj = unit.get("mark_obj") or {}
    enc = unit.get("encoding") if isinstance(unit.get("encoding"), dict) else {}
    view = unit.get("view") if isinstance(unit.get("view"), dict) else {}
    blob = _mark_text_blob(mark_obj).strip()
    if blob:
        return blob
    own = view.get("data")
    inh = (unit.get("inherited") or {}).get("data") if isinstance(unit.get("inherited"), dict) else None
    return (_data_text_blob(own, enc) or _data_text_blob(inh, enc) or "").strip()


def classify_unit_role(
    mark_t: str | None,
    mark_obj: dict,
    enc: dict,
    own_data: Any,
    inherited_data: Any,
) -> str:
    """启发式角色：primary/secondary/grid/title/source/annotation/drawn_axis。"""
    text_blob = _mark_text_blob(mark_obj)
    if mark_t == "text":
        data_blob = _data_text_blob(own_data, enc) or _data_text_blob(inherited_data, enc)
        combined = (text_blob or data_blob or "").strip()
        if _is_source_text(combined):
            return "source"
        x_ch, y_ch = _channel(enc, "x"), _channel(enc, "y")
        # 自绘轴刻度：一侧 data field + 一侧像素 value → 拍前可丢（VL 默认轴恢复）
        if _has_field_channel(enc, "text") and (
            (x_ch.get("field") and y_ch.get("value") is not None)
            or (y_ch.get("field") and x_ch.get("value") is not None)
        ):
            return "drawn_axis"
        # 数据标签：text 与位置通道均绑字段（柱上数值等）
        if _has_field_channel(enc, "text") and (
            x_ch.get("field") or y_ch.get("field") or _channel(enc, "theta").get("field")
        ):
            return "secondary_data"
        # 环图/极坐标中心合计：自有少行 data + text.field，无空间 field/绝对定位
        # （默认落在原点；属图表语义，拍前必须保留）
        x_val = x_ch.get("value")
        y_val = y_ch.get("value")
        own_rows = _row_count(own_data) if own_data is not None else 0
        if (
            _has_field_channel(enc, "text")
            and own_data is not None
            and 0 < own_rows <= 3
            and not x_ch.get("field")
            and not y_ch.get("field")
            and not _channel(enc, "theta").get("field")
            and x_val is None
            and y_val is None
        ):
            return "secondary_data"
        # 无 field 的绝对定位大字号 ≈ 标题（提升到根）；其余绝对文案保留为 annotation
        # （多行说明勿标 subtitle，否则拍前 lift 只留首条、其余被丢）
        fs = mark_obj.get("fontSize")
        if combined and isinstance(fs, (int, float)) and fs >= 18 and (
            x_val is not None or y_val is not None
        ):
            return "title"
        if combined and not _has_field_channel(enc, "text") and (
            x_val is not None or y_val is not None
        ):
            return "annotation"
        return "annotation"

    if mark_t == "tick":
        # 数据参考 tick（如五年均值）保留为 overlay
        if _has_field_channel(enc, "x", "y"):
            return "secondary_data"
        return "annotation"

    if mark_t == "rule":
        y_f = _channel(enc, "y").get("field")
        x_const = _channel(enc, "x").get("value") is not None
        x2 = "x2" in enc
        rows = _row_count(own_data) if own_data is not None else 0
        # 自绘水平网格：y=grid 字段，或多行 + x/x2 常数跨度
        if y_f == "grid" or (rows >= 3 and x_const and x2):
            return "grid"
        # 有字段的参考线（零线/均值）→ overlay；纯常数装饰 → annotation
        if _has_field_channel(enc, "x", "y"):
            return "secondary_data"
        if rows <= 2 and (x_const or _channel(enc, "y").get("value") is not None):
            return "annotation"
        return "annotation"

    if mark_t == "rect":
        # 注释底框 / 衰退带：少行常数坐标
        if _row_count(own_data) <= 3 and not _has_field_channel(enc, "x", "y"):
            return "annotation"
        if not _has_field_channel(enc, "x", "y") and _channel(enc, "x").get("value") is not None:
            return "annotation"
        return "secondary_data"

    if mark_t in _PRIMARY_MARKS:
        root_rows = _row_count(inherited_data)
        own_rows = _row_count(own_data)
        # 编码字段与根数据字段无交集 → 装饰箭头/注释几何
        root_fields: set[str] = set()
        if isinstance(inherited_data, dict):
            vals = inherited_data.get("values")
            if isinstance(vals, list) and vals and isinstance(vals[0], dict):
                root_fields = {k for k in vals[0].keys() if isinstance(k, str)}
        enc_fields = set()
        for ch_name in ("x", "y", "theta", "color", "detail", "order", "radius"):
            f = _channel(enc, ch_name).get("field")
            if isinstance(f, str):
                enc_fields.add(f)
        if root_fields and enc_fields and not (enc_fields & root_fields):
            return "annotation"
        # 环图中心遮罩：自有极少行、无数据通道，仅 outer/innerRadius（配合中心文字）
        if (
            mark_t == "arc"
            and own_data is not None
            and 0 < own_rows <= 2
            and not enc_fields
            and (
                isinstance(mark_obj.get("outerRadius"), (int, float))
                or isinstance(mark_obj.get("innerRadius"), (int, float))
            )
        ):
            return "secondary_data"
        uses_root = own_data is None or own_rows == 0 or (
            isinstance(own_data, dict)
            and isinstance(inherited_data, dict)
            and own_data is inherited_data
        )
        if uses_root or (root_rows > 0 and own_rows == 0):
            return "primary_data"
        if own_rows > 0 and own_rows < max(root_rows // 3, 3):
            return "annotation"
        return "primary_data"

    return "annotation"


def primary_encoding_fields(units: list[dict[str, Any]]) -> set[str]:
    """主几何（及同级数据层）上的空间/度量字段名，供识别真正的柱上数值标签。"""
    fields: set[str] = set()
    for u in units:
        if u.get("role") not in ("primary_data", "secondary_data"):
            continue
        if u.get("mark_type") in (None, "text"):
            continue
        enc = u.get("encoding") if isinstance(u.get("encoding"), dict) else {}
        for ch in ("x", "y", "theta", "color", "x2", "y2"):
            c = enc.get(ch) if isinstance(enc.get(ch), dict) else {}
            f = c.get("field")
            if isinstance(f, str) and f:
                fields.add(f)
    return fields


def _is_pixel_canvas_channel(ch: Any) -> bool:
    """位置通道是否为导出器像素画布（axis:null + 固定域 / datum），而非数据轴。"""
    if not isinstance(ch, dict):
        return False
    if ch.get("datum") is not None:
        return True
    if ch.get("field") is None:
        return False
    if ch.get("axis") is not None:
        return False
    scale = ch.get("scale") if isinstance(ch.get("scale"), dict) else {}
    domain = scale.get("domain")
    if isinstance(domain, list) and len(domain) == 2:
        try:
            float(domain[0])
            float(domain[1])
            return True
        except (TypeError, ValueError):
            return False
    # axis:null + quantitative + nice:false（常见像素域写法）
    if ch.get("type") == "quantitative" and scale.get("nice") is False:
        return True
    return False


def is_per_mark_value_label(
    unit: dict[str, Any], primary_fields: set[str] | None = None
) -> bool:
    """是否为「绑在主几何数据上的柱上/点上数值标签」（可被 remove_value_labels 删除）。

    像素画布上的自有 data 标注（品牌字、扇区 callout、侧栏品牌列表）即使用
    text.field + x/y，也不是柱上数值——不得整批删除。
    """
    if unit.get("mark_type") != "text":
        return False
    if unit.get("role") in ("title", "subtitle", "source", "drawn_axis"):
        return False
    enc = unit.get("encoding") if isinstance(unit.get("encoding"), dict) else {}
    text_ch = enc.get("text") if isinstance(enc.get("text"), dict) else {}
    if not isinstance(text_ch.get("field"), str) or not text_ch["field"]:
        return False
    pos_fields: set[str] = set()
    has_pos = False
    canvas_pos = False
    for ch_name in ("x", "y", "theta"):
        c = enc.get(ch_name) if isinstance(enc.get(ch_name), dict) else {}
        if isinstance(c.get("field"), str) and c["field"]:
            has_pos = True
            pos_fields.add(c["field"])
        if c.get("datum") is not None:
            has_pos = True
        if ch_name in ("x", "y") and _is_pixel_canvas_channel(c):
            canvas_pos = True
    if not has_pos:
        return False

    view = unit.get("view") if isinstance(unit.get("view"), dict) else {}
    own = view.get("data")
    has_own_values = isinstance(own, dict) and isinstance(own.get("values"), list)

    # 继承父表、无自有 values → 经典柱上/点上标签
    if not has_own_values:
        return True

    # 自有表 + 像素画布定位 → 注释/callout/品牌字，保留
    if canvas_pos:
        return False

    # 自有表但位置字段与主几何字段相交 → 仍在数据坐标系上标数
    pf = primary_fields if primary_fields is not None else set()
    if pos_fields & pf:
        return True

    return False


def score_unit(
    mark_t: str | None,
    role: str,
    enc: dict,
    own_data: Any,
    inherited_data: Any,
    has_transform: bool,
) -> int:
    score = _MARK_BASE_SCORE.get(mark_t or "", 0)
    if role == "primary_data":
        score += 40
    elif role == "secondary_data":
        score += 10
    elif role == "grid":
        score -= 80
    elif role in ("title", "subtitle", "source", "annotation", "drawn_axis"):
        score -= 60

    if _has_field_channel(enc, "x", "y", "theta", "latitude", "longitude"):
        score += 25
    if has_transform:
        score += 15
    root_rows = _row_count(inherited_data)
    own_rows = _row_count(own_data)
    if root_rows >= 5 and (own_rows == 0 or own_data is inherited_data):
        score += 20
    # 自有小表（轴标签）降权
    if own_rows > 0 and own_rows <= 12 and mark_t == "text":
        score -= 20
    return score


def walk_annotated_units(spec: dict) -> list[dict[str, Any]]:
    """深度优先：每个带 mark 的 unit 附带合并 encoding、角色与打分。"""
    out: list[dict[str, Any]] = []

    def walk(node: Any, inherited: dict) -> None:
        if not isinstance(node, dict):
            return
        inh = dict(inherited)
        for key in ("data", "width", "height"):
            if key in node:
                inh[key] = node[key]
        # 父层 transform（filter/calculate/fold）对子 layer 生效，必须继承
        if isinstance(node.get("transform"), list) and node["transform"]:
            prev = list(inh.get("transform") or [])
            inh["transform"] = prev + copy.deepcopy(node["transform"])
        if isinstance(node.get("encoding"), dict):
            inh["encoding"] = merge_encoding(
                inh.get("encoding") if isinstance(inh.get("encoding"), dict) else None,
                node["encoding"],
            )

        if "mark" in node:
            mark = node.get("mark")
            mark_t = mark_type_of(mark)
            mark_obj = mark if isinstance(mark, dict) else {}
            child_enc = node.get("encoding") if isinstance(node.get("encoding"), dict) else {}
            # 进入 unit 前的 inherited 尚为父 encoding（本节点 encoding 尚未合入）
            parent_enc = (
                inherited.get("encoding")
                if isinstance(inherited.get("encoding"), dict)
                else {}
            )
            effective_enc = merge_encoding(parent_enc, child_enc)
            own_data = node.get("data")
            # 祖先 data 必须取进入本节点前的 inherited，勿用已合入本节点 data 的 inh
            inherited_data = inherited.get("data")
            role = classify_unit_role(
                mark_t, mark_obj, effective_enc, own_data, inherited_data
            )
            # 本节点 transform 已并入 inh；打分看是否有任意 transform
            has_tf = bool(inh.get("transform")) or bool(node.get("transform"))
            sc = score_unit(
                mark_t,
                role,
                effective_enc,
                own_data,
                inherited_data,
                has_tf,
            )
            out.append(
                {
                    "view": node,
                    "inherited": inh,
                    "encoding": effective_enc,
                    "parent_encoding": dict(parent_enc),
                    "mark_type": mark_t,
                    "mark_obj": mark_obj,
                    "role": role,
                    "score": sc,
                    "index": len(out),
                }
            )
            return

        for key in COMPOSITION_KEYS:
            kids = node.get(key)
            if isinstance(kids, list):
                for kid in kids:
                    walk(kid, inh)
        nested = node.get("spec")
        if isinstance(nested, dict):
            walk(nested, inh)

    walk(spec, {})
    return out


def resolve_primary_unit(spec: dict) -> dict[str, Any] | None:
    units = walk_annotated_units(spec)
    if not units:
        return None
    primary = [u for u in units if u["role"] == "primary_data"]
    pool = primary or [
        u for u in units if u["mark_type"] not in (None, "text") and u["role"] != "grid"
    ] or units
    return max(pool, key=lambda u: u["score"])


def primary_paint_targets(spec: dict) -> list[dict]:
    """改色目标：主数据几何（可多个 area/line 系列），排除网格/标注。"""
    units = walk_annotated_units(spec)
    primaries = [u["view"] for u in units if u["role"] == "primary_data"]
    if primaries:
        return primaries
    # 回退：最高分非 chrome
    ranked = sorted(
        (
            u
            for u in units
            if u["role"]
            not in ("grid", "title", "subtitle", "source", "annotation", "drawn_axis")
        ),
        key=lambda u: -u["score"],
    )
    if ranked:
        return [ranked[0]["view"]]
    geom = [u["view"] for u in units if u["mark_type"] not in (None, "text")]
    return geom or [u["view"] for u in units]


def geometry_targets(spec: dict, *, include_secondary: bool = True) -> list[dict]:
    """改图型等：非 chrome 几何。"""
    units = walk_annotated_units(spec)
    skip = {"title", "subtitle", "source", "annotation", "grid", "drawn_axis"}
    if include_secondary:
        views = [u["view"] for u in units if u["role"] not in skip]
    else:
        views = [u["view"] for u in units if u["role"] == "primary_data"]
    if views:
        return views
    return [u["view"] for u in units if u["mark_type"] != "text"] or [u["view"] for u in units]


def drawn_grid_units(spec: dict) -> list[dict[str, Any]]:
    return [u for u in walk_annotated_units(spec) if u["role"] == "grid"]


def title_text_units(spec: dict) -> list[dict[str, Any]]:
    return [u for u in walk_annotated_units(spec) if u["role"] in ("title", "subtitle")]


def source_text_units(spec: dict) -> list[dict[str, Any]]:
    return [u for u in walk_annotated_units(spec) if u["role"] == "source"]


def apply_paint_color(mark_obj: dict, color: str) -> None:
    """按实际绘制通道写入颜色（fill / stroke / color）。"""
    mt = mark_obj.get("type")
    has_fill = "fill" in mark_obj
    has_stroke = "stroke" in mark_obj
    if has_fill:
        mark_obj["fill"] = color
    if has_stroke and (mt in _STROKE_MARKS or not has_fill):
        mark_obj["stroke"] = color
    if not has_fill and not has_stroke:
        mark_obj["color"] = color
    elif has_fill and not has_stroke and mt not in _STROKE_MARKS:
        # 保留 color 与 fill 一致，便于 VL / 下游事实读取
        mark_obj["color"] = color


def read_paint_color(mark_obj: dict) -> str | None:
    for key in ("fill", "color", "stroke"):
        v = mark_obj.get(key)
        if isinstance(v, str) and v.startswith("#"):
            return v
    return None


def chrome_digest_for_llm(spec: dict, limit: int = 24) -> list[dict[str, Any]]:
    """给慢道 LLM 的紧凑层摘要，用于复核角色（不发明 ops）。"""
    return units_digest_for_llm(walk_annotated_units(spec), limit=limit)


def units_digest_for_llm(units: list[dict[str, Any]], limit: int = 24) -> list[dict[str, Any]]:
    """从已注解 units 生成 LLM 摘要（含绝对坐标线索，便于识别自绘轴）。"""
    rows = []
    for u in units[:limit]:
        mark_obj = u.get("mark_obj") or {}
        enc = u.get("encoding") or {}
        x_ch, y_ch = _channel(enc, "x"), _channel(enc, "y")
        abs_coord = (x_ch.get("value") is not None) or (y_ch.get("value") is not None)
        mixed_axisish = bool(
            _has_field_channel(enc, "text")
            and (
                (x_ch.get("field") and y_ch.get("value") is not None)
                or (y_ch.get("field") and x_ch.get("value") is not None)
            )
        )
        own = u["view"].get("data") if isinstance(u.get("view"), dict) else None
        rows.append(
            {
                "index": u["index"],
                "mark_type": u["mark_type"],
                "role_heuristic": u["role"],
                "score": u["score"],
                "fill": mark_obj.get("fill"),
                "stroke": mark_obj.get("stroke"),
                "color": mark_obj.get("color"),
                "fontSize": mark_obj.get("fontSize"),
                "text": (unit_text_content(u) or _mark_text_blob(mark_obj) or "")[:80],
                "own_rows": _row_count(own) if own is not None else 0,
                "abs_coord": abs_coord,
                "likely_drawn_axis": mixed_axisish,
                "fields": [
                    f"{ch}:{(_channel(enc, ch).get('field') or ('value=' + str(_channel(enc, ch).get('value'))))}"
                    for ch in ("x", "y", "theta", "color", "text", "x2", "y2")
                    if ch in enc
                ],
            }
        )
    return rows


def refine_drawn_axis_roles(units: list[dict[str, Any]]) -> list[dict]:
    """mock/回退：自绘轴刻度 → drawn_axis（拍前唯一默认丢弃的图层角色）。

    live 路径优先由 LLM 裁决；本函数仅在无 LLM 或 LLM 失败时使用。
    """
    overrides: list[dict] = []
    for u in units:
        if u.get("mark_type") != "text":
            continue
        enc = u.get("encoding") or {}
        if not _has_field_channel(enc, "text"):
            continue
        x_ch, y_ch = _channel(enc, "x"), _channel(enc, "y")
        if (x_ch.get("field") and y_ch.get("value") is not None) or (
            y_ch.get("field") and x_ch.get("value") is not None
        ):
            if u.get("role") != "drawn_axis":
                overrides.append(
                    {
                        "index": u["index"],
                        "role": "drawn_axis",
                        "rationale": "drawn axis tick labels (field + pixel value)",
                    }
                )
    if overrides:
        apply_role_overrides(units, overrides)
    return overrides


def apply_role_overrides(units: list[dict], overrides: list[dict]) -> None:
    """就地应用 LLM 返回的 {index, role} 覆盖（仅允许已知角色）。"""
    allowed = {
        "primary_data",
        "secondary_data",
        "grid",
        "title",
        "subtitle",
        "source",
        "annotation",
        "drawn_axis",
    }
    by_idx = {u["index"]: u for u in units}
    for item in overrides or []:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        role = item.get("role")
        if idx not in by_idx or role not in allowed:
            continue
        by_idx[idx]["role"] = role
        # 重算分数
        u = by_idx[idx]
        inh = u.get("inherited") if isinstance(u.get("inherited"), dict) else {}
        has_tf = bool(inh.get("transform")) or bool(u["view"].get("transform"))
        u["score"] = score_unit(
            u["mark_type"],
            role,
            u["encoding"],
            u["view"].get("data"),
            inh.get("data"),
            has_tf,
        )
