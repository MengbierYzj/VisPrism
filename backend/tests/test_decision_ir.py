"""Decision IR：chart_slice 与读图决策归一（含强调绑定）。"""
from app.core.actions import apply_ops, build_emphasis_ops, compile_then
from app.core.decision_ir import (
    build_chart_slice,
    infer_color_structure,
    infer_emphasis_binding,
    normalize_read_decision,
)
from app.core.spec_rebuild import _restore_chrome_from_original


def test_build_chart_slice_color_and_title():
    spec = {
        "title": {"text": "Share of streaming", "subtitle": "Nielsen"},
        "mark": "arc",
        "encoding": {
            "theta": {"field": "pct", "type": "quantitative"},
            "color": {
                "field": "cat",
                "type": "nominal",
                "scale": {"range": ["#111111", "#222222"]},
            },
        },
        "data": {"values": []},
    }
    facts = {
        "mark_type": "arc",
        "color_field": "cat",
        "per_category_coloring": True,
        "colors_effective": ["#111111", "#222222"],
        "categories": ["A", "B"],
        "series_count": 1,
        "color_count": 2,
    }
    slice_ = build_chart_slice(spec, facts)
    assert slice_["mark_type"] == "arc"
    assert slice_["title_text"] == "Share of streaming"
    assert slice_["color"]["field"] == "cat"
    assert slice_["color"]["scale_range"] == ["#111111", "#222222"]
    assert "color" in slice_["encoding_channels"]
    # 单序列按类着色 ≠ multi-series scale
    assert slice_["color_structure"] == "mark_only"
    assert slice_["category_samples"] == ["A", "B"]


def test_infer_color_structure_literal_and_series():
    assert (
        infer_color_structure(
            {
                "literal_color_encoding": True,
                "accent_color": "#d46c31",
                "series_count": 1,
            }
        )
        == "literal_condition"
    )
    assert (
        infer_color_structure(
            {"color_field": "Entity", "series_count": 4, "series_values": ["A", "B"]}
        )
        == "series_scale"
    )


def test_infer_emphasis_binding_series_not_year():
    facts = {
        "category_field": "Year",
        "color_field": "Entity",
        "series_count": 4,
        "series_values": ["North America (WB)", "Sub-Saharan Africa (WB)"],
        "categories": [2005, 2010, 2024],
    }
    bind = infer_emphasis_binding(
        facts,
        emphasis_target="Sub-Saharan Africa (WB)",
        color_structure="series_scale",
    )
    assert bind["emphasis_field"] == "Entity"
    assert bind["emphasis_mechanism"] == "series_scale"


def test_normalize_rejects_year_bound_to_series_name():
    facts = {
        "category_field": "Year",
        "color_field": "Entity",
        "series_count": 4,
        "series_values": ["A", "B"],
        "categories": [2005, 2010],
        "chart_slice": {
            "color_structure": "series_scale",
            "category_field": "Year",
            "color_field": "Entity",
            "series_samples": ["A", "B"],
            "category_samples": [2005, 2010],
        },
    }
    fallback = {
        "data_topic": "general",
        "intent": "trend",
        "emphasis_target": None,
        "coloring_mode": "categorical",
        "summary": "fallback",
    }
    raw = {
        "data_topic": "science",
        "intent": "trend",
        "emphasis_target": "B",
        "emphasis_field": "Year",  # 错绑
        "emphasis_mechanism": "category_condition",
        "coloring_mode": "categorical",
        "organization": "Multi-series lines",
        "summary": "Internet use",
    }
    out = normalize_read_decision(raw, facts, fallback=fallback)
    assert out["emphasis_field"] == "Entity"
    assert out["emphasis_mechanism"] == "series_scale"
    assert out["decision_source"] == "llm+infer_binding"


def test_normalize_read_decision_trusts_llm_mode():
    fallback = {
        "data_topic": "general",
        "intent": "comparison",
        "emphasis_target": None,
        "coloring_mode": "uniform",
        "summary": "fallback",
    }
    raw = {
        "data_topic": "culture",
        "intent": "composition",
        "emphasis_target": "Streaming",
        "emphasis_field": "cat",
        "emphasis_mechanism": "category_condition",
        "coloring_mode": "categorical",
        "organization": "Four-part donut composition",
        "summary": "Streaming share of TV",
    }
    facts = {
        "category_field": "cat",
        "color_field": "cat",
        "series_count": 1,
        "per_category_coloring": True,
        "color_count": 4,
        "categories": ["Streaming", "Broadcast"],
        "series_values": [],
        "chart_slice": {
            "color_structure": "mark_only",
            "category_field": "cat",
            "color_field": "cat",
            "category_samples": ["Streaming", "Broadcast"],
            "series_samples": [],
        },
    }
    out = normalize_read_decision(raw, facts, fallback=fallback)
    assert out["coloring_mode"] == "categorical"
    assert out["intent"] == "composition"
    assert out["organization"].startswith("Four-part")
    assert out["emphasis_field"] == "cat"
    assert out["emphasis_mechanism"] == "category_condition"
    assert out["decision_source"] == "llm"


def test_build_emphasis_ops_series_scale_not_highlight(registry):
    persona = registry.get("economist")
    facts = {
        "category_field": "Year",
        "color_field": "Entity",
        "series_count": 4,
        "series_values": [
            "North America (WB)",
            "East Asia and Pacific (WB)",
            "South Asia (WB)",
            "Sub-Saharan Africa (WB)",
        ],
        "emphasis_target": "Sub-Saharan Africa (WB)",
        "emphasis_field": "Entity",
        "emphasis_mechanism": "series_scale",
    }
    ops, needs = build_emphasis_ops(
        persona, facts, accent="#E3120B", base="#141F52"
    )
    assert not needs
    assert len(ops) == 1
    assert ops[0]["action"] == "set_color_range"
    assert ops[0]["colors"][-1] == "#E3120B"
    assert "highlight_category" not in {o["action"] for o in ops}

    # unit 视图（非 layer）上 set_color_range 应写入 scale.range
    spec = {
        "data": {
            "values": [
                {"Entity": "North America (WB)", "Year": 2005, "Share": 1},
                {"Entity": "Sub-Saharan Africa (WB)", "Year": 2005, "Share": 2},
            ]
        },
        "mark": {"type": "line"},
        "encoding": {
            "x": {"field": "Year", "type": "quantitative"},
            "y": {"field": "Share", "type": "quantitative"},
            "color": {
                "field": "Entity",
                "type": "nominal",
                "scale": {
                    "domain": facts["series_values"],
                    "range": ["#111111", "#222222", "#333333", "#444444"],
                },
            },
        },
    }
    out = apply_ops(spec, ops)
    assert out["encoding"]["color"]["field"] == "Entity"
    assert "#E3120B" in (out["encoding"]["color"].get("scale") or {}).get("range", [])


def test_build_emphasis_ops_literal_condition(registry):
    persona = registry.get("bbc")
    facts = {
        "category_field": "year",
        "literal_color_encoding": True,
        "accent_color": "#d46c31",
        "colors_effective": ["#f7d570"],
        "emphasis_target": 2025,
        "emphasis_field": "year",
        "emphasis_mechanism": "literal_condition",
    }
    ops, needs = build_emphasis_ops(
        persona, facts, accent="#FAAB18", base="#1380A1"
    )
    assert needs == []
    assert ops[0]["action"] == "set_mark_color"
    assert ops[0]["accent_color"] == "#FAAB18"


def test_compile_emphasized_mark_uses_binding(registry):
    persona = registry.get("economist")
    # Economist 强调色常用品牌红（ui.brand_color），不必依赖 hong-kong 令牌
    accent = persona.ui.get("brand_color") or "#E3120B"
    facts = {
        "category_field": "Year",
        "color_field": "Entity",
        "series_count": 4,
        "series_values": ["A", "B", "C", "D"],
        "emphasis_target": "B",
        "emphasis_field": "Entity",
        "emphasis_mechanism": "series_scale",
    }
    compiled = compile_then(
        persona, {"set": "emphasized-mark.color", "to": accent}, facts
    )
    assert compiled["renderable"]
    assert any(o.get("action") == "set_color_range" for o in compiled["ops"])
    assert not any(o.get("action") == "highlight_category" for o in compiled["ops"])


def test_restore_chrome_fills_missing_title():
    original = {
        "title": {"text": "Berlin bike theft", "subtitle": "Source: Police"},
        "mark": "area",
    }
    working = {"mark": "area", "encoding": {}}
    out = _restore_chrome_from_original(original, working)
    assert out["title"]["text"] == "Berlin bike theft"
    assert out["title"]["subtitle"] == "Source: Police"
