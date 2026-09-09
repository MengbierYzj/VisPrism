"""拍3.5 · 机构口吻标题文案：慢道撰写，快道核验。

canvas 画板的目标效果是「标题直接说结论」（如 "Product C is the clear winner"），
而确定性模板只能拼出 "X leads (162)" 这类句式。本模块在 live 模式下，把被采纳的
标题类规范（takeaway 标题 / sentence case / 极简标题 / 克制机智）交给 LLM 撰写
机构口吻的文案，再用程序验证器把关，延续「快慢分工」思路——慢道负责判断与创作，
快道负责事实与规范校验：

- 事实接地：文案中的数字必须能在图表事实（数据切片/极值/原标题）中找到，防编造；
- 机构约束：sentence case、eBay 1-2 词上限、CFPB ≤95 字符逐条硬校验；
- 类别名大小写还原：防止 sentence case 启发式误伤数据中的专有名词；
- 任一校验不过或调用失败 → 保留确定性改写结果，不影响可用性。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .actions import _normalize_plain_text, _to_sentence_case

# 会触发文案撰写的标题类规则
TITLE_RULE_IDS: tuple[str, ...] = (
    "s-title-descriptive",  # BBC/IBM/CMU/CFPB：标题陈述要点
    "s-title-brief",        # eBay：1-2 词极简标题，语境放副标题
    "s-wit",                # Economist：克制的机智
    "s-title-case",         # BBC/eBay：sentence case
)

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")

# 数字接地白名单的事实来源：图表数据与用户输入里出现过的数字才允许出现在文案中
_FACT_KEYS_FOR_NUMBERS = (
    "title_text", "subtitle", "categories", "series_values",
    "max_category", "min_category", "chart_slice",
    "summary", "communication_goal",
)


def _parse_num(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def _collect_numeric_facts(facts: dict) -> list[float]:
    pool: list[float] = []

    def walk(x: Any) -> None:
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            pool.append(float(x))
        elif isinstance(x, str):
            for tok in _NUM_RE.findall(x):
                v = _parse_num(tok)
                if v is not None:
                    pool.append(v)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for key in _FACT_KEYS_FOR_NUMBERS:
        walk(facts.get(key))
    return pool


def _grounded(text: str, pool: list[float]) -> bool:
    """文案中的每个数字都要能对上事实池（容差覆盖四舍五入）。"""
    for tok in _NUM_RE.findall(text or ""):
        v = _parse_num(tok)
        if v is None:
            continue
        if not any(abs(v - p) <= max(0.5, abs(p) * 0.01) for p in pool):
            return False
    return True


def _looks_title_case(text: str) -> bool:
    """Title Case Everywhere 才需要归一；正常 sentence case 不动，避免误伤专有名词。"""
    words = [w for w in re.split(r"\s+", text) if w][1:]
    caps = [w for w in words if len(w) >= 4 and w[:1].isalpha() and w[:1].isupper()]
    return len(caps) >= 2 and len(caps) / max(len(words), 1) > 0.5


def _restore_known_casing(text: str, facts: dict) -> str:
    """把数据中的类别名按原始大小写还原（防 sentence case 误伤 "Product C"/"Berlin"）。"""
    names: list[str] = []
    cats = facts.get("categories")
    if isinstance(cats, list):
        names.extend(str(c) for c in cats if isinstance(c, str))
    for key in ("max_category", "min_category"):
        mc = facts.get(key)
        if isinstance(mc, dict) and isinstance(mc.get("name"), str):
            names.append(mc["name"])
    for name in sorted(set(names), key=len, reverse=True):
        if not name.strip():
            continue
        text = re.sub(re.escape(name), name, text, flags=re.IGNORECASE)
    return text[:1].upper() + text[1:] if text else text


def validate_and_normalize(raw: Any, facts: dict, rule_ids: set[str]) -> dict | None:
    """程序验证器：不过关就返回 None（调用方回落确定性改写）。"""
    if not isinstance(raw, dict):
        return None
    title = _normalize_plain_text(raw.get("title"))
    subtitle = _normalize_plain_text(raw.get("subtitle")) or None
    if not title:
        return None
    # 机构标题规范普遍要求无句末标点（问号保留：BBC 允许设问式标题）
    title = title.rstrip(" .;:!，。；")
    if "s-title-case" in rule_ids and _looks_title_case(title):
        title = _to_sentence_case(title)
    title = _restore_known_casing(title, facts)
    if "s-title-brief" in rule_ids and len(title.split()) > 4:
        return None
    if len(title) > 95:  # CFPB 桌面端单行上限，作为通用护栏
        return None
    pool = _collect_numeric_facts(facts)
    if not _grounded(title, pool):
        return None
    if subtitle:
        subtitle = subtitle.rstrip(" ;，；")
        if "s-title-case" in rule_ids and _looks_title_case(subtitle):
            subtitle = _to_sentence_case(subtitle)
        subtitle = _restore_known_casing(subtitle, facts)
        old_title_l = _normalize_plain_text(facts.get("title_text")).lower()
        # 副标题不得复述标题（含新标题与原标题）；过长/编造数字则弃用副标题但保留标题
        if (
            len(subtitle) > 140
            or subtitle.lower() in (title.lower(), old_title_l)
            or not _grounded(subtitle, pool)
        ):
            subtitle = None
    old_title = _normalize_plain_text(facts.get("title_text"))
    if title.lower() == old_title.lower() and not subtitle:
        return None  # 无实质变化，不产生空转 op
    return {
        "title": title,
        "subtitle": subtitle,
        "rationale": _normalize_plain_text(raw.get("rationale"))[:200],
    }


def _copywriter_system(persona, title_items: list[dict]) -> str:
    norms = []
    for it in title_items:
        story = persona.story_text(it.get("story_id", ""))
        line = f"- [{it['rule_id']}] {it.get('rule_text', '')}"
        if story:
            line += f"\n  Guide voice: \"{story}\""
        norms.append(line)
    quotes = [
        f"- {p.title + ': ' if p.title else ''}{p.quote}"
        for p in (persona.philosophy or [])[:2]
    ]
    brief_line = (
        "4. The title must be at most 2 words (hard limit 4); put all context in the subtitle.\n"
        if any(it["rule_id"] == "s-title-brief" for it in title_items)
        else ""
    )
    return (
        f"You are the chart copy editor at {persona.name}, rewriting a chart's title "
        "(and optionally subtitle) so it reads exactly like your institution published it.\n\n"
        "Institutional title norms you must satisfy (verbatim from the style guide):\n"
        + "\n".join(norms)
        + ("\n\nInstitution voice:\n" + "\n".join(quotes) if quotes else "")
        + "\n\nHard rules:\n"
        "1. The title states the chart's takeaway — a claim the reader can verify from the data, "
        "not a topic label. Prefer plain words over numbers when the point is qualitative "
        "(e.g. \"the clear winner\", \"far ahead\").\n"
        "2. Use ONLY names and numbers that appear in chart_facts. Never invent, extrapolate "
        "or re-round values.\n"
        "3. Sentence case; no ending punctuation.\n"
        + brief_line +
        "5. subtitle adds context (units, scope, timeframe) in one short line and never restates "
        "the title; return null if you have nothing real to add.\n"
        "6. If communication_goal is present, serve it.\n\n"
        "Return JSON only: {\"title\": \"...\", \"subtitle\": \"...\" or null, "
        "\"rationale\": \"one sentence on why this copy serves the institution's norms\"}"
    )


def _copywriter_user(facts: dict) -> str:
    payload = {
        "task": "title_copy",
        "chart_facts": {
            k: facts.get(k)
            for k in (
                "title_text", "subtitle", "mark_type", "category_field", "value_field",
                "categories", "max_category", "min_category", "series_count",
                "data_topic", "intent", "summary", "communication_goal",
            )
            if facts.get(k) is not None
        },
        "chart_slice": facts.get("chart_slice"),
    }
    return json.dumps(payload, ensure_ascii=False)


async def apply_title_copywriter(persona, facts: dict, adopted: list[dict], llm) -> list[dict]:
    """live 模式下改写被采纳标题条目的 ops；mock/校验失败一律原样返回。

    多条标题规则同时被采纳时（如 BBC 的 descriptive + case），所有条目写入同一
    标题/副标题文本（幂等）——拍4 的 _merge_persona_by_conflict_key 会按 strength
    只留一条 applied，无论哪条胜出都携带完整文案。
    """
    idxs = [i for i, it in enumerate(adopted) if it.get("rule_id") in TITLE_RULE_IDS]
    if not idxs or getattr(llm, "mode", "mock") != "live":
        return adopted
    items = [adopted[i] for i in idxs]
    try:
        raw = await llm.chat_json(_copywriter_system(persona, items), _copywriter_user(facts))
    except Exception:  # noqa: BLE001 — 文案是增强步骤，任何失败都回落确定性结果
        return adopted
    copy = validate_and_normalize(raw, facts, {it["rule_id"] for it in items})
    if not copy:
        return adopted
    note = "Slow lane drafted the copy; fast lane verified facts, casing and length."
    if copy.get("rationale"):
        note = f"{copy['rationale']} ({note})"
    for i in idxs:
        it = adopted[i]
        ops = [
            op for op in (it.get("ops") or [])
            if op.get("action") not in ("set_title_text", "set_subtitle")
        ]
        ops.append({"action": "set_title_text", "text": copy["title"]})
        if copy.get("subtitle"):
            ops.append({
                "action": "set_subtitle",
                "text": copy["subtitle"],
                "preserve_source": True,
            })
        it["ops"] = ops
        it["suggested_only"] = False
        it["rationale"] = f"{it.get('rationale') or ''}；{note}".strip("；")
        it["detail"] = it["rationale"]
    return adopted
