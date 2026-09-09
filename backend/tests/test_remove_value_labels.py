"""remove_value_labels：去掉柱上数值 text 层，保留 condition 双色。"""
from __future__ import annotations

import json
from pathlib import Path

from app.core.actions import apply_ops, apply_ops_with_effect
from app.core.specfacts import extract_facts
from app.core.visual_review import _finding_to_adopted

ROOT = Path(__file__).resolve().parents[2]
TV = ROOT / "data" / "dataset" / "16_us_tv_viewership" / "chart_spec.json"


def _amazonish_spec() -> dict:
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": 900,
        "height": 500,
        "data": {
            "values": [
                {"year": 1995, "area": 29059, "label": "29.1K"},
                {"year": 2025, "area": 5796, "label": "5.8K"},
            ]
        },
        "layer": [
            {
                "mark": {"type": "bar"},
                "encoding": {
                    "x": {"field": "year", "type": "ordinal"},
                    "y": {"field": "area", "type": "quantitative"},
                    "color": {
                        "condition": {"test": "datum.year == 2025", "value": "#d46c31"},
                        "value": "#f7d570",
                    },
                },
            },
            {
                "mark": {
                    "type": "text",
                    "align": "left",
                    "angle": -55,
                    "fontSize": 12,
                },
                "encoding": {
                    "x": {"field": "year", "type": "ordinal"},
                    "y": {"field": "area", "type": "quantitative"},
                    "text": {"field": "label", "type": "nominal"},
                },
            },
        ],
    }


def test_remove_value_labels_drops_text_layer():
    out, report = apply_ops_with_effect(
        _amazonish_spec(), [{"action": "remove_value_labels"}]
    )
    assert report.changed is True
    layers = out.get("layer") or []
    assert len(layers) == 1
    mark = layers[0].get("mark")
    assert (mark if isinstance(mark, str) else mark.get("type")) == "bar"


def test_set_mark_color_preserves_condition_accent():
    spec = _amazonish_spec()
    # 去掉 text 层，只测配色
    spec["layer"] = [spec["layer"][0]]
    out = apply_ops(spec, [{"action": "set_mark_color", "color": "#1380A1"}])
    color = out["layer"][0]["encoding"]["color"]
    assert color["value"] == "#1380A1"
    assert color["condition"]["test"] == "datum.year == 2025"
    assert color["condition"]["value"] == "#d46c31"


def test_pixel_canvas_callouts_are_not_value_labels():
    """自有像素 data 的标注/品牌字不是柱上数值；facts 与 remove 都不得整批清掉。"""
    raw = json.loads(TV.read_text(encoding="utf-8"))
    facts = extract_facts(raw, {})
    assert facts["has_value_labels"] is False
    out = apply_ops(raw, [{"action": "remove_value_labels"}])
    assert json.dumps(out).count('"type": "text"') == json.dumps(raw).count(
        '"type": "text"'
    )
    assert "Nielsen" in json.dumps(out)


def test_overlap_without_value_labels_does_not_remove_text(registry):
    """视觉重叠但无柱上数值层 → 加留白，不 remove_value_labels。"""
    persona = registry.get("economist")
    item = _finding_to_adopted(
        persona,
        {"height": 560, "has_value_labels": False, "axis_x_dense": False},
        {
            "issue": "mark_label_overlap",
            "verdict": "adopt",
            "severity": "medium",
            "preferred_actions": ["remove_value_labels"],
            "rationale": "labels look crowded",
        },
    )
    assert item is not None
    actions = {o.get("action") for o in item["ops"]}
    assert "remove_value_labels" not in actions
