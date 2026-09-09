"""Composer 冲突检测与消解。"""
import asyncio
import json

from app.core.composer import apply_design, resolve_change_conflicts
from app.core.semantic_composer import compose_component_slots
from app.llm import LLMClient


def _mark_color_change(persona: str, rule: str, color: str) -> dict:
    return {
        "id": f"{persona}:{rule}",
        "rule_id": rule,
        "label": f"{persona} color",
        "ops": [{"action": "set_mark_color", "color": color}],
    }


def _bg_change(persona: str, rule: str, color: str) -> dict:
    return {
        "id": f"{persona}:{rule}",
        "rule_id": rule,
        "label": f"{persona} bg",
        "ops": [{"action": "set_background", "color": color}],
    }


def test_compose_component_effects_are_path_level():
    from app.core.actions import describe_op
    from app.core.composer import _op_effects

    op = {
        "action": "compose_component",
        "component": "color",
        "spec_paths": ["/vconcat/0/layer/0/encoding/color"],
        "candidate_spec": {"mark": {"color": "#1380A1"}},
    }
    effects = _op_effects(op)
    assert effects[0][0] == "spec.vconcat.0.layer.0.encoding.color"
    assert "compose_component" not in effects[0][0]
    assert "color" in describe_op(op)
    assert describe_op(op) != "compose_component"


def test_no_conflict_different_nodes():
    changes = [
        _mark_color_change("bbc", "a-color-single", "#1380A1"),
        _bg_change("economist", "d-canvas-bg", "#F5F4EF"),
    ]
    resolved, conflicts = resolve_change_conflicts(changes)
    assert conflicts == []
    assert all(ch.get("ops") for ch in resolved)


def test_semantic_component_composer_executes_declared_path_removal():
    source = {
        "mark": "line",
        "encoding": {"x": {"field": "Date"}, "y": {"field": "Price"}, "strokeDash": {"field": "basis"}},
    }
    candidate = {"mark": "line", "encoding": {"x": {"field": "Date"}, "y": {"field": "Price"}}}
    final, applied, conflicts, notes = compose_component_slots(source, [{
        "id": "bbc:v2:line-style",
        "component": "color",
        "candidate_spec": candidate,
        "spec_paths": [],
        "removed_paths": ["/encoding/strokeDash"],
    }])
    assert "strokeDash" not in final["encoding"]
    assert applied == ["bbc:v2:line-style"]
    assert conflicts == []
    assert notes == []


def test_conflict_winner_by_more_adoptions():
    changes = [
        _mark_color_change("bbc", "a-color-single", "#1380A1"),
        _mark_color_change("bbc", "a-color-two", "#1380A1"),
        _mark_color_change("bbc", "a-color-multi", "#1380A1"),
        _mark_color_change("economist", "s-palette-blues", "#141F52"),
        _mark_color_change("economist", "a-emphasis", "#E3120B"),
    ]
    resolved, conflicts = resolve_change_conflicts(changes)
    assert len(conflicts) >= 1
    assert conflicts[0]["winner_persona_id"] == "bbc"
    assert conflicts[0]["loser_persona_id"] == "economist"
    assert conflicts[0]["node"] == "mark.color"
    eco_resolved = [c for c in resolved if c["id"].startswith("economist:")]
    assert all(not c.get("ops") for c in eco_resolved)


def test_compose_component_borrows_slots_from_two_institutions():
    spec = {
        "title": {"text": "Waste", "color": "#2d2e2d"},
        "mark": {"type": "bar", "color": "#168c96"},
        "encoding": {"x": {"field": "a"}, "y": {"field": "b"}},
    }
    bbc = {
        **spec,
        "mark": {"type": "bar", "color": "#1380A1"},
    }
    eco = {
        **spec,
        "title": {"text": "The US leads", "color": "#141F52"},
    }
    changes = [
        {
            "id": "bbc:v2:color",
            "label": "Color and emphasis",
            "component_detail": {"spec_paths": ["/mark/color"]},
            "ops": [{"action": "compose_component", "component": "color", "candidate_spec": bbc, "spec_paths": ["/mark/color"]}],
        },
        {
            "id": "economist:v2:title",
            "label": "Title and narrative",
            "component_detail": {"spec_paths": ["/title/text", "/title/color"]},
            "ops": [{"action": "compose_component", "component": "title", "candidate_spec": eco, "spec_paths": ["/title/text", "/title/color"]}],
        },
    ]
    result = asyncio.run(apply_design(spec, changes, "", LLMClient()))
    assert result["final_spec"]["mark"]["color"] == "#1380A1"
    assert result["final_spec"]["title"]["text"] == "The US leads"
    assert result["final_spec"]["title"]["color"] == "#141F52"
    assert set(result["applied"]) == {"bbc:v2:color", "economist:v2:title"}
    assert result["skipped"] == []


def test_conflict_apply_uses_winner_color():
    spec = {"mark": "bar", "encoding": {"x": {"field": "a"}, "y": {"field": "b"}}}
    changes = [
        _mark_color_change("bbc", "a1", "#1380A1"),
        _mark_color_change("bbc", "a2", "#1380A1"),
        _mark_color_change("economist", "e1", "#141F52"),
    ]
    result = asyncio.run(apply_design(spec, changes, "", LLMClient()))
    assert result["conflicts"]
    assert result["final_spec"]["mark"]["color"] == "#1380A1"
    assert "economist:e1" in [s["id"] for s in result["skipped"]]


class _LiveComposerLLM:
    mode = "live"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat_json(self, system, user):
        self.calls.append((system, json.loads(user)))
        return self.responses.pop(0)


def _v2_change(cid: str, scope: str, candidate: dict, paths: list[str]) -> dict:
    return {
        "id": cid,
        "scope": scope,
        "label": scope.title(),
        "reason": f"Apply {scope}",
        "component_detail": {"before": "old", "after": "new", "spec_paths": paths},
        "contract": {"verified": True, "source": "programmatic_diff_inventory", "scope": scope, "actual_paths": paths},
        "ops": [{"action": "compose_component", "component": scope, "candidate_spec": candidate, "spec_paths": paths}],
    }


def test_live_v2_composer_reconstructs_full_spec_without_free_text(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_VISION_MODE", "off")
    source = {
        "data": {"values": [{"a": "A", "v": 1}, {"a": "B", "v": 2}]},
        "mark": "bar",
        "encoding": {"x": {"field": "a", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}},
    }
    bbc = {**source, "mark": {"type": "bar", "color": "#1380A1"}}
    change = _v2_change("bbc:v2:color", "color", bbc, ["/mark/color"])
    response = {
        "final_spec": {
            "data": {"$ref": "__vizguide_primary_data__"},
            "mark": {"type": "bar", "color": "#1380A1"},
            "encoding": source["encoding"],
        },
        "implementation": [{"change_id": change["id"], "realized_paths": ["/mark/color"], "note": "BBC blue"}],
        "conflicts": [],
    }
    llm = _LiveComposerLLM([response])

    result = asyncio.run(apply_design(source, [change], "", llm, {"communication_goal": "Compare A and B"}))

    assert len(llm.calls) == 1
    assert llm.calls[0][1]["communication_goal"] == "Compare A and B"
    assert result["composition"]["mode"] == "llm_reconstruction"
    assert result["final_spec"]["data"] == source["data"]
    assert result["final_spec"]["mark"]["color"] == "#1380A1"
    assert result["applied"] == [change["id"]]


def test_unverified_change_is_blocked_before_composition():
    source = {"mark": "bar", "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    candidate = {**source, "background": "#111111"}
    change = _v2_change("bbc:v2:unverified", "color", candidate, ["/background"])
    change["contract"]["verified"] = False
    llm = _LiveComposerLLM([])

    result = asyncio.run(apply_design(source, [change], "", llm))

    assert llm.calls == []
    assert result["final_spec"] == source
    assert result["applied"] == []
    assert result["skipped"] == [{
        "id": change["id"],
        "reason": "Advisor change failed source-to-candidate contract verification and cannot be composed",
    }]


def test_live_v2_composer_repairs_missing_decision_implementation(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_VISION_MODE", "off")
    source = {
        "data": {"values": [{"a": "A", "v": 1}]},
        "mark": "bar",
        "encoding": {"x": {"field": "a", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}},
    }
    candidate = {**source, "background": "#111111"}
    change = _v2_change("economist:v2:color", "color", candidate, ["/background"])
    draft = {
        "final_spec": {"data": {"$ref": "__vizguide_primary_data__"}, "mark": "bar", "encoding": source["encoding"], "background": "#111111"},
        "implementation": [],
        "conflicts": [],
    }
    repaired = {
        **draft,
        "implementation": [{"change_id": change["id"], "realized_paths": ["/background"]}],
    }
    llm = _LiveComposerLLM([draft, repaired])

    result = asyncio.run(apply_design(source, [change], "", llm))

    assert len(llm.calls) == 2
    assert "validation_errors" in llm.calls[1][1]
    assert result["composition"]["mode"] == "llm_reconstruction"
    assert result["applied"] == [change["id"]]


def test_live_v2_composer_falls_back_when_repair_is_not_verifiable(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_VISION_MODE", "off")
    source = {"mark": "bar", "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    candidate = {**source, "background": "#111111"}
    change = _v2_change("economist:v2:color", "color", candidate, ["/background"])
    bad = {"final_spec": {"mark": "bar"}, "implementation": [], "conflicts": []}
    llm = _LiveComposerLLM([bad, bad])

    result = asyncio.run(apply_design(source, [change], "", llm))

    assert result["composition"]["mode"] == "deterministic_fallback"
    assert result["final_spec"]["background"] == "#111111"
    assert any("回退确定性组合" in note for note in result["notes"])
