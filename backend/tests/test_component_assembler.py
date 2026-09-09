from app.core.actions import apply_ops
from app.core.component_assembler import build_component_ir


def test_component_reassembly_keeps_plot_callout_and_separates_footer():
    spec = {
        "width": 500, "height": 250,
        "layer": [
            {"mark": "line", "encoding": {"x": {"field": "year", "type": "quantitative", "axis": None}, "y": {"field": "value", "type": "quantitative", "axis": None}}},
            {"mark": {"type": "text", "text": "Bike thefts"}, "encoding": {"x": {"value": -20}, "y": {"value": -60}}},
            {"mark": {"type": "text", "text": "10-year average"}, "encoding": {"x": {"value": 5}, "y": {"value": 45}}},
            {"mark": "text", "data": {"values": [{"year": 2020}]}, "encoding": {"x": {"field": "year", "type": "quantitative", "axis": None}, "y": {"value": 260}, "text": {"field": "year"}}},
            {"mark": {"type": "text", "text": "Source: Police"}, "encoding": {"x": {"value": -20}, "y": {"value": 300}}},
        ],
    }
    assert build_component_ir(spec)["pixel_positioned_text"] is True
    out = apply_ops(spec, [{"action": "reassemble_components", "profile": "editorial"}])
    plot, footer = out["vconcat"]
    assert out["title"]["text"] == "Bike thefts"
    assert len(plot["layer"]) == 2  # line + in-plot reference annotation
    assert plot["layer"][1]["mark"]["text"] == "10-year average"
    assert footer["data"]["values"][0]["text"] == "Source: Police"
    assert "axis" not in plot["layer"][0]["encoding"]["x"]


def test_component_reassembly_honors_validated_llm_regions():
    spec = {
        "width": 300, "height": 200,
        "layer": [
            {"mark": "bar", "encoding": {"x": {"field": "x", "type": "ordinal"}, "y": {"field": "y", "type": "quantitative"}}},
            {"mark": {"type": "text", "text": "Original title"}, "encoding": {"x": {"value": 0}, "y": {"value": -70}}},
            {"mark": {"type": "text", "text": "Important callout"}, "encoding": {"x": {"value": 120}, "y": {"value": 80}}},
        ],
    }
    out = apply_ops(spec, [{"action": "reassemble_components", "placements": [
        {"index": 1, "region": "title", "rewrite": "A concise title"},
        {"index": 2, "region": "plot", "rewrite": "Key callout"}
    ]}])
    assert out["title"]["text"] == "A concise title"
    assert any(isinstance(layer.get("mark"), dict) and layer["mark"].get("text") == "Key callout" for layer in out["layer"])


def test_fixed_pixel_layout_rejects_root_geometry_changes_without_migration():
    spec = {
        "width": 500, "height": 250,
        "layer": [
            {"mark": "line", "encoding": {"x": {"field": "year", "type": "quantitative"}, "y": {"field": "value", "type": "quantitative"}}},
            {"mark": {"type": "text", "text": "Source: Police"}, "encoding": {"x": {"value": 0}, "y": {"value": 280}}},
        ],
    }
    out = apply_ops(spec, [
        {"action": "set_size", "width": 640, "height": 450},
        {"action": "merge_config", "config": {"padding": 20}},
    ])
    assert out["width"] == 500 and out["height"] == 250
    assert "config" not in out or "padding" not in out["config"]


def test_reassembly_uses_single_content_bounds_contract_not_imported_padding():
    spec = {
        "width": 300, "height": 180, "padding": {"left": 50, "top": 80, "right": 20, "bottom": 60},
        "autosize": {"type": "none", "resize": False},
        "layer": [
            {"mark": "line", "encoding": {"x": {"field": "x", "type": "quantitative"}, "y": {"field": "y", "type": "quantitative"}}},
            {"mark": {"type": "text", "text": "Chart title"}, "encoding": {"x": {"value": 0}, "y": {"value": -70}}},
            {"mark": {"type": "text", "text": "Source: Police"}, "encoding": {"x": {"value": 0}, "y": {"value": 210}}},
        ],
    }
    out = apply_ops(spec, [{"action": "reassemble_components"}])
    expected = {"type": "pad", "contains": "content", "resize": True}
    assert out["autosize"] == expected and out["bounds"] == "full"
    assert "padding" not in out
    assert out["vconcat"][0]["autosize"] == expected
    assert "padding" not in out["vconcat"][0]
