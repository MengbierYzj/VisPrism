"""布局结构审计：程序可检的轴/图例定位卫生（不依赖看图）。

导出器常把「朝向 + 绝对像素」做成耦合包（如 y 轴 titleAngle:0 + titleX/Y）。
拍前重建若只剥坐标、留下朝向，会得到半清理状态（水平轴标题落在轴中段）。

本模块职责：
1. 一包清理轴绝对定位及其配套朝向（供 spec_rebuild）；
2. 产出 layout_slice / flags（供 facts、拍3 vision 附带）；
3. 高置信结构问题可程序落地，不经多模态猜几何。
"""
from __future__ import annotations

import copy
from typing import Any

# 轴上导出器绝对定位与通道级字体（通道字号会盖住 config）
ABS_AXIS_KEYS = (
    "titleX",
    "titleY",
    "labelX",
    "labelY",
    "offset",
    "labelFontSize",
    "titleFontSize",
    "labelFont",
    "titleFont",
    "labelFontWeight",
    "titleFontWeight",
)
ABS_AXIS_POS_KEYS = frozenset({"titleX", "titleY", "labelX", "labelY", "offset"})
ABS_LEGEND_KEYS = ("legendX", "legendY", "offset")


def _is_flat_angle(angle: Any) -> bool:
    return angle in (0, 0.0)


def clean_axis_layout(axis: Any, *, channel: str | None = None) -> dict | None | bool:
    """剥绝对定位；y 轴水平 titleAngle 与定位一包清除，恢复默认竖直标题。"""
    if axis is None or axis is False:
        return axis
    if not isinstance(axis, dict):
        return None
    out = {k: v for k, v in axis.items() if k not in ABS_AXIS_KEYS}
    # y 默认竖直；残留 titleAngle:0（原靠 titleX/Y 钉顶左）会居中落在轴中段
    if channel == "y" and _is_flat_angle(out.get("titleAngle")):
        out.pop("titleAngle", None)
    return out


def iter_axis_bindings(spec: dict) -> list[dict[str, Any]]:
    """遍历所有 encoding 中的轴绑定：{channel, axis, path}。"""
    out: list[dict[str, Any]] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        enc = node.get("encoding")
        if isinstance(enc, dict):
            for ch_name, ch in enc.items():
                if not isinstance(ch, dict):
                    continue
                axis = ch.get("axis")
                if isinstance(axis, dict):
                    out.append(
                        {
                            "channel": ch_name,
                            "axis": axis,
                            "path": f"{path}.encoding.{ch_name}.axis",
                        }
                    )
        for key in ("layer", "hconcat", "vconcat", "concat"):
            kids = node.get(key)
            if isinstance(kids, list):
                for i, kid in enumerate(kids):
                    walk(kid, f"{path}.{key}[{i}]")
        if isinstance(node.get("spec"), dict):
            walk(node["spec"], f"{path}.spec")

    walk(spec, "$")
    return out


def _pixel_text_layers(spec: dict) -> list[dict[str, Any]]:
    """粗列绝对像素 text（mark.x/y 或 encoding value），供 layout_slice 提示。"""
    items: list[dict[str, Any]] = []
    try:
        from .view_geometry import walk_annotated_units
    except Exception:  # noqa: BLE001
        return items

    for u in walk_annotated_units(spec):
        if u.get("mark_type") != "text":
            continue
        if u.get("role") in ("title", "subtitle", "source"):
            continue
        view = u.get("view") if isinstance(u.get("view"), dict) else {}
        mark = view.get("mark") if isinstance(view.get("mark"), dict) else {}
        enc = u.get("encoding") if isinstance(u.get("encoding"), dict) else {}
        px = mark.get("x") if isinstance(mark.get("x"), (int, float)) else None
        py = mark.get("y") if isinstance(mark.get("y"), (int, float)) else None
        if px is None:
            xch = enc.get("x") if isinstance(enc.get("x"), dict) else {}
            if xch.get("value") is not None and not xch.get("field"):
                try:
                    px = float(xch["value"])
                except (TypeError, ValueError):
                    px = None
        if py is None:
            ych = enc.get("y") if isinstance(enc.get("y"), dict) else {}
            if ych.get("value") is not None and not ych.get("field"):
                try:
                    py = float(ych["value"])
                except (TypeError, ValueError):
                    py = None
        if px is None and py is None:
            continue
        items.append(
            {
                "index": u.get("index"),
                "role": u.get("role"),
                "x": px,
                "y": py,
            }
        )
    return items[:24]


def build_layout_slice(spec: dict, facts: dict | None = None) -> dict[str, Any]:
    """紧凑布局 IR（非完整 VL）：轴朝向/绝对键、图例绝对键、像素 text 摘要。"""
    facts = facts if isinstance(facts, dict) else {}
    axes: list[dict[str, Any]] = []
    flags: list[str] = []
    for bind in iter_axis_bindings(spec):
        ch = str(bind["channel"])
        axis = bind["axis"]
        abs_pos = sorted(k for k in ABS_AXIS_POS_KEYS if k in axis)
        ang = axis.get("titleAngle")
        entry = {
            "channel": ch,
            "title": axis.get("title"),
            "titleAngle": ang,
            "abs_pos_keys": abs_pos,
            "has_labelExpr": bool(
                isinstance(axis.get("labelExpr"), str) and axis["labelExpr"].strip()
            ),
            "tick_count": len(axis["values"])
            if isinstance(axis.get("values"), list)
            else None,
        }
        axes.append(entry)
        if ch == "y" and _is_flat_angle(ang) and not abs_pos:
            flags.append("orphaned_horizontal_y_title")
        if abs_pos:
            flags.append(f"abs_axis_pos:{ch}")

    legend_abs = False

    def _scan_legends(node: Any) -> None:
        nonlocal legend_abs
        if not isinstance(node, dict):
            return
        enc = node.get("encoding")
        if isinstance(enc, dict):
            for ch in enc.values():
                if not isinstance(ch, dict):
                    continue
                leg = ch.get("legend")
                if isinstance(leg, dict) and any(k in leg for k in ("legendX", "legendY")):
                    legend_abs = True
        for key in ("layer", "hconcat", "vconcat", "concat"):
            kids = node.get(key)
            if isinstance(kids, list):
                for kid in kids:
                    _scan_legends(kid)
        if isinstance(node.get("spec"), dict):
            _scan_legends(node["spec"])

    _scan_legends(spec)
    if legend_abs:
        flags.append("abs_legend_pos")

    pixel_text = _pixel_text_layers(spec)
    if pixel_text:
        flags.append("pixel_positioned_text")

    if facts.get("axis_x_dense"):
        flags.append("axis_x_dense")
    if facts.get("has_value_labels"):
        flags.append("has_value_labels")

    # 去重保序
    seen: set[str] = set()
    uniq_flags: list[str] = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            uniq_flags.append(f)

    return {
        "axes": axes[:16],
        "pixel_text_layers": pixel_text,
        "flags": uniq_flags,
        "width": facts.get("width") or spec.get("width"),
        "height": facts.get("height") or spec.get("height"),
        "padding": copy.deepcopy(spec.get("padding"))
        if isinstance(spec.get("padding"), (dict, int, float))
        else None,
    }


def program_layout_candidates(layout_slice: dict) -> list[dict[str, Any]]:
    """由 layout_slice 产出程序候选（可 auto_fix 或交给 vision 确认）。"""
    if not isinstance(layout_slice, dict):
        return []
    flags = [str(f) for f in (layout_slice.get("flags") or [])]
    out: list[dict[str, Any]] = []

    if "orphaned_horizontal_y_title" in flags:
        out.append(
            {
                "id": "orphaned_horizontal_y_title",
                "issue": "mark_label_overlap",
                "severity": (
                    "Y-axis title uses horizontal titleAngle without absolute "
                    "titleX/Y offsets (orphaned exporter layout)"
                ),
                "severity": "high",
                "auto_fix": True,
                "preferred_actions": ["normalize_axis_title_layout"],
                "rationale": (
                    "Structural layout IR: horizontal y-axis title without "
                    "pixel offsets lands mid-axis; restore default orientation."
                ),
            }
        )

    if "abs_axis_pos:x" in flags or "abs_axis_pos:y" in flags:
        out.append(
            {
                "id": "abs_axis_offsets",
                "issue": "other",
                "severity": "Axis still carries absolute titleX/titleY offsets",
                "severity": "medium",
                "auto_fix": True,
                "preferred_actions": ["normalize_axis_title_layout"],
                "rationale": (
                    "Absolute axis title offsets are brittle under size/padding "
                    "ops; normalize to VL defaults."
                ),
            }
        )

    if "axis_x_dense" in flags:
        out.append(
            {
                "id": "axis_x_dense",
                "issue": "whitespace",
                "synopsis": "Dense x-axis tick labels (program facts)",
                "severity": "medium",
                "auto_fix": False,  # 已有 thin 接地；交 vision 可确认
                "preferred_actions": ["thin_axis_labels"],
                "rationale": "Program facts marked axis_x_dense.",
            }
        )

    if "pixel_positioned_text" in flags:
        out.append(
            {
                "id": "pixel_positioned_text",
                "issue": "mark_label_overlap",
                "synopsis": "Spec has pixel-positioned text layers",
                "severity": "low",
                "auto_fix": False,
                "preferred_actions": ["increase_padding", "nudge_title"],
                "rationale": (
                    "Absolute text layers may collide after size changes; "
                    "confirm on image."
                ),
            }
        )

    return out


def normalize_axis_title_layout(spec: dict) -> bool:
    """就地：剥轴绝对定位 + 清除孤儿水平 y 轴 titleAngle。返回是否有改动。"""
    changed = False

    def walk(node: Any) -> None:
        nonlocal changed
        if not isinstance(node, dict):
            return
        enc = node.get("encoding")
        if isinstance(enc, dict):
            for ch_name, ch in enc.items():
                if not isinstance(ch, dict):
                    continue
                axis = ch.get("axis")
                if not isinstance(axis, dict):
                    continue
                cleaned = clean_axis_layout(axis, channel=str(ch_name))
                if isinstance(cleaned, dict) and cleaned != axis:
                    ch["axis"] = cleaned
                    changed = True
                elif cleaned is None and axis:
                    ch.pop("axis", None)
                    changed = True
        for key in ("layer", "hconcat", "vconcat", "concat"):
            kids = node.get(key)
            if isinstance(kids, list):
                for kid in kids:
                    walk(kid)
        if isinstance(node.get("spec"), dict):
            walk(node["spec"])

    walk(spec)
    return changed


def program_layout_adopted(layout_slice: dict) -> list[dict[str, Any]]:
    """高置信结构问题 → 拍3 可直接 adopted（L3-derived / 程序）。"""
    adopted: list[dict[str, Any]] = []
    for c in program_layout_candidates(layout_slice):
        if not c.get("auto_fix"):
            continue
        actions = list(c.get("preferred_actions") or [])
        ops = [{"action": a} for a in actions if a == "normalize_axis_title_layout"]
        if not ops:
            continue
        adopted.append(
            {
                "layer": "L3-derived",
                "rule_id": f"d-layout-{c['id']}",
                "rule_text": str(c.get("synopsis") or c["id"]),
                "strength": "should",
                "story_id": "",
                "src": ["layout-audit"],
                "derived": True,
                "ops": ops,
                "confidence": "medium" if c.get("severity") == "high" else "low",
                "rationale": str(c.get("rationale") or "layout audit"),
                "suggested_only": False,
                "philosophy_quote": "",
                "label": "Axis title layout",
            }
        )
    return adopted
