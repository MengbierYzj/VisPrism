"""set_color_range 落地：scale:null、hex 列、无 color 通道多序列。"""
import json
from pathlib import Path

from app.core.actions import apply_ops_with_effect, current_mark_color
from app.core.spec_rebuild import rebuild_spec_for_advisor
from app.core.view_geometry import walk_annotated_units


REPO = Path(__file__).resolve().parents[2]


def test_set_color_range_overwrites_null_scale():
    spec = {
        "mark": "arc",
        "data": {
            "values": [
                {"Category": "A", "Percentage": 40, "Color": "#111111"},
                {"Category": "B", "Percentage": 60, "Color": "#222222"},
            ]
        },
        "encoding": {
            "theta": {"field": "Percentage", "type": "quantitative"},
            "color": {"field": "Color", "type": "nominal", "scale": None},
        },
    }
    out, report = apply_ops_with_effect(
        spec, [{"action": "set_color_range", "colors": ["#1380A1", "#FAAB18"]}]
    )
    assert report.changed
    color = out["encoding"]["color"]
    assert color["field"] == "Category"
    assert color["scale"]["range"] == ["#1380A1", "#FAAB18"]


def test_berlin_dual_area_gets_series_colors():
    berlin = next((REPO / "data" / "dataset").glob("08*/Berlin*.json"))
    spec = json.loads(berlin.read_text(encoding="utf-8"))
    working, _prep = rebuild_spec_for_advisor(spec)
    colors = ["#1380A1", "#FAAB18"]
    out, report = apply_ops_with_effect(
        working, [{"action": "set_color_range", "colors": colors}]
    )
    assert report.changed
    primaries = [
        u for u in walk_annotated_units(out) if u["role"] == "primary_data"
    ]
    assert len(primaries) >= 2
    painted = []
    for u in primaries[:2]:
        mark = u["view"].get("mark")
        assert isinstance(mark, dict)
        painted.append(mark.get("fill") or mark.get("color") or mark.get("stroke"))
    assert painted[0] == "#1380A1"
    assert painted[1] == "#FAAB18"


def test_tv_donut_color_range_on_arc():
    path = REPO / "data" / "dataset" / "16_us_tv_viewership" / "chart_spec.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    colors = ["#1380A1", "#FAAB18", "#007f7f", "#333333"]
    out, report = apply_ops_with_effect(
        spec, [{"action": "set_color_range", "colors": colors}]
    )
    assert report.changed
    arcs = [
        u
        for u in walk_annotated_units(out)
        if u.get("mark_type") == "arc"
    ]
    assert arcs
    color = (arcs[0].get("encoding") or {}).get("color") or {}
    assert isinstance(color.get("scale"), dict)
    assert color["scale"].get("range") == colors
    assert color.get("field") == "Category"
