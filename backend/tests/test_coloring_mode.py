"""配色模式：拍1 立意 + 拍2/3 原则裁决，避免组成图整饼同色。"""
from app.core.actions import compile_then
from app.core.beats import (
    beat2_detect,
    infer_coloring_mode,
    _coloring_mode_satisfied,
    _mock_adjudicate,
    _mock_read,
    _ops_for_coloring_mode,
    _palette_colors,
    _promote_emphasis_color_rules,
)
from app.core.detectors import det_palette_blues
from app.core.persona import Persona


def _pie_facts(**extra):
    base = {
        "mark_type": "arc",
        "category_field": "case_type",
        "value_field": "cases",
        "category_count": 4,
        "categories": ["A", "B", "C", "D"],
        "series_count": 1,
        "color_field": "case_type",
        "per_category_coloring": True,
        "color_count": 4,
        "title_text": "Share of cases",
    }
    base.update(extra)
    return base


def test_infer_composition_is_categorical():
    assert infer_coloring_mode(_pie_facts(), intent="composition") == "categorical"


def test_infer_comparison_bar_rainbow_is_uniform():
    facts = {
        "mark_type": "bar",
        "series_count": 1,
        "category_count": 5,
        "color_field": "product",
        "per_category_coloring": True,
    }
    assert infer_coloring_mode(facts, intent="comparison") == "uniform"


def test_infer_literal_accent_is_highlight():
    facts = {
        "mark_type": "bar",
        "series_count": 1,
        "literal_color_encoding": True,
        "accent_color": "#d46c31",
        "colors_effective": ["#f7d570"],
        "color_count": 2,
    }
    assert infer_coloring_mode(facts, intent="comparison") == "highlight"


def test_ops_for_highlight_keeps_accent(registry):
    persona = registry.get("bbc")
    facts = {
        "literal_color_encoding": True,
        "accent_color": "#d46c31",
        "colors_effective": ["#f7d570"],
    }
    ops = _ops_for_coloring_mode(persona, facts, "highlight")
    assert ops and ops[0]["action"] == "set_mark_color"
    assert ops[0].get("accent_color")
    assert ops[0]["accent_color"] != ops[0]["color"]


def test_ops_paired_literal_not_color_range(registry):
    """字面双色 + category_field（如 year）时 paired 不得写无效的 set_color_range。"""
    persona = registry.get("economist")
    facts = {
        "literal_color_encoding": True,
        "accent_color": "#d46c31",
        "colors_effective": ["#f7d570"],
        "category_field": "year",
        "category_count": 38,
        "color_field": None,
        "coloring_mode": "highlight",
    }
    for mode in ("paired", "categorical", "uniform", "highlight"):
        ops = _ops_for_coloring_mode(persona, facts, mode)
        assert ops, mode
        assert ops[0]["action"] == "set_mark_color", mode
        assert ops[0].get("accent_color"), mode
        assert not any(o.get("action") == "set_color_range" for o in ops)


def test_mock_read_arc_sets_categorical():
    sem = _mock_read({}, _pie_facts())
    assert sem["intent"] == "composition"
    assert sem["coloring_mode"] == "categorical"


def test_pie_color_single_escalates_and_adopts_palette(registry):
    persona: Persona = registry.get("bbc")
    facts = {**_pie_facts(), **_mock_read({}, _pie_facts())}
    assert facts["coloring_mode"] == "categorical"

    _cands, escalations, *_rest = beat2_detect(persona, {"mark": "arc"}, facts)
    color_esc = [e for e in escalations if e["rule_id"] == "a-color-single"]
    assert color_esc, "组成图单序列配色应升级慢道而非直接收成单色"
    alts = (color_esc[0].get("compiled") or {}).get("color_alternatives") or []
    assert any(a.get("id") == "categorical" for a in alts)

    adopted, _rejected = _mock_adjudicate(persona, facts, color_esc)
    assert adopted
    ops = adopted[0]["ops"]
    assert any(o.get("action") == "set_color_range" for o in ops)
    assert not any(
        o.get("action") == "remove_encoding_channel" and o.get("channel") == "color"
        for o in ops
    )
    colors = next(o["colors"] for o in ops if o.get("action") == "set_color_range")
    assert len(colors) >= 3
    assert len(set(colors)) >= 3


def test_compile_then_mark_color_keeps_channel_in_categorical(registry):
    persona = registry.get("bbc")
    facts = {**_pie_facts(), "coloring_mode": "categorical"}
    out = compile_then(persona, {"set": "mark.color", "to": "{color.bbc-blue}"}, facts)
    assert not any(
        o.get("action") == "remove_encoding_channel" for o in out["ops"]
    )


def test_in_palette_wrong_order_not_satisfied(registry):
    """颜色都在色板内但未按指南序列 → 原则未落实。"""
    persona = registry.get("economist")
    palette = _palette_colors(persona)
    assert len(palette) >= 4
    shuffled = [palette[2], palette[0], palette[3], palette[1]]
    facts = _pie_facts(
        coloring_mode="categorical",
        colors_effective=shuffled,
        intent="composition",
    )
    assert not _coloring_mode_satisfied(persona, facts, "categorical")
    ops = _ops_for_coloring_mode(persona, facts, "categorical")
    assert any(o.get("action") == "set_color_range" for o in ops)
    assert ops[0]["colors"][:4] == palette[:4]


def test_uniform_rainbow_in_palette_not_satisfied(registry):
    persona = registry.get("economist")
    palette = _palette_colors(persona)
    facts = {
        "mark_type": "bar",
        "series_count": 1,
        "category_count": 4,
        "color_field": "product",
        "per_category_coloring": True,
        "color_count": 4,
        "coloring_mode": "uniform",
        "colors_effective": palette[:4],
    }
    assert not _coloring_mode_satisfied(persona, facts, "uniform")


def test_palette_blues_flags_assignment_gap(registry):
    """主色已在 chicago 内，但组成图未按序列分配 → L1 仍违规。"""
    persona = registry.get("economist")
    chicago = persona.resolve_color("chicago-20")
    palette = _palette_colors(persona)
    colors = [chicago, palette[-1], palette[-2], palette[-3]]
    facts = _pie_facts(
        coloring_mode="categorical",
        colors_effective=colors,
        intent="composition",
    )
    det = det_palette_blues(persona, {"mark": "arc"}, facts)
    assert det.violated
    assert any(o.get("action") == "set_color_range" for o in det.ops)


def test_beat2_applies_or_escalates_color_principles(registry):
    """无「仅成员检查放行」：原则缺口须产生候选或带备选的升级。"""
    persona = registry.get("economist")
    palette = _palette_colors(persona)
    facts = {
        **_pie_facts(
            coloring_mode="categorical",
            colors_effective=[palette[3], palette[2], palette[1], palette[0]],
            intent="composition",
        ),
        "summary": "composition share",
        "data_topic": "general",
    }
    cands, escalations, *_ = beat2_detect(persona, {"mark": "arc"}, facts)
    color_fix = [
        c
        for c in cands
        if any(
            isinstance(o, dict) and o.get("action") in ("set_color_range", "set_mark_color")
            for o in (c.get("ops") or [])
        )
    ]
    color_esc = [
        e
        for e in escalations
        if (e.get("compiled") or {}).get("color_alternatives")
        or e.get("rule_id") == "d-color-assignment"
    ]
    assert color_fix or color_esc, "应出现配色原则修复（候选或慢道升级）"
    if color_esc and not color_fix:
        adopted, _ = _mock_adjudicate(persona, facts, color_esc)
        assert adopted
        assert any(o.get("action") == "set_color_range" for o in adopted[0]["ops"])


def test_promote_emphasis_overrides_reject_and_empty_suggest(registry):
    """字面双色已有强调时，a-emphasis 驳回/空建议 → 强制落地 set_mark_color。"""
    persona = registry.get("economist")
    facts = {
        "literal_color_encoding": True,
        "accent_color": "#d46c31",
        "colors_effective": ["#f7d570"],
        "emphasis_target": 2025,
        "emphasis_field": "year",
        "emphasis_mechanism": "literal_condition",
        "coloring_mode": "highlight",
    }
    esc = {
        "layer": "L2",
        "rule_id": "a-emphasis",
        "rule_text": "突出关键信息",
        "strength": "should",
        "story_id": "n-emphasis",
        "src": ["L140"],
        "why": "test",
        "compiled": {"ops": [], "needs": [], "any_of": ["文字加粗", "单一强色高亮"]},
    }
    adopted, rejected = _promote_emphasis_color_rules(
        persona,
        facts,
        [esc],
        [{"rule_id": "a-emphasis", "ops": [], "suggested_only": True, "rationale": "empty"}],
        [{"rule_id": "a-emphasis", "reason": "llm reject"}],
    )
    # 空建议被补全；驳回项不再保留同 id
    assert any(
        a.get("rule_id") == "a-emphasis"
        and not a.get("suggested_only")
        and any(o.get("action") == "set_mark_color" and o.get("accent_color") for o in a.get("ops") or [])
        for a in adopted
    )
    assert not any(r.get("rule_id") == "a-emphasis" for r in rejected)
