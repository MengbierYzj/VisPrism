"""布局执行端：新 ops、compile_then 布局词汇、style_pass 风格化与 persona 布局候选。

对应问题：提案只动颜色/标题，布局知识编进 persona 后无法落地成 ops。
"""
import asyncio
import copy

import pytest

from app.core.actions import apply_ops, compile_then
from app.core.style_pass import MOVES, available_moves, validate_moves


def bar_spec(**enc_extra) -> dict:
    spec = {
        "title": "Sales by product",
        "data": {"values": [{"p": "A", "v": 10}, {"p": "B", "v": 40}, {"p": "C", "v": 25}]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "p", "type": "nominal", "axis": {"labelAngle": -45}},
            "y": {"field": "v", "type": "quantitative"},
        },
    }
    spec["encoding"].update(enc_extra)
    return spec


class StubPersona:
    name = "Stub"
    philosophy: list = []

    def resolve_color(self, key):
        return "#e0e0e0" if key == "grid" else None


FACTS_BAR = {"mark_type": "bar", "category_field": "p", "has_legend": False, "color_field": None}


# ---------- 新 ops ----------

def test_sort_categories_desc_and_asc():
    out = apply_ops(bar_spec(), [{"action": "sort_categories", "order": "desc"}])
    assert out["encoding"]["x"]["sort"] == "-y"
    out2 = apply_ops(out, [{"action": "sort_categories", "order": "asc"}])
    assert out2["encoding"]["x"]["sort"] == "y"


def test_sort_categories_skips_temporal_axis():
    spec = bar_spec()
    spec["encoding"]["x"]["type"] = "temporal"
    out = apply_ops(spec, [{"action": "sort_categories"}])
    assert "sort" not in out["encoding"]["x"]


def test_set_orientation_swaps_channels_and_sort():
    sorted_spec = apply_ops(bar_spec(), [{"action": "sort_categories", "order": "desc"}])
    out = apply_ops(sorted_spec, [{"action": "set_orientation", "to": "horizontal"}])
    assert out["encoding"]["y"]["field"] == "p"
    assert out["encoding"]["x"]["field"] == "v"
    # sort 引用从 -y 翻到 -x；倾斜标签随类别轴移除
    assert out["encoding"]["y"]["sort"] == "-x"
    assert "labelAngle" not in (out["encoding"]["y"].get("axis") or {})


def test_set_orientation_noop_for_line():
    spec = bar_spec()
    spec["mark"] = "line"
    out = apply_ops(spec, [{"action": "set_orientation", "to": "horizontal"}])
    assert out["encoding"]["x"]["field"] == "p"


def test_add_value_labels_vertical_and_idempotent():
    out = apply_ops(bar_spec(), [{"action": "add_value_labels"}])
    assert len(out["layer"]) == 2
    label = out["layer"][1]
    assert label["mark"]["type"] == "text"
    assert label["encoding"]["text"]["field"] == "v"
    # 已有标注层 → 不再重复添加
    again = apply_ops(out, [{"action": "add_value_labels"}])
    assert again == out


def test_add_value_labels_horizontal_alignment():
    horiz = apply_ops(bar_spec(), [{"action": "set_orientation", "to": "horizontal"}])
    out = apply_ops(horiz, [{"action": "add_value_labels"}])
    assert out["layer"][1]["mark"]["align"] == "left"


def test_add_value_labels_skips_multiseries():
    spec = bar_spec(color={"field": "series", "type": "nominal"})
    out = apply_ops(spec, [{"action": "add_value_labels"}])
    assert "layer" not in out


def test_direct_label_removes_redundant_legend():
    spec = bar_spec(color={"field": "p", "type": "nominal"})
    out = apply_ops(spec, [{"action": "direct_label"}])
    assert out["encoding"]["color"]["legend"] is None


def test_direct_label_line_end_labels():
    spec = {
        "mark": "line",
        "encoding": {
            "x": {"field": "year", "type": "temporal"},
            "y": {"field": "v", "type": "quantitative"},
            "color": {"field": "series", "type": "nominal"},
        },
    }
    out = apply_ops(spec, [{"action": "direct_label"}])
    assert len(out["layer"]) == 2
    label_enc = out["layer"][1]["encoding"]
    assert label_enc["text"]["field"] == "series"
    assert label_enc["y"]["aggregate"] == {"argmax": "year"}
    assert out["layer"][0]["encoding"]["color"]["legend"] is None


def test_set_axis_zero_targets_quantitative_channel():
    spec = bar_spec()
    spec["encoding"]["y"]["scale"] = {"zero": False}
    out = apply_ops(spec, [{"action": "set_axis_zero"}])
    assert out["encoding"]["y"]["scale"]["zero"] is True
    assert "scale" not in out["encoding"]["x"]


def test_set_grid_style_dotted_with_opacity():
    out = apply_ops(bar_spec(), [{"action": "set_grid_style", "style": "dotted", "opacity": 0.4}])
    axis = out["encoding"]["y"]["axis"]
    assert axis["gridDash"] == [1, 3]
    assert axis["gridOpacity"] == 0.4
    # 显式关网格的轴不动
    spec2 = bar_spec()
    spec2["encoding"]["y"]["axis"] = {"grid": False}
    out2 = apply_ops(spec2, [{"action": "set_grid_style", "style": "dotted"}])
    assert "gridDash" not in out2["encoding"]["y"]["axis"]


def test_set_band_padding_writes_category_scale():
    out = apply_ops(bar_spec(), [{"action": "set_band_padding", "inner": 0.33, "outer": 0.17}])
    scale = out["encoding"]["x"]["scale"]
    assert scale["paddingInner"] == 0.33
    assert scale["paddingOuter"] == 0.17


# ---------- compile_then 布局词汇 ----------

@pytest.mark.parametrize(
    "then,expected_action",
    [
        ({"set": "axis.zero", "to": "on"}, "set_axis_zero"),
        ({"set": "grid.style", "to": "dotted"}, "set_grid_style"),
        ({"set": "labels.values", "to": "on"}, "add_value_labels"),
        ({"set": "sort.categories", "to": "desc"}, "sort_categories"),
        ({"set": "orientation", "to": "horizontal"}, "set_orientation"),
        ({"set": "bar.spacing", "to": "bars-2x-gap"}, "set_band_padding"),
        ({"set": "axis.tick-density", "to": 8}, "thin_axis_labels"),
        ({"set": "axis.label-angle", "to": "horizontal"}, "set_axis"),
    ],
)
def test_compile_then_layout_targets(then, expected_action):
    out = compile_then(StubPersona(), then, dict(FACTS_BAR))
    assert out["renderable"], then
    assert [op["action"] for op in out["ops"]] == [expected_action]


def test_compile_then_layout_gates():
    line_facts = {"mark_type": "line", "category_field": None, "has_legend": False, "color_field": None}
    assert not compile_then(StubPersona(), {"set": "labels.values", "to": "on"}, line_facts)["renderable"]
    assert not compile_then(StubPersona(), {"set": "orientation", "to": "horizontal"}, line_facts)["renderable"]
    assert not compile_then(StubPersona(), {"set": "labels.direct", "to": "on"}, dict(FACTS_BAR))["renderable"]
    legend_facts = dict(FACTS_BAR, has_legend=True)
    assert compile_then(StubPersona(), {"set": "labels.direct", "to": "on"}, legend_facts)["renderable"]


# ---------- persona 布局候选（generic fallback 检测器） ----------

def test_personas_emit_layout_candidates(registry):
    from app.core.beats import beat2_detect
    from app.core.specfacts import extract_facts

    spec = bar_spec(color={"field": "p", "type": "nominal"})
    spec["encoding"]["y"]["scale"] = {"zero": False}

    def fast_actions(pid):
        persona = registry.get(pid)
        facts = extract_facts(spec, {})
        cands, *_ = beat2_detect(persona, spec, facts)
        return {c["rule_id"]: {op["action"] for op in c["ops"]} for c in cands}

    who = fast_actions("who")
    assert "set_grid_style" in who.get("s-grid-dotted", set())
    assert "add_value_labels" in who.get("s-data-labels", set())

    shopify = fast_actions("shopify")
    assert "add_value_labels" in shopify.get("s-bar-labels", set())
    assert "set_band_padding" in shopify.get("s-bar-proportion", set())

    ebay = fast_actions("ebay")
    assert "set_axis_zero" in ebay.get("s-axis-zero", set())

    cmu = fast_actions("cmu")
    assert "direct_label" in cmu.get("s-legend-avoid", set())

    ibm = fast_actions("ibm")
    assert "direct_label" in ibm.get("s-legend-direct-label", set())


def test_new_persona_files_are_english_only(registry):
    """WHO/CMU/CFPB/Shopify 的规则与叙事文本不得含 CJK 字符。"""
    def has_cjk(text: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")

    for pid in ("who", "cmu", "cfpb", "shopify"):
        p = registry.get(pid)
        for r in p.rules:
            assert not has_cjk(r.rule), (pid, r.id)
        for a in p.adaptations:
            assert not has_cjk(str(a.raw)), (pid, a.id)
        for s in p.stories:
            text = s if isinstance(s, str) else getattr(s, "story", str(s))
            assert not has_cjk(text), (pid, s)
        for ph in p.philosophy:
            assert not has_cjk(ph.quote), (pid, ph.id)
        for suit in p.applicability.get("suits") or []:
            assert not has_cjk(suit), pid


# ---------- style_pass（拍3.6 风格化） ----------

def test_available_moves_gating():
    facts = {"mark_type": "bar", "component_ir": {}}
    moves = available_moves(bar_spec(), facts, [])
    assert {"bar_spacing", "corner_rounding", "canvas_margin", "grid_weight", "axis_frame", "chart_height"} <= set(moves)
    assert "mark_opacity" not in moves  # bar 不在 mark_opacity 适用集

    # 表面被 L1 规则占用 → 让位
    adopted = [{"ops": [{"action": "set_band_padding", "inner": 0.33}]}]
    assert "bar_spacing" not in available_moves(bar_spec(), facts, adopted)

    # 像素定位文字 → 画布类动作不可用
    fixed = {"mark_type": "bar", "component_ir": {"pixel_positioned_text": True}}
    moves_fixed = available_moves(bar_spec(), fixed, [])
    assert "canvas_margin" not in moves_fixed and "chart_height" not in moves_fixed


def test_validate_moves_clamps_and_grounds():
    class P:
        class _Ph:
            def __init__(self, id, quote):
                self.id, self.quote = id, quote

        philosophy = [_Ph("p-clear", "Clarity first.")]

    raw = {
        "moves": [
            {"move": "bar_spacing", "params": {"padding_inner": 5.0}, "principle_id": "p-clear", "label": "Slim bars", "note": "Air between bars."},
            {"move": "grid_weight", "params": {"dash": "dotted", "grid_opacity": 0.05}, "principle_id": "p-clear", "label": "Whisper grid", "note": ""},
            {"move": "grid_weight", "params": {"dash": "dashed"}, "principle_id": "p-clear", "label": "dup", "note": ""},   # 重复 move 丢弃
            {"move": "canvas_margin", "params": {"padding": 20}, "principle_id": "p-unknown", "label": "x", "note": ""},    # 假原则丢弃
            {"move": "not_a_move", "params": {}, "principle_id": "p-clear", "label": "x", "note": ""},
        ]
    }
    out = validate_moves(raw, P(), bar_spec(), MOVES)
    assert [v["move"] for v in out] == ["bar_spacing", "grid_weight"]
    assert out[0]["params"]["padding_inner"] == 0.75          # 夹到上界
    assert out[1]["params"]["grid_opacity"] == 0.15           # 夹到下界
    assert out[1]["ops"][0]["action"] == "set_grid_style"


def test_style_proposals_empty_in_mock(registry):
    from app.core.style_pass import style_proposals

    class MockLLM:
        mode = "mock"

    persona = registry.get("bbc")
    out = asyncio.run(style_proposals(persona, bar_spec(), {"mark_type": "bar"}, [], MockLLM()))
    assert out == []
