"""用户意图理解：归类 → 指南内落地。"""
import asyncio

from app.core.actions import apply_ops
from app.core.persona import load_persona_dict
from app.core.runner import RunStore, start_run, wait_run
from app.core.specfacts import extract_facts
from app.core.user_intent import (
    attach_user_intent,
    l1_never_conflicts,
    mock_analyze_goal,
)
from app.llm import LLMClient


DUMBBELL = {
    "title": {"text": "UK Diesel Price Gap"},
    "width": 650,
    "height": 360,
    "data": {
        "values": [
            {"Date": "2013-01-02", "VAT_exc": 116.61, "VAT_inc": 139.93},
            {"Date": "2022-07-01", "VAT_exc": 165.87, "VAT_inc": 199.07},
        ]
    },
    "layer": [
        {
            "mark": {"type": "rule", "color": "#888888"},
            "encoding": {
                "y": {"field": "Date", "type": "nominal"},
                "x": {"field": "VAT_exc", "type": "quantitative"},
                "x2": {"field": "VAT_inc"},
            },
        },
        {
            "mark": {"type": "point", "color": "#1f77b4"},
            "encoding": {
                "y": {"field": "Date", "type": "nominal"},
                "x": {"field": "VAT_exc", "type": "quantitative"},
            },
        },
    ],
}

BAR = {
    "mark": "bar",
    "data": {
        "values": [
            {"Country": "United States", "Plastic waste": 74.3},
            {"Country": "China", "Plastic waste": 29.0},
            {"Country": "Nigeria", "Plastic waste": 27.0},
        ]
    },
    "encoding": {
        "y": {"field": "Country", "type": "nominal"},
        "x": {"field": "Plastic waste", "type": "quantitative"},
    },
}


def test_mock_communication_fills_emphasis():
    facts = extract_facts(BAR)
    goal = "Highlight the huge gap and emphasize United States"
    facts["communication_goal"] = goal
    analysis = mock_analyze_goal(goal, facts)
    assert analysis["kind"] in ("communication", "mixed")
    persona = load_persona_dict(
        {
            "institution": {"id": "t", "name": "t", "source": "inline"},
            "L1_signature": {"tokens": {}, "rules": []},
            "L2_adaptations": [],
            "L3_narrative": {"philosophy": [], "stories": []},
        },
        kind="custom",
    )
    attach_user_intent(persona, BAR, facts, analysis)
    assert facts["emphasis_target"] == "United States"
    assert facts["user_intent_analysis"]["kind"] in ("communication", "mixed")
    assert not any(
        c.get("focus") == "chart.type" and c.get("ops") and not c.get("suggested_only")
        for c in facts.get("user_constraint_items") or []
    )


def test_mock_edit_simple_bar_rebuild():
    facts = extract_facts(DUMBBELL)
    facts["communication_goal"] = "Adjust the chart to a Simple Bar"
    persona = load_persona_dict(
        {
            "institution": {"id": "t", "name": "t", "source": "inline"},
            "L1_signature": {"tokens": {}, "rules": []},
            "L2_adaptations": [],
            "L3_narrative": {"philosophy": [], "stories": []},
        },
        kind="custom",
    )
    attach_user_intent(persona, DUMBBELL, facts)
    assert facts["user_intent_analysis"]["kind"] == "edit"
    items = facts["user_constraint_items"]
    assert items and items[0]["ops"][0]["action"] == "set_mark_type"
    out = apply_ops(DUMBBELL, items[0]["ops"])
    assert out["mark"]["type"] == "bar"
    assert "layer" not in out


def test_mock_mixed_emphasis_and_brand_color():
    facts = extract_facts(BAR)
    facts["communication_goal"] = "Emphasize United States and use the brand primary color"
    persona = load_persona_dict(
        {
            "institution": {"id": "t", "name": "t", "source": "inline"},
            "L1_signature": {
                "tokens": {"color": {"primary": "#1380A1"}},
                "rules": [],
            },
            "L2_adaptations": [],
            "L3_narrative": {"philosophy": [], "stories": []},
        },
        kind="custom",
    )
    attach_user_intent(persona, BAR, facts)
    assert facts["user_intent_analysis"]["kind"] == "mixed"
    assert facts["emphasis_target"] == "United States"
    color_items = [c for c in facts["user_constraint_items"] if c.get("focus") == "color"]
    assert color_items and color_items[0]["ops"][0]["color"] == "#1380A1"


def test_l1_never_conflict_blocks_user_color():
    persona = load_persona_dict(
        {
            "institution": {"id": "t", "name": "t", "source": "inline"},
            "L1_signature": {
                "tokens": {"color": {"primary": "#1380A1"}},
                "rules": [
                    {
                        "id": "s-house-palette",
                        "rule": "only house palette",
                        "strength": "never",
                        "check": "programmatic",
                        "src": ["t"],
                    }
                ],
            },
            "L2_adaptations": [],
            "L3_narrative": {"philosophy": [], "stories": []},
        },
        kind="custom",
    )
    persona.ui = {"palette": ["#1380A1", "#FF5500"]}
    ops = [{"action": "set_mark_color", "color": "#FF0000"}]
    facts = extract_facts(BAR)
    conflicts = l1_never_conflicts(persona, BAR, ops, facts)
    assert "s-house-palette" in conflicts

    facts["communication_goal"] = "force a bad color"
    analysis = {
        "kind": "edit",
        "items": [
            {
                "kind": "edit",
                "focus": "color",
                "slots": {},
                "grounding": "action_space",
                "ops": ops,
                "suggested_only": False,
                "rationale": "force bad color",
            }
        ],
        "summary": "edit",
    }
    attach_user_intent(persona, BAR, facts, analysis)
    assert facts["user_intent_rejected"]
    assert not facts["user_constraint_items"]


def test_advisor_end_to_end_user_bar_edit():
    class Single:
        def get(self, persona_id):
            if persona_id != "ui-test":
                return None
            return load_persona_dict(
                {
                    "institution": {"id": "ui-test", "name": "ui-test", "source": "inline"},
                    "L1_signature": {"tokens": {}, "rules": []},
                    "L2_adaptations": [],
                    "L3_narrative": {"philosophy": [], "stories": []},
                },
                kind="custom",
            )

    async def main():
        store = RunStore()
        run, err = start_run(
            store,
            Single(),
            LLMClient(),
            DUMBBELL,
            ["ui-test"],
            {"communication_goal": "Adjust the chart to a Simple Bar"},
        )
        assert err == "" and run is not None
        await wait_run(run)
        return run

    run = asyncio.run(main())
    prop = run.agents["ui-test"].proposal
    assert prop["facts"]["user_intent_analysis"]["kind"] == "edit"
    assert prop["modified_spec"]["mark"]["type"] == "bar"
    assert "layer" not in prop["modified_spec"]
    assert any(c["rule_id"].startswith("u-chart") and c["status"] == "applied" for c in prop["changes"])


def test_plain_narrative_no_edit_ops():
    facts = extract_facts(BAR)
    facts["communication_goal"] = "I want readers to understand the price story carefully."
    persona = load_persona_dict(
        {
            "institution": {"id": "t", "name": "t", "source": "inline"},
            "L1_signature": {"tokens": {}, "rules": []},
            "L2_adaptations": [],
            "L3_narrative": {"philosophy": [], "stories": []},
        },
        kind="custom",
    )
    attach_user_intent(persona, BAR, facts)
    # 可能是 communication 或 other；不应有可执行 chart 改型
    assert not any(
        c.get("ops") and c.get("focus") == "chart.type" and not c.get("suggested_only")
        for c in facts.get("user_constraint_items") or []
    )


def test_beat4_user_chart_type_overrides_persona_trend():
    """用户 pie 与机构 trend→line 冲突时：pie applied，机构图型降为 suggested。"""
    from app.core.beats import beat4_compile

    persona = load_persona_dict(
        {
            "institution": {"id": "ibm-t", "name": "ibm-t", "source": "inline"},
            "L1_signature": {"tokens": {}, "rules": []},
            "L2_adaptations": [],
            "L3_narrative": {"philosophy": [], "stories": []},
        },
        kind="custom",
    )
    spec = {
        "data": {"values": [{"Year": "2020", "PM25": 51.8}, {"Year": "2022", "PM25": 33.6}]},
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "Year", "type": "nominal"},
            "y": {"field": "PM25", "type": "quantitative"},
        },
    }
    facts = {
        "category_field": "Year",
        "value_field": "PM25",
        "category_channel": "x",
        "user_constraint_items": [
            {
                "rule_id": "u-chart-pie",
                "layer": "user",
                "strength": "must",
                "src": ["user:communication_goal"],
                "ops": [
                    {
                        "action": "set_mark_type",
                        "mark_type": "arc",
                        "chart_type": "pie",
                        "rebuild_unit": True,
                        "category_field": "Year",
                        "value_field": "PM25",
                        "category_channel": "x",
                    }
                ],
                "suggested_only": False,
                "confidence": "high",
                "rationale": "user pie",
            }
        ],
    }
    candidates = [
        {
            "rule_id": "a-trend-line",
            "layer": "L2",
            "strength": "should",
            "src": ["L14"],
            "story_id": "",
            "ops": [
                {
                    "action": "set_mark_type",
                    "mark_type": "line",
                    "rebuild_unit": True,
                    "category_field": "Year",
                    "value_field": "PM25",
                    "category_channel": "x",
                }
            ],
            "confidence": "high",
            "suggested_only": False,
            "rule_text": '{"prefer":"chart.type","to":"line"}',
        }
    ]
    modified, changes, _inv, trace = beat4_compile(
        persona, spec, facts, candidates, [], [], {"medium": "digital"}
    )
    assert modified["mark"]["type"] == "arc"
    assert "theta" in modified["encoding"]
    by_id = {c["rule_id"]: c for c in changes}
    assert by_id["u-chart-pie"]["status"] == "applied"
    assert by_id["a-trend-line"]["status"] == "suggested"
    assert "a-trend-line" in (trace.get("user_priority_deferred") or [])


def test_beat4_user_pie_gets_categorical_palette_not_primary():
    """用户 pie 后应写入分类色板 range，并缓议单色 mark.color。"""
    from app.core.beats import beat4_compile

    persona = load_persona_dict(
        {
            "institution": {"id": "ibm-t", "name": "ibm-t", "source": "inline"},
            "L1_signature": {
                "tokens": {
                    "color": {"primary": "#6929C4"},
                    "palette": {
                        "categorical": ["#6929C4", "#1192E8", "#005D5D", "#9F1853"]
                    },
                },
                "rules": [],
            },
            "L2_adaptations": [],
            "L3_narrative": {"philosophy": [], "stories": []},
        },
        kind="custom",
    )
    spec = {
        "data": {
            "values": [
                {"Year": "2020", "PM25": 51.8},
                {"Year": "2022", "PM25": 33.6},
            ]
        },
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "Year", "type": "nominal"},
            "y": {"field": "PM25", "type": "quantitative"},
        },
    }
    facts = {
        "category_field": "Year",
        "value_field": "PM25",
        "category_channel": "x",
        "user_constraint_items": [
            {
                "rule_id": "u-chart-pie",
                "layer": "user",
                "strength": "must",
                "src": ["user:communication_goal"],
                "ops": [
                    {
                        "action": "set_mark_type",
                        "mark_type": "arc",
                        "chart_type": "pie",
                        "rebuild_unit": True,
                        "category_field": "Year",
                        "value_field": "PM25",
                        "category_channel": "x",
                    }
                ],
                "suggested_only": False,
                "confidence": "high",
                "rationale": "user pie",
            }
        ],
    }
    candidates = [
        {
            "rule_id": "a-custom-2",
            "layer": "L2",
            "strength": "should",
            "src": ["L61"],
            "story_id": "",
            "ops": [{"action": "set_mark_color", "color": "#6929C4"}],
            "confidence": "medium",
            "suggested_only": False,
            "rule_text": '{"set":"mark.color","to":"{color.primary}"}',
        }
    ]
    modified, changes, _inv, _tr = beat4_compile(
        persona, spec, facts, candidates, [], [], {"medium": "digital"}
    )
    assert modified["mark"]["type"] == "arc"
    assert "color" not in modified["mark"] or modified["mark"].get("color") is None
    enc_color = modified["encoding"]["color"]
    assert enc_color["field"] == "Year"
    assert enc_color["scale"]["range"][0] == "#6929C4"
    assert enc_color["scale"]["range"][1] == "#1192E8"
    by_id = {c["rule_id"]: c for c in changes}
    assert by_id["u-chart-pie"]["status"] == "applied"
    assert by_id["u-color-range-categorical"]["status"] == "applied"
    assert by_id["a-custom-2"]["status"] == "suggested"


def test_multi_focus_user_intent_emits_multiple_decisions():
    """同一 goal 的强调 + 图型应产生多条 user-layer decisions。"""
    facts = extract_facts(BAR)
    facts["communication_goal"] = (
        "Emphasize United States and change the chart to a pie chart"
    )
    persona = load_persona_dict(
        {
            "institution": {"id": "t", "name": "t", "source": "inline"},
            "L1_signature": {"tokens": {}, "rules": []},
            "L2_adaptations": [],
            "L3_narrative": {"philosophy": [], "stories": []},
        },
        kind="custom",
    )
    attach_user_intent(persona, BAR, facts)
    items = facts["user_constraint_items"]
    focuses = {c.get("focus") for c in items}
    assert "emphasis" in focuses
    assert "chart.type" in focuses
    assert len(items) >= 2
