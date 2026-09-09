"""Advisor 工作前基础设定（briefing）测试。"""
import asyncio

from app.core.advisor_briefing import (
    beat1_read_system,
    briefing_system_preamble,
    build_advisor_briefing,
    intent_analyze_system,
)
from app.core.beats import beat1_read
from app.core.persona import load_persona_dict
from app.core.specfacts import extract_facts
from app.llm import LLMClient


def _mini_persona():
    return load_persona_dict(
        {
            "institution": {
                "id": "demo",
                "name": "Demo Org",
                "domain": "journalism",
                "source": "inline",
            },
            "applicability": {"suits": ["新闻图表"], "promises": ["清晰可读"]},
            "L1_signature": {
                "tokens": {"color": {"primary": "#BB1919"}, "palette": {"categorical": ["#1380A1"]}},
                "rules": [
                    {
                        "id": "s-never-3d",
                        "rule": "Never use 3D charts",
                        "strength": "never",
                        "check": "llm",
                        "src": ["L1"],
                    }
                ],
            },
            "L2_adaptations": [
                {
                    "id": "a-trend-line",
                    "when": {"intent": "trend"},
                    "then": {"prefer": "chart.type", "to": "line"},
                    "strength": "should",
                    "check": "programmatic",
                    "src": ["L2"],
                }
            ],
            "L3_narrative": {
                "philosophy": [
                    {
                        "id": "p-clarity",
                        "title": "Clarity First",
                        "quote": "Clarity over decoration.",
                        "src": ["L3"],
                    }
                ],
                "stories": [{"id": "n-trend", "story": "趋势用折线", "src": ["L3"]}],
            },
        },
        kind="custom",
    )


SPEC = {
    "title": {"text": "Sales by Year"},
    "mark": "bar",
    "data": {"values": [{"Year": "2020", "Sales": 10}, {"Year": "2021", "Sales": 20}]},
    "encoding": {
        "x": {"field": "Year", "type": "nominal"},
        "y": {"field": "Sales", "type": "quantitative"},
    },
}


def test_build_advisor_briefing_identity_and_layers():
    persona = _mini_persona()
    facts = extract_facts(SPEC, {"communication_goal": "展示销售趋势"})
    briefing = build_advisor_briefing(persona, facts, SPEC)
    assert briefing["persona_id"] == "demo"
    assert "visualization design expert" in briefing["role"]
    assert "Demo Org" in briefing["role"]
    assert briefing["user_goal"] == "展示销售趋势"
    assert "Sales by Year" in briefing["chart"]["narrative"]
    assert briefing["layers"]["L1"]["rule_counts"]["never"] == 1
    assert briefing["layers"]["L2"]["adaptation_count"] == 1
    assert "trend" in briefing["layers"]["L2"]["intent_or_task_keys"]
    assert briefing["layers"]["L3"]["philosophy_count"] == 1
    preamble = briefing_system_preamble(briefing)
    assert (
        "L1 Dispositional Signature" in preamble
        and "L2 Characteristic Adaptations" in preamble
        and "L3 Narrative Identity" in preamble
    )
    assert "展示销售趋势" in preamble


def test_prompt_systems_include_briefing():
    persona = _mini_persona()
    facts = extract_facts(SPEC, {"communication_goal": "强调 2021"})
    briefing = build_advisor_briefing(persona, facts, SPEC)
    s1 = beat1_read_system(briefing)
    assert "Beat 1 · chart reading" in s1 and "Demo Org" in s1
    s_intent = intent_analyze_system(briefing)
    assert "intent analyzer" in s_intent and "Do not invent hex" in s_intent


def test_beat1_attaches_advisor_briefing():
    persona = _mini_persona()
    facts = extract_facts(SPEC, {"communication_goal": "突出趋势"})
    llm = LLMClient()

    async def _run():
        return await beat1_read(persona, SPEC, facts, llm)

    out_facts, trace = asyncio.run(_run())
    assert isinstance(out_facts.get("advisor_briefing"), dict)
    assert out_facts["advisor_briefing"]["persona_id"] == "demo"
    assert out_facts["advisor_briefing"].get("read_summary")
    assert trace["beat"] == 1
