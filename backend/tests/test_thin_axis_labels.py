"""thin_axis_labels：稀疏密轴刻度；facts 密轴检测。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from app.core.actions import apply_ops
from app.core.specfacts import extract_facts


ROOT = Path(__file__).resolve().parents[2]
COVID_SPEC = ROOT / "data" / "dataset" / "06_COVID_excess_deaths" / "chart_spec.json"


def _covid_spec() -> dict:
    return json.loads(COVID_SPEC.read_text(encoding="utf-8"))


def test_covid_facts_axis_x_dense_no_value_labels():
    facts = extract_facts(_covid_spec(), {})
    assert facts["axis_x_dense"] is True
    assert int(facts["axis_x_tick_count"] or 0) >= 10
    assert facts["has_value_labels"] is False


def test_thin_axis_labels_subsamples_values():
    before = _covid_spec()
    vals_before = before["encoding"]["x"]["axis"]["values"]
    assert len(vals_before) == 12
    out = apply_ops(before, [{"action": "thin_axis_labels", "channel": "x", "max_ticks": 8}])
    vals = out["encoding"]["x"]["axis"]["values"]
    assert len(vals) <= 8
    assert vals[0] == vals_before[0]
    assert vals[-1] == vals_before[-1]
    assert out["encoding"]["x"]["axis"]["labelPadding"] >= 12
    # 长日期水平字仍会撞：倾斜
    assert out["encoding"]["x"]["axis"]["labelAngle"] == -35
    # labelExpr 仍保留，子集刻度可继续映射日期文案
    assert "labelExpr" in out["encoding"]["x"]["axis"]
    # 不删除 layer
    assert len(out["layer"]) == len(before["layer"])


def test_dense_axis_font_size_capped_after_hierarchy():
    """BBC 轴字号 18 不得抵消 thin_axis 的疏密修复。"""
    out = apply_ops(
        _covid_spec(),
        [
            {
                "action": "set_font_sizes",
                "title": 28,
                "subtitle": 22,
                "axis_label": 18,
                "axis_title": 18,
            },
            {"action": "thin_axis_labels", "channel": "x", "max_ticks": 8},
        ],
    )
    assert out["encoding"]["x"]["axis"]["labelAngle"] == -35
    assert float(out["config"]["axisX"]["labelFontSize"]) <= 13


def test_dense_axis_font_size_capped_when_thin_runs_first():
    """thin 先倾斜后，set_font_sizes(axis_label=18) 仍须封顶（密轴判定与角度无关）。"""
    out = apply_ops(
        _covid_spec(),
        [
            {"action": "thin_axis_labels", "channel": "x", "max_ticks": 8},
            {
                "action": "set_font_sizes",
                "title": 28,
                "subtitle": 22,
                "axis_label": 18,
                "axis_title": 18,
            },
        ],
    )
    assert out["encoding"]["x"]["axis"]["labelAngle"] == -35
    assert float(out["config"]["axisX"]["labelFontSize"]) <= 13


def test_thin_axis_noop_when_already_sparse():
    spec = {
        "mark": "bar",
        "encoding": {
            "x": {"field": "a", "type": "ordinal", "axis": {"values": [1, 2, 3]}},
            "y": {"field": "b", "type": "quantitative"},
        },
        "data": {"values": [{"a": 1, "b": 1}, {"a": 2, "b": 2}, {"a": 3, "b": 3}]},
    }
    out = apply_ops(copy.deepcopy(spec), [{"action": "thin_axis_labels", "max_ticks": 8}])
    assert out["encoding"]["x"]["axis"]["values"] == [1, 2, 3]


def test_thin_axis_derives_ordinal_domain_when_values_not_explicit():
    spec = {
        "mark": "bar",
        "data": {"values": [{"year": year, "v": year} for year in range(1988, 2026)]},
        "encoding": {
            "x": {"field": "year", "type": "ordinal", "axis": {"labelAngle": -45}},
            "y": {"field": "v", "type": "quantitative"},
        },
    }
    out = apply_ops(spec, [{"action": "thin_axis_labels", "channel": "x", "max_ticks": 8}])
    values = out["encoding"]["x"]["axis"]["values"]
    assert len(values) <= 8
    assert values[0] == 1988 and values[-1] == 2025


def test_set_axis_only_applies_safe_axis_and_scale_fields():
    spec = {
        "mark": "bar",
        "encoding": {
            "x": {"field": "c", "type": "nominal"},
            "y": {"field": "v", "type": "quantitative"},
        },
    }
    out = apply_ops(spec, [{
        "action": "set_axis", "channel": "y",
        "axis": {"grid": True, "gridColor": "#cccccc", "unsafe": "ignored"},
        "scale": {"zero": True, "domainMax": 10, "unsafe": 1},
    }])
    y = out["encoding"]["y"]
    assert y["axis"] == {"grid": True, "gridColor": "#cccccc"}
    assert y["scale"] == {"zero": True, "domainMax": 10}


def test_mark_and_text_style_actions_keep_data_and_encoding_intact():
    spec = {
        "data": {"values": [{"c": "A", "v": 1}]},
        "layer": [
            {"mark": "bar", "encoding": {"x": {"field": "c", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}},
            {"mark": {"type": "text", "text": "note", "fontSize": 9}},
        ],
    }
    out = apply_ops(spec, [
        {"action": "set_mark_style", "style": {"cornerRadius": 3, "opacity": 0.85, "text": "ignored"}},
        {"action": "set_text_style", "style": {"fontSize": 12, "fontWeight": "bold", "text": "ignored"}},
    ])
    assert out["layer"][0]["mark"]["cornerRadius"] == 3
    assert out["layer"][0]["mark"]["opacity"] == 0.85
    assert out["layer"][1]["mark"]["fontSize"] == 12
    assert out["layer"][1]["mark"]["fontWeight"] == "bold"
    assert out["layer"][1]["mark"]["text"] == "note"
