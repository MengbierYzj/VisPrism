"""拍4执行层：真实 applied、同节点合并、用户锁。"""
from app.core.actions import apply_ops_with_effect
from app.core.beats import (
    _build_execution_plan,
    _merge_persona_by_conflict_key,
    beat4_compile,
)
from app.core.persona import Persona


def _bar_spec(**extra):
    spec = {
        "mark": "bar",
        "encoding": {
            "x": {"field": "a", "type": "nominal"},
            "y": {"field": "b", "type": "quantitative"},
        },
        "data": {"values": [{"a": "x", "b": 1}]},
    }
    spec.update(extra)
    return spec


def test_apply_ops_with_effect_detects_change():
    spec = _bar_spec()
    out, report = apply_ops_with_effect(
        spec, [{"action": "set_mark_color", "color": "#1380A1"}]
    )
    assert report.changed
    assert "set_mark_color" in report.applied_actions
    assert (out.get("mark") or {}).get("color") == "#1380A1" or (
        isinstance(out.get("mark"), dict) and out["mark"].get("fill") == "#1380A1"
    )


def test_apply_ops_with_effect_noop_empty_encoding_target():
    # 空组合视图：encoding 落点为 None → 静默 no-op
    spec = {"vconcat": []}
    _out, report = apply_ops_with_effect(
        spec, [{"action": "set_color_range", "colors": ["#111111", "#222222"]}]
    )
    assert not report.changed
    assert "set_color_range" in report.noop_actions


def test_merge_adopted_beats_candidate_color():
    cand = {
        "rule_id": "a-color-single",
        "strength": "should",
        "ops": [{"action": "set_mark_color", "color": "#1380A1"}],
    }
    adop = {
        "rule_id": "d-color-assignment",
        "strength": "should",
        "ops": [{"action": "set_color_range", "colors": ["#1", "#2", "#3"]}],
    }
    exec_items, superseded = _merge_persona_by_conflict_key([cand], [adop])
    assert len(exec_items) == 1
    assert exec_items[0]["rule_id"] == "d-color-assignment"
    assert any(s["rule_id"] == "a-color-single" for s in superseded)
    assert "更高优先级" in (superseded[0].get("rationale") or "")


def test_beat4_noop_is_suggested_not_applied(registry):
    persona: Persona = registry.get("bbc")
    # 空组合 → set_color_range 无落点
    spec = {"vconcat": []}
    candidates = [
        {
            "rule_id": "a-color-multi",
            "layer": "L2",
            "strength": "should",
            "src": [],
            "story_id": "",
            "ops": [{"action": "set_color_range", "colors": ["#1380A1", "#FAAB18"]}],
            "confidence": "medium",
        }
    ]
    modified, changes, _inv, trace = beat4_compile(
        persona, spec, {}, candidates, [], [], None
    )
    by_id = {c["rule_id"]: c for c in changes}
    assert by_id["a-color-multi"]["status"] == "suggested"
    assert "未能写入" in by_id["a-color-multi"]["reason"]
    assert modified == spec
    assert trace.get("noop_suggested") == 1


def test_beat4_real_write_is_applied(registry):
    persona: Persona = registry.get("bbc")
    spec = _bar_spec()
    candidates = [
        {
            "rule_id": "s-brand",
            "layer": "L1",
            "strength": "should",
            "src": [],
            "story_id": "",
            "ops": [{"action": "set_mark_color", "color": "#1380A1"}],
            "confidence": "high",
        }
    ]
    modified, changes, _inv, _tr = beat4_compile(
        persona, spec, {}, candidates, [], [], None
    )
    assert changes[0]["status"] == "applied"
    assert changes[0]["rule_id"] == "s-brand"
    mark = modified.get("mark")
    assert isinstance(mark, dict)
    assert mark.get("color") == "#1380A1" or mark.get("fill") == "#1380A1"


def test_beat4_candidate_superseded_by_adopted(registry):
    persona: Persona = registry.get("bbc")
    spec = _bar_spec(
        encoding={
            "x": {"field": "a", "type": "nominal"},
            "y": {"field": "b", "type": "quantitative"},
            "color": {"field": "a", "type": "nominal"},
        }
    )
    candidates = [
        {
            "rule_id": "a-color-single",
            "layer": "L2",
            "strength": "should",
            "src": [],
            "story_id": "",
            "ops": [{"action": "set_mark_color", "color": "#1380A1"}],
            "confidence": "medium",
        }
    ]
    adopted = [
        {
            "rule_id": "d-color-assignment",
            "layer": "L2-derived",
            "strength": "should",
            "src": [],
            "story_id": "",
            "ops": [{"action": "set_color_range", "colors": ["#1380A1", "#FAAB18", "#007f7f"]}],
            "confidence": "medium",
            "derived": True,
        }
    ]
    _mod, changes, _inv, _tr = beat4_compile(
        persona, spec, {}, candidates, adopted, [], None
    )
    by_id = {c["rule_id"]: c for c in changes}
    assert by_id["d-color-assignment"]["status"] == "applied"
    assert by_id["a-color-single"]["status"] == "suggested"
    assert "更高优先级" in by_id["a-color-single"]["reason"]


def test_build_execution_plan_user_locks_mark_type(registry):
    persona: Persona = registry.get("bbc")
    facts = {
        "user_constraint_items": [
            {
                "rule_id": "u-chart-bar",
                "layer": "user",
                "ops": [{"action": "set_mark_type", "mark_type": "bar"}],
                "suggested_only": False,
                "strength": "should",
                "src": [],
                "story_id": "",
            }
        ]
    }
    candidates = [
        {
            "rule_id": "a-chart-pie",
            "ops": [{"action": "set_mark_type", "mark_type": "arc", "chart_type": "pie"}],
            "suggested_only": False,
            "strength": "must",
            "layer": "L2",
            "src": [],
            "story_id": "",
        }
    ]
    executable, suggested, deferred = _build_execution_plan(
        persona, facts, candidates, []
    )
    assert any(i["rule_id"] == "u-chart-bar" for i in executable)
    assert any(d["rule_id"] == "a-chart-pie" for d in deferred)
    assert not any(i["rule_id"] == "a-chart-pie" for i in executable)
