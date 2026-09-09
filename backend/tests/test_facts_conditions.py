"""快道基础：事实提取与 L2 条件求值（match / no_match / unknown 三态）。"""
from app.core.conditions import MATCH, NO_MATCH, UNKNOWN, eval_when
from app.core.specfacts import extract_facts


def test_extract_facts_example(example_spec):
    f = extract_facts(example_spec)
    assert f["mark_type"] == "bar"
    assert f["category_field"] == "product" and f["value_field"] == "num"
    assert f["category_count"] == 4
    assert f["per_category_coloring"] is True   # color 字段与类别轴同字段
    assert f["series_count"] == 1
    assert f["has_legend"] is False             # 显式 legend: null
    assert f["grid_y"] is True and f["grid_x"] is False
    assert f["has_source_note"] is False
    assert f["max_category"] == {"name": "C产品", "value": 450}
    assert f["color_count"] == 4                # 默认 scheme 按类别估计


def test_conditions_three_states(example_spec):
    facts = extract_facts(example_spec)
    assert eval_when({"series_count": 1}, facts)[0] == MATCH
    assert eval_when({"series_count": {"gte": 3}}, facts)[0] == NO_MATCH
    assert eval_when({"series_count": {"gt": 6}}, facts)[0] == NO_MATCH
    # 语义条件 → 升级
    assert eval_when({"intent": "突出关键信息"}, facts)[0] == UNKNOWN
    # 受控词槽可快判；中文语义值不可
    facts_topic = {**facts, "data_topic": "business"}
    assert eval_when({"data_topic": ["health", "environment"]}, facts_topic)[0] == NO_MATCH
    assert eval_when({"data_topic": "知名政党"}, facts_topic)[0] == UNKNOWN
    # viewport 数值比较（spec width 350 作为视口回退）
    assert eval_when({"viewport": {"lte": "600px"}}, facts)[0] == MATCH
    assert eval_when({"viewport": {"gt": "600px"}}, facts)[0] == NO_MATCH
    # 混合：一假即假（no_match 优先于 unknown）
    assert eval_when({"series_count": 2, "intent": "x"}, facts)[0] == NO_MATCH
