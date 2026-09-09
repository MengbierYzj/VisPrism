"""Composer 冲突检测与消解。"""
import asyncio

from app.core.composer import apply_design, resolve_change_conflicts
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
