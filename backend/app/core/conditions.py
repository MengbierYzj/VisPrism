"""L2 when 条件求值（快道）。

结构化条件直接判定 match / no_match；语义条件（intent、data_role、自然语言
取值等）返回 unknown → 列入升级清单交慢道裁决。这实现了 default-intervened
的"缺省快判、判不了升级"。
"""
from __future__ import annotations

import re
from typing import Any

MATCH, NO_MATCH, UNKNOWN = "match", "no_match", "unknown"

_SLUG = re.compile(r"^[a-z][a-z0-9_-]*$")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")

# 永远语义化的条件键：快道不判，直接升级
SEMANTIC_KEYS = {"intent", "data_role", "data_range", "comparison", "context", "task", "audience"}


def _to_num(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = _NUM.search(v)
        if m:
            return float(m.group())
    return None


def _cmp(cond: Any, actual: Any) -> str:
    """数值比较：cond 为标量（相等）或 {gt/gte/lt/lte/eq: n}。"""
    a = _to_num(actual)
    if a is None:
        return UNKNOWN
    if isinstance(cond, dict):
        for op, raw in cond.items():
            n = _to_num(raw)
            if n is None:
                return UNKNOWN
            ok = {
                "gt": a > n, "gte": a >= n, "lt": a < n, "lte": a <= n, "eq": a == n,
            }.get(op)
            if ok is None:
                return UNKNOWN
            if not ok:
                return NO_MATCH
        return MATCH
    n = _to_num(cond)
    if n is None:
        return UNKNOWN
    return MATCH if a == n else NO_MATCH


def _membership(cond: Any, actual: Any) -> str:
    """离散值比较：条件值须是受控词槽（slug）才可快判，否则语义化 → unknown。"""
    values = cond if isinstance(cond, list) else [cond]
    values = [str(v) for v in values]
    if not all(_SLUG.match(v) for v in values):
        return UNKNOWN
    if actual is None:
        return UNKNOWN
    return MATCH if str(actual) in values else NO_MATCH


def eval_when(when: dict, facts: dict) -> tuple[str, list[dict]]:
    """返回 (整体判定, 逐键明细)。全部 match → match；任一 no_match → no_match；
    否则 unknown（升级）。空 when 视为无条件 match。"""
    if not when:
        return MATCH, []
    details = []
    verdicts = []
    for key, cond in when.items():
        if key in SEMANTIC_KEYS:
            v = UNKNOWN
            note = "语义条件，升级慢道"
        elif key in ("series_count", "category_count", "color_count", "row_count"):
            v = _cmp(cond, facts.get(key))
            note = f"facts.{key}={facts.get(key)}"
        elif key == "viewport":
            v = _cmp(cond, facts.get("viewport_px"))
            note = f"facts.viewport_px={facts.get('viewport_px')}"
        elif key == "data_topic":
            v = _membership(cond, facts.get("data_topic"))
            note = f"facts.data_topic={facts.get('data_topic')}"
        elif key == "medium":
            v = _membership(cond, facts.get("medium"))
            note = f"facts.medium={facts.get('medium')}"
        else:
            v = UNKNOWN
            note = "未知条件键，升级慢道"
        details.append({"key": key, "cond": cond, "verdict": v, "note": note})
        verdicts.append(v)
    if NO_MATCH in verdicts:
        return NO_MATCH, details
    if UNKNOWN in verdicts:
        return UNKNOWN, details
    return MATCH, details
