from app.core.specfacts import extract_facts


def test_extract_facts_emits_chart_audit_ir():
    spec = {
        "data": {"values": [{"category": str(i), "value": i} for i in range(14)]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "category", "type": "nominal"},
            "y": {"field": "value", "type": "quantitative", "scale": {"zero": False}},
        },
    }
    audit = extract_facts(spec)["chart_audit"]
    assert audit["axes"]["x_dense"] is True
    assert audit["axes"]["y_zero"] is False
    assert audit["marks"]["type"] == "bar"
