"""多模态 L3 视觉审图：图片规范化、接地 ops、拍3 跳过路径。"""
from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

from app.core.runner import make_context
from app.core.visual_review import (
    _finding_to_adopted,
    _ground_actions,
    annotation_text_baseline,
    normalize_preview_image,
    run_visual_review,
    strategy_escalations_from_findings,
)
from app.llm import LLMClient


def _tiny_png_data_url() -> str:
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def test_normalize_preview_image_data_url():
    url = _tiny_png_data_url()
    assert normalize_preview_image(url) == url


def test_normalize_preview_image_rejects_junk():
    assert normalize_preview_image("not-an-image") is None
    assert normalize_preview_image(123) is None


def test_annotation_text_baseline_keeps_static_text_only():
    spec = {
        "layer": [
            {"mark": {"type": "text", "text": "10 year average"}},
            {"mark": {"type": "text"}, "encoding": {"text": {"field": "year"}}},
            {"layer": [{"mark": {"type": "text", "text": "Callout"}}]},
        ]
    }
    assert annotation_text_baseline(spec) == ["10 year average", "Callout"]


def test_make_context_keeps_preview_image():
    url = _tiny_png_data_url()
    ctx = make_context({"communication_goal": "hi", "preview_image": url})
    assert ctx["communication_goal"] == "hi"
    assert ctx["preview_image"].startswith("data:image/png;base64,")


def test_ground_increase_padding(registry):
    persona = registry.get("bbc")
    ops, suggested, _soft = _ground_actions(persona, {"height": 400}, ["increase_padding"])
    assert any(o.get("action") == "merge_config" for o in ops)
    assert suggested is False


def test_finding_shorten_labels_grounds_remove_ops(registry):
    """无密轴事实时 shorten_labels 仍回退 remove_value_labels（柱上数字路径）。"""
    persona = registry.get("bbc")
    item = _finding_to_adopted(
        persona,
        {"height": 400, "has_value_labels": True},
        {
            "issue": "mark_label_overlap",
            "verdict": "adopt",
            "severity": "high",
            "preferred_actions": ["increase_height", "shorten_labels"],
            "rationale": "labels collide",
            "l3_refs": ["Clarity"],
        },
    )
    assert item is not None
    assert item["rule_id"] == "v-overlap"
    # 可执行 op 与 soft 拆开：有 set_size / remove_value_labels 则应可落地
    assert item["suggested_only"] is False
    actions = {o.get("action") for o in item["ops"]}
    assert "set_size" in actions
    assert "remove_value_labels" in actions
    assert "thin_axis_labels" not in actions
    assert item["derived"] is True
    assert item["confidence"] == "medium"


def test_finding_overlap_dense_axis_grounds_thin_not_remove(registry):
    """密轴（如 COVID 周日期轴）重叠 → thin_axis_labels，勿误删数值层。"""
    persona = registry.get("economist")
    item = _finding_to_adopted(
        persona,
        {
            "height": 450,
            "width": 800,
            "axis_x_dense": True,
            "axis_x_tick_count": 12,
            "has_value_labels": False,
        },
        {
            "issue": "mark_label_overlap",
            "verdict": "adopt",
            "severity": "medium",
            "preferred_actions": ["shorten_labels"],
            "rationale": "x-axis date labels overlap",
        },
    )
    assert item is not None
    actions = {o.get("action") for o in item["ops"]}
    assert "thin_axis_labels" in actions
    assert "remove_value_labels" not in actions


def test_finding_overlap_defaults_to_thin_when_dense(registry):
    """重叠类未给 preferred_actions 时，按 denseness 默认补 thin。"""
    persona = registry.get("bbc")
    item = _finding_to_adopted(
        persona,
        {"axis_x_dense": True, "has_value_labels": False},
        {
            "issue": "mark_label_overlap",
            "verdict": "adopt",
            "preferred_actions": [],
            "rationale": "crowded ticks",
        },
    )
    assert item is not None
    actions = {o.get("action") for o in item["ops"]}
    assert "thin_axis_labels" in actions
    assert "remove_value_labels" not in actions


def test_recolor_uniform_skipped_when_semantic_multicolor(registry):
    persona = registry.get("bbc")
    ops, suggested, soft = _ground_actions(
        persona,
        {"colors_effective": ["#f7d570", "#d46c31"], "coloring_mode": "uniform"},
        ["recolor_uniform"],
    )
    assert ops == []
    assert suggested is True
    assert any("skipped_semantic" in s for s in soft)


def test_recolor_paired_literal_grounds_set_mark_color(registry):
    """视觉成对色差 + 字面双色：接地为 set_mark_color(+accent)，非 set_color_range。"""
    persona = registry.get("economist")
    facts = {
        "literal_color_encoding": True,
        "accent_color": "#d46c31",
        "colors_effective": ["#f7d570"],
        "category_field": "year",
        "color_field": None,
        "coloring_mode": "highlight",
    }
    ops, suggested, _soft = _ground_actions(persona, facts, ["recolor_paired"])
    assert suggested is False
    assert any(
        o.get("action") == "set_mark_color" and o.get("accent_color") for o in ops
    )
    assert not any(o.get("action") == "set_color_range" for o in ops)

    item = _finding_to_adopted(
        persona,
        facts,
        {
            "issue": "color_similarity",
            "verdict": "adopt",
            "confidence": "medium",
            "preferred_actions": ["recolor_paired"],
            "rationale": "highlight hue off-palette",
        },
    )
    assert item is not None
    assert item["rule_id"] == "v-color-similarity"
    assert item["suggested_only"] is False
    assert any(
        o.get("action") == "set_mark_color" and o.get("accent_color")
        for o in item["ops"]
    )


def test_run_visual_review_skips_when_mock(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_VISION_MODE", "auto")
    monkeypatch.setenv("VIZGUIDE_LLM_MODE", "mock")

    class FakePersona:
        id = "bbc"
        name = "BBC"
        philosophy = []
        stories = []

        def philosophy_text(self):
            return ""

    async def _run():
        adopted, rejected, meta = await run_visual_review(
            FakePersona(),
            {"data": {"values": [{"a": 1}]}, "mark": "point"},
            {},
            LLMClient(),
        )
        assert adopted == []
        assert meta.get("skipped") == "llm_not_live"

    asyncio.run(_run())


def test_layout_is_recorded_but_not_directly_applied_when_vision_skipped(monkeypatch):
    """视觉模块只记录结构问题；不得绕过 persona 策略直接落地。"""
    monkeypatch.setenv("VIZGUIDE_VISION_MODE", "auto")
    monkeypatch.setenv("VIZGUIDE_LLM_MODE", "mock")

    class FakePersona:
        id = "bbc"
        name = "BBC"
        philosophy = []
        stories = []

        def philosophy_text(self):
            return ""

    spec = {
        "data": {"values": [{"a": 1, "b": 2}]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "a", "type": "ordinal"},
            "y": {
                "field": "b",
                "type": "quantitative",
                "axis": {"title": "Y", "titleAngle": 0},
            },
        },
    }

    async def _run():
        adopted, rejected, meta = await run_visual_review(
            FakePersona(), spec, {}, LLMClient()
        )
        assert meta.get("skipped") == "llm_not_live"
        assert adopted == []
        assert "orphaned_horizontal_y_title" in (meta.get("layout_flags") or [])

    asyncio.run(_run())


def test_run_visual_review_uses_server_render(registry, monkeypatch):
    monkeypatch.setenv("VIZGUIDE_LLM_MODE", "live")
    monkeypatch.setenv("VIZGUIDE_VISION_MODE", "auto")
    monkeypatch.setenv("VIZGUIDE_VISION_SERVER_RENDER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class VisionLLM(LLMClient):
        mode = "live"

        def __init__(self):
            super().__init__()
            self.images = []

        async def chat_json_vision(self, system, user_text, image_data_url, **kwargs):
            self.images.append(image_data_url)
            return {"findings": []}

    persona = registry.get("bbc")
    spec = {
        "data": {"values": [{"a": "A", "b": 10}, {"a": "B", "b": 20}]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "a", "type": "nominal"},
            "y": {"field": "b", "type": "quantitative"},
        },
    }
    llm = VisionLLM()

    async def _run():
        adopted, rejected, meta = await run_visual_review(persona, spec, {}, llm)
        assert meta.get("ran") is True
        assert meta.get("image_source") == "server_render"
        assert llm.images and llm.images[0].startswith("data:image/png;base64,")

    asyncio.run(_run())


def test_chat_json_vision_message_shape(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_LLM_MODE", "live")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content='{"findings":[]}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            pass

    llm = LLMClient()
    llm._client = FakeClient()
    url = _tiny_png_data_url()

    result = asyncio.run(
        llm.chat_json_vision("sys", "look", url, detail="low", retries=0)
    )
    assert result == {"findings": []}
    content = captured["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png")


def test_visual_review_live_returns_evidence_then_persona_strategy_grounds_it(registry, monkeypatch):
    monkeypatch.setenv("VIZGUIDE_LLM_MODE", "live")
    monkeypatch.setenv("VIZGUIDE_VISION_MODE", "auto")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class VisionLLM(LLMClient):
        mode = "live"

        async def chat_json_vision(self, system, user_text, image_data_url, **kwargs):
            return {
                "findings": [
                    {
                        "issue": "whitespace",
                        "severity": "tight margins",
                        "l3_refs": ["Less is more"],
                        "severity": "medium",
                        "verdict": "adopt",
                        "preferred_actions": ["increase_padding"],
                        "rationale": "Need more whitespace",
                    }
                ]
            }

    persona = registry.get("bbc")
    facts = {"preview_image": _tiny_png_data_url(), "height": 400, "chart_slice": {}}

    async def _run():
        adopted, rejected, meta = await run_visual_review(
            persona, {"mark": "bar"}, facts, VisionLLM()
        )
        assert meta.get("ran") is True
        assert adopted == []
        assert meta["findings"][0]["issue"] == "whitespace"
        # 原始 BBC 无手工 visual strategy；不能回退到共享 v-whitespace。
        assert strategy_escalations_from_findings(persona, facts, meta) == []

    asyncio.run(_run())
