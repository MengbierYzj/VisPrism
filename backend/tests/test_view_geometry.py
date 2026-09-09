"""复合图主几何打分、encoding 合并、fill/stroke 改色、自绘 chrome。"""
import json
from pathlib import Path

from app.core.actions import apply_ops, current_mark_color
from app.core.specfacts import extract_facts
from app.core.view_geometry import (
    apply_paint_color,
    primary_paint_targets,
    resolve_primary_unit,
    walk_annotated_units,
)

ROOT = Path(__file__).resolve().parents[2]
BERLIN = ROOT / "data" / "dataset" / "08_berlin bike theft" / "Berlin's Bike.json"
PLASTIC = ROOT / "data" / "dataset" / "14_plastic_waste_generation_per_capita" / "chart_spec.json"


def _berlin() -> dict:
    return json.loads(BERLIN.read_text(encoding="utf-8"))


def test_berlin_primary_is_area_not_grid_rule():
    spec = _berlin()
    primary = resolve_primary_unit(spec)
    assert primary is not None
    assert primary["mark_type"] == "area"
    assert primary["role"] == "primary_data"
    facts = extract_facts(spec)
    assert facts["mark_type"] == "area"
    assert facts["value_field"] == "Recorded Cases"
    assert facts["category_field"] == "Year"
    assert facts["has_drawn_grid"] is True
    assert facts["has_title"] is True
    assert "Bike Theft" in (facts["title_text"] or "")
    assert facts["title_from_text_layer"] is True
    assert facts["has_source_note"] is True
    roles = {u["role"] for u in walk_annotated_units(spec)}
    assert "grid" in roles
    assert "title" in roles
    assert "source" in roles


def test_berlin_set_mark_color_writes_fill_not_only_color():
    spec = _berlin()
    out = apply_ops(spec, [{"action": "set_mark_color", "color": "#1380A1"}])
    paints = primary_paint_targets(out)
    assert paints
    for view in paints:
        mark = view["mark"]
        assert mark["type"] == "area"
        assert mark.get("fill") == "#1380A1"
    # 网格 stroke 不被主色覆盖
    units = walk_annotated_units(out)
    grids = [u for u in units if u["role"] == "grid"]
    assert grids
    assert grids[0]["mark_obj"].get("stroke") == "#e7e7e7"


def test_berlin_merge_config_recolors_drawn_grid():
    spec = _berlin()
    out = apply_ops(
        spec,
        [
            {
                "action": "merge_config",
                "config": {"axisY": {"grid": True, "gridColor": "#cbcbcb"}},
            }
        ],
    )
    grids = [u for u in walk_annotated_units(out) if u["role"] == "grid"]
    assert grids[0]["mark_obj"]["stroke"] == "#cbcbcb"


def test_berlin_font_size_patches_title_text_layer():
    spec = _berlin()
    out = apply_ops(spec, [{"action": "set_font_sizes", "title": 28}])
    titles = [u for u in walk_annotated_units(out) if u["role"] == "title"]
    assert titles
    assert titles[0]["mark_obj"]["fontSize"] == 28


def test_plastic_still_reads_bar_and_colors():
    spec = json.loads(PLASTIC.read_text(encoding="utf-8"))
    facts = extract_facts(spec)
    assert facts["mark_type"] == "bar"
    assert facts["category_field"] == "Country"
    out = apply_ops(spec, [{"action": "set_mark_color", "color": "#6929C4"}])
    assert out["vconcat"][0]["layer"][0]["mark"]["color"] == "#6929C4"
    assert current_mark_color(out) == "#6929C4"


def test_apply_paint_color_prefers_fill():
    mark = {"type": "area", "fill": "#4e78c3", "fillOpacity": 0.6}
    apply_paint_color(mark, "#1380A1")
    assert mark["fill"] == "#1380A1"
    assert mark["color"] == "#1380A1"
