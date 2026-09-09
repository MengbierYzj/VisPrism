"""字体/背景/标题文案可执行性 + IBM 可落地图型别名。"""
from __future__ import annotations

from app.core.actions import (
    CHART_TYPE_MARK_ALIASES,
    EXECUTABLE_MARKS,
    NON_EXECUTABLE_CHART_TYPES,
    apply_ops,
    compile_then,
)
from app.core.beats import _derived_proposals, _mock_adjudicate
from app.core.persona import load_persona_dict


class _Persona:
    def resolve_color(self, to):
        return "#F5F4EF" if "canvas" in str(to) else None

    def resolve_color_list(self, to):
        return []

    def resolve_token(self, to):
        return to


def test_set_font_sizes_strips_channel_overrides():
    spec = {
        "mark": "bar",
        "encoding": {
            "x": {
                "field": "a",
                "type": "nominal",
                "axis": {"labelFontSize": 9, "titleFontSize": 9},
            },
            "y": {"field": "b", "type": "quantitative"},
        },
        "title": "Hello World",
    }
    out = apply_ops(
        spec,
        [
            {"action": "set_font", "family": "Helvetica"},
            {
                "action": "set_font_sizes",
                "title": 28,
                "axis_label": 18,
                "axis_title": 18,
            },
        ],
    )
    axis = out["encoding"]["x"]["axis"]
    assert "labelFontSize" not in axis
    assert "titleFontSize" not in axis
    assert out["config"]["axis"]["labelFontSize"] == 18
    assert out["config"]["title"]["fontSize"] == 28
    assert out["title"]["fontSize"] == 28
    assert "Helvetica" in out["config"]["font"]
    assert "Helvetica" in out["title"]["font"]
    assert out["config"]["axisX"]["labelFont"]  # 轴向细分一并写入


def test_set_title_text_updates_root_and_layer():
    spec = {
        "title": {"text": "OLD TITLE HERE"},
        "layer": [
            {
                "mark": {"type": "text", "text": "OLD TITLE HERE", "fontSize": 22},
                "encoding": {"x": {"value": 0}, "y": {"value": 0}},
            },
            {"mark": "bar", "encoding": {"x": {"field": "a"}, "y": {"field": "b"}}},
        ],
    }
    out = apply_ops(spec, [{"action": "set_title_text", "text": "New sentence case"}])
    assert out["title"]["text"] == "New sentence case"
    assert out["layer"][0]["mark"]["text"] == "New sentence case"


def test_set_title_text_does_not_clobber_annotation_callouts():
    """字号加大后 annotation 勿被误判为 title 并整批改成同一标题。"""
    spec = {
        "title": {"text": "Berlin’s Bike Theft Statistics"},
        "layer": [
            {"mark": "area", "encoding": {"x": {"field": "y"}, "y": {"field": "v"}}},
            {
                "mark": {
                    "type": "text",
                    "text": "Only about 4-5% of Berlin’s",
                    "fontSize": 14,
                },
                "encoding": {"x": {"value": 0}, "y": {"value": 10}},
            },
            {
                "mark": {
                    "type": "text",
                    "text": "recorded bike theft cases get",
                    "fontSize": 14,
                },
                "encoding": {"x": {"value": 100}, "y": {"value": 10}},
            },
        ],
    }
    out = apply_ops(
        spec,
        [
            {"action": "set_font_sizes", "title": 28, "subtitle": 22, "axis_label": 14},
            {
                "action": "set_title_text",
                "text": "Berlin’s bike theft statistics",
            },
        ],
    )
    assert out["title"]["text"] == "Berlin’s bike theft statistics"
    texts = [
        ly["mark"]["text"]
        for ly in out["layer"]
        if isinstance(ly.get("mark"), dict) and ly["mark"].get("type") == "text"
    ]
    assert texts == [
        "Only about 4-5% of Berlin’s",
        "recorded bike theft cases get",
    ]
    assert texts.count("Berlin’s bike theft statistics") == 0


def test_mock_title_case_emits_ops():
    persona = load_persona_dict(
        {
            "institution": {"id": "t", "name": "T"},
            "L1_signature": {"tokens": {}, "rules": []},
        }
    )
    esc = {
        "layer": "L1",
        "rule_id": "s-title-case",
        "rule_text": "sentence case",
        "strength": "must",
        "src": ["L59"],
        "story_id": "",
        "why": "llm",
    }
    adopted, rejected = _mock_adjudicate(
        persona, {"title_text": "Plastic Waste Generation Per Capita"}, [esc]
    )
    assert not rejected
    assert adopted[0]["ops"][0]["action"] == "set_title_text"
    assert adopted[0]["ops"][0]["text"] == "Plastic waste generation per capita"


def test_economist_css_font_token_resolves_to_serif():
    from app.core.actions import persona_font_family, apply_ops
    from app.core.persona import PersonaRegistry
    from app.config import settings

    reg = PersonaRegistry(settings.data_dir, settings.storage_dir / "personas")
    eco = reg.get("economist")
    fam = persona_font_family(eco)
    assert fam and "Georgia" in fam
    out = apply_ops(
        {"mark": "bar", "encoding": {"x": {"field": "a"}, "y": {"field": "b"}}, "title": "T"},
        [{"action": "set_font", "family": fam}],
    )
    assert "Georgia" in out["config"]["font"]
    assert "Georgia" in out["title"]["font"]
    persona = load_persona_dict(
        {
            "institution": {"id": "eco", "name": "Eco"},
            "L1_signature": {
                "tokens": {"color": {"canvas": {"paper": "#F5F4EF"}}},
                "rules": [],
            },
            "L3_narrative": {
                "philosophy": [
                    {"id": "p-harmony", "title": "Visual harmony", "quote": "q"}
                ]
            },
        }
    )
    proposals = _derived_proposals(persona, {}, {"background": "#ffffff"})
    assert len(proposals) == 1
    assert proposals[0]["ops"][0]["color"] == "#F5F4EF"


def test_ibm_aliases_executable_subset(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_PREFER_MODE", "apply")
    facts = {
        "category_field": "Cat",
        "value_field": "Val",
        "category_channel": "x",
        "color_field": "Series",
    }
    executable_names = [
        "simple bar",
        "grouped bar",
        "floating bar",
        "lollipop",
        "bubble",
        "line",
        "area",
        "boxplot",
        "histogram",
        "stream",
        "donut",
        "pie",
        "stacked bar",
        "stacked area",
        "scattorplot",
        "heatmap",
    ]
    for name in executable_names:
        out = compile_then(_Persona(), {"prefer": "chart.type", "to": name}, facts)
        assert out["renderable"] is True, name
        assert out["ops"], name
        assert out["ops"][0]["mark_type"] in EXECUTABLE_MARKS, name

    for name in ("radar", "wordcloud", "treemap", "choropleth map", "network diagram"):
        out = compile_then(_Persona(), {"prefer": "chart.type", "to": name}, facts)
        assert out["renderable"] is False, name
        key = name.lower()
        assert key in NON_EXECUTABLE_CHART_TYPES or CHART_TYPE_MARK_ALIASES.get(
            key, key
        ) not in EXECUTABLE_MARKS


def test_donut_and_bubble_rebuild():
    facts = {
        "category_field": "Cat",
        "value_field": "Val",
        "category_channel": "x",
    }
    donut = compile_then(_Persona(), {"set": "chart.type", "to": "donut"}, facts)
    spec = {
        "data": {"values": [{"Cat": "a", "Val": 1}, {"Cat": "b", "Val": 2}]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "Cat", "type": "nominal"},
            "y": {"field": "Val", "type": "quantitative"},
        },
    }
    out = apply_ops(spec, donut["ops"])
    assert out["mark"]["type"] == "arc"
    assert out["mark"].get("innerRadius") == 50
    assert "theta" in out["encoding"]

    bubble = compile_then(_Persona(), {"set": "chart.type", "to": "bubble"}, facts)
    out2 = apply_ops(spec, bubble["ops"])
    assert out2["mark"]["type"] == "point"
    assert out2["encoding"]["size"]["field"] == "Val"
