"""复合视图（vconcat/layer）上的 mark/encoding ops 与事实提取。"""
import json
from pathlib import Path

from app.core.actions import apply_ops, current_mark_color
from app.core.specfacts import extract_facts

PLASTIC = Path(__file__).resolve().parents[2] / "data" / "dataset" / "14_plastic_waste_generation_per_capita" / "chart_spec.json"


def _plastic_spec() -> dict:
    return json.loads(PLASTIC.read_text(encoding="utf-8"))


def test_set_mark_color_targets_bar_layer_not_vconcat_root():
    spec = _plastic_spec()
    out = apply_ops(spec, [{"action": "set_mark_color", "color": "#6929C4"}])
    assert "mark" not in out  # 禁止在 vconcat 根创建无 type 的 mark
    bar = out["vconcat"][0]["layer"][0]["mark"]
    assert bar["type"] == "bar"
    assert bar["color"] == "#6929C4"
    # 标注/来源 text 层不被改色
    assert out["vconcat"][0]["layer"][1]["mark"]["color"] == "#333333"
    assert out["vconcat"][1]["mark"]["color"] == "#666666"


def test_set_mark_type_on_layered_vconcat():
    spec = _plastic_spec()
    out = apply_ops(spec, [{"action": "set_mark_type", "mark_type": "point"}])
    assert "mark" not in out
    assert out["vconcat"][0]["layer"][0]["mark"]["type"] == "point"


def test_highlight_category_writes_encoding_on_bar_layer():
    spec = _plastic_spec()
    out = apply_ops(
        spec,
        [
            {
                "action": "highlight_category",
                "field": "Country",
                "value": "United States",
                "color": "#E3120B",
            }
        ],
    )
    assert "encoding" not in out
    enc = out["vconcat"][0]["layer"][0]["encoding"]
    assert enc["color"]["condition"]["value"] == "#E3120B"
    assert "color" not in out["vconcat"][0]["layer"][0]["mark"]


def test_current_mark_color_reads_nested_bar():
    assert current_mark_color(_plastic_spec()) == "#168c96"


def test_current_mark_color_reads_encoding_literal_value():
    """mark 已清空、颜色只在 encoding.color.value 时仍应读到机构蓝。"""
    spec = {
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "Year", "type": "ordinal"},
            "y": {"field": "v", "type": "quantitative"},
            "color": {
                "condition": {"test": "datum['Year'] === '1995'", "value": "#FF0000"},
                "value": "#1380A1",
            },
        },
    }
    assert current_mark_color(spec) == "#1380A1"


def test_highlight_uses_encoding_base_not_vega_default():
    """高亮后基色不得回退 #4c78a8（Vega 默认蓝）。"""
    spec = {
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "Year", "type": "ordinal"},
            "y": {"field": "v", "type": "quantitative"},
            "color": {"value": "#1380A1"},
        },
    }
    out = apply_ops(
        spec,
        [
            {
                "action": "highlight_category",
                "field": "Year",
                "value": "1995",
                "color": "#FF0000",
            }
        ],
    )
    assert out["encoding"]["color"]["value"] == "#1380A1"
    assert out["encoding"]["color"]["condition"]["value"] == "#FF0000"
    # 数值年份用 ==，避免 === '1995' 永不命中
    assert out["encoding"]["color"]["condition"]["test"] == "datum['Year'] == 1995"


def test_highlight_category_noop_on_series_color_field():
    """多序列 color.field：highlight_category 拒绝改写（须走 set_color_range）。"""
    spec = {
        "data": {
            "values": [
                {"Entity": "A", "Year": 2005, "Share": 1},
                {"Entity": "B", "Year": 2005, "Share": 3},
            ]
        },
        "encoding": {
            "x": {"field": "Year", "type": "quantitative"},
            "y": {"field": "Share", "type": "quantitative"},
            "color": {
                "field": "Entity",
                "type": "nominal",
                "scale": {"range": ["#c84b31", "#4c6a9c"]},
            },
        },
        "layer": [
            {"mark": {"type": "line", "strokeWidth": 1.5}},
            {"mark": {"type": "point", "filled": True}},
        ],
    }
    out = apply_ops(
        spec,
        [
            {
                "action": "highlight_category",
                "field": "Year",
                "value": "B",
                "color": "#E3120B",
            }
        ],
    )
    # 未改写：仍保留 Entity 分组色
    assert out["encoding"]["color"]["field"] == "Entity"
    assert "condition" not in out["encoding"]["color"]
    assert out["encoding"]["color"]["scale"]["range"] == ["#c84b31", "#4c6a9c"]


def test_highlight_preserves_existing_literal_condition_test():
    """输入已有双色 condition 时，高亮只换色、保留原 test（如 year==2025）。"""
    spec = {
        "data": {"values": [{"year": 2025, "area": 1}, {"year": 1995, "area": 2}]},
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "year", "type": "ordinal"},
            "y": {"field": "area", "type": "quantitative"},
            "color": {
                "condition": {"test": "datum.year == 2025", "value": "#d46c31"},
                "value": "#f7d570",
            },
        },
    }
    out = apply_ops(
        spec,
        [
            {
                "action": "set_mark_color",
                "color": "#1380A1",
                "accent_color": "#FAAB18",
            },
            {
                "action": "highlight_category",
                "field": "year",
                "value": "1995",
                "color": "#FAAB18",
                "base_color": "#1380A1",
            },
        ],
    )
    color = out["encoding"]["color"]
    assert color["value"] == "#1380A1"
    assert color["condition"]["value"] == "#FAAB18"
    assert color["condition"]["test"] == "datum.year == 2025"


def test_extract_facts_from_vconcat_layer():
    facts = extract_facts(_plastic_spec())
    assert facts["mark_type"] == "bar"
    assert facts["category_field"] == "Country"
    assert facts["value_field"] == "Plastic waste"
    assert facts["category_count"] == 5
    assert facts["colors_effective"] == ["#168c96"]
    assert facts["color_source"] == "mark"
    assert facts["has_source_note"] is True
    assert facts["title_text"] == "Plastic waste generation per capita, 2020"
    assert facts["is_single_view"] is True


def test_simple_unit_spec_mark_color_unchanged():
    spec = {"mark": "bar", "encoding": {"x": {"field": "a"}, "y": {"field": "b", "type": "quantitative"}}}
    out = apply_ops(spec, [{"action": "set_mark_color", "color": "#1380A1"}])
    assert out["mark"] == {"type": "bar", "color": "#1380A1"}
