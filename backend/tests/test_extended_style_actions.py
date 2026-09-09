from app.core.actions import apply_ops, compile_then


class Persona:
    def resolve_color(self, value):
        return value if isinstance(value, str) and value.startswith("#") else None

    def resolve_token(self, value):
        return value


def test_bar_and_line_style_compile_and_apply():
    spec = {"mark": {"type": "bar"}, "encoding": {"x": {"field": "month"}}}
    compiled = compile_then(Persona(), {"set": "bar.style", "to": {"cornerRadius": 4, "strokeWidth": 2}}, {})
    assert compiled["renderable"] and compiled["ops"]
    out = apply_ops(spec, compiled["ops"])
    assert out["mark"]["cornerRadius"] == 4
    assert out["mark"]["strokeWidth"] == 2


def test_axis_encoding_and_annotation_actions():
    spec = {"mark": "line", "encoding": {"x": {"field": "date"}, "y": {"field": "value"}}}
    axis = compile_then(Persona(), {"set": "axis.y", "to": {"axis": {"grid": False, "ticks": True}, "scale": {"zero": True}}}, {})
    out = apply_ops(spec, axis["ops"])
    assert out["encoding"]["y"]["axis"]["grid"] is False
    assert out["encoding"]["y"]["scale"]["zero"] is True

    shape = compile_then(Persona(), {"set": "encoding.shape", "to": {"field": "status", "type": "nominal"}}, {})
    out = apply_ops(out, shape["ops"])
    assert out["encoding"]["shape"]["field"] == "status"
