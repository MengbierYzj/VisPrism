"""layout_audit：轴标题定位包清理 + layout_slice 程序候选。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from app.core.actions import apply_ops
from app.core.layout_audit import (
    build_layout_slice,
    clean_axis_layout,
    normalize_axis_title_layout,
    program_layout_adopted,
    program_layout_candidates,
)
from app.core.spec_rebuild import rebuild_spec_for_advisor
from app.core.specfacts import extract_facts

ROOT = Path(__file__).resolve().parents[2]
COVID = ROOT / "data" / "dataset" / "06_COVID_excess_deaths" / "chart_spec.json"


def test_clean_axis_strips_orphaned_horizontal_y_title():
    axis = {
        "title": "Weekly deaths",
        "titleAngle": 0,
        "titleAlign": "left",
        "values": [0, 5000],
    }
    out = clean_axis_layout(axis, channel="y")
    assert "titleAngle" not in out
    assert out["title"] == "Weekly deaths"


def test_clean_axis_keeps_x_title_angle_zero():
    axis = {"title": "Week", "titleAngle": 0, "titleX": 800, "titleY": 25}
    out = clean_axis_layout(axis, channel="x")
    assert out.get("titleAngle") == 0
    assert "titleX" not in out and "titleY" not in out


def test_covid_rebuild_clears_y_title_angle_with_abs_package():
    raw = json.loads(COVID.read_text(encoding="utf-8"))
    working, _ = rebuild_spec_for_advisor(raw)
    y_axis = working["layer"][0]["encoding"]["y"]["axis"]
    assert "titleX" not in y_axis and "titleY" not in y_axis
    assert y_axis.get("titleAngle") not in (0, 0.0)
    assert y_axis.get("title") == "Weekly deaths"
    slice_ = build_layout_slice(working, extract_facts(working, {}))
    assert "orphaned_horizontal_y_title" not in slice_["flags"]


def test_layout_slice_flags_orphan_before_normalize():
    spec = {
        "mark": "bar",
        "encoding": {
            "x": {"field": "a", "type": "ordinal"},
            "y": {
                "field": "b",
                "type": "quantitative",
                "axis": {"title": "Y", "titleAngle": 0},
            },
        },
        "data": {"values": [{"a": 1, "b": 2}]},
    }
    facts = extract_facts(spec, {})
    assert "orphaned_horizontal_y_title" in facts["layout_flags"]
    cands = program_layout_candidates(facts["layout_slice"])
    assert any(c["id"] == "orphaned_horizontal_y_title" and c["auto_fix"] for c in cands)
    adopted = program_layout_adopted(facts["layout_slice"])
    assert any(a["rule_id"] == "d-layout-orphaned_horizontal_y_title" for a in adopted)


def test_normalize_op_fixes_orphan_y_title():
    spec = {
        "mark": "bar",
        "encoding": {
            "y": {
                "field": "b",
                "type": "quantitative",
                "axis": {"title": "Y", "titleAngle": 0, "titleY": -15},
            }
        },
        "data": {"values": [{"b": 1}]},
    }
    out = apply_ops(copy.deepcopy(spec), [{"action": "normalize_axis_title_layout"}])
    axis = out["encoding"]["y"]["axis"]
    assert "titleAngle" not in axis
    assert "titleY" not in axis


def test_normalize_axis_title_layout_mutates():
    spec = {
        "layer": [
            {
                "mark": "bar",
                "encoding": {
                    "y": {"field": "b", "type": "quantitative", "axis": {"titleAngle": 0}}
                },
            }
        ]
    }
    assert normalize_axis_title_layout(spec) is True
    assert "titleAngle" not in spec["layer"][0]["encoding"]["y"]["axis"]
