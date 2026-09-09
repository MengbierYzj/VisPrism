"""拍前 extract→emit 重建（非原地补丁）。"""
import json
from pathlib import Path

from app.core.actions import apply_ops
from app.core.spec_rebuild import rebuild_spec_for_advisor
from app.core.view_geometry import walk_annotated_units

ROOT = Path(__file__).resolve().parents[2]
COVID = ROOT / "data" / "dataset" / "06_COVID_excess_deaths" / "chart_spec.json"
PLASTIC = (
    ROOT
    / "data"
    / "dataset"
    / "14_plastic_waste_generation_per_capita"
    / "chart_spec.json"
)
BERLIN = list((ROOT / "data" / "dataset").glob("08*/Berlin*.json"))[0]
GUN = ROOT / "data" / "dataset" / "10_US_made_gun_exports" / "chart_spec.json"


def test_covid_rebuild_keeps_layers_clears_abs_legend():
    raw = json.loads(COVID.read_text(encoding="utf-8"))
    working, report = rebuild_spec_for_advisor(raw)
    assert report["changed"] is True
    assert report["mode"] == "extract_emit"
    assert len(working["layer"]) == 2
    assert working["layer"][0]["mark"]["type"] == "bar"
    assert working["layer"][1]["mark"]["type"] == "tick"
    assert working["layer"][0].get("transform")
    for ly in working["layer"]:
        legend = ly["encoding"]["color"]["legend"]
        assert legend["orient"] in ("top", "bottom", "left", "right")
        assert "legendX" not in legend and "legendY" not in legend
    # 轴绝对坐标已清
    x_axis = working["encoding"]["x"]["axis"]
    assert "titleX" not in x_axis and "titleY" not in x_axis


def test_covid_set_legend_bottom_all_layers():
    raw = json.loads(COVID.read_text(encoding="utf-8"))
    working, _ = rebuild_spec_for_advisor(raw)
    out = apply_ops(working, [{"action": "set_legend", "orient": "bottom"}])
    assert out["layer"][0]["encoding"]["color"]["legend"]["orient"] == "bottom"
    assert out["layer"][1]["encoding"]["color"]["legend"]["orient"] == "bottom"


def test_simple_bar_passthrough():
    spec = {
        "mark": "bar",
        "data": {"values": [{"a": "x", "b": 1}]},
        "encoding": {
            "x": {"field": "a", "type": "nominal"},
            "y": {"field": "b", "type": "quantitative"},
        },
    }
    working, report = rebuild_spec_for_advisor(spec)
    assert report["changed"] is False
    assert report["mode"] == "passthrough"
    assert working["mark"] == "bar"


def test_plastic_still_readable_after_rebuild_or_pass():
    raw = json.loads(PLASTIC.read_text(encoding="utf-8"))
    working, report = rebuild_spec_for_advisor(raw)
    # vconcat 可能重建或保留；主几何仍为 bar
    units = walk_annotated_units(working)
    marks = [u["mark_type"] for u in units if u["role"] == "primary_data"]
    assert "bar" in marks or any(u["mark_type"] == "bar" for u in units)
    assert report["mode"] in ("extract_emit", "passthrough", "fallback_copy")


def test_berlin_keeps_area_drops_text_chrome():
    raw = json.loads(BERLIN.read_text(encoding="utf-8"))
    working, report = rebuild_spec_for_advisor(raw)
    assert report["changed"] is True
    roles = [u["role"] for u in walk_annotated_units(working)]
    assert "title" not in roles
    assert "source" not in roles
    assert any(u["mark_type"] == "area" for u in walk_annotated_units(working))
    assert working.get("title") or True  # 标题应提升到根 title
    assert "Bike" in str((working.get("title") or {}).get("text") or "")


def _is_drawn_axis_text_layer(ly: dict) -> bool:
    enc = ly.get("encoding") if isinstance(ly.get("encoding"), dict) else {}
    text = enc.get("text") if isinstance(enc.get("text"), dict) else {}
    if not text.get("field"):
        return False
    x, y = enc.get("x") if isinstance(enc.get("x"), dict) else {}, enc.get("y") if isinstance(
        enc.get("y"), dict
    ) else {}
    return bool(
        (x.get("field") and y.get("value") is not None)
        or (y.get("field") and x.get("value") is not None)
    )


def test_berlin_drops_drawn_axis_text_layers_but_keeps_annotations():
    """自绘轴刻度可丢；导出器 annotation 像素坐标须原样保留且文字遮罩透明。"""
    raw = json.loads(BERLIN.read_text(encoding="utf-8"))
    working, report = rebuild_spec_for_advisor(raw)
    assert report.get("role_source") == "heuristic"
    assert int(report.get("dropped_drawn_axis") or 0) >= 1
    assert int(report.get("pixel_position_layers") or 0) == 0
    assert int(report.get("pixel_coordinate_layers") or 0) == 0
    assert int(report.get("transparent_annotation_backplates") or 0) >= 1
    assert working["autosize"] == {"type": "none", "resize": False}
    assert working["padding"]["top"] == raw["padding"]["top"]
    blob = json.dumps(working, ensure_ascii=False)
    assert "10 year average" in blob
    assert "prevent bike thefts" in blob
    # 假轴丢弃后主图 encoding 不应再带 axis:null
    plot = (working.get("vconcat") or [working])[0]
    root_enc = plot.get("encoding") or working.get("encoding") or {}
    for ch in ("x", "y"):
        ch_obj = root_enc.get(ch) if isinstance(root_enc.get(ch), dict) else {}
        assert ch_obj.get("axis") is not None or "axis" not in ch_obj

    # 5.05/45.55 是原画布像素，VL 会直接用于 text translate，不得反算成数据值；
    # 白色 rect 遮罩不应盖住曲线。
    average = next(
        ly for ly in working["layer"]
        if (ly.get("mark") or {}).get("text") == "10 year average"
    )
    assert average["encoding"]["x"]["value"] == 5.05
    assert average["encoding"]["y"]["value"] == 45.55
    backplate = next(
        ly for ly in working["layer"]
        if (ly.get("mark") or {}).get("type") == "rect"
    )
    assert backplate["mark"]["fill"] == "transparent"


def test_value_only_xy_stays_in_encoding_without_invalid_mark_coordinates():
    """Vega-Lite 不接受 mark.x/y；value-only encoding 应完整保留。"""
    from app.core.spec_rebuild import _apply_pixel_position_to_layer_ir

    ly = {
        "mark": {"type": "text", "text": "footer", "fontSize": 12},
        "encoding": {"x": {"value": -10}, "y": {"value": 340}, "text": {"value": "footer"}},
    }
    _apply_pixel_position_to_layer_ir(ly)
    assert ly["encoding"]["x"] == {"value": -10}
    assert ly["encoding"]["y"] == {"value": 340}
    assert not ly.get("pixel_position")


def test_llm_role_overrides_drop_drawn_axis(monkeypatch):
    """live 路径：LLM 把假轴标为 drawn_axis 后不再保留假轴 text。"""
    import asyncio

    from app.core.spec_rebuild import rebuild_spec_for_advisor_async

    raw = json.loads(BERLIN.read_text(encoding="utf-8"))

    class _LLM:
        mode = "live"

        async def chat_json(self, system, user):
            payload = json.loads(user)
            ovs = []
            for row in payload.get("layers") or []:
                if row.get("likely_drawn_axis") or row.get("role_heuristic") == "drawn_axis":
                    ovs.append(
                        {
                            "index": row["index"],
                            "role": "drawn_axis",
                            "rationale": "drawn axis",
                        }
                    )
            return {"overrides": ovs}

    working, report = asyncio.run(rebuild_spec_for_advisor_async(raw, _LLM()))
    assert report.get("role_source") == "llm"
    assert any(o.get("role") == "drawn_axis" for o in (report.get("role_overrides") or []))
    text_layers = [
        ly
        for ly in (working.get("layer") or [])
        if (ly.get("mark") or {}).get("type") == "text" or ly.get("mark") == "text"
    ]
    assert not any(_is_drawn_axis_text_layer(ly) for ly in text_layers)


def test_rebuild_uses_llm_for_missing_axis_title_natural_language():
    """新默认轴标题不能退化为字段名或逗号拼接。"""
    import asyncio

    from app.core.spec_rebuild import rebuild_spec_for_advisor_async

    raw = json.loads(BERLIN.read_text(encoding="utf-8"))

    class _LLM:
        mode = "live"

        def __init__(self):
            self.calls = 0

        async def chat_json(self, system, user):
            self.calls += 1
            if "axis titles" in system:
                return {"x_title": "Year", "y_title": "Bicycle theft cases"}
            payload = json.loads(user)
            return {
                "overrides": [
                    {"index": row["index"], "role": "drawn_axis", "rationale": "axis"}
                    for row in payload.get("layers") or []
                    if row.get("likely_drawn_axis")
                ]
            }

    working, report = asyncio.run(rebuild_spec_for_advisor_async(raw, _LLM()))
    assert report["axis_title_source"] == "llm"
    blob = json.dumps(working, ensure_ascii=False)
    assert "Bicycle theft cases" in blob


def test_rebuild_keeps_annotation_callout():
    """拍前默认保留 annotation 标注，不得当 chrome 丢掉。"""
    spec = {
        "data": {"values": [{"a": "x", "b": 1}, {"a": "y", "b": 2}]},
        "layer": [
            {
                "mark": "bar",
                "encoding": {
                    "x": {"field": "a", "type": "nominal"},
                    "y": {"field": "b", "type": "quantitative"},
                },
            },
            {
                "data": {"values": [{"note": "Peak here"}]},
                "mark": {"type": "text", "dx": 12, "fontSize": 12, "color": "#333"},
                "encoding": {
                    "x": {"value": 120},
                    "y": {"value": 40},
                    "text": {"field": "note"},
                },
            },
        ],
    }
    # 绝对定位 + text.field → 当前启发式为 annotation（非 drawn_axis）
    roles = [u["role"] for u in walk_annotated_units(spec)]
    assert "annotation" in roles
    working, report = rebuild_spec_for_advisor(spec)
    assert report["mode"] == "extract_emit"
    blob = json.dumps(working, ensure_ascii=False)
    assert "Peak here" in blob


def test_radial_arc_keeps_parent_transform_size_inner_radius():
    """极坐标弧图：父层 calculate/filter + 尺寸 + innerRadius 丢失会导致只剩标题文字。"""
    raw = json.loads(GUN.read_text(encoding="utf-8"))
    working, report = rebuild_spec_for_advisor(raw)
    assert report["changed"] is True
    layers = working.get("layer") or []
    # 主弧 + 中心孔 + 3.7M + US EXPORTS
    assert len(layers) >= 3
    primary = next(
        ly
        for ly in layers
        if (ly.get("mark") or {}).get("type") == "arc"
        and isinstance((ly.get("encoding") or {}).get("theta"), dict)
    )
    assert primary["mark"].get("innerRadius") == 86
    assert working.get("width") == 760
    assert working.get("height") == 620
    tf = primary.get("transform") or working.get("transform") or []
    assert any(t.get("filter") for t in tf if isinstance(t, dict))
    assert any(t.get("as") == "Destination group" for t in tf if isinstance(t, dict))
    enc = primary.get("encoding") or {}
    assert enc["theta"]["field"] == "Country"
    assert enc["radius"]["field"] == "Cumulative Volume"
    assert enc["color"]["field"] == "Destination group"
    # 中心合计不得当 chrome 丢掉
    blob = json.dumps(working, ensure_ascii=False)
    assert "3.7M" in blob
    assert "US EXPORTS" in blob
    # 中心文字层不得误挂主表 filter
    for ly in layers:
        mark = ly.get("mark") if isinstance(ly.get("mark"), dict) else {}
        if mark.get("type") != "text":
            continue
        vals = ((ly.get("data") or {}).get("values") or [])
        if any(isinstance(r, dict) and r.get("label") == "3.7M" for r in vals):
            assert not ly.get("transform")
