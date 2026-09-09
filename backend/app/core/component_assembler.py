"""每个 persona 独立使用的组件 IR 与受控重组编译器。

仅处理 Datawrapper 式像素画布：文字/自绘坐标轴先拆为语义组件，再由 L2
component-assembly 规则授权重组，避免在绝对坐标文本层上继续叠加 padding/size。
"""
from __future__ import annotations

import copy
import json
from typing import Any


def _mark_type(node: dict) -> str:
    mark = node.get("mark")
    return str(mark.get("type") if isinstance(mark, dict) else mark or "").lower()


def _text_value(node: dict) -> str:
    mark = node.get("mark") if isinstance(node.get("mark"), dict) else {}
    value = mark.get("text") if isinstance(mark, dict) else None
    return value.strip() if isinstance(value, str) else ""


def _initial_region(item: dict, height: float) -> str:
    y = item.get("y")
    text = str(item.get("text") or "")
    if isinstance(y, (int, float)) and y <= -60:
        return "title"
    if isinstance(y, (int, float)) and y < 0:
        return "header"
    if "source:" in text.lower() or (isinstance(y, (int, float)) and y > height):
        return "footer"
    return "plot"


def _paragraphs(static_text: list[dict], height: float) -> list[dict]:
    """Recover semantic paragraphs from export-time visual line fragments.

    Datawrapper-like exports commonly emit one text layer per wrapped visual line.
    Grouping must happen before the LLM sees the content, otherwise it can make
    contradictory decisions for pieces of one sentence.
    """
    ordered = sorted(static_text, key=lambda x: (float(x.get("y") or 0), float(x.get("x") or 0), x["index"]))
    groups: list[list[dict]] = []
    for item in ordered:
        region = _initial_region(item, height)
        if not groups:
            groups.append([item])
            continue
        current = groups[-1]
        prev = current[-1]
        prev_region = _initial_region(prev, height)
        close_rows = isinstance(item.get("y"), (int, float)) and isinstance(prev.get("y"), (int, float)) and 0 <= item["y"] - prev["y"] <= 24
        # Attribution is a separate legal/editorial paragraph even when it is one
        # visual line below a preceding explanatory footer.
        source_boundary = "source:" in str(item.get("text") or "").lower() or "source:" in str(prev.get("text") or "").lower()
        if region == prev_region and close_rows and not source_boundary:
            current.append(item)
        else:
            groups.append([item])
    out = []
    for n, members in enumerate(groups):
        # For fragments on the same visual row, x establishes reading order.
        rows: dict[float, list[dict]] = {}
        for member in members:
            rows.setdefault(float(member.get("y") or 0), []).append(member)
        ordered_members = [m for y in sorted(rows) for m in sorted(rows[y], key=lambda x: (float(x.get("x") or 0), x["index"]))]
        out.append({
            "id": f"paragraph-{n}",
            "indices": [m["index"] for m in ordered_members],
            "region": _initial_region(ordered_members[0], height),
            "text": " ".join(str(m["text"]).strip() for m in ordered_members if str(m.get("text") or "").strip()),
            "x": ordered_members[0].get("x"), "y": ordered_members[0].get("y"),
        })
    return out


def build_component_ir(spec: dict) -> dict:
    layers = spec.get("layer") if isinstance(spec.get("layer"), list) else []
    static_text: list[dict] = []
    drawn_axis_count = 0
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict) or _mark_type(layer) != "text":
            continue
        enc = layer.get("encoding") if isinstance(layer.get("encoding"), dict) else {}
        x, y = enc.get("x") if isinstance(enc.get("x"), dict) else {}, enc.get("y") if isinstance(enc.get("y"), dict) else {}
        pixel = x.get("value") is not None or y.get("value") is not None
        text = _text_value(layer)
        if not text and isinstance(enc.get("text"), dict):
            # field text + one fixed dimension is normally a hand-drawn axis.
            drawn_axis_count += 1
        if pixel and text:
            static_text.append({"index": index, "text": text, "x": x.get("value"), "y": y.get("value")})
    height = float(spec.get("height") or 300)
    paragraphs = _paragraphs(static_text, height)
    paragraph_by_index = {index: p["id"] for p in paragraphs for index in p["indices"]}
    for item in static_text:
        item["paragraph_id"] = paragraph_by_index.get(item["index"])
    source = [x["text"] for x in static_text if "source:" in x["text"].lower()]
    titles = [x["text"] for x in static_text if isinstance(x.get("y"), (int, float)) and x["y"] <= -60]
    notes = [x["text"] for x in static_text if x["text"] not in titles and x["text"] not in source]
    return {
        "kind": "pixel_canvas" if static_text or drawn_axis_count else "standard",
        "pixel_positioned_text": bool(static_text),
        "static_text": static_text,
        "paragraphs": paragraphs,
        "drawn_axis_count": drawn_axis_count,
        "title_candidates": titles,
        "note_candidates": notes,
        "source_candidates": source,
        "nontext_layer_count": sum(1 for x in layers if isinstance(x, dict) and _mark_type(x) != "text"),
    }


def select_component_assembly(persona, component_ir: dict) -> dict | None:
    if not component_ir.get("pixel_positioned_text"):
        return None
    for adaptation in persona.adaptations:
        if adaptation.scope != "component-assembly":
            continue
        when = adaptation.when or {}
        if when.get("pixel_positioned_text") is True:
            return {"rule_id": adaptation.id, "quote": adaptation.raw.get("evidence_quote", ""), "op": {
                "action": "reassemble_components", "profile": adaptation.raw.get("then", {}).get("profile", "editorial")
            }}
    return None


async def plan_component_assembly_with_llm(persona, facts: dict, llm, plan: dict | None) -> dict | None:
    """拍3 LLM 规划文字区域；结果只能引用现有 component index 和受限 region。"""
    if not plan or getattr(llm, "mode", "mock") != "live":
        return plan
    ir = facts.get("component_ir") if isinstance(facts.get("component_ir"), dict) else {}
    texts = ir.get("static_text") if isinstance(ir.get("static_text"), list) else []
    if not texts:
        return plan
    system = (
        f"You are the component-layout planner for {persona.name}. This is Beat 3 of a four-beat pipeline. "
        "Classify every supplied existing paragraph into exactly one region: title, header, plot, or footer. "
        "Use the original x/y, chart purpose, and visual findings. Keep data callouts/reference labels inside plot; "
        "paragraphs originally below the plot must remain footer, while paragraphs above it remain title/header. "
        "You may rewrite title, header, footer, "
        "or plot annotation text only when the rewrite is supported by the chart facts and this institution's rules. "
        "Never alter Source/credit text or invent numbers, dates, entities, or claims. Do not output Vega-Lite or coordinates. "
        "A paragraph is indivisible: never split, omit, reorder, or assign its visual fragments separately. "
        "Output JSON only: "
        '{"placements":[{"paragraph_id":"paragraph-0","region":"title|header|plot|footer","rewrite":"existing or revised complete paragraph","rule_refs":["rule id"],"reason":"short"}]}. '
        f"Institution evidence: {plan.get('quote') or ''}"
    )
    persona_rules = [
        {"id": rule.id, "rule": rule.rule, "strength": rule.strength}
        for rule in list(getattr(persona, "rules", []) or [])[:24]
    ]
    persona_l3 = [
        {"id": p.id, "title": p.title, "quote": p.quote}
        for p in list(getattr(persona, "philosophy", []) or [])[:12]
    ]
    valid_rule_refs = {x["id"] for x in persona_rules} | {x["id"] for x in persona_l3}
    payload = {
        "component_ir": {"width": facts.get("width"), "height": facts.get("height"), "paragraphs": ir.get("paragraphs", []),
                         "drawn_axis_count": ir.get("drawn_axis_count")},
        "chart_slice": facts.get("chart_slice"),
        "visual_findings": (facts.get("visual_review") or {}).get("findings", []),
        "persona_rules": persona_rules,
        "persona_l3": persona_l3,
    }
    try:
        raw = await llm.chat_json(system, json.dumps(payload, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - deterministic spatial fallback remains safe
        return plan
    candidates = raw.get("placements") if isinstance(raw, dict) else []
    paragraphs = ir.get("paragraphs") if isinstance(ir.get("paragraphs"), list) else []
    paragraph_by_id = {str(p.get("id")): p for p in paragraphs if isinstance(p, dict) and p.get("id")}
    placements = []
    seen = set()
    for item in candidates if isinstance(candidates, list) else []:
        if not isinstance(item, dict):
            continue
        paragraph_id, region = str(item.get("paragraph_id") or ""), str(item.get("region") or "").lower()
        paragraph = paragraph_by_id.get(paragraph_id)
        if paragraph and paragraph_id not in seen and region in {"title", "header", "plot", "footer"}:
            # The planner may refine content, but it cannot move a paragraph across
            # the plot boundary: that would reintroduce the original coordinate
            # system bug under a different representation.
            original_region = str(paragraph.get("region") or "plot")
            allowed_regions = {
                "title": {"title", "header"}, "header": {"title", "header"},
                "plot": {"plot"}, "footer": {"footer"},
            }.get(original_region, {original_region})
            if region not in allowed_regions:
                continue
            original = str(paragraph.get("text") or "")
            rewrite = str(item.get("rewrite") or original).strip()
            # 来源是归因证据，必须逐字保留；其他改写也有长度上限，避免把段落扩成新文案。
            if "source:" in original.lower() or not rewrite or len(rewrite) > 600:
                rewrite = original
            refs = [str(x) for x in (item.get("rule_refs") or []) if isinstance(x, str) and str(x) in valid_rule_refs][:4]
            placements.append({"paragraph_id": paragraph_id, "indices": list(paragraph.get("indices") or []), "region": region, "rewrite": rewrite,
                               "rule_refs": refs, "reason": str(item.get("reason") or "")[:180]})
            seen.add(paragraph_id)
    # 不完整 LLM 输出不用于删改；未覆盖组件由确定性原位置分类兜底。
    if placements:
        plan = copy.deepcopy(plan)
        plan["op"]["placements"] = placements
        plan["planner"] = "llm"
    return plan


def _wrap_for_width(text: str, width: Any, font_size: int = 12) -> list[str]:
    """Presentation-only wrapping; semantic paragraph remains one planner item."""
    try:
        chars = max(28, int(float(width or 480) / max(font_size * 0.58, 1)))
    except (TypeError, ValueError):
        chars = 64
    words, lines, line = text.split(), [], []
    for word in words:
        candidate = " ".join(line + [word])
        if line and len(candidate) > chars:
            lines.append(" ".join(line)); line = [word]
        else:
            line.append(word)
    if line:
        lines.append(" ".join(line))
    return lines or [text]


def reassemble_components(spec: dict, profile: str = "editorial", placements: list[dict] | None = None) -> bool:
    """按 header / plot / footer 重组手工 text canvas，保留图内注释位置。"""
    ir = build_component_ir(spec)
    if not ir.get("pixel_positioned_text"):
        return False
    layers = spec.get("layer") if isinstance(spec.get("layer"), list) else None
    if not layers:
        return False
    height = float(spec.get("height") or 300)
    paragraphs = ir.get("paragraphs") if isinstance(ir.get("paragraphs"), list) else []
    title = next((str(p.get("text") or "") for p in paragraphs if p.get("region") == "title"), "")
    placement_by_paragraph = {str(p.get("paragraph_id")): p for p in (placements or []) if isinstance(p, dict) and p.get("paragraph_id")}
    # Compatibility with existing callers/tests that still submit an index.
    for p in placements or []:
        if isinstance(p, dict) and p.get("index") is not None:
            paragraph = next((q for q in paragraphs if p.get("index") in (q.get("indices") or [])), None)
            if paragraph:
                placement_by_paragraph.setdefault(str(paragraph["id"]), p)
    kept, header_lines, footer_lines = [], [], []
    static_indices = {x.get("index") for x in ir.get("static_text", [])}
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict) or _mark_type(layer) != "text":
            if isinstance(layer, dict):
                kept.append(copy.deepcopy(layer))
            continue
        if index not in static_indices:  # field-text layers are manually drawn axes
            continue
    for paragraph in paragraphs:
        instruction = placement_by_paragraph.get(str(paragraph["id"]), {})
        region = str(instruction.get("region") or paragraph.get("region") or "plot")
        rendered_text = str(instruction.get("rewrite") or paragraph.get("text") or "").strip()
        if not rendered_text:
            continue
        if region == "title":
            title = rendered_text
        elif region == "header":
            header_lines.extend(_wrap_for_width(rendered_text, spec.get("width"), 12))
        elif region == "footer":
            footer_lines.extend(_wrap_for_width(rendered_text, spec.get("width"), 11))
        else:
            first_index = (paragraph.get("indices") or [None])[0]
            layer_copy = copy.deepcopy(layers[first_index]) if isinstance(first_index, int) else None
            if isinstance(layer_copy, dict) and isinstance(layer_copy.get("mark"), dict):
                # One mark per paragraph keeps its text semantically and visually contiguous.
                layer_copy["mark"]["text"] = "\n".join(_wrap_for_width(rendered_text, spec.get("width"), 12))
                layer_copy["mark"]["lineBreak"] = "\n"
                kept.append(layer_copy)
    for layer in kept:
        enc = layer.get("encoding") if isinstance(layer.get("encoding"), dict) else {}
        for channel in ("x", "y"):
            ch = enc.get(channel)
            if isinstance(ch, dict) and ch.get("axis") is None:
                ch.pop("axis", None)
    # Imported pixel canvases frequently have both a large manual padding and
    # autosize:none.  Copying either into both concat levels creates two nested,
    # fixed boxes that can never grow to include title, axes and footer.  The
    # rebuilt contract has exactly one data viewport (plot) and one outer box
    # (root), both with renderer-managed content bounds.
    plot_width, plot_height = spec.get("width") or 480, spec.get("height") or 300
    plot = {k: copy.deepcopy(v) for k, v in spec.items()
            if k not in ("layer", "title", "config", "usermeta", "padding", "autosize", "bounds", "spacing", "width", "height")}
    plot["width"], plot["height"] = plot_width, plot_height
    plot["autosize"] = {"type": "pad", "contains": "content", "resize": True}
    plot["layer"] = kept
    footer = None
    if footer_lines:
        footer_height = max(30, 16 * len(footer_lines) + 8)
        footer = {
            "width": plot_width, "height": footer_height,
            "data": {"values": [{"line": 4 + 16 * i, "text": line} for i, line in enumerate(footer_lines)]},
            "mark": {"type": "text", "align": "left", "baseline": "top", "fontSize": 11},
            "encoding": {"x": {"datum": 0, "type": "quantitative", "scale": {"domain": [0, 1]}, "axis": None},
                         "y": {"field": "line", "type": "quantitative", "scale": {"domain": [0, footer_height]}, "axis": None}, "text": {"field": "text"}},
        }
    root = {k: copy.deepcopy(v) for k, v in spec.items()
            if k not in ("layer", "width", "height", "title", "usermeta", "padding", "autosize", "bounds", "spacing")}
    root["autosize"] = {"type": "pad", "contains": "content", "resize": True}
    root["bounds"] = "full"
    root["title"] = {"text": title or "Data chart", "subtitle": header_lines, "anchor": "start",
                     "subtitleFontSize": 12, "subtitleLineHeight": 16}
    if footer:
        root["vconcat"] = [plot, footer]
        root["spacing"] = 6
    else:
        root.update(plot)
    spec.clear()
    spec.update(root)
    spec.setdefault("usermeta", {})["component_assembly"] = {
        "profile": profile, "preserved_static_text": [x["text"] for x in ir.get("static_text", [])],
        "paragraphs": paragraphs,
        "layout_contract": {"root": "autosize-pad/full-bounds", "plot_viewport": [plot_width, plot_height],
                            "footer_height": footer.get("height") if footer else 0},
        "placements": placements or [],
        "replaced_drawn_axes": ir.get("drawn_axis_count", 0),
    }
    return True
