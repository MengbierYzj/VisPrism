import asyncio
from types import SimpleNamespace

from app.core.proposal_explainer import summarize_proposal


class FakeLLM:
    mode = "live"

    def __init__(self):
        self.user = ""

    async def chat_json(self, system, user, retries=1):
        self.user = user
        return {
            "goal_summary": "This chart compares sales across regions so the main contrast is easy to see.",
            "change_explanations": [{"id": "c1", "text": "The labels are clearer because the chart has limited space."}],
        }


def test_live_summary_uses_chart_and_persona_evidence():
    rule = SimpleNamespace(id="r1", raw={"evidence_quote": "Keep labels concise."}, rule="Keep labels concise.")
    persona = SimpleNamespace(name="Test", rules=[rule], adaptations=[], philosophy=[])
    changes = [{
        "id": "c1", "rule_id": "r1", "label": "Label spacing", "layer": "L3-derived",
        "status": "applied", "prompt": "Shorten labels", "reason": "The labels overlap.", "warrant": {},
    }]
    llm = FakeLLM()
    result = asyncio.run(summarize_proposal(
        persona,
        {"title_text": "Regional sales", "mark_type": "bar", "summary": "Sales by region"},
        changes,
        [{"beat": 1, "name": "Read", "summary": "read chart"}],
        llm,
    ))
    assert result["source"] == "llm"
    assert result["change_explanations"]["c1"].startswith("The labels")
    assert "Keep labels concise" in llm.user


def test_mock_mode_returns_readable_fallback():
    persona = SimpleNamespace(name="Test", rules=[], adaptations=[], philosophy=[])
    changes = [{"id": "c1", "label": "Color", "status": "suggested", "reason": "Improve contrast."}]
    result = asyncio.run(summarize_proposal(persona, {"summary": "A bar chart"}, changes, [], SimpleNamespace(mode="mock")))
    assert result["source"] == "fallback"
    assert "Color" in result["change_explanations"]["c1"]
