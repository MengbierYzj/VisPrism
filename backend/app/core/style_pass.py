"""拍3.6 · L3 风格化：设计哲学 → 受控布局/几何动作，让成图带上机构气质。

用户观察：提案几乎只动颜色和标题，布局/间距/mark 几何（窄条大留白、画布
呼吸感、网格轻重、轴框有无）从不出现——因为 ops 只从 L1/L2 规则编译，而
多数指南没写这类细节，哲学层（L3）没有落地成 ops 的通道。

本模块延续「慢道判断、快道有界执行」：live 模式下把 persona 的哲学原则 +
版面相关令牌 + 图表几何事实交给 LLM，在一个**受控动作空间**（每个动作映射
到既有安全 op，参数带硬边界，validator 负责钳制）里提议 0-3 个风格动作；
每个动作必须点名一条真实哲学原则作为担保，产出 L3-derived / may / low 置信
的采纳项，交拍4 统一编译与效果核验。mock 或失败返回空列表，不影响主链路。

与 v1 的差别（应对「各家都挑同样两个 move、只差参数」的同质化）：
- 动作空间 3 → 7（网格轻重、轴框有无、图高比例进入词汇表）；
- prompt 要求「选别家不会选的 move 组合与参数」，并给出机构倾向示例；
- 已被 L1/L2 规则占用的表面自动让位（_surface_taken），避免同节点打架。
"""
from __future__ import annotations

import json
from typing import Any

# move → 参数边界与适用 mark；params 值三种形态：
#   (lo, hi) 数值区间 / [choice, ...] 枚举 / bool 开关
MOVES: dict[str, dict] = {
    "bar_spacing": {
        "marks": {"bar"},
        "params": {"padding_inner": (0.05, 0.75), "padding_outer": (0.0, 0.6)},
        "label": "Bar rhythm",
    },
    "corner_rounding": {
        "marks": {"bar"},
        "params": {"radius": (0.0, 8.0)},
        "label": "Mark finish",
    },
    "canvas_margin": {
        "marks": None,
        "params": {"padding": (8.0, 48.0)},
        "label": "Canvas breathing room",
    },
    "mark_opacity": {
        "marks": {"circle", "line", "area", "point"},
        "params": {"opacity": (0.55, 1.0)},
        "label": "Mark weight",
    },
    "grid_weight": {
        "marks": None,
        "params": {"grid_opacity": (0.15, 1.0), "dash": ["solid", "dotted", "dashed"]},
        "label": "Grid presence",
    },
    "axis_frame": {
        "marks": None,
        "params": {"domain": bool, "ticks": bool},
        "label": "Axis frame",
    },
    "chart_height": {
        "marks": None,
        "params": {"height": (240.0, 520.0)},
        "label": "Canvas proportion",
    },
}

_TOKEN_HINT_KEYS = ("spacing", "space", "gap", "padding", "radius", "margin", "grid")


def _spacing_tokens(persona) -> dict:
    """版面相关令牌（spacing/gap/radius…）作为 LLM 参数取值的机构线索。"""
    out: dict = {}
    try:
        index = persona.token_index()
    except Exception:
        return out
    for key, value in index.items():
        lowered = str(key).lower()
        if any(hint in lowered for hint in _TOKEN_HINT_KEYS) and isinstance(value, (str, int, float)):
            out[str(key)] = value
        if len(out) >= 12:
            break
    return out


def _band_channel(spec: dict) -> str | None:
    """找 bar 的类别轴（band scale 所在通道）；无（如时间轴 bar）则 bar_spacing 不可用。"""
    from .actions import _iter_encoding_views

    for view in _iter_encoding_views(spec):
        enc = view.get("encoding")
        if not isinstance(enc, dict):
            continue
        for cat_key, val_key in (("x", "y"), ("y", "x")):
            cat, val = enc.get(cat_key), enc.get(val_key)
            if (
                isinstance(cat, dict)
                and cat.get("field")
                and str(cat.get("type") or "") in ("nominal", "ordinal")
                and isinstance(val, dict)
                and str(val.get("type") or "") == "quantitative"
            ):
                return cat_key
    return None


def _surface_taken(adopted: list[dict], move: str) -> bool:
    """已有规则占用同一表面（如尺寸规则带 padding）时让位，避免同节点打架。"""
    for item in adopted or []:
        for op in item.get("ops") or []:
            action = op.get("action")
            if move == "bar_spacing" and (
                action == "set_band_padding"
                or (action == "set_axis" and isinstance(op.get("scale"), dict) and "paddingInner" in op["scale"])
            ):
                return True
            if move == "corner_rounding" and action == "set_mark_style" and isinstance(op.get("style"), dict) and any(
                k.startswith("cornerRadius") for k in op["style"]
            ):
                return True
            if move == "canvas_margin" and action == "merge_config" and isinstance(op.get("config"), dict) and "padding" in op["config"]:
                return True
            if move == "chart_height" and action == "set_size":
                return True
            if move == "mark_opacity" and action == "set_mark_style" and isinstance(op.get("style"), dict) and "opacity" in op["style"]:
                return True
            if move == "grid_weight" and (
                action == "set_grid_style"
                or (action == "merge_config" and isinstance(op.get("config"), dict) and any(k in op["config"] for k in ("axisY", "axisX", "axis")))
                or (action == "set_axis" and isinstance(op.get("axis"), dict) and any(k.startswith("grid") for k in op["axis"]))
            ):
                return True
            if move == "axis_frame" and action == "set_axis" and isinstance(op.get("axis"), dict) and any(
                k in op["axis"] for k in ("domain", "ticks")
            ):
                return True
    return False


def available_moves(spec: dict, facts: dict, adopted: list[dict]) -> dict[str, dict]:
    """按图表形态与已占用表面收窄动作空间（不给模型任何越界机会）。"""
    mark = str(facts.get("mark_type") or "")
    fixed_layout = bool((facts.get("component_ir") or {}).get("pixel_positioned_text")) or bool(
        facts.get("component_assembly_plan")
    )
    out: dict[str, dict] = {}
    for move, meta in MOVES.items():
        marks = meta["marks"]
        if marks is not None and mark not in marks:
            continue
        if move == "bar_spacing" and _band_channel(spec) is None:
            continue
        if move in ("canvas_margin", "chart_height") and fixed_layout:
            continue
        if move in ("grid_weight", "axis_frame") and mark == "arc":
            continue
        if _surface_taken(adopted, move):
            continue
        out[move] = meta
    return out


def _clamp(value: Any, lo: float, hi: float) -> float | None:
    try:
        return round(max(lo, min(float(value), hi)), 3)
    except (TypeError, ValueError):
        return None


def _build_ops(move: str, params: dict, spec: dict) -> list[dict] | None:
    """move + 钳制后的参数 → 既有安全 ops；不可编译返回 None。"""
    if move == "bar_spacing":
        inner, outer = params.get("padding_inner"), params.get("padding_outer")
        if inner is None and outer is None:
            return None
        op: dict = {"action": "set_band_padding"}
        if inner is not None:
            op["inner"] = inner
        if outer is not None:
            op["outer"] = outer
        return [op]
    if move == "corner_rounding":
        radius = params.get("radius")
        if radius is None:
            return None
        return [{"action": "set_mark_style", "style": {"cornerRadiusEnd": radius}}]
    if move == "canvas_margin":
        padding = params.get("padding")
        if padding is None:
            return None
        return [{"action": "merge_config", "config": {"padding": padding}}]
    if move == "mark_opacity":
        opacity = params.get("opacity")
        if opacity is None:
            return None
        return [{"action": "set_mark_style", "style": {"opacity": opacity}}]
    if move == "grid_weight":
        op = {"action": "set_grid_style"}
        dash = params.get("dash")
        if isinstance(dash, str):
            op["style"] = dash
        if params.get("grid_opacity") is not None:
            op["opacity"] = params["grid_opacity"]
        return [op] if len(op) > 1 else None
    if move == "axis_frame":
        patch = {}
        if "domain" in params:
            patch["domain"] = bool(params["domain"])
        if "ticks" in params:
            patch["ticks"] = bool(params["ticks"])
        if not patch:
            return None
        return [
            {"action": "set_axis", "channel": "x", "axis": dict(patch)},
            {"action": "set_axis", "channel": "y", "axis": dict(patch)},
        ]
    if move == "chart_height":
        height = params.get("height")
        if height is None:
            return None
        return [{"action": "set_size", "height": int(height)}]
    return None


def validate_moves(raw: Any, persona, spec: dict, moves: dict[str, dict]) -> list[dict]:
    """快道钳制：动作必须在空间内、参数夹到边界、哲学原则必须真实存在。"""
    if not isinstance(raw, dict):
        return []
    principle_ids = {p.id for p in getattr(persona, "philosophy", [])}
    quotes = {p.id: p.quote for p in getattr(persona, "philosophy", [])}
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw.get("moves") or []:
        if not isinstance(entry, dict):
            continue
        move = str(entry.get("move") or "")
        if move not in moves or move in seen:
            continue
        principle = str(entry.get("principle_id") or "")
        if principle not in principle_ids:
            continue
        bounds = moves[move]["params"]
        params_in = entry.get("params") if isinstance(entry.get("params"), dict) else {}
        params: dict = {}
        for key, bound in bounds.items():
            if key not in params_in:
                continue
            value = params_in[key]
            if isinstance(bound, tuple):
                clamped = _clamp(value, bound[0], bound[1])
                if clamped is not None:
                    params[key] = clamped
            elif isinstance(bound, list):
                if isinstance(value, str) and value in bound:
                    params[key] = value
            elif bound is bool:
                if isinstance(value, bool):
                    params[key] = value
                elif str(value).lower() in ("on", "off", "true", "false"):
                    params[key] = str(value).lower() in ("on", "true")
        ops = _build_ops(move, params, spec)
        if not ops:
            continue
        seen.add(move)
        out.append(
            {
                "move": move,
                "params": params,
                "principle_id": principle,
                "quote": quotes.get(principle, ""),
                "label": str(entry.get("label") or moves[move]["label"])[:40],
                "note": str(entry.get("note") or "").strip()[:200],
                "ops": ops,
            }
        )
        if len(out) >= 3:
            break
    return out


def _style_system(persona, moves: dict[str, dict]) -> str:
    lines = []
    for move, meta in moves.items():
        params = []
        for key, bound in meta["params"].items():
            if isinstance(bound, tuple):
                params.append(f"{key} in [{bound[0]}, {bound[1]}]")
            elif isinstance(bound, list):
                params.append(f"{key} in {{{', '.join(bound)}}}")
            else:
                params.append(f"{key} on/off")
        lines.append(f"- {move}: {', '.join(params)}")
    philosophy = "\n".join(
        f"- [{p.id}] {p.title}: \"{p.quote}\"" for p in getattr(persona, "philosophy", [])
    )
    return (
        f"You are the chart art director at {persona.name}. The chart's colours and text are already "
        "handled by written rules; your job is the part style guides rarely write down — the visual "
        "rhythm that makes a chart recognisably yours: bar weight versus whitespace, canvas breathing "
        "room, grid presence, axis framing, mark finish and weight.\n\n"
        "Your institution's design philosophy:\n"
        f"{philosophy}\n\n"
        "Available moves and hard parameter bounds (you may use each move at most once):\n"
        f"{chr(10).join(lines)}\n\n"
        "Propose 0-3 moves that would make this chart feel like one of your institution's published "
        "charts. Every move must be genuinely motivated by one of the philosophy principles above — "
        "cite its id. If the chart already reads right, or no principle speaks to these surfaces, "
        "return an empty list; never decorate for its own sake.\n"
        "Be opinionated and be DIFFERENT: pick the move combination and parameter values that express "
        "YOUR institution's characteristic density and rhythm — a minimal product house might drop the "
        "axis frame and run a whisper-light grid; an editorial house might keep a firm baseline, tighter "
        "bars and a heavier grid; a scientific publisher might choose dotted grid and generous margins. "
        "Do not settle for the generic middle values or the same two moves any institution would pick.\n\n"
        'Return JSON only: {"moves": [{"move": "bar_spacing", "params": {"padding_inner": 0.5}, '
        '"principle_id": "...", "label": "2-4 words", "note": "one sentence, institution voice, on the '
        'intended feel"}]}'
    )


def _style_user(facts: dict, spec: dict, tokens: dict) -> str:
    payload = {
        "chart": {
            "mark": facts.get("mark_type"),
            "categories": facts.get("category_count"),
            "series": facts.get("series_count"),
            "width": spec.get("width"),
            "height": spec.get("height"),
            "current_padding": spec.get("padding") or (spec.get("config") or {}).get("padding"),
            "title": facts.get("title_text"),
        },
        "institution_layout_tokens": tokens or None,
        "communication_goal": facts.get("communication_goal"),
    }
    return json.dumps(payload, ensure_ascii=False)


async def style_proposals(persona, spec: dict, facts: dict, adopted: list[dict], llm) -> list[dict]:
    """live 下按哲学提议风格动作；mock/无哲学/无可用动作/失败一律返回 []。"""
    if getattr(llm, "mode", "mock") != "live":
        return []
    if not getattr(persona, "philosophy", None):
        return []
    moves = available_moves(spec, facts, adopted)
    if not moves:
        return []
    try:
        raw = await llm.chat_json(_style_system(persona, moves), _style_user(facts, spec, _spacing_tokens(persona)))
    except Exception:
        return []
    validated = validate_moves(raw, persona, spec, moves)
    out = []
    for v in validated:
        out.append(
            {
                "layer": "L3-derived",
                "rule_id": f"d-style-{v['move']}",
                "rule_text": v["note"] or f"{v['label']} tuned to the house rhythm",
                "strength": "may",
                "story_id": "",
                "src": [f"philosophy.{v['principle_id']}"],
                "derived": True,
                "ops": v["ops"],
                "confidence": "low",
                "rationale": v["note"] or v["label"],
                "suggested_only": False,
                "philosophy_quote": v["quote"],
                "label": v["label"],
            }
        )
    return out
