"""拍3.5 机构口吻文案：慢道撰写 + 快道核验（数字接地/长度/大小写/回落）。"""
import asyncio
import json

from app.core.beats import _live_adjudicate
from app.core.copywriter import apply_title_copywriter, validate_and_normalize


FACTS = {
    "title_text": "Sales by product",
    "subtitle": None,
    "mark_type": "bar",
    "category_field": "product",
    "value_field": "sales",
    "categories": ["Product A", "Product B", "Product C"],
    "max_category": {"name": "Product C", "value": 162},
    "min_category": {"name": "Product A", "value": 54},
    "series_count": 1,
    "chart_slice": {
        "rows": [
            {"product": "Product A", "sales": 54},
            {"product": "Product B", "sales": 98},
            {"product": "Product C", "sales": 162},
        ]
    },
}


class CopyLLM:
    """按 payload 路由的 live stub：items→裁决，title_copy→文案。"""

    mode = "live"

    def __init__(self, copy_payload):
        self.copy_payload = copy_payload
        self.copy_calls = []

    async def chat_json(self, system, user, **kwargs):
        payload = json.loads(user)
        if payload.get("task") == "title_copy":
            self.copy_calls.append((system, payload))
            return self.copy_payload
        if "items" in payload:
            return {
                "verdicts": [
                    {
                        "id": item["id"],
                        "verdict": "adopt",
                        "rationale": "title should state the takeaway",
                        "confidence": "high",
                    }
                    for item in payload["items"]
                ]
            }
        return {}


def _title_item(rule_id="s-title-descriptive", ops=None):
    return {
        "layer": "L1",
        "rule_id": rule_id,
        "rule_text": "Title states the takeaway",
        "strength": "should",
        "story_id": "",
        "src": ["L61"],
        "derived": False,
        "ops": ops if ops is not None else [
            {"action": "set_title_text", "text": "Product C leads (162)"}
        ],
        "confidence": "medium",
        "rationale": "adopted",
        "suggested_only": False,
        "detail": "adopted",
    }


def _escalation(rule_id="s-title-descriptive"):
    return {
        "layer": "L1",
        "rule_id": rule_id,
        "rule_text": "Title states the takeaway; subtitle adds context",
        "strength": "should",
        "story_id": "",
        "src": ["L61"],
        "why": "check: llm",
        "when": {},
        "compiled": {"ops": [], "needs": [], "any_of": None},
    }


# ---------------------------------------------------------------------------
# 验证器
# ---------------------------------------------------------------------------

def test_validator_accepts_grounded_takeaway_copy():
    out = validate_and_normalize(
        {
            "title": "Product C is the clear winner",
            "subtitle": "Quarterly sales, all regions",
            "rationale": "Takeaway first.",
        },
        FACTS,
        {"s-title-descriptive"},
    )
    assert out and out["title"] == "Product C is the clear winner"
    assert out["subtitle"] == "Quarterly sales, all regions"


def test_validator_rejects_fabricated_numbers():
    assert (
        validate_and_normalize(
            {"title": "Product C wins with 87% share"}, FACTS, {"s-title-descriptive"}
        )
        is None
    )
    # 事实池内的数字（含四舍五入容差）可以通过
    out = validate_and_normalize(
        {"title": "Product C tops the chart at 162"}, FACTS, {"s-title-descriptive"}
    )
    assert out and "162" in out["title"]


def test_validator_enforces_brief_cap_and_restores_casing():
    assert (
        validate_and_normalize(
            {"title": "Total quarterly sales overview for all products"},
            FACTS,
            {"s-title-brief"},
        )
        is None
    )
    out = validate_and_normalize(
        {"title": "product c is the Clear Winner"}, FACTS, {"s-title-case"}
    )
    assert out and out["title"].startswith("Product C ")


def test_validator_drops_subtitle_restating_title_and_noop_copy():
    out = validate_and_normalize(
        {"title": "Product C is the clear winner", "subtitle": "Product C is the clear winner"},
        FACTS,
        {"s-title-descriptive"},
    )
    assert out and out["subtitle"] is None
    # 与原标题相同且无副标题 → 无实质变化
    assert (
        validate_and_normalize({"title": "Sales by product"}, FACTS, {"s-title-descriptive"})
        is None
    )


# ---------------------------------------------------------------------------
# apply_title_copywriter
# ---------------------------------------------------------------------------

def test_copywriter_replaces_deterministic_ops_and_adds_subtitle(registry):
    persona = registry.get("bbc")
    llm = CopyLLM(
        {
            "title": "Product C is the clear winner",
            "subtitle": "Quarterly sales by product",
            "rationale": "States the takeaway per the guide.",
        }
    )
    # descriptive 带确定性模板 ops；case 条目为空 ops（真实流程中的 suggested-only 形态）
    adopted = [_title_item(), _title_item(rule_id="s-title-case", ops=[])]
    out = asyncio.run(apply_title_copywriter(persona, dict(FACTS), adopted, llm))
    t0 = {op["action"]: op for op in out[0]["ops"]}
    t1 = {op["action"]: op for op in out[1]["ops"]}
    # 两个标题条目写同一标题/副标题（幂等）：拍4按 strength 合并后胜者必携带完整文案
    assert t0["set_title_text"]["text"] == "Product C is the clear winner"
    assert t1["set_title_text"]["text"] == "Product C is the clear winner"
    assert t0["set_subtitle"]["text"] == t1["set_subtitle"]["text"] == "Quarterly sales by product"
    assert out[0]["suggested_only"] is False and out[1]["suggested_only"] is False
    assert "fast lane verified" in out[0]["rationale"]


def test_copywriter_mock_mode_is_noop():
    class MockLLM:
        mode = "mock"

        async def chat_json(self, *a, **k):
            raise AssertionError("mock 模式不得发起文案调用")

    adopted = [_title_item()]
    before = json.dumps(adopted, sort_keys=True)
    out = asyncio.run(apply_title_copywriter(object(), dict(FACTS), adopted, MockLLM()))
    assert json.dumps(out, sort_keys=True) == before


def test_live_adjudicate_applies_verified_copy(registry, example_spec):
    persona = registry.get("bbc")
    llm = CopyLLM(
        {
            "title": "Product C is the clear winner",
            "subtitle": "Quarterly sales by product",
            "rationale": "Takeaway-first title per the guide.",
        }
    )
    adopted, rejected = asyncio.run(
        _live_adjudicate(persona, example_spec, dict(FACTS), [_escalation()], llm)
    )
    assert not rejected
    assert len(adopted) == 1 and len(llm.copy_calls) == 1
    ops = {op["action"]: op for op in adopted[0]["ops"]}
    assert ops["set_title_text"]["text"] == "Product C is the clear winner"
    assert ops["set_subtitle"]["text"] == "Quarterly sales by product"
    assert ops["set_subtitle"]["preserve_source"] is True
    assert adopted[0]["suggested_only"] is False
    # 提示词携带规则原文与图表事实
    system, payload = llm.copy_calls[0]
    assert "Title states the takeaway" in system
    assert payload["chart_facts"]["max_category"]["name"] == "Product C"


def test_live_adjudicate_falls_back_when_copy_ungrounded(registry, example_spec):
    persona = registry.get("bbc")
    llm = CopyLLM({"title": "Product C wins with 87% share"})
    adopted, rejected = asyncio.run(
        _live_adjudicate(persona, example_spec, dict(FACTS), [_escalation()], llm)
    )
    assert not rejected and len(adopted) == 1
    # 编造数字被验证器拦下 → 回落确定性改写（对该 facts 会给出要点式标题）
    actions = [op["action"] for op in adopted[0]["ops"]]
    texts = [op.get("text", "") for op in adopted[0]["ops"]]
    assert "87" not in " ".join(texts)
    assert adopted[0]["suggested_only"] is (not actions)
