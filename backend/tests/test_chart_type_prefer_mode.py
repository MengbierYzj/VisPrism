"""VIZGUIDE_PREFER_MODE：prefer 建议 vs 落地；复合图 set_mark_type rebuild。"""
from app.core.actions import apply_ops, compile_then


class _Persona:
    def resolve_color(self, token):
        if token in ("{color.bbc-teal}", "color.bbc-teal", "#1380A1"):
            return "#1380A1"
        if isinstance(token, str) and token.startswith("#"):
            return token
        return None

    def resolve_color_list(self, _token):
        return None

    def resolve_token(self, token):
        return token

    def token_index(self):
        return {}

    @property
    def ui(self):
        return {}


def test_prefer_chart_type_suggest_by_default(monkeypatch):
    monkeypatch.delenv("VIZGUIDE_PREFER_MODE", raising=False)
    monkeypatch.delenv("VIZGUIDE_CHART_TYPE_PREFER_MODE", raising=False)
    out = compile_then(_Persona(), {"prefer": "chart.type", "to": "bar"}, {})
    assert out["renderable"] is False
    assert out["ops"] == []
    assert "prefer chart.type" in out["note"]


def test_prefer_mark_color_still_executes_in_suggest_mode(monkeypatch):
    """suggest 仅卡住 chart.type；其它可编译 prefer（如 mark.color）仍落地。"""
    monkeypatch.delenv("VIZGUIDE_PREFER_MODE", raising=False)
    monkeypatch.setenv("VIZGUIDE_CHART_TYPE_PREFER_MODE", "suggest")
    out = compile_then(_Persona(), {"prefer": "mark.color", "to": "{color.bbc-teal}"}, {})
    assert out["renderable"] is True
    assert out["ops"] == [{"action": "set_mark_color", "color": "#1380A1"}]


def test_prefer_chart_type_apply_mode_emits_set_mark_type(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_PREFER_MODE", "apply")
    monkeypatch.setenv("VIZGUIDE_ADVISOR_CHART_TYPE_MODE", "allow")
    out = compile_then(_Persona(), {"prefer": "chart.type", "to": "bar"}, {})
    assert out["renderable"] is True
    assert out["ops"][0]["action"] == "set_mark_type"
    assert out["ops"][0]["mark_type"] == "bar"
    assert out["ops"][0].get("chart_type") == "bar"
    assert "apply mode" in out["note"]


def test_legacy_chart_type_prefer_mode_env_still_works(monkeypatch):
    monkeypatch.delenv("VIZGUIDE_PREFER_MODE", raising=False)
    monkeypatch.setenv("VIZGUIDE_CHART_TYPE_PREFER_MODE", "apply")
    monkeypatch.setenv("VIZGUIDE_ADVISOR_CHART_TYPE_MODE", "allow")
    out = compile_then(_Persona(), {"prefer": "chart.type", "to": "line"}, {})
    assert out["renderable"] is True
    assert out["ops"][0]["mark_type"] == "line"


def test_prefer_chart_type_apply_mode_maps_aliases(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_PREFER_MODE", "apply")
    monkeypatch.setenv("VIZGUIDE_ADVISOR_CHART_TYPE_MODE", "allow")
    facts = {
        "category_field": "Country",
        "value_field": "Value",
        "category_channel": "x",
    }
    out = compile_then(_Persona(), {"prefer": "chart.type", "to": "pie"}, facts)
    assert out["renderable"] is True
    op = out["ops"][0]
    assert op["action"] == "set_mark_type"
    assert op["mark_type"] == "arc"
    assert op["chart_type"] == "pie"
    assert op["rebuild_unit"] is True


def test_prefer_open_chart_type_still_suggested_in_apply_mode(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_PREFER_MODE", "apply")
    monkeypatch.setenv("VIZGUIDE_ADVISOR_CHART_TYPE_MODE", "allow")
    # radar 等 VL 无原生 mark：即使 apply 模式也只能 suggested
    out = compile_then(_Persona(), {"prefer": "chart.type", "to": "radar"}, {})
    assert out["renderable"] is False
    assert out["ops"] == []


def test_prefer_bubble_executable_in_apply_mode(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_PREFER_MODE", "apply")
    monkeypatch.setenv("VIZGUIDE_ADVISOR_CHART_TYPE_MODE", "allow")
    facts = {
        "category_field": "Country",
        "value_field": "Value",
        "category_channel": "x",
    }
    out = compile_then(_Persona(), {"prefer": "chart.type", "to": "bubble"}, facts)
    assert out["renderable"] is True
    assert out["ops"][0]["mark_type"] == "point"
    assert out["ops"][0]["chart_type"] == "bubble"


def test_set_chart_type_unchanged_when_prefer_suggest(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_PREFER_MODE", "suggest")
    monkeypatch.setenv("VIZGUIDE_ADVISOR_CHART_TYPE_MODE", "allow")
    out = compile_then(_Persona(), {"set": "chart.type", "to": "line"}, {})
    assert out["renderable"] is True
    assert out["ops"][0]["action"] == "set_mark_type"
    assert out["ops"][0]["mark_type"] == "line"
    assert out["ops"][0].get("chart_type") == "line"


def test_prefer_line_rebuilds_layered_rule_span_chart(monkeypatch):
    """rule+tick+point 的 span 图：prefer line 应折叠为单 unit 折线，而非只改首层 mark。"""
    monkeypatch.setenv("VIZGUIDE_PREFER_MODE", "apply")
    monkeypatch.setenv("VIZGUIDE_ADVISOR_CHART_TYPE_MODE", "allow")
    facts = {
        "category_field": "Year",
        "value_field": "BasePrice",
        "category_channel": "x",
    }
    compiled = compile_then(_Persona(), {"prefer": "chart.type", "to": "line"}, facts)
    assert compiled["ops"][0]["rebuild_unit"] is True
    spec = {
        "data": {"values": [{"Year": "2013", "BasePrice": 116.61, "FullPrice": 139.93}]},
        "layer": [
            {
                "mark": {"type": "rule", "size": 3},
                "encoding": {
                    "x": {"field": "Year", "type": "nominal"},
                    "y": {"field": "BasePrice", "type": "quantitative"},
                    "y2": {"field": "FullPrice"},
                },
            },
            {
                "mark": {"type": "tick", "size": 18},
                "encoding": {
                    "x": {"field": "Year", "type": "nominal"},
                    "y": {"field": "FullPrice", "type": "quantitative"},
                },
            },
            {
                "mark": {"type": "point", "size": 100},
                "encoding": {
                    "x": {"field": "Year", "type": "nominal"},
                    "y": {"field": "BasePrice", "type": "quantitative"},
                },
            },
        ],
    }
    out = apply_ops(spec, compiled["ops"])
    assert "layer" not in out
    assert out["mark"]["type"] == "line"
    assert out["encoding"]["x"]["field"] == "Year"
    assert out["encoding"]["y"]["field"] == "BasePrice"
    assert "y2" not in out["encoding"]


def test_set_mark_type_rebuild_fallback_without_flag():
    """漏标 rebuild_unit 时，多几何层 + 字段仍应折叠。"""
    spec = {
        "data": {"values": [{"a": "x", "b": 1}]},
        "layer": [
            {
                "mark": {"type": "rule"},
                "encoding": {
                    "x": {"field": "a", "type": "nominal"},
                    "y": {"field": "b", "type": "quantitative"},
                    "y2": {"field": "b"},
                },
            },
            {
                "mark": {"type": "point"},
                "encoding": {
                    "x": {"field": "a", "type": "nominal"},
                    "y": {"field": "b", "type": "quantitative"},
                },
            },
        ],
    }
    out = apply_ops(
        spec,
        [
            {
                "action": "set_mark_type",
                "mark_type": "bar",
                "category_field": "a",
                "value_field": "b",
                "category_channel": "x",
            }
        ],
    )
    assert "layer" not in out
    assert out["mark"]["type"] == "bar"
    assert out["encoding"]["x"]["field"] == "a"


def test_sequential_pie_then_line_rebuilds_encoding_on_unit():
    """单 unit 上 pie→line 连续改型须重建 encoding，避免 line+theta 残缺图。"""
    facts = {
        "category_field": "Year",
        "value_field": "PM25",
        "category_channel": "x",
    }
    pie = {
        "action": "set_mark_type",
        "mark_type": "arc",
        "chart_type": "pie",
        "rebuild_unit": True,
        **{k: facts[k] for k in ("category_field", "value_field", "category_channel")},
    }
    line = {
        "action": "set_mark_type",
        "mark_type": "line",
        "rebuild_unit": True,
        **{k: facts[k] for k in ("category_field", "value_field", "category_channel")},
    }
    spec = {
        "data": {"values": [{"Year": "2020", "PM25": 51.8}]},
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "Year", "type": "nominal"},
            "y": {"field": "PM25", "type": "quantitative"},
        },
    }
    mid = apply_ops(spec, [pie])
    assert mid["mark"]["type"] == "arc"
    assert "theta" in mid["encoding"]
    out = apply_ops(mid, [line])
    assert out["mark"]["type"] == "line"
    assert out["encoding"]["x"]["field"] == "Year"
    assert out["encoding"]["y"]["field"] == "PM25"
    assert "theta" not in out["encoding"]
