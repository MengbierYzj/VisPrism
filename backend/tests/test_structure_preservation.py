from app.core.actions import apply_ops
from app.core.specfacts import extract_facts, structure_baseline


def test_same_type_mark_change_does_not_flatten_composition():
    spec = {
        "vconcat": [
            {"mark": {"type": "line", "strokeDash": [4, 2]}, "encoding": {
                "x": {"field": "date"}, "y": {"field": "value"},
                "detail": {"field": "series"}, "tooltip": {"field": "value"},
            }},
            {"mark": "text", "encoding": {"text": {"field": "note"}}},
        ]
    }
    before = structure_baseline(spec)
    out = apply_ops(spec, [{"action": "set_mark_type", "mark_type": "line", "chart_type": "line",
                            "rebuild_unit": True, "category_field": "date", "value_field": "value"}])
    after = structure_baseline(out)
    assert after["unit_count"] == before["unit_count"]
    assert after["annotation_count"] == before["annotation_count"]
    assert set(before["encoding_channels"]).issubset(after["encoding_channels"])
    assert "vconcat" in out


def test_same_primary_line_does_not_flatten_brush_layer_or_series_encoding():
    """Brush rect 是辅助层；line→line 不能因它存在就触发 rebuild_unit。"""
    spec = {
        "layer": [
            {"data": {"values": [{"start": "2020-01-01", "end": "2020-02-01"}]},
             "mark": {"type": "rect", "opacity": 0.15},
             "encoding": {"x": {"field": "start", "type": "temporal"},
                          "x2": {"field": "end"}}},
            {"data": {"values": [{"date": "2020-01-01", "rate": 3, "series": "A"},
                                     {"date": "2020-02-01", "rate": 4, "series": "A"},
                                     {"date": "2020-03-01", "rate": 5, "series": "A"}]},
             "mark": "line",
             "encoding": {"x": {"field": "date", "type": "temporal"},
                          "y": {"field": "rate", "type": "quantitative"},
                          "color": {"field": "series", "type": "nominal"}}},
        ]
    }
    out = apply_ops(spec, [{"action": "set_mark_type", "mark_type": "line", "chart_type": "line",
                            "rebuild_unit": True, "category_field": "date", "value_field": "rate"}])
    assert len(out["layer"]) == 2
    assert out["layer"][0]["mark"]["type"] == "rect"
    assert out["layer"][1]["data"]["values"][0]["rate"] == 3
    assert out["layer"][1]["encoding"]["color"]["field"] == "series"


def test_explicit_axis_values_are_not_marked_dense_by_data_domain():
    spec = {
        "data": {"values": [{"date": i, "value": i} for i in range(100)]},
        "mark": "line",
        "encoding": {"x": {"field": "date", "type": "ordinal", "axis": {"values": [0, 20, 40, 60, 80]}},
                      "y": {"field": "value", "type": "quantitative"}},
    }
    facts = extract_facts(spec)
    assert facts["axis_x_tick_count"] == 5
    assert facts["axis_x_dense"] is False
