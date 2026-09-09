"""拍3 多模态视觉审图（L3 原则 + 渲染图）。

默认由服务端将 working Vega-Lite 渲成 PNG（vl-convert）；可选
context.preview_image 覆盖。再辅以 chart_slice + L3 哲学。
输出：结构化 findings（问题证据）；不直接生成通用 ops。
LLM 不写 VL、不发明 hex；渲染失败 / mock / vision=off 时跳过。
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

from ..config import settings
from ..llm import LLMClient, LLMError
from .advisor_briefing import briefing_system_preamble
from .decision_ir import build_chart_slice
from .layout_audit import build_layout_slice, program_layout_adopted, program_layout_candidates
from .persona import Persona

_DATA_URL_RE = re.compile(
    r"^data:(image/(?:png|jpeg|jpg|webp|gif));base64,([A-Za-z0-9+/=\s]+)$",
    re.I,
)

ISSUE_TO_RULE = {
    "mark_label_overlap": "v-overlap",
    "text_mark_collision": "v-overlap",
    "overlap": "v-overlap",
    "color_similarity": "v-color-similarity",
    "pairwise_color": "v-color-similarity",
    "whitespace": "v-whitespace",
    "crowding": "v-whitespace",
    "other": "v-visual",
}

# 可落地为受控 ops 的动作
EXECUTABLE_ACTIONS = frozenset(
    {
        "increase_padding",
        "increase_height",
        "recolor_categorical",
        "recolor_paired",
        "recolor_uniform",
        "remove_value_labels",
        "shorten_labels",  # 按 facts 分流：密轴→thin_axis_labels；数值层→remove_value_labels
        "thin_axis_labels",
        "thin_axis_ticks",  # 同 thin_axis_labels
        "rotate_x_labels",
        "reduce_axis_grid",
        "zero_baseline",
        "widen_bars",
        "separate_bars",
        "round_bar_corners",
        "soften_marks",
        "improve_text_legibility",
        "deemphasize_annotations",
        "move_legend_top",
        "remove_legend_title",
        "tighten_axis_titles",
        "normalize_axis_title_layout",
    }
)
# 仅建议、不拖累可执行 op 的落地
SOFT_ACTIONS = frozenset({"nudge_title", "none"})

ALLOWED_ACTIONS = EXECUTABLE_ACTIONS | SOFT_ACTIONS


def annotation_text_baseline(spec: dict, limit: int = 24) -> list[str]:
    """提取原稿中静态 text annotation，供重建完整性与视觉审查对照。

    只收集 ``mark.text``，不把数据字段的坐标刻度/数值标签误当成不可丢失的
    文案。Vega-Lite text mark 没有背景属性即为透明底；这里保留的是应在成图中
    可见的文字事实，而非要求模型重写文案。
    """
    if not isinstance(spec, dict):
        return []
    found: list[str] = []

    def visit(node: Any) -> None:
        if not isinstance(node, dict) or len(found) >= limit:
            return
        mark = node.get("mark")
        if isinstance(mark, dict) and str(mark.get("type") or "").lower() == "text":
            value = mark.get("text")
            if isinstance(value, str) and value.strip() and value.strip() not in found:
                found.append(value.strip())
        for key in ("layer", "hconcat", "vconcat", "concat"):
            for child in node.get(key) or []:
                visit(child)

    visit(spec)
    return found


def normalize_preview_image(raw: Any, max_chars: int | None = None) -> str | None:
    """将 context.preview_image 规范为 data URL；非法或过大返回 None。"""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    limit = max_chars if max_chars is not None else settings.preview_image_max_chars
    if len(s) > limit:
        return None
    if s.startswith("https://") or s.startswith("http://"):
        return s if len(s) < 2048 else None
    m = _DATA_URL_RE.match(s)
    if m:
        mime = m.group(1).lower().replace("jpg", "jpeg")
        b64 = re.sub(r"\s+", "", m.group(2))
        try:
            base64.b64decode(b64, validate=True)
        except Exception:  # noqa: BLE001
            return None
        return f"data:{mime};base64,{b64}"
    b64 = re.sub(r"\s+", "", s)
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", b64) or len(b64) < 32:
        return None
    try:
        base64.b64decode(b64, validate=True)
    except Exception:  # noqa: BLE001
        return None
    return f"data:image/png;base64,{b64}"


def _l3_bundle(persona: Persona) -> dict[str, Any]:
    philosophy = [
        {"id": p.id, "title": p.title, "quote": (p.quote or "")[:240]}
        for p in (persona.philosophy or [])[:12]
    ]
    story_vals = (
        list((persona.stories or {}).values())
        if isinstance(persona.stories, dict)
        else list(persona.stories or [])
    )
    stories = [
        {"id": s.id, "text": (getattr(s, "story", None) or "")[:200]}
        for s in story_vals[:8]
    ]
    return {"philosophy": philosophy, "stories": stories}


def visual_review_system(persona: Persona, briefing: dict | None) -> str:
    task = (
        "You are this institution's visualization design critic. "
        "Inspect the rendered chart IMAGE against L3 design philosophy only "
        "(clarity, whitespace, accessibility perception, restrained color, etc.). "
        "Focus on issues that require seeing the image: mark/label overlap, "
        "pairwise color confusion, crowding/insufficient whitespace.\n"
        "A source annotation baseline may be supplied. Check that its short static "
        "texts remain visible in the rendered image and are not covered by an opaque "
        "background. Text annotations should keep a transparent background; do not "
        "ask to add a text box merely for decoration. If a baseline text is missing, "
        "report issue=other with preferred_actions=[none]; this is an integrity alert "
        "for the programmatic rebuild, not a request to invent replacement wording.\n"
        "An original_structure baseline may be supplied. Treat loss of an original series, mark, "
        "annotation layer, or encoding channel as a high-severity integrity issue; report it as "
        "other with preferred_actions=[none] so the programmatic preservation check can block the change.\n"
        "You also receive layout_slice + program_layout_candidates from a structural "
        "layout audit (axis titleAngle/offsets, dense ticks, pixel text). Treat those "
        "as high-priority hints: confirm on the image when possible; do not invent "
        "geometry that contradicts them. Structural orphans (e.g. horizontal y-axis "
        "title without titleX/Y) are already auto-fixed programmatically—prefer noting "
        "remaining visual issues.\n"
        "Do NOT rewrite Vega-Lite. Do NOT invent hex colors or numeric token values.\n"
        "For each real issue set verdict=adopt; if the chart looks fine for that issue, omit it "
        "or use verdict=reject. This stage is evidence-only: do not choose or propose an edit.\n"
        f"Institution philosophy:\n{persona.philosophy_text()}\n\n"
        'Output JSON only: {"findings":[{"issue":"mark_label_overlap|color_similarity|'
        'whitespace|other","severity":"short English","l3_refs":["philosophy title"],'
        '"severity":"high|medium|low","verdict":"adopt|reject",'
        '"rationale":"one English sentence"}]}'
    )
    if not briefing:
        return f"You are the visual design critic for {persona.name}.\n" + task
    return briefing_system_preamble(briefing) + "\n\n## Current task (Beat 3 · visual L3 review)\n" + task


def _has_semantic_multicolor(facts: dict) -> bool:
    """已有高亮目标、highlight 模式、或有效多色（含 condition 着色）时勿强行单色。"""
    mode = str(facts.get("coloring_mode") or "").strip().lower()
    if mode in ("highlight", "paired", "categorical"):
        return True
    if facts.get("emphasis_target"):
        return True
    colors = [c for c in (facts.get("colors_effective") or []) if isinstance(c, str)]
    # 去重后仍 ≥2 → 图上已有角色色差（如末年强调）
    uniq = {c.lower() for c in colors}
    if len(uniq) >= 2:
        return True
    return False


def _overlap_label_ops(facts: dict, requested: set[str]) -> list[dict]:
    """重叠接地：VL facts 优先——密轴→thin；确有柱上数值层且请求 remove/shorten→remove。

    不得因 has_value_labels 对「仅 thin」请求附带删字；也不得在无数值层时把
    shorten 回退成 remove（像素标注图会被误删光）。
    """
    ops: list[dict] = []
    dense = bool(facts.get("axis_x_dense"))
    has_vals = bool(facts.get("has_value_labels"))
    want_thin = bool(requested & {"thin_axis_labels", "thin_axis_ticks"})
    # 显式 remove 仅在确有柱上数值层时落地；否则 no-op（避免误删 callout）
    want_remove = bool(requested & {"remove_value_labels"}) and has_vals
    if "shorten_labels" in requested:
        if dense:
            want_thin = True
        elif has_vals:
            want_remove = True
        # 无密轴且无柱上数值：不落地 remove，留给 padding/height
    if want_thin:
        ops.append({"action": "thin_axis_labels", "channel": "x", "max_ticks": 8})
    if want_remove:
        ops.append({"action": "remove_value_labels"})
    return ops


def _ground_actions(
    persona: Persona, facts: dict, actions: list[str]
) -> tuple[list[dict], bool, list[str]]:
    """将 preferred_actions 接地为受控 ops。

    返回 (ops, suggested_only, soft_notes)。
    软建议（nudge_title）不阻止可执行 ops 落地；仅当没有任何可执行 op 时 suggested_only。
    """
    ops: list[dict] = []
    soft_notes: list[str] = []
    skip_uniform = _has_semantic_multicolor(facts)
    overlap_req: set[str] = set()

    for act in actions:
        if act not in ALLOWED_ACTIONS or act == "none":
            continue
        if act in SOFT_ACTIONS:
            if act != "none":
                soft_notes.append(act)
            continue
        if act == "increase_padding":
            ops.append({"action": "merge_config", "config": {"padding": 16}})
        elif act == "increase_height":
            h = facts.get("height") or (facts.get("chart_slice") or {}).get("height")
            try:
                base = int(h) if h else 450
            except (TypeError, ValueError):
                base = 450
            ops.append({"action": "set_size", "height": base + 48})
        elif act in (
            "shorten_labels",
            "remove_value_labels",
            "thin_axis_labels",
            "thin_axis_ticks",
        ):
            overlap_req.add(act)
        elif act == "normalize_axis_title_layout":
            if not any(o.get("action") == "normalize_axis_title_layout" for o in ops):
                ops.append({"action": "normalize_axis_title_layout"})
        elif act == "rotate_x_labels":
            ops.append({
                "action": "set_axis", "channel": "x",
                "axis": {"labelAngle": -45, "labelAlign": "right", "labelBaseline": "middle", "labelOverlap": True, "labelPadding": 8},
            })
        elif act == "reduce_axis_grid":
            # 常见时间序列：移除干扰较大的纵向网格，保留水平读数辅助线。
            ops.extend([
                {"action": "set_axis", "channel": "x", "axis": {"grid": False}},
                {"action": "set_axis", "channel": "y", "axis": {"grid": True}},
            ])
        elif act == "zero_baseline":
            # 仅柱/面积等长度编码可安全采用零基线；散点/折线不由视觉层擅自截断。
            if str(facts.get("mark_type") or "").lower() in {"bar", "area", "rect"}:
                ops.append({"action": "set_axis", "channel": "y", "scale": {"zero": True}})
            else:
                soft_notes.append("zero_baseline_not_applicable")
        elif act in {"widen_bars", "separate_bars"}:
            if str(facts.get("mark_type") or "").lower() == "bar":
                ops.append({"action": "set_axis", "channel": "x", "scale": {"paddingInner": 0.1 if act == "widen_bars" else 0.35}})
            else:
                soft_notes.append(f"{act}_not_bar")
        elif act == "round_bar_corners":
            if str(facts.get("mark_type") or "").lower() == "bar":
                ops.append({"action": "set_mark_style", "style": {"cornerRadius": 3}})
            else:
                soft_notes.append("round_bar_corners_not_bar")
        elif act == "soften_marks":
            ops.append({"action": "set_mark_style", "style": {"opacity": 0.85}})
        elif act == "improve_text_legibility":
            ops.append({"action": "set_text_style", "style": {"fontSize": 12}})
        elif act == "deemphasize_annotations":
            if facts.get("has_value_labels"):
                overlap_req.add("remove_value_labels")
            else:
                ops.append({"action": "set_text_style", "style": {"opacity": 0.85}})
        elif act == "move_legend_top":
            if facts.get("has_legend"):
                ops.append({"action": "set_legend", "orient": "top"})
            else:
                soft_notes.append("move_legend_top_no_legend")
        elif act == "remove_legend_title":
            if facts.get("has_legend"):
                ops.append({"action": "set_legend", "title": None})
            else:
                soft_notes.append("remove_legend_title_no_legend")
        elif act == "tighten_axis_titles":
            ops.extend([
                {"action": "set_axis", "channel": "x", "axis": {"titlePadding": 8}},
                {"action": "set_axis", "channel": "y", "axis": {"titlePadding": 8}},
            ])
        elif act in ("recolor_categorical", "recolor_paired", "recolor_uniform"):
            mode = act.replace("recolor_", "")
            # 字面双色/highlight：成对色差须换机构主色+强调色，勿因 category_field 走 range
            try:
                from .beats import _needs_literal_highlight_ops, _ops_for_coloring_mode

                if _needs_literal_highlight_ops(facts):
                    mode = "highlight"
            except Exception:  # noqa: BLE001
                from .beats import _ops_for_coloring_mode
            if mode == "uniform" and skip_uniform and not (
                facts.get("literal_color_encoding")
                or str(facts.get("coloring_mode") or "") == "highlight"
            ):
                soft_notes.append("recolor_uniform_skipped_semantic_multicolor")
                continue
            try:
                colored = _ops_for_coloring_mode(persona, facts, mode)
            except Exception:  # noqa: BLE001
                colored = []
            if colored:
                ops.extend(colored)
            else:
                soft_notes.append(f"{act}_ungrounded")

    if overlap_req:
        for o in _overlap_label_ops(facts, overlap_req):
            if not any(existing.get("action") == o.get("action") for existing in ops):
                ops.append(o)

    suggested_only = not ops
    return ops, suggested_only, soft_notes


def _finding_to_adopted(persona: Persona, facts: dict, finding: dict) -> dict | None:
    if not isinstance(finding, dict):
        return None
    if str(finding.get("verdict") or "adopt").lower() != "adopt":
        return None
    issue = str(finding.get("issue") or "other").strip().lower()
    rule_id = ISSUE_TO_RULE.get(issue, "v-visual")
    actions = [
        str(a).strip().lower()
        for a in (finding.get("preferred_actions") or [])
        if isinstance(a, str)
    ]
    actions = [a for a in actions if a in ALLOWED_ACTIONS]
    # 重叠类默认补接地动作（模型常只写 issue、不写 preferred_actions）
    if rule_id == "v-overlap" and not any(
        a
        in (
            "remove_value_labels",
            "shorten_labels",
            "thin_axis_labels",
            "thin_axis_ticks",
            "increase_padding",
            "increase_height",
        )
        for a in actions
    ):
        # 密轴→thin；柱上数值→remove；否则只加留白（勿 shorten→误删标注）
        if facts.get("axis_x_dense"):
            actions = list(actions) + ["thin_axis_labels"]
        elif facts.get("has_value_labels"):
            actions = list(actions) + ["remove_value_labels"]
        else:
            actions = list(actions) + ["increase_padding"]
    ops, suggested_only, soft_notes = _ground_actions(persona, facts, actions)
    conf = finding.get("severity")
    if conf not in ("high", "medium", "low"):
        conf = "low"
    if conf == "high":
        conf = "medium"
    l3_refs = [str(x) for x in (finding.get("l3_refs") or []) if x][:4]
    rationale = str(finding.get("rationale") or finding.get("severity") or "Visual L3 review")
    if l3_refs:
        rationale = f"{rationale} (L3: {', '.join(l3_refs)})"
    if soft_notes:
        rationale = f"{rationale}；soft={','.join(soft_notes)}"
    phil = persona.philosophy[0] if persona.philosophy else None
    return {
        "layer": "L3-derived",
        "rule_id": rule_id,
        "rule_text": str(finding.get("severity") or issue),
        "strength": "should",
        "story_id": "",
        "src": [f"L3-visual:{r}" for r in l3_refs] or ["L3-visual"],
        "derived": True,
        "ops": ops,
        "confidence": conf,
        "rationale": rationale,
        "suggested_only": suggested_only,
        "philosophy_quote": (phil.quote if phil else "") or "",
        "label": None,
    }


def _ensure_layout_facts(spec: dict, facts: dict) -> tuple[dict, list[dict]]:
    """保证 facts 含 layout_slice，并返回程序可落地 adopted。"""
    layout_slice = facts.get("layout_slice")
    if not isinstance(layout_slice, dict):
        layout_slice = build_layout_slice(spec, facts)
        facts["layout_slice"] = layout_slice
        facts["layout_flags"] = list(layout_slice.get("flags") or [])
    return layout_slice, list(program_layout_adopted(layout_slice))


async def run_visual_review(
    persona: Persona,
    spec: dict,
    facts: dict,
    llm: LLMClient,
) -> tuple[list[dict], list[dict], dict]:
    """返回 (adopted, rejected, meta)。

    本函数只负责看图和记录证据；不直接落地通用 ``v-*`` 修改。随后同一拍的
    persona strategy 会把 finding 结合本机构 quote 编译成候选动作。
    """
    from .spec_render import render_vl_to_png_data_url

    layout_slice, layout_adopted = _ensure_layout_facts(spec, facts)
    meta: dict[str, Any] = {
        "ran": False,
        "skipped": None,
        "image_source": None,
        "layout_flags": layout_slice.get("flags"),
        "layout_auto": [a["rule_id"] for a in layout_adopted],
    }

    def _skip(reason: str) -> tuple[list[dict], list[dict], dict]:
        meta["skipped"] = reason
        return [], [], meta

    if settings.vision_mode == "off":
        return _skip("vision_mode=off")
    if llm.mode != "live":
        return _skip("llm_not_live")

    image = facts.get("preview_image")
    image_source = "client" if image else None
    if not image:
        data_url, render_meta = render_vl_to_png_data_url(spec)
        meta["render"] = render_meta
        if data_url:
            image = data_url
            facts["preview_image"] = data_url
            image_source = "server_render"
        else:
            return _skip(f"render_failed:{render_meta.get('error') or 'unknown'}")
    meta["image_source"] = image_source

    chart_slice = facts.get("chart_slice")
    if not isinstance(chart_slice, dict):
        chart_slice = build_chart_slice(spec, facts)
    layout_candidates = program_layout_candidates(layout_slice)
    adopted: list[dict] = []

    briefing = facts.get("advisor_briefing")
    if not isinstance(briefing, dict):
        briefing = None
    system = visual_review_system(persona, briefing)
    user = json.dumps(
        {
            "task": "Inspect the attached chart image for visual issues vs L3 principles.",
            "chart_slice": chart_slice,
            "layout_slice": layout_slice,
            "program_layout_candidates": layout_candidates,
            "l3": _l3_bundle(persona),
            "coloring_mode": facts.get("coloring_mode"),
            "colors_effective": facts.get("colors_effective"),
            "emphasis_target": facts.get("emphasis_target"),
            "semantic_multicolor": _has_semantic_multicolor(facts),
            "source_annotation_baseline": list(facts.get("annotation_text_baseline") or [])[:24],
            "original_structure": facts.get("original_structure"),
            "chart_audit": facts.get("chart_audit"),
        },
        ensure_ascii=False,
    )
    try:
        if not hasattr(llm, "chat_json_vision"):
            meta.update(
                {
                    "ran": False,
                    "skipped": "no_vision_api",
                    "layout_flags": layout_slice.get("flags"),
                    "layout_auto": [a["rule_id"] for a in adopted],
                }
            )
            return [], [], meta
        raw = await llm.chat_json_vision(system, user, str(image), detail="low")
    except LLMError as exc:
        meta.update(
            {
                "ran": False,
                "skipped": f"vision_error:{exc}",
                "layout_flags": layout_slice.get("flags"),
                "layout_auto": [a["rule_id"] for a in adopted],
            }
        )
        return [], [], meta
    except Exception as exc:  # noqa: BLE001
        meta.update(
            {
                "ran": False,
                "skipped": f"vision_error:{type(exc).__name__}: {exc}",
                "layout_flags": layout_slice.get("flags"),
                "layout_auto": [a["rule_id"] for a in adopted],
            }
        )
        return [], [], meta

    findings = []
    if isinstance(raw, dict):
        findings = raw.get("findings") or []
    elif isinstance(raw, list):
        findings = raw
    if not isinstance(findings, list):
        findings = []

    rejected: list[dict] = []
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            continue
        issue = str(f.get("issue") or "other").strip().lower()
        rule_id = ISSUE_TO_RULE.get(issue, "v-visual")
        if str(f.get("verdict") or "").lower() == "reject":
            rejected.append(
                {
                    "rule_id": rule_id,
                    "layer": "L3-derived",
                    "label": rule_id,
                    "reason": str(f.get("rationale") or "visual review: no change"),
                    "src": ["L3-visual"],
                }
            )
            continue
        # findings 只进入 meta，交给 persona-specific strategy 在拍3裁决。

    meta.update(
        {
            "ran": True,
            "model": settings.vision_model,
            "finding_count": len(findings),
            "findings": findings,
            "adopted": [],
            "rejected": [r["rule_id"] for r in rejected],
            "layout_flags": layout_slice.get("flags"),
            "layout_auto": [
                a["rule_id"] for a in layout_adopted
            ],
        }
    )
    return [], rejected, meta


def strategy_escalations_from_findings(persona: Persona, facts: dict, meta: dict) -> list[dict]:
    """将视觉问题映射为当前 persona YAML 明确允许的策略候选。

    每项都携带机构 quote；没有 strategy 的问题只记录，不会退回成共享通用操作。
    """
    findings = meta.get("findings") if isinstance(meta.get("findings"), list) else []
    component_ir = facts.get("component_ir") if isinstance(facts.get("component_ir"), dict) else {}
    pixel_canvas = bool(component_ir.get("pixel_positioned_text"))
    out: list[dict] = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict) or str(finding.get("verdict") or "adopt").lower() != "adopt":
            continue
        issue = str(finding.get("issue") or "other").strip().lower()
        # 策略属于 L2 adaptation：有条件（视觉 issue + chart facts）、有动作，
        # 只是 scope=visual-strategy 令其不在拍2脱离图像证据时提前触发。
        for adaptation in persona.adaptations:
            if adaptation.scope != "visual-strategy":
                continue
            strategy = adaptation.raw
            if not isinstance(strategy, dict) or issue not in {str(x).lower() for x in strategy.get("visual_issues", [])}:
                continue
            when = strategy.get("when") if isinstance(strategy.get("when"), dict) else {}
            if when.get("axis_x_dense") is True and not facts.get("axis_x_dense"):
                continue
            marks = {str(x).lower() for x in when.get("mark_types", [])}
            if marks and str(facts.get("mark_type") or "").lower() not in marks:
                continue
            then = strategy.get("then") if isinstance(strategy.get("then"), dict) else {}
            actions = [str(a) for a in then.get("visual_actions", [])]
            # 像素画布的文字碰撞不是普通 label 密度问题。padding/height/删除文字会
            # 改变绝对布局；必须交给 component-assembly，而非视觉策略直接补丁。
            if pixel_canvas and issue in {"mark_label_overlap", "text_mark_collision", "overlap", "whitespace", "crowding"}:
                unsafe = {"increase_padding", "increase_height", "remove_value_labels", "improve_text_legibility", "deemphasize_annotations"}
                if set(actions) & unsafe:
                    continue
            ops, suggested_only, notes = _ground_actions(persona, facts, actions)
            quote = str(strategy.get("evidence_quote") or "").strip()
            if not quote:
                continue
            sid = str(strategy.get("id") or f"visual-{index}")
            out.append({
                "layer": "L3-derived", "rule_id": sid, "rule_text": quote,
                "strength": str(strategy.get("strength") or "should"), "story_id": "",
                "src": [f"L3-strategy:{sid}"], "when": {},
                "why": f"visual issue={issue}; {finding.get('rationale') or ''}",
                "compiled": {"ops": ops, "needs": [], "any_of": None},
                "suggested_only": suggested_only,
                "strategy_notes": notes,
            })
    return out
