"""Advisor pre-flight briefing (prompt engineering).

Before the four-beat pipeline, assemble a reproducible briefing per persona advisor:
- Role: institutional visualization design expert
- Chart reading: narrative from programmatic facts
- User intent: communication_goal
- Three-layer digest: L1 disposition / L2 adaptations / L3 narrative

Written to facts.advisor_briefing and injected into beat-1 / beat-3 / intent-analysis
system prompts. Does not change the four-beat topology or add an extra LLM beat.
"""
from __future__ import annotations

import json
import re
from typing import Any


def _clip(text: str, n: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    return s if len(s) <= n else s[: n - 1] + "…"


def _chart_narrative(facts: dict) -> dict[str, Any]:
    """Build a chart-reading narrative from programmatic facts (no LLM)."""
    mark = facts.get("mark_type") or "unknown"
    cats = facts.get("categories") or []
    cat_n = facts.get("category_count")
    if cat_n is None and isinstance(cats, list):
        cat_n = len(cats)
    maxc = facts.get("max_category") if isinstance(facts.get("max_category"), dict) else {}
    minc = facts.get("min_category") if isinstance(facts.get("min_category"), dict) else {}
    sample_cats = [str(c) for c in (cats[:6] if isinstance(cats, list) else [])]
    parts = [
        f"mark={mark}",
        f"category_field={facts.get('category_field') or '—'}",
        f"value_field={facts.get('value_field') or '—'}",
    ]
    if cat_n is not None:
        parts.append(f"category_count={cat_n}")
    if sample_cats:
        parts.append("categories=" + ", ".join(sample_cats))
    if maxc.get("name") is not None:
        parts.append(f"max={maxc.get('name')}({maxc.get('value')})")
    if minc.get("name") is not None:
        parts.append(f"min={minc.get('name')}({minc.get('value')})")
    if facts.get("title_text"):
        parts.insert(0, f'title="{facts["title_text"]}"')
    if facts.get("series_count"):
        parts.append(f"series_count={facts['series_count']}")
    if facts.get("color_field"):
        parts.append(f"color_field={facts['color_field']}")
    if facts.get("per_category_coloring"):
        parts.append("per_category_coloring=yes")
    if facts.get("color_count"):
        parts.append(f"color_count={facts['color_count']}")
    if facts.get("coloring_mode"):
        parts.append(f"coloring_mode={facts['coloring_mode']}")
    if facts.get("has_drawn_grid"):
        parts.append("drawn_grid=yes")
    if facts.get("title_from_text_layer"):
        parts.append("title_from=text_layer")
    if facts.get("unit_count"):
        parts.append(f"units={facts['unit_count']}")
    narrative = "; ".join(parts) + "."
    return {
        "title": facts.get("title_text"),
        "mark_type": mark,
        "category_field": facts.get("category_field"),
        "value_field": facts.get("value_field"),
        "color_field": facts.get("color_field"),
        "per_category_coloring": bool(facts.get("per_category_coloring")),
        "category_count": cat_n,
        "categories_sample": sample_cats,
        "max_category": maxc or None,
        "min_category": minc or None,
        "series_count": facts.get("series_count"),
        "coloring_mode": facts.get("coloring_mode"),
        "has_drawn_grid": bool(facts.get("has_drawn_grid")),
        "title_from_text_layer": bool(facts.get("title_from_text_layer")),
        "narrative": narrative,
    }


def _l1_digest(persona) -> dict[str, Any]:
    must = [r for r in persona.rules if getattr(r, "strength", "") == "must"]
    never = [r for r in persona.rules if getattr(r, "strength", "") == "never"]
    should = [r for r in persona.rules if getattr(r, "strength", "") == "should"]
    brand = None
    if hasattr(persona, "resolve_color"):
        brand = persona.resolve_color("{color.primary}") or (persona.ui or {}).get("brand_color")
    # 优先指南 categorical 序（分配原则用）；回退 ui.palette
    palette: list[str] = []
    if hasattr(persona, "resolve_color_list"):
        palette = [
            c
            for c in (persona.resolve_color_list("{palette.categorical}") or [])
            if isinstance(c, str)
        ]
    if not palette:
        raw = (persona.ui or {}).get("palette") or []
        palette = [c for c in raw if isinstance(c, str)] if isinstance(raw, list) else []
    samples = []
    for r in (must + never + should)[:8]:
        samples.append(
            {
                "id": r.id,
                "strength": r.strength,
                "text": _clip(getattr(r, "rule", "") or ""),
            }
        )
    return {
        "rule_counts": {
            "must": len(must),
            "never": len(never),
            "should": len(should),
            "total": len(persona.rules),
        },
        "brand_color": brand,
        "palette_sample": palette[:8],
        "rule_samples": samples,
    }


def _l2_digest(persona) -> dict[str, Any]:
    items = []
    intents: list[str] = []
    for ad in persona.adaptations[:12]:
        when = ad.when if isinstance(ad.when, dict) else {}
        intent = when.get("intent") or when.get("task") or when.get("context")
        if intent and str(intent) not in intents:
            intents.append(str(intent))
        items.append(
            {
                "id": ad.id,
                "when": when,
                "then": ad.then if isinstance(ad.then, (dict, str)) else str(ad.then),
                "strength": ad.strength,
            }
        )
    return {
        "adaptation_count": len(persona.adaptations),
        "intent_or_task_keys": intents[:10],
        "samples": items,
    }


def _l3_digest(persona) -> dict[str, Any]:
    philos = []
    for p in persona.philosophy[:6]:
        philos.append(
            {
                "id": p.id,
                "title": getattr(p, "title", "") or "",
                "quote": _clip(getattr(p, "quote", "") or "", 200),
            }
        )
    stories = []
    for sid, st in list(persona.stories.items())[:6]:
        stories.append({"id": sid, "story": _clip(getattr(st, "story", "") or "", 120)})
    return {
        "philosophy_count": len(persona.philosophy),
        "story_count": len(persona.stories),
        "philosophy": philos,
        "stories": stories,
    }


def build_advisor_briefing(persona, facts: dict, spec: dict | None = None) -> dict[str, Any]:
    """Assemble advisor foundation briefing (deterministic, reproducible)."""
    full_name = (persona.ui or {}).get("full_name") or persona.name
    suits = (persona.applicability or {}).get("suits") or []
    promises = (persona.applicability or {}).get("promises") or []
    chart = _chart_narrative(facts)
    goal = facts.get("communication_goal")
    role = (
        f"You are a visualization design expert advisor for {full_name} "
        f"(institution id={persona.id}). "
        f"Domain: {persona.domain or 'general'}. "
        "You reason with this institution's three-layer design persona knowledge "
        "(L1 Dispositional Signature, L2 Characteristic Adaptations, L3 Narrative Identity) "
        "to understand the user goal and the input chart, then propose executable "
        "visualization edits that follow institutional norms. "
        "Do not invent hex colors outside the guide or actions outside the action space."
    )
    operating = [
        "First understand what the chart says and the data facts, then incorporate the user's natural-language goal.",
        "L1 (must/never) constraints are context-invariant; never violate them on conflict.",
        "L2 (when→then) adapts to situation; prefer chart types compile to ops or suggestions per system policy.",
        "L3 philosophy and reason stories support slow-path adjudication and explanations; they must not invent new executable actions.",
        "Colors and type sizes must resolve via institutional tokens; the model must not freely invent color values.",
        "Color assignment is a design decision, not a token dump: choose coloring_mode first, then map institutional palette colors to roles.",
        "Four-beat topology: slow read → fast detect → slow adjudicate → fast compile/verify.",
    ]
    color_principles = [
        "Decide coloring_mode before picking hexes: uniform | paired | categorical | highlight.",
        "uniform: one measure / one series / redundant category rainbow → one institutional primary (keep emphasis accent if present).",
        "paired: exactly two comparable series → primary + contrasting secondary from the guide pair.",
        "categorical: parts-of-whole, composition, or 3+ distinct identities encoded by color → N distinct palette colors; never paint all parts the same hue.",
        "highlight: one category/series to emphasize → base institutional color + accent; do not recolor every category as accent.",
        "series_count==1 does NOT imply uniform when color encodes part/category identity (composition / per-category color that carries meaning).",
        "Prefer the institutional categorical sequence in guide order; take the first N colors for N parts/series—do not repeat one swatch across all marks.",
        "Harmony: stay inside the guide palette; avoid arbitrary remixes; supporting/reference series may use neutral gray when the guide says so.",
        "Never invent hex colors outside the institutional palette/tokens.",
    ]
    briefing = {
        "persona_id": persona.id,
        "persona_name": persona.name,
        "full_name": full_name,
        "domain": persona.domain,
        "role": role,
        "applicability": {
            "suits": suits[:6] if isinstance(suits, list) else [],
            "promises": promises[:4] if isinstance(promises, list) else [],
        },
        "chart": chart,
        "user_goal": goal,
        "layers": {
            "L1": _l1_digest(persona),
            "L2": _l2_digest(persona),
            "L3": _l3_digest(persona),
        },
        "operating_principles": operating,
        "color_principles": color_principles,
    }
    if isinstance(spec, dict):
        briefing["spec_shape"] = {
            "keys": [
                k
                for k in (
                    "mark",
                    "encoding",
                    "layer",
                    "vconcat",
                    "hconcat",
                    "concat",
                    "title",
                    "data",
                )
                if k in spec
            ],
            "has_values": isinstance((spec.get("data") or {}).get("values"), list)
            if isinstance(spec.get("data"), dict)
            else False,
        }
    return briefing


def briefing_system_preamble(briefing: dict[str, Any]) -> str:
    """Render briefing as a slow-path system prompt preamble."""
    layers = briefing.get("layers") or {}
    l1 = layers.get("L1") or {}
    l2 = layers.get("L2") or {}
    l3 = layers.get("L3") or {}
    chart = briefing.get("chart") or {}
    appl = briefing.get("applicability") or {}
    lines = [
        str(briefing.get("role") or "").strip(),
        "",
        "## Institutional applicability",
        f"- suits: {', '.join(appl.get('suits') or []) or '—'}",
        f"- promises: {', '.join(appl.get('promises') or []) or '—'}",
        "",
        "## Input chart (programmatic facts)",
        str(chart.get("narrative") or "(no chart facts)"),
        "",
        "## User goal",
        str(briefing.get("user_goal") or "(no natural-language goal provided)"),
        "",
        "## L1 Dispositional Signature digest",
        f"- rule_counts: {json.dumps(l1.get('rule_counts') or {}, ensure_ascii=False)}",
        f"- brand/primary color: {l1.get('brand_color') or '—'}",
        f"- palette sample: {', '.join(l1.get('palette_sample') or []) or '—'}",
    ]
    for r in (l1.get("rule_samples") or [])[:5]:
        lines.append(f"  · [{r.get('strength')}] {r.get('id')}: {r.get('text')}")
    lines.extend(
        [
            "",
            "## L2 Characteristic Adaptations digest",
            f"- adaptation_count: {l2.get('adaptation_count', 0)}",
            f"- common intent/task: {', '.join(l2.get('intent_or_task_keys') or []) or '—'}",
        ]
    )
    for ad in (l2.get("samples") or [])[:5]:
        then = ad.get("then")
        then_s = then if isinstance(then, str) else json.dumps(then, ensure_ascii=False)
        lines.append(
            f"  · {ad.get('id')}: when={json.dumps(ad.get('when') or {}, ensure_ascii=False)} then={then_s}"
        )
    lines.extend(["", "## L3 Narrative Identity digest"])
    for p in (l3.get("philosophy") or [])[:4]:
        title = p.get("title") or ""
        lines.append(f"  · [{p.get('id')}] {title + ': ' if title else ''}{p.get('quote')}")
    for s in (l3.get("stories") or [])[:3]:
        lines.append(f"  · story[{s.get('id')}]: {s.get('story')}")
    lines.extend(
        [
            "",
            "## Color assignment principles (institutional)",
            f"- brand/primary: {l1.get('brand_color') or '—'}",
            f"- palette (ordered): {', '.join(l1.get('palette_sample') or []) or '—'}",
            f"- chart color_field: {chart.get('color_field') or '—'}",
            f"- per_category_coloring: {chart.get('per_category_coloring')}",
            f"- coloring_mode (if decided): {chart.get('coloring_mode') or 'pending'}",
        ]
    )
    for p in briefing.get("color_principles") or []:
        lines.append(f"  · {p}")
    lines.extend(["", "## Operating principles"])
    for i, p in enumerate(briefing.get("operating_principles") or [], 1):
        lines.append(f"{i}. {p}")
    return "\n".join(lines).strip()


def chrome_roles_system() -> str:
    """Live intake：裁决复合图层角色，供 extract→emit 决定保留/丢弃。"""
    return (
        "You classify layers of a multi-layer Vega-Lite / Datawrapper-style chart "
        "BEFORE the system rebuilds a clean working spec.\n"
        "POLICY: keep as much visual content as possible. Only drop true drawn-axis "
        "tick layers (role=drawn_axis). Callouts, center totals, arrows, and grids "
        "must be kept (annotation or secondary_data/grid)—do NOT mark them drawn_axis.\n"
        "Allowed roles: primary_data, secondary_data, grid, title, subtitle, source, "
        "annotation, drawn_axis.\n"
        "Critical distinctions:\n"
        "- primary_data: main data geometry (area/bar/line/arc/point with data fields).\n"
        "- secondary_data: data overlays (reference mean line; value labels ON marks "
        "where position channels bind data fields; donut/radial CENTER totals and "
        "hole-mask arcs with own tiny data and no x/y field).\n"
        "- grid: drawn gridlines (often rule layers) — KEEP.\n"
        "- title / subtitle / source: chart chrome text (including Source: lines); "
        "these are lifted to root title (content preserved).\n"
        "- annotation: decorative arrows, callouts, notes — KEEP (not dropped).\n"
        "- drawn_axis: ONLY fake axis tick labels — one channel is a pixel/constant "
        "value (e.g. y:value=303.8) and the other is a field, with text.field. "
        "These are dropped so standard VL axes can restore. "
        "Field likely_drawn_axis=true is a strong hint for drawn_axis.\n"
        "When unsure between annotation and drawn_axis, prefer annotation (keep).\n"
        "Return overrides whenever the heuristic role is wrong.\n"
        "Do not invent colors or ops.\n"
        'Output JSON only: {"overrides":[{"index":0,"role":"drawn_axis","rationale":"drawn x-axis ticks"}]} '
        "Use an empty overrides list only when every heuristic role is already correct."
    )


def intent_analyze_system(briefing: dict[str, Any] | None = None) -> str:
    """Intent-analyzer system prompt: institutional briefing first, then controlled JSON."""
    base = (
        "Under the institutional expert briefing above, you also act as an intent analyzer. "
        "Read the user's natural-language goal and chart facts, and classify into "
        "communication (emphasis/intent for the audience), edit (explicit component changes), or other. "
        "Emit ONE item per distinct focus when the goal covers multiple concerns "
        "(e.g. separate items for emphasis, intent, chart.type, color)—do not collapse into a single item. "
        "You may emit multiple items. Do not invent hex colors or actions not listed. "
        "When the user mentions color or the chart needs part/category distinction, "
        "emit a color focus item whose rationale names the needed coloring_mode "
        "(uniform|paired|categorical|highlight) per Color assignment principles—"
        "do not treat 'use the brand palette' as permission to paint every part the same hue. "
        "slots may only use: intent(comparison|trend|composition|distribution|correlation), "
        "emphasis_target(category name), chart_type, color_role(primary|accent|canvas), "
        "coloring_mode(uniform|paired|categorical|highlight), "
        "anchor(start|middle|end), orient(top|bottom|left|right). "
        'Output JSON only: {"kind":"communication|edit|mixed|other","summary":"one English sentence",'
        '"items":[{"kind":"communication|edit|other","focus":"emphasis|intent|chart.type|color|title|legend|none",'
        '"slots":{},"grounding":"persona_rule|persona_token|action_space|none","rationale":"one English sentence"}]}'
    )
    if not briefing:
        return base
    return briefing_system_preamble(briefing) + "\n\n## Current task\n" + base


def beat1_read_system(briefing: dict[str, Any] | None = None) -> str:
    task = (
        "You understand the chart from a compact chart_slice (NOT a full Vega-Lite dump), "
        "programmatic facts, and the user's communication goal. "
        "Use institutional judgment—do not rely on series_count alone. "
        "Produce a Decision IR for downstream norm detection. "
        "Treat the user goal primarily as communication intent; "
        "explicit edit requests are structured later by the intent analyzer—here identify "
        "data_topic, intent, emphasis_target, emphasis_field, emphasis_mechanism, "
        "coloring_mode, and a short organization note. "
        "Coloring_mode (required): apply the Color assignment principles above. "
        "Use categorical when color must distinguish parts/categories/identities "
        "(composition, parts-of-whole, 3+ color-coded groups)—even if series_count is 1. "
        "Use uniform only when a single institutional primary is enough and collapsing "
        "category colors would not erase meaningful distinctions. "
        "Use paired for two series; highlight when one category should stand out. "
        "Emphasis binding (required when emphasis_target is set): "
        "Read chart_slice.color_structure, category_field, color_field, "
        "category_samples, series_samples. "
        "emphasis_field MUST be the encoding field whose domain contains emphasis_target "
        "(e.g. Entity for a region name—never bind a series name to Year/time). "
        "emphasis_mechanism MUST be one of: "
        "series_scale (multi-series color.field — program will remap scale.range), "
        "literal_condition (value+condition dual-tone bars), "
        "category_condition (single-series category axis highlight). "
        "If color_structure is series_scale, use series_scale + color_field. "
        "If color_structure is literal_condition, use literal_condition. "
        "organization: one English sentence on how the chart is structured "
        "(e.g. layered area+line, dual series, composition donuts) for later adjudication. "
        'Output JSON only: {"data_topic": "one of business|health|environment|politics|science|culture|general",'
        '"intent": "one of comparison|trend|composition|distribution|correlation",'
        '"emphasis_target": "value worth emphasizing (or null)", '
        '"emphasis_field": "encoding field name or null", '
        '"emphasis_mechanism": "series_scale|literal_condition|category_condition|null", '
        '"coloring_mode": "one of uniform|paired|categorical|highlight", '
        '"organization": "one English sentence", '
        '"summary": "one English chart-reading sentence"}'
    )
    if not briefing:
        return "You are a data visualization editor.\n" + task
    return briefing_system_preamble(briefing) + "\n\n## Current task (Beat 1 · chart reading)\n" + task


def beat3_adjudicate_system(persona, briefing: dict[str, Any] | None = None) -> str:
    task = (
        "You are this institution's visualization design-norm adjudicator; stay faithful to its self-narrative.\n"
        f"Design philosophy:\n{persona.philosophy_text()}\n\n"
        "For each escalated item, decide with three branches:\n"
        "(a) Guide text warrants it (src has direct support and situation fits) → adopt, confidence high|medium;\n"
        "(b) Text is insufficient but design philosophy can derive it → adopt, confidence low, derived true;\n"
        "(c) No warrant → reject (prefer leaving the chart unchanged).\n"
        "Branch (b) is a real lane, not a formality: institutions are defined by their design "
        "philosophy as much as by written rules. When the chart shows a genuine problem inside the "
        "supplied action space and one of your philosophy principles clearly speaks to it, adopt with "
        "derived=true (confidence low) instead of rejecting for lack of verbatim text — and name the "
        "principle in the rationale. Philosophy-derived adoptions are how the institution's L3 layer "
        "becomes visible to the user; use them whenever they are genuinely warranted.\n"
        "Return exactly one verdict per input item id — cover every item, omit none.\n"
        "Each item may include chart_slice and chart_audit (hierarchy, axes, marks, labels, legend, accessibility). "
        "Use it to judge whether color/title/structure changes are warranted—do not guess "
        "from rule text alone.\n"
        "For title norms, treat chart_audit.hierarchy as ground truth about the current title's form: "
        "title_style is the observed casing (title_case violates a sentence-case norm), and "
        "title_generic_topic_label=true means the title merely names the topic without stating a takeaway. "
        "When a norm asks for a takeaway/descriptive title and title_generic_topic_label is true — especially "
        "when communication_goal names the story — prefer adopt; the actual wording is written downstream "
        "under fact-grounded verification, so adopting does not require you to invent copy here.\n"
        "First identify the concrete chart problem and its evidence, then decide whether this institution's "
        "rule is an appropriate remedy. The rationale must explain the observed problem, the guide evidence, "
        "and the expected visual effect.\n"
        "The payload may include persona_knowledge diagnostics, chart_type_guidance, palette_guidance, and conflicts. "
        "Use those structures as supporting IBM-specific knowledge, while still deciding only among supplied actions.\n"
        "Decide only within the given action_space / any_of / color_alternatives; "
        "do not invent new colors or numeric values.\n"
        "Color rules: obey Color assignment principles and facts.coloring_mode. "
        "If color_alternatives are provided, set coloring_choice to one of their ids "
        "(uniform|paired|categorical|highlight) that preserves meaningful distinctions—"
        "never adopt a uniform single-hue option when parts/categories must stay visually distinct "
        "(composition / categorical mode). Prefer guide-ordered palette subsets. "
        "If chart_slice.color.scale_range already matches the guide sequence for categorical mode, "
        "you may reject redundant recoloring.\n"
        "User intent analysis (communication/edit/mixed) is only for situation fit, emphasis target, and rule choice; "
        "it must not override guide evidence or expand the action space. If kind is communication/mixed and when "
        "aligns with user_intent_analysis.slots / facts.intent|emphasis_target, prefer adopt.\n"
        'Output JSON only: {"verdicts": [{"id": "...", "verdict": "adopt|reject", "confidence": "high|medium|low",'
        ' "derived": false, "strategy": "exact any_of text or null", '
        '"coloring_choice": "uniform|paired|categorical|highlight|null", '
        '"emphasis_target": "category name or null", '
        '"rationale": "one English sentence"}]}'
    )
    if not briefing:
        return f"You are the visualization design-norm adjudicator for {persona.name}.\n" + task
    return briefing_system_preamble(briefing) + "\n\n## Current task (Beat 3 · adjudication)\n" + task
