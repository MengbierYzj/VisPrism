from app.core.parser_agent import _assemble_persona


def test_semantic_knowledge_fields_survive_assembly():
    text = "# Test\nFor comparison bar charts, start the numerical axis at zero."
    fragment = {
        "tokens": [],
        "requirements": [{
            "classification": "L2",
            "requirement": "For comparison bar charts, start the numerical axis at zero.",
            "strength": "must",
            "when": {"intent": "comparison"},
            "then": {"set": "axis.y", "to": {"scale": {"zero": True}}},
            "applicability": {"intent": "comparison", "mark_type": ["bar"]},
            "problem_type": "misleading_magnitude",
            "principle_refs": ["p-consistent"],
            "actions": ["set_axis"],
            "verification": ["y_scale_zero_true"],
            "evidence": {"lines": "L2", "quote": "For comparison bar charts, start the numerical axis at zero."},
        }],
        "diagnostics": [{"id": "axis-zero", "problem_type": "misleading_magnitude"}],
        "chart_type_guidance": [],
        "palette_guidance": [],
        "conflicts": [],
    }
    data, _ = _assemble_persona("Test", text, [fragment], 1)
    rule = data["L2_adaptations"][0]
    assert rule["applicability"]["mark_type"] == ["bar"]
    assert rule["problem_type"] == "misleading_magnitude"
    assert rule["verification"] == ["y_scale_zero_true"]
    assert data["diagnostics"][0]["id"] == "axis-zero"


def test_parser_preserves_persona_specific_visual_and_component_l2_strategies():
    text = """# Guide
Avoid crowded axis labels; reduce ticks so readers can follow the chart.
Keep the headline, explanatory copy and source attribution in distinct reading regions.
"""
    fragment = {
        "tokens": [],
        "requirements": [
            {
                "classification": "L2", "requirement": "Reduce dense axis labels for readability.",
                "strength": "should", "scope": "visual-strategy", "when": {"axis_x_dense": True},
                "visual_issues": ["crowding", "overlap"], "actions": ["thin_axis_labels", "reduce_axis_grid"],
                "evidence": {"lines": "L2", "quote": "Avoid crowded axis labels; reduce ticks so readers can follow the chart."},
            },
            {
                "classification": "L2", "requirement": "Keep headline, explanatory copy and source in distinct reading regions.",
                "strength": "should", "scope": "component-assembly", "when": {}, "actions": [],
                "evidence": {"lines": "L3", "quote": "Keep the headline, explanatory copy and source attribution in distinct reading regions."},
            },
        ],
        "diagnostics": [], "chart_type_guidance": [], "palette_guidance": [], "conflicts": [],
    }
    data, _ = _assemble_persona("Guide", text, [fragment], 1)
    strategies = {item.get("scope"): item for item in data["L2_adaptations"]}
    visual = strategies["visual-strategy"]
    assert visual["visual_issues"] == ["crowding", "overlap"]
    assert visual["then"] == {"visual_actions": ["thin_axis_labels", "reduce_axis_grid"]}
    component = strategies["component-assembly"]
    assert component["when"] == {"pixel_positioned_text": True}
    assert component["then"] == {"profile": "editorial"}
