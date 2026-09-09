"""四拍管线端到端（mock 慢道）：BBC / Economist 对 example.json 的完整推理。"""
import asyncio
import json
from pathlib import Path

from app.core.beats import _live_adjudicate
from app.core.persona import load_persona_dict
from app.core.runner import RunStore, start_run, wait_run
from app.llm import LLMClient


def _run(registry, spec, persona_ids, context=None, llm=None):
    async def main():
        store = RunStore()
        run, err = start_run(
            store, registry, llm or LLMClient(), spec, persona_ids, context or {}
        )
        assert err == "" and run is not None
        await wait_run(run)
        return run

    return asyncio.run(main())


def _changes_by_rule(proposal):
    return {c["rule_id"]: c for c in proposal["changes"]}


def test_live_adjudicate_rejects_missing_data_role_without_llm(registry, example_spec):
    class MustNotCallLLM:
        async def chat_json(self, *args, **kwargs):
            raise AssertionError("缺少 data_role 时不应调用 LLM 猜测")

    escalation = {
        "layer": "L2",
        "rule_id": "a-supporting-color",
        "rule_text": "辅助数据使用灰色",
        "strength": "should",
        "story_id": "",
        "src": ["L44"],
        "when": {"data_role": "supporting"},
        "why": "语义条件",
        "compiled": {
            "ops": [{"action": "set_mark_color", "color": "#333333"}],
            "needs": [],
            "any_of": None,
        },
    }

    adopted, rejected = asyncio.run(
        _live_adjudicate(
            registry.get("bbc"),
            example_spec,
            {"intent": "comparison", "emphasis_target": "C产品"},
            [escalation],
            MustNotCallLLM(),
        )
    )

    assert not adopted
    assert rejected[0]["rule_id"] == "a-supporting-color"
    assert "不允许 LLM 猜测" in rejected[0]["reason"]


def test_communication_goal_and_slice_reach_every_advisor(registry, example_spec):
    class RecordingLiveLLM:
        mode = "live"

        def __init__(self):
            self.beat1_payloads = []

        async def chat_json(self, system, user, **kwargs):
            payload = json.loads(user)
            # 拍前角色 / 拍3 / 意图分析 / 拍1 Decision IR
            if "layers" in payload:
                return {"overrides": []}
            if "items" in payload:
                return {"verdicts": []}
            if "advisor_briefing" in payload and "chart_slice" in payload:
                self.beat1_payloads.append(payload)
                return {
                    "data_topic": "general",
                    "intent": "comparison",
                    "emphasis_target": None,
                    "coloring_mode": "uniform",
                    "organization": "Single-series categorical bar comparison",
                    "summary": "突出 reported 与 solved cases 的巨大差距。",
                }
            if "communication_goal" in payload:
                return {
                    "kind": "communication",
                    "summary": "emphasize the huge gap",
                    "items": [],
                }
            return {"verdicts": []}

    goal = "I want to visualize this huge gap between reported and solved cases beautifully."
    llm = RecordingLiveLLM()
    run = _run(
        registry,
        example_spec,
        ["bbc", "economist"],
        {"communication_goal": goal},
        llm,
    )

    assert run.status == "done"
    assert len(llm.beat1_payloads) == 2
    # 拍1 传 chart_slice，不再塞完整 VL
    assert all(isinstance(payload.get("chart_slice"), dict) for payload in llm.beat1_payloads)
    assert all("spec" not in payload for payload in llm.beat1_payloads)
    assert all(payload["communication_goal"] == goal for payload in llm.beat1_payloads)
    for persona_id in ("bbc", "economist"):
        proposal = run.agents[persona_id].proposal
        assert proposal["facts"]["communication_goal"] == goal
        assert "巨大差距" in proposal["facts"]["summary"]
        assert isinstance(proposal["facts"].get("decision_ir"), dict)


def test_bbc2_huge_gap_chart_type_rule_is_suggested_when_advisor_mode_locked():
    class SinglePersonaRegistry:
        def __init__(self, persona):
            self.persona = persona

        def get(self, persona_id):
            return self.persona if persona_id == self.persona.id else None

    # 不依赖 gitignored 的自定义 yaml；用最小 persona 验证 task 门与 pie 编译。
    persona = load_persona_dict(
        {
            "institution": {"id": "bbc-2", "name": "bbc-2", "source": "inline"},
            "L1_signature": {"tokens": {}, "rules": []},
            "L2_adaptations": [
                {
                    "id": "a-chart-pie-gap",
                    "when": {"task": "huge-gap"},
                    "then": {"set": "chart.type", "to": "pie"},
                    "strength": "must",
                    "check": "programmatic",
                    "src": ["custom"],
                }
            ],
            "L3_narrative": {"philosophy": [], "stories": []},
        },
        kind="custom",
    )
    scatter_spec = {
        "mark": {"type": "point", "filled": True},
        "data": {
            "values": [
                {"case_type": "reported", "cases": 1000},
                {"case_type": "solved", "cases": 100},
            ]
        },
        "encoding": {
            "x": {"field": "case_type", "type": "nominal"},
            "y": {"field": "cases", "type": "quantitative"},
        },
    }
    goal = "I want to visualize this huge gap between reported and solved cases beautifully."

    run = _run(
        SinglePersonaRegistry(persona),
        scatter_spec,
        ["bbc-2"],
        {"communication_goal": goal},
    )
    proposal = run.agents["bbc-2"].proposal
    change = _changes_by_rule(proposal)["a-chart-pie-gap"]

    assert change["status"] == "suggested"
    assert change["ops"] == []
    assert proposal["original_spec"]["mark"]["type"] == "point"
    assert proposal["modified_spec"]["mark"]["type"] == "point"


def test_bbc_pipeline(registry, example_spec):
    run = _run(registry, example_spec, ["bbc"])
    agent = run.agents["bbc"]
    assert agent.status == "done", agent.error
    p = agent.proposal
    spec2 = p["modified_spec"]
    ch = _changes_by_rule(p)

    # L2 快道：单序列 → BBC 蓝（去类别着色 + 主色直注）
    assert ch["a-color-single"]["status"] == "applied"
    # L1 快道：来源署名、左对齐、水平网格、尺寸
    assert ch["s-source"]["status"] == "applied"
    sub = spec2["title"]["subtitle"]
    sub_blob = " ".join(sub) if isinstance(sub, list) else str(sub)
    assert "Source:" in sub_blob
    assert spec2["title"]["anchor"] == "start"
    assert spec2["config"]["axisY"]["gridColor"] == "#cbcbcb"
    assert spec2["width"] == 640 and spec2["height"] == 450
    # 慢道裁决：强调目标 → 橙色高亮（条件着色，基色为 BBC 蓝）
    hl = ch["a-color-highlight"]
    assert hl["status"] == "applied" and hl["confidence"] == "medium"
    cond = spec2["encoding"]["color"]
    assert cond["condition"]["value"] == "#FAAB18"
    assert "C产品" in cond["condition"]["test"]
    assert cond["value"] == "#1380A1"
    # 驳回留痕（无担保不改）
    assert p["rejected"], "慢道应有驳回项留痕"
    # 四拍 trace 完整且快慢标注正确
    lanes = [t["lane"] for t in p["trace"]]
    assert lanes == ["slow", "fast", "slow", "fast"]
    # L1 不变量核验全部通过（含无障碍对比度在重着色后解除）
    acc = next(i for i in p["invariants"] if i["rule_id"] == "s-accessibility")
    assert acc["ok"] is True and acc.get("initially_violated") is True
    # 每处修改均有担保（标签 + 依据）
    for c in p["changes"]:
        assert c["label"] and c["reason"] and c["warrant"]["source_file"]


def test_economist_pipeline(registry, example_spec):
    run = _run(registry, example_spec, ["economist"])
    agent = run.agents["economist"]
    assert agent.status == "done", agent.error
    p = agent.proposal
    spec2 = p["modified_spec"]
    ch = _changes_by_rule(p)

    # L1：主色恒深蓝（去类别着色）；字号入音阶
    assert ch["s-palette-blues"]["status"] == "applied"
    assert "color" not in spec2["encoding"] or "condition" in spec2["encoding"]["color"]
    assert ch["s-type-scale"]["status"] == "applied"
    assert spec2["config"]["axis"]["labelFontSize"] == 11
    # 慢道：any-of 择"单一强色高亮"（品牌红），基色深蓝
    cond = spec2["encoding"]["color"]
    assert cond["condition"]["value"] == "#E3120B"
    assert cond["value"] == "#141F52"
    # L3 哲学推导：canvas 令牌 → 图底（derived，降置信）
    canvas = ch["d-canvas-bg"]
    assert canvas["confidence"] == "low" and canvas["warrant"]["derived"] is True
    assert spec2["background"] in ("#F5F4EF", "#EFF5F5")
    # 图型迁移类建议被驳回（数据范围/类别数不满足）
    rejected_ids = {r["rule_id"] for r in p["rejected"]}
    assert {"a-chart-bubble", "a-chart-thermometer"} <= rejected_ids


def test_parallel_run_isolated(registry, example_spec):
    run = _run(registry, example_spec, ["bbc", "economist"])
    assert run.status == "done"
    bbc_spec = run.agents["bbc"].proposal["modified_spec"]
    eco_spec = run.agents["economist"].proposal["modified_spec"]
    # 两机构各自成案且互不污染
    assert bbc_spec["encoding"]["color"]["value"] == "#1380A1"
    assert eco_spec["encoding"]["color"]["value"] == "#141F52"
    assert "background" not in bbc_spec
