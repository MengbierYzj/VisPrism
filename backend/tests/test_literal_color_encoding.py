"""Literal encoding.color must not block house mark colors."""
from app.core.actions import apply_ops, compile_then
from app.core.specfacts import extract_facts


class _Persona:
    def resolve_color(self, token):
        if "orange" in str(token):
            return "#FAAB18"
        if isinstance(token, str) and token.startswith("#"):
            return token
        return "#1380A1"

    def resolve_color_list(self, token):
        return ["#1380A1", "#FAAB18"]

    def resolve_token(self, token):
        return token


def _animals_spec():
    return {
        "mark": {"type": "bar"},
        "data": {
            "values": [
                {"Animal": "Dog", "Share": 73},
                {"Animal": "Octopus", "Share": 24},
            ]
        },
        "encoding": {
            "x": {"field": "Animal", "type": "nominal"},
            "y": {"field": "Share", "type": "quantitative"},
            "color": {
                "condition": {"test": "datum.Animal === 'Octopus'", "value": "#8c2f05"},
                "value": "#dc4805",
            },
        },
    }


def test_literal_color_encoding_fact():
    facts = extract_facts(_animals_spec())
    assert facts["literal_color_encoding"] is True
    assert facts["color_field"] is None
    assert facts["accent_color"] == "#8c2f05"
    assert "#dc4805" in (facts["colors_effective"] or [])


def test_set_mark_color_preserves_condition_without_accent():
    """无 accent 时保留 condition 强调结构，只换基色（避免末条/峰值被抹成单色）。"""
    out = apply_ops(_animals_spec(), [{"action": "set_mark_color", "color": "#1380A1"}])
    color = out["encoding"]["color"]
    assert color["value"] == "#1380A1"
    assert color["condition"]["test"] == "datum.Animal === 'Octopus'"
    assert color["condition"]["value"] == "#8c2f05"


def test_set_mark_color_rewrites_condition_with_accent():
    out = apply_ops(
        _animals_spec(),
        [{"action": "set_mark_color", "color": "#1380A1", "accent_color": "#FAAB18"}],
    )
    color = out["encoding"]["color"]
    assert color["value"] == "#1380A1"
    assert color["condition"]["value"] == "#FAAB18"
    assert color["condition"]["test"] == "datum.Animal === 'Octopus'"


def test_compile_mark_color_adds_accent_for_literal():
    facts = extract_facts(_animals_spec())
    compiled = compile_then(_Persona(), {"set": "mark.color", "to": "{color.bbc-blue}"}, facts)
    op = compiled["ops"][-1]
    assert op["action"] == "set_mark_color"
    assert op["color"] == "#1380A1"
    assert op.get("accent_color") == "#FAAB18"
