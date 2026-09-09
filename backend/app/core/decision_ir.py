"""Decision IR：LLM 理解/裁决用的紧凑图摘要（不经 LLM 写 VL）。

程序负责 WorkingSpec + Ops；LLM 只读 slice / facts，产出语义与裁决字段。
强调绑定（emphasis_field + emphasis_mechanism）由拍1 产出，拍4 按机制编译。
"""
from __future__ import annotations

from typing import Any

COLORING_MODES = frozenset({"uniform", "paired", "categorical", "highlight"})
EMPHASIS_MECHANISMS = frozenset(
    {"series_scale", "literal_condition", "category_condition"}
)


def _clip(s: Any, n: int = 120) -> str:
    t = str(s or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _primary_view(spec: dict) -> dict | None:
    """取主几何 unit（根 unit 或 layer 中第一个带 mark+encoding 的）。"""
    if not isinstance(spec, dict):
        return None
    if isinstance(spec.get("mark"), (str, dict)) and isinstance(spec.get("encoding"), dict):
        return spec
    for key in ("layer", "hconcat", "vconcat", "concat"):
        kids = spec.get(key)
        if not isinstance(kids, list):
            continue
        for child in kids:
            if not isinstance(child, dict):
                continue
            hit = _primary_view(child)
            if hit is not None:
                return hit
    return None


def _mark_type(mark: Any) -> str | None:
    if isinstance(mark, str):
        return mark
    if isinstance(mark, dict) and isinstance(mark.get("type"), str):
        return mark["type"]
    return None


def _series_n(facts: dict) -> int:
    try:
        return int(facts.get("series_count") or 1)
    except (TypeError, ValueError):
        return 1


def infer_color_structure(facts: dict, color: dict | None = None) -> str:
    """程序可判定的着色结构（供 LLM 与编译分流，非图型特判）。

    series_scale 仅多序列（series_count>=2）；单序列按类着色仍走 mark_only /
    category_condition，避免与 a-color-single 收束冲突。
    """
    color = color if isinstance(color, dict) else {}
    color_field = color.get("field") or facts.get("color_field")
    if facts.get("literal_color_encoding") and facts.get("accent_color"):
        return "literal_condition"
    if color_field and _series_n(facts) >= 2:
        return "series_scale"
    return "mark_only"


def _sample_list(values: Any, n: int = 12) -> list[Any]:
    if not isinstance(values, list):
        return []
    out = []
    for v in values:
        if v is None:
            continue
        out.append(v)
        if len(out) >= n:
            break
    return out


def allowed_emphasis_fields(facts: dict, chart_slice: dict | None = None) -> set[str]:
    """emphasis_field 合法集合。"""
    fields: set[str] = set()
    for key in ("category_field", "color_field"):
        v = facts.get(key)
        if isinstance(v, str) and v.strip():
            fields.add(v.strip())
    if isinstance(chart_slice, dict):
        for key in ("category_field", "color_field"):
            v = chart_slice.get(key)
            if isinstance(v, str) and v.strip():
                fields.add(v.strip())
        color = chart_slice.get("color") if isinstance(chart_slice.get("color"), dict) else {}
        cf = color.get("field")
        if isinstance(cf, str) and cf.strip():
            fields.add(cf.strip())
    return fields


def infer_emphasis_binding(
    facts: dict,
    *,
    emphasis_target: Any = None,
    color_structure: str | None = None,
) -> dict[str, Any]:
    """确定性强调绑定（mock / LLM 校验失败回退）。"""
    target = emphasis_target if emphasis_target is not None else facts.get("emphasis_target")
    if target is not None and not isinstance(target, (str, int, float)):
        target = str(target)
    if isinstance(target, str) and not target.strip():
        target = None

    structure = color_structure or infer_color_structure(facts)
    series_vals = {_norm_token(v) for v in (facts.get("series_values") or [])}
    cat_vals = {_norm_token(v) for v in (facts.get("categories") or [])}
    color_field = facts.get("color_field")
    category_field = facts.get("category_field")
    tnorm = _norm_token(target) if target is not None else ""

    if structure == "literal_condition":
        return {
            "emphasis_target": target,
            "emphasis_field": category_field or color_field,
            "emphasis_mechanism": "literal_condition",
        }

    if (
        target is not None
        and color_field
        and tnorm in series_vals
        and (structure == "series_scale" or _series_n(facts) >= 2)
    ):
        return {
            "emphasis_target": target,
            "emphasis_field": color_field,
            "emphasis_mechanism": "series_scale",
        }

    if target is not None and category_field and (tnorm in cat_vals or not series_vals):
        return {
            "emphasis_target": target,
            "emphasis_field": category_field,
            "emphasis_mechanism": "category_condition",
        }

    if structure == "series_scale" and color_field:
        return {
            "emphasis_target": target,
            "emphasis_field": color_field,
            "emphasis_mechanism": "series_scale",
        }

    return {
        "emphasis_target": target,
        "emphasis_field": category_field or color_field,
        "emphasis_mechanism": "category_condition" if target is not None else None,
    }


def _norm_token(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def build_chart_slice(spec: dict, facts: dict | None = None) -> dict[str, Any]:
    """给慢道 LLM 的紧凑图摘要（替代完整 VL JSON）。"""
    facts = facts or {}
    view = _primary_view(spec) or {}
    enc = view.get("encoding") if isinstance(view.get("encoding"), dict) else {}
    # 父层无 color.field 时，从子 layer 取（共享 encoding 重建后常两边都有）
    color = enc.get("color") if isinstance(enc.get("color"), dict) else {}
    if not color.get("field"):
        for child in spec.get("layer") or []:
            if not isinstance(child, dict):
                continue
            cenc = child.get("encoding") if isinstance(child.get("encoding"), dict) else {}
            c0 = cenc.get("color") if isinstance(cenc.get("color"), dict) else {}
            if c0.get("field"):
                color = c0
                break
    scale = color.get("scale") if isinstance(color.get("scale"), dict) else {}
    title = spec.get("title")
    title_text = facts.get("title_text")
    subtitle = None
    if isinstance(title, dict):
        title_text = title_text or title.get("text")
        subtitle = title.get("subtitle")
    elif isinstance(title, str):
        title_text = title_text or title

    color_field = color.get("field") or facts.get("color_field")
    category_field = facts.get("category_field")
    color_structure = infer_color_structure(facts, color)
    category_samples = _sample_list(facts.get("categories"))
    series_samples = _sample_list(facts.get("series_values"))
    if not series_samples and isinstance(scale.get("domain"), list):
        series_samples = _sample_list(scale.get("domain"))

    color_slice: dict[str, Any] = {
        "field": color_field,
        "type": color.get("type"),
        "has_condition": "condition" in color,
        "literal_value": color.get("value") if not color.get("field") else None,
        "scale_range": [
            c for c in (scale.get("range") or []) if isinstance(c, str)
        ][:12],
        "scale_domain": [
            d for d in (scale.get("domain") or []) if isinstance(d, (str, int, float))
        ][:12],
    }

    return {
        "mark_type": _mark_type(view.get("mark")) or facts.get("mark_type"),
        "title_text": _clip(title_text, 160),
        "subtitle": subtitle
        if isinstance(subtitle, (str, list))
        else None,
        "encoding_channels": sorted(enc.keys()) if enc else sorted(
            (view.get("encoding") or {}).keys()
            if isinstance(view.get("encoding"), dict)
            else []
        ),
        "color": color_slice,
        "color_field": color_field,
        "color_structure": color_structure,
        "colors_effective": list(facts.get("colors_effective") or [])[:12],
        "color_count": facts.get("color_count"),
        "per_category_coloring": bool(facts.get("per_category_coloring")),
        "category_field": category_field,
        "value_field": facts.get("value_field"),
        "category_count": facts.get("category_count"),
        "series_count": facts.get("series_count"),
        "categories": category_samples,
        "category_samples": category_samples,
        "series_values": series_samples,
        "series_samples": series_samples,
        "layer_roles": [
            {
                "index": r.get("index"),
                "mark_type": r.get("mark_type"),
                "role": r.get("role"),
            }
            for r in (facts.get("layer_roles") or [])[:16]
            if isinstance(r, dict)
        ],
        "spec_keys": [
            k
            for k in (
                "mark",
                "encoding",
                "layer",
                "vconcat",
                "hconcat",
                "title",
                "data",
            )
            if k in spec
        ],
    }


def _target_in_domain(target: Any, domain: list[Any]) -> bool:
    if target is None or not domain:
        return False
    t = _norm_token(target)
    return any(_norm_token(v) == t for v in domain)


def normalize_read_decision(raw: Any, facts: dict, *, fallback: dict) -> dict[str, Any]:
    """拍1 LLM JSON → Decision IR 语义字段（无效则回退 fallback）。

    校验 emphasis_field / emphasis_mechanism；错绑时回退 ``infer_emphasis_binding``。
    """
    if not isinstance(raw, dict):
        fb = {**fallback, "decision_source": "fallback_invalid"}
        bind = infer_emphasis_binding({**facts, **fb}, emphasis_target=fb.get("emphasis_target"))
        return {**fb, **bind}

    intent = str(raw.get("intent") or fallback.get("intent") or "comparison").strip()
    mode = str(raw.get("coloring_mode") or "").strip().lower()
    if mode not in COLORING_MODES:
        mode = str(fallback.get("coloring_mode") or "uniform")
    emphasis = raw.get("emphasis_target")
    if emphasis is not None and not isinstance(emphasis, (str, int, float)):
        emphasis = str(emphasis) if emphasis else None
    if isinstance(emphasis, str) and not emphasis.strip():
        emphasis = None
    if emphasis is None:
        emphasis = fallback.get("emphasis_target")

    organization = str(raw.get("organization") or "").strip()
    chart_slice = facts.get("chart_slice") if isinstance(facts.get("chart_slice"), dict) else {}
    structure = (
        chart_slice.get("color_structure")
        or infer_color_structure(facts)
    )
    allowed = allowed_emphasis_fields(facts, chart_slice)

    emp_field = raw.get("emphasis_field")
    if emp_field is not None:
        emp_field = str(emp_field).strip() or None
    mechanism = str(raw.get("emphasis_mechanism") or "").strip().lower() or None
    if mechanism and mechanism not in EMPHASIS_MECHANISMS:
        mechanism = None

    series_domain = list(
        chart_slice.get("series_samples")
        or chart_slice.get("series_values")
        or facts.get("series_values")
        or []
    )
    cat_domain = list(
        chart_slice.get("category_samples")
        or chart_slice.get("categories")
        or facts.get("categories")
        or []
    )

    bind_ok = True
    if emp_field and emp_field not in allowed:
        bind_ok = False
    if mechanism == "series_scale":
        color_f = facts.get("color_field") or chart_slice.get("color_field")
        if emp_field and color_f and emp_field != color_f:
            bind_ok = False
        if emphasis is not None and series_domain and not _target_in_domain(emphasis, series_domain):
            bind_ok = False
    elif mechanism == "category_condition":
        cat_f = facts.get("category_field") or chart_slice.get("category_field")
        if emp_field and cat_f and emp_field != cat_f and emp_field not in allowed:
            bind_ok = False
        if emphasis is not None and cat_domain and not _target_in_domain(emphasis, cat_domain):
            # 允许 max 名在 categories 中；若域空则不否决
            if cat_domain:
                bind_ok = False
    elif mechanism == "literal_condition":
        if structure not in ("literal_condition", "mark_only"):
            # 结构不是字面双色时不信任该 mechanism
            if structure == "series_scale":
                bind_ok = False

    used_infer = False
    if not mechanism or (emphasis is not None and not emp_field) or not bind_ok:
        used_infer = True
        inferred = infer_emphasis_binding(
            {**facts, "emphasis_target": emphasis},
            emphasis_target=emphasis,
            color_structure=structure,
        )
        emp_field = inferred.get("emphasis_field")
        mechanism = inferred.get("emphasis_mechanism")
        if not bind_ok and emphasis is not None and not mechanism:
            emphasis = None
            emp_field = None

    return {
        "data_topic": str(raw.get("data_topic") or fallback.get("data_topic") or "general"),
        "intent": intent,
        "emphasis_target": emphasis,
        "emphasis_field": emp_field,
        "emphasis_mechanism": mechanism,
        "coloring_mode": mode,
        "summary": str(raw.get("summary") or fallback.get("summary") or ""),
        "organization": organization[:400] if organization else "",
        "decision_source": "llm+infer_binding" if used_infer else "llm",
    }


def attach_slice_to_escalation_items(
    items: list[dict], chart_slice: dict[str, Any]
) -> list[dict]:
    """拍3 items 附带同一 chart_slice（只读）。"""
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({**it, "chart_slice": chart_slice})
    return out
