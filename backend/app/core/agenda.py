"""拍后 · 主持人议程合成：把跨机构 changes 织成 canvas 式的自然议题叙事。

Review Board 的"死板感"来自议题层没有智能参与——标题是类别标签、行文是 ops
模板。本模块延续「慢道写、快道验」：live 模式下由 LEAD 主持人视角的一次 LLM
调用产出议程叙事——

- 议题标题是针对这张图的设计判断句（"Categorical rainbow doesn't serve the
  goal"），不是类别名；
- blurb 用 1-2 句诊断问题并回应传播目标；
- 每个机构一行设计语言的处理概括（"Single accent on the leader; context muted
  to grey"），并声明覆盖的 change id；
- 每个议题带主持人讨论开场白与贴合议题的预设追问。

快道验证：change id 必须真实存在且属于该机构、全量覆盖（漏网 changes 归入
兜底议题）、数据型数字必须接地、长度上限逐条硬校验。mock 或调用/验证失败返回
None，前端回落本地确定性派生，行为不劣化。
"""

from __future__ import annotations

import colorsys
import json
import re
from typing import Any

from .actions import _normalize_plain_text, describe_ops
from .copywriter import _NUM_RE, _collect_numeric_facts, _parse_num

# 与前端 DESIGN_OBJECTS/CATEGORY_ANCHOR 对齐的锚点类别词汇表
CATEGORY_KEYS = ("title", "color", "labels", "axes", "layout", "typography", "other")

_FALLBACK_TITLE = "Smaller refinements from the guides"

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")

# 漏网 change 救援：按关键词归类，与既有同类议题合并（模型偶发漏排重要修改时兜底）
_RESCUE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("title", re.compile(r"\btitle|\bheadline|\bsubtitle|\btakeaway", re.I)),
    ("color", re.compile(r"colou?r|palette|highlight|emphasi|accent|rainbow|hue", re.I)),
    ("axes", re.compile(r"grid|axis|axes|tick|baseline", re.I)),
    ("labels", re.compile(r"legend|label|tooltip|annotation|source", re.I)),
    ("typography", re.compile(r"font|typograph|typeface", re.I)),
    ("layout", re.compile(r"sort|orient|horizontal|vertical|spacing|padding|margin|whitespace|rhythm|aspect|size", re.I)),
)


def _classify_text(text: str) -> str | None:
    for cat, pat in _RESCUE_PATTERNS:
        if pat.search(text or ""):
            return cat
    return None


def _hex_color_name(token: str) -> str:
    """hex → 口语颜色词：叙事行里说 "purple" 而不是 "#6929c4"（色板 swatch 由前端渲染）。"""
    h = token.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 24:
        if mx > 235:
            return "white"
        if mx < 40:
            return "black"
        return "light grey" if mx > 160 else ("grey" if mx > 90 else "dark grey")
    hue = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360
    for limit, name in (
        (15, "red"), (45, "orange"), (68, "yellow"), (150, "green"),
        (200, "teal"), (255, "blue"), (290, "purple"), (335, "magenta"), (360, "red"),
    ):
        if hue <= limit:
            return name
    return "colour"


def _humanize_colors(text: str) -> str:
    return _HEX_RE.sub(lambda m: _hex_color_name(m.group(0)), text or "")


def _grounded_loose(text: str, pool: list[float]) -> bool:
    """宽松接地：百分数与 >24 的数字须在事实池内；小整数（色数/条数等设计口语）放行。"""
    for m in _NUM_RE.finditer(text or ""):
        v = _parse_num(m.group(0))
        if v is None:
            continue
        tail = (text[m.end():m.end() + 1] or "").strip()
        is_percent = tail.startswith("%")
        if not is_percent and v <= 24:
            continue
        if not any(abs(v - p) <= max(0.5, abs(p) * 0.01) for p in pool):
            return False
    return True


def _change_digest(change: dict, persona=None) -> dict:
    warrant = change.get("warrant") if isinstance(change.get("warrant"), dict) else {}
    out = {
        "id": change.get("id"),
        "label": change.get("label"),
        "layer": change.get("layer"),
        "status": change.get("status"),
        "strength": change.get("strength"),
        "derived": bool(warrant.get("derived")),
        "effects": (describe_ops(change.get("ops") or []) or "")[:220] or None,
        "reason": str(change.get("reason") or "")[:260],
        "warrant_quote": str(warrant.get("quote") or warrant.get("story") or "")[:180],
    }
    # 规则原文与 L2 触发条件：让主持人能写出 "When {situation}, use {approach}" 的 why 行
    if persona is not None:
        rid = str(change.get("rule_id") or "")
        rule = next((r for r in getattr(persona, "rules", []) if r.id == rid), None)
        if rule is not None:
            out["rule_text"] = str(rule.rule or "")[:220]
        else:
            ad = next((a for a in getattr(persona, "adaptations", []) if a.id == rid), None)
            if ad is not None:
                if ad.when:
                    out["when"] = ad.when
                if ad.then is not None:
                    out["then"] = ad.then
    return out


def _chart_digest(facts: dict, context: dict) -> dict:
    keys = (
        "title_text", "subtitle", "mark_type", "categories", "series_count",
        "category_count", "max_category", "min_category", "data_topic",
        "intent", "summary",
    )
    out = {k: facts.get(k) for k in keys if facts.get(k) is not None}
    goal = context.get("communication_goal") or facts.get("communication_goal")
    if goal:
        out["communication_goal"] = goal
    return out


def _agenda_system(persona_names: dict[str, str]) -> str:
    roster = ", ".join(f"{pid} = {name}" for pid, name in persona_names.items())
    return (
        "You are LEAD, the moderator of an institutional design review board for a chart. "
        "Several institutional advisors have each proposed concrete changes (supplied with their "
        "reasons and guideline warrants). Your job is to organize the review into a natural, "
        "expert-sounding issue agenda — the way a good design-crit facilitator would.\n\n"
        f"Advisors on the board: {roster}.\n\n"
        "Write 2-5 issues. For each issue:\n"
        "- title: a crisp design-critique claim about THIS chart, ≤ 80 chars. Good titles read like "
        "\"Categorical rainbow doesn't serve the goal\" or \"Title states the topic, not the takeaway\" "
        "— never a generic category name like \"Color & emphasis\".\n"
        "- blurb: 1-2 short sentences diagnosing the problem on this specific chart — name the actual "
        "encodings, series or values involved, and the communication goal when relevant. No filler "
        "like \"essential for clarity\" or \"detracting from readability\".\n"
        "- category: exactly one of title|color|labels|axes|layout|typography|other (anchor placement).\n"
        "- treatments: one entry per advisor that addresses this issue — a single line stating the "
        "concrete action that institution takes on the chart, in its design voice, ≤ 110 chars, plus "
        "change_ids listing the exact change ids it covers. Bad: \"Ensure colors maximize contrast\" "
        "(generic advice). Good: \"Single accent on the solved series; context muted to grey\". Refer "
        "to colours by role or name (accent, grey context, house navy), never raw hex codes.\n"
        "- each treatment also carries why: one line (≤ 130 chars) voicing the institutional warrant "
        "behind it, phrased by the driving change's layer:\n"
        "  * L2 (has a `when` condition): strictly \"When {situation}, {approach}\" — the situation "
        "from the rule's `when`/reason, e.g. \"When one series carries the story, colour only that "
        "series and let the rest recede\".\n"
        "  * L1 (unconditional signature, has rule_text): state the house norm plainly, e.g. "
        "\"House norm: titles state the finding, sentence case, left-aligned\".\n"
        "  * derived=true (philosophy-derived): cite the principle, e.g. \"From 'Less is more': "
        "ink that doesn't aid reading is removed\".\n"
        "  Ground the why in the supplied rule_text / when / reason / warrant_quote; never invent "
        "section numbers or conditions.\n"
        "- discussion_intro: 1-2 moderator sentences framing how the advisors' strategies relate "
        "(agree / differ and how) for the discussion thread.\n"
        "- quick_asks: 2-3 short questions (≤ 70 chars each) the chart author would put TO the "
        "advisors — probing or challenging the recommendation, like \"Won't readers lose precise "
        "values without gridlines?\". Never survey the author about their own preference.\n\n"
        "Tone anchor (a different chart; match this register, don't copy content):\n"
        "{\"title\": \"Categorical rainbow doesn't serve the goal\", \"blurb\": \"Four hues encode "
        "product, but the goal is a single comparison — colour carries no meaning and dilutes emphasis "
        "on the leader.\", \"category\": \"color\", \"discussion_intro\": \"Both advisors flag the "
        "categorical palette; BBC mutes the context while The Economist re-encodes in house colours.\", "
        "\"quick_asks\": [\"What about colour-blind readers?\"], \"treatments\": [{\"persona_id\": "
        "\"bbc\", \"line\": \"Single accent on the leader; context muted to grey\", \"why\": \"When "
        "one value carries the story, colour only that value and let the rest recede\", \"change_ids\": "
        "[\"bbc:x\"]}]}\n\n"
        "Hard rules:\n"
        "1. A change id may appear in at most one issue; never invent ids. Assign a change to an "
        "issue only if it genuinely addresses that concern — never pad an issue with loosely related "
        "changes (a palette swap does not belong under a gridline issue). Changes that fit nowhere "
        "may be omitted; they are collected into a catch-all automatically. Do place the significant "
        "ones: title, colour, chart type, emphasis, gridlines. Emphasis/highlight changes usually "
        "belong with the colour issue or an issue of their own tied to the communication goal — "
        "don't leave them for the catch-all.\n"
        "2. Group by design concern, not by institution; an issue raised by more advisors comes first.\n"
        "3. Use only names and numbers present in the input; never invent data values.\n"
        "4. Plain English, no markdown, no exclamation marks.\n\n"
        "Return JSON only: {\"issues\": [{\"title\": \"...\", \"blurb\": \"...\", "
        "\"category\": \"color\", \"discussion_intro\": \"...\", \"quick_asks\": [\"...\"], "
        "\"treatments\": [{\"persona_id\": \"bbc\", \"line\": \"...\", \"why\": \"...\", "
        "\"change_ids\": [\"bbc:x\"]}]}]}"
    )


def validate_agenda(raw: Any, proposals: dict[str, dict], pool: list[float]) -> dict | None:
    """快道验证：id 接地、全量覆盖、数字接地、长度上限；不过关的部件逐级降级。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("issues"), list):
        return None
    changes_by_id: dict[str, tuple[str, dict]] = {}
    for pid, prop in proposals.items():
        for c in prop.get("changes") or []:
            cid = str(c.get("id") or "")
            if cid:
                changes_by_id[cid] = (pid, c)
    if not changes_by_id:
        return None

    used: set[str] = set()
    issues_out: list[dict] = []
    for item in raw["issues"]:
        if not isinstance(item, dict):
            continue
        title = _humanize_colors(_normalize_plain_text(item.get("title")))[:110]
        if not title or not _grounded_loose(title, pool):
            continue
        category = str(item.get("category") or "").strip().lower()
        if category not in CATEGORY_KEYS:
            category = "other"
        # 议题标题的判断句比模型给的类别更可信（"Title lacks…" 不该锚在 labels）
        cat_from_title = _classify_text(title)
        if cat_from_title and cat_from_title != category:
            category = cat_from_title
        treatments_out: list[dict] = []
        for t in item.get("treatments") or []:
            if not isinstance(t, dict):
                continue
            pid = str(t.get("persona_id") or "")
            ids = [
                str(cid) for cid in (t.get("change_ids") or [])
                if str(cid) in changes_by_id
                and changes_by_id[str(cid)][0] == pid
                and str(cid) not in used
            ]
            if not ids:
                continue
            used.update(ids)
            first_label = str(changes_by_id[ids[0]][1].get("label") or "")
            line = _humanize_colors(_normalize_plain_text(t.get("line")))[:140]
            if not line or not _grounded_loose(line, pool):
                line = first_label
            why = _humanize_colors(_normalize_plain_text(t.get("why")))[:170]
            if why and not _grounded_loose(why, pool):
                why = ""
            # 同一机构在同一议题下的多条 treatment 合并成一行（前端每机构渲染一行）
            existing = next((x for x in treatments_out if x["persona_id"] == pid), None)
            if existing is not None:
                existing["change_ids"].extend(ids)
                if line and line.lower() not in existing["line"].lower():
                    joined = f"{existing['line'].rstrip('. ')}; {line}"
                    existing["line"] = joined[:180]
                if why and not existing["why"]:
                    existing["why"] = why
            else:
                treatments_out.append({"persona_id": pid, "line": line, "why": why, "change_ids": ids})
        if not treatments_out:
            continue
        blurb = _humanize_colors(_normalize_plain_text(item.get("blurb")))[:340]
        if blurb and not _grounded_loose(blurb, pool):
            blurb = ""
        intro = _humanize_colors(_normalize_plain_text(item.get("discussion_intro")))[:340]
        if intro and not _grounded_loose(intro, pool):
            intro = ""
        quick_asks = [
            _humanize_colors(_normalize_plain_text(q))[:90]
            for q in (item.get("quick_asks") or [])
            if isinstance(q, str) and _normalize_plain_text(q)
        ][:3]
        issues_out.append(
            {
                "title": title,
                "blurb": blurb,
                "category": category,
                "discussion_intro": intro,
                "quick_asks": quick_asks,
                "treatments": treatments_out,
            }
        )

    if not issues_out:
        return None

    # 覆盖度排序（多机构议题在前），与既有 Review Board 排序语义一致
    def _sort_issues() -> None:
        issues_out.sort(
            key=lambda it: (
                -len(it["treatments"]),
                -sum(len(t["change_ids"]) for t in it["treatments"]),
            )
        )

    _sort_issues()

    # 救援：漏网 change 按关键词归类；已存在同类议题（每类取覆盖度最高者）则拉回，
    # 行文退化为 change label（效果行由前端照常渲染），保证重要修改不落兜底。
    cat_issue: dict[str, dict] = {}
    for it in issues_out:
        for cat, pat in _RESCUE_PATTERNS:
            if it["category"] == cat or pat.search(it["title"]):
                cat_issue.setdefault(cat, it)
    for cid, (pid, change) in changes_by_id.items():
        if cid in used:
            continue
        # change id 内嵌 rule_id（"pid:rule"），一并参与关键词分类
        cat = _classify_text(f"{cid} {change.get('rule_id') or ''} {change.get('label') or ''}")
        target = cat_issue.get(cat) if cat else None
        if target is None:
            continue
        used.add(cid)
        existing = next((t for t in target["treatments"] if t["persona_id"] == pid), None)
        if existing is not None:
            existing["change_ids"].append(cid)
        else:
            target["treatments"].append(
                {"persona_id": pid, "line": str(change.get("label") or ""), "why": "", "change_ids": [cid]}
            )
    _sort_issues()

    # 剩余漏网 changes → 兜底议题，保证每条修改仍有采纳入口
    leftovers = [cid for cid in changes_by_id if cid not in used]
    if leftovers:
        by_pid: dict[str, list[str]] = {}
        for cid in leftovers:
            by_pid.setdefault(changes_by_id[cid][0], []).append(cid)
        treatments = []
        for pid, ids in by_pid.items():
            label = str(changes_by_id[ids[0]][1].get("label") or "")
            line = label if len(ids) == 1 else f"{label} and {len(ids) - 1} more"
            treatments.append({"persona_id": pid, "line": line, "why": "", "change_ids": ids})
        issues_out.append(
            {
                "title": _FALLBACK_TITLE,
                "blurb": "",
                "category": "other",
                "discussion_intro": "",
                "quick_asks": [],
                "treatments": treatments,
            }
        )
    return {"issues": issues_out}


async def synthesize_agenda(
    order: list[str], proposals: dict[str, dict], context: dict, llm, personas: dict | None = None
) -> dict | None:
    """live 模式下合成议程；mock/无提案/调用或验证失败一律返回 None（前端回落）。

    ``personas``（可选 {pid: Persona}）用于把规则原文与 L2 `when` 条件注入 digest，
    让 why 行能按层写出统一句式。
    """
    if getattr(llm, "mode", "mock") != "live":
        return None
    proposals = {pid: proposals[pid] for pid in order if pid in proposals}
    if not proposals or not any(p.get("changes") for p in proposals.values()):
        return None

    persona_names = {
        pid: str(prop.get("persona_name") or pid) for pid, prop in proposals.items()
    }
    rep_facts = next(
        (p.get("facts") for p in proposals.values() if isinstance(p.get("facts"), dict)),
        {},
    )
    digest = {
        "chart_facts": _chart_digest(rep_facts or {}, context or {}),
        "advisors": [
            {
                "persona_id": pid,
                "persona_name": persona_names[pid],
                "changes": [
                    _change_digest(c, (personas or {}).get(pid))
                    for c in (prop.get("changes") or [])
                ],
            }
            for pid, prop in proposals.items()
        ],
    }
    try:
        raw = await llm.chat_json(
            _agenda_system(persona_names),
            json.dumps({"task": "review_agenda", **digest}, ensure_ascii=False),
        )
    except Exception:  # noqa: BLE001 — 议程是叙事增强步骤，任何失败都回落
        return None
    digest_json = json.dumps(digest, ensure_ascii=False)
    pool = _collect_numeric_facts(rep_facts if isinstance(rep_facts, dict) else {})
    pool.extend(v for v in (_parse_num(tok) for tok in _NUM_RE.findall(digest_json)) if v is not None)
    return validate_agenda(raw, proposals, pool)
