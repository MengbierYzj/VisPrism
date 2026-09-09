"""Parser Agent：分块覆盖、真实证据、三层映射与自然语言保留。"""
import json

from pathlib import Path

from app.core.parser_agent import (
    PERSONA_AUDIT_KEYS,
    PERSONA_CANONICAL_KEYS,
    _assemble_persona,
    _chunk_document,
    _deterministic_candidates,
    _heuristic_fragment,
    parse_guideline,
    split_persona_documents,
)


class FakeChunkLLM:
    mode = "live"

    async def chat_json(self, system: str, user: str, retries: int = 1):
        payload = json.loads(user)
        content = payload["content"]
        tokens = []
        requirements = []
        if 'font <- "Helvetica"' in content:
            tokens.append(
                {
                    "path": "font.family",
                    "value": "Helvetica",
                    "evidence": {"lines": "L2", "quote": 'font <- "Helvetica"'},
                }
            )
            requirements.append(
                {
                    "classification": "L1",
                    "requirement": "所有图表文字使用 Helvetica",
                    "strength": "must",
                    "when": {},
                    "then": {"set": "font.family", "to": "{font.family}"},
                    "reason": "保持出版图形一致",
                    "evidence": {"lines": "L2", "quote": 'font <- "Helvetica"'},
                }
            )
        if "legend.position = \"top\"" in content:
            requirements.extend(
                [
                    {
                        "classification": "L1",
                        "requirement": "图例默认置于图表顶部",
                        "strength": "should",
                        "when": {},
                        "then": {"set": "legend.orient", "to": "top"},
                        "reason": "",
                        "evidence": {
                            "lines": "L3",
                            "quote": 'legend.position = "top"',
                        },
                    },
                    {
                        "classification": "L1",
                        "requirement": "优先直接标注数据，避免依赖图例",
                        "strength": "should",
                        "when": {},
                        "then": None,
                        "reason": "直接标注更易理解",
                        "evidence": {
                            "lines": "L4",
                            "quote": "it’s better to label data directly",
                        },
                    },
                ]
            )
        if "single series uses blue" in content:
            tokens.append(
                {
                    "path": "color.primary",
                    "value": "#1380A1",
                    "evidence": {
                        "lines": "L220",
                        "quote": "single series uses blue #1380A1",
                    },
                }
            )
            requirements.append(
                {
                    "classification": "L2",
                    "requirement": "单序列使用主蓝色",
                    "strength": "should",
                    "when": {"series_count": 1},
                    "then": {"set": "mark.color", "to": "{color.primary}"},
                    "reason": "",
                    "evidence": {
                        "lines": "L220",
                        "quote": "single series uses blue #1380A1",
                    },
                }
            )
        return {"tokens": tokens, "requirements": requirements}


class RecordingChunkLLM:
    mode = "live"

    def __init__(self):
        self.contents = []

    async def chat_json(self, system: str, user: str, retries: int = 1):
        content = json.loads(user)["content"]
        self.contents.append(content)
        return {"tokens": [], "requirements": []}


class OneRuleChunkLLM:
    mode = "live"

    async def chat_json(self, system: str, user: str, retries: int = 1):
        payload = json.loads(user)
        line = payload["content"].split(":", 1)[1]
        return {
            "tokens": [
                {
                    "path": "color.primary",
                    "value": "#123456",
                    "evidence": {"lines": "L1", "quote": line},
                }
            ],
            "requirements": [
                {
                    "classification": "L1",
                    "requirement": "主系列必须使用品牌色",
                    "strength": "must",
                    "when": {},
                    "then": {"set": "mark.color", "to": "{color.primary}"},
                    "reason": "",
                    "evidence": {"lines": "L1", "quote": line},
                }
            ],
        }


def test_chunk_document_covers_full_source():
    text = "\n".join(f"line {i} " + ("x" * 80) for i in range(250))
    chunks = _chunk_document(text, max_chars=1000)
    assert len(chunks) > 2
    assert chunks[0]["start"] == 1
    assert chunks[-1]["end"] == 250
    assert sum(c["end"] - c["start"] + 1 for c in chunks) == 250


def test_live_parser_uses_configured_smaller_chunks(monkeypatch):
    import asyncio

    monkeypatch.setenv("VIZGUIDE_PARSER_CHUNK_CHARS", "1000")
    llm = RecordingChunkLLM()
    text = "\n".join(f"line {i} " + ("x" * 80) for i in range(80))

    asyncio.run(parse_guideline("Chunk Test", text, llm))

    assert len(llm.contents) > 4
    assert max(len(content) for content in llm.contents) < 1300


def test_failed_quality_gate_keeps_successful_live_fragments():
    import asyncio

    text = "Brand swatch #123456 must be used for the main series."
    data, warnings = asyncio.run(parse_guideline("Partial", text, OneRuleChunkLLM()))

    assert data["parser_provenance"]["mode"] == "quality-failed"
    assert data["L1_signature"]["tokens"]["color"]["primary"] == "#123456"
    assert len(data["L1_signature"]["rules"]) == 1
    assert any("仍未通过质量门" in warning for warning in warnings)


def test_assemble_rejects_placeholder_and_ungrounded_condition():
    text = "real requirement\nUse a top legend\nExample: life expectancy in Malawi"
    fragments = [
        {
            "tokens": [],
            "requirements": [
                {
                    "classification": "L1",
                    "requirement": "泛化规则",
                    "evidence": {"lines": "原文行号/段落", "quote": "占位"},
                },
                {
                    "classification": "L2",
                    "requirement": "健康主题使用绿色",
                    "when": {"data_topic": ["health"]},
                    "then": {"set": "mark.color", "to": "#00FF00"},
                    "evidence": {
                        "lines": "L3",
                        "quote": "Example: life expectancy in Malawi",
                    },
                },
            ],
        }
    ]
    data, warnings = _assemble_persona("Test", text, fragments, 1)
    assert not data["L2_adaptations"]
    assert data["parser_provenance"]["rejected_items"] >= 1
    assert data["evidence_catalog"]["examples"]
    assert any("示例条件不得提升" in w for w in warnings)


def test_quality_gate_counts_only_rules_that_compile_to_ops():
    text = "Always use the primary color.\nAlways use the accent color."
    fragments = [
        {
            "tokens": [],
            "requirements": [
                {
                    "classification": "L1",
                    "requirement": "始终使用主色",
                    "strength": "must",
                    "when": {},
                    "then": {"set": "mark.color", "to": "{color.primary}"},
                    "evidence": {"lines": "L1", "quote": text.splitlines()[0]},
                },
                {
                    "classification": "L1",
                    "requirement": "始终使用强调色",
                    "strength": "must",
                    "when": {},
                    "then": {"set": "mark.color", "to": "{color.accent}"},
                    "evidence": {"lines": "L2", "quote": text.splitlines()[1]},
                },
            ],
        }
    ]

    data, _ = _assemble_persona("Missing Tokens", text, fragments, 1)

    assert "可执行 L1/L2 规范少于 2 条" in data["parser_provenance"]["quality_errors"]
    assert "未提取到有证据的设计令牌" in data["parser_provenance"]["quality_errors"]


def test_quality_gate_allows_narrative_guide_without_color_tokens():
    """Apple 类 HIG：无 hex 令牌，但 ≥2 条 prefer chart.type 应过门。"""
    text = (
        "Bar marks work well in charts that help people compare values.\n"
        "Line marks can also show how values change over time.\n"
        "Point marks help you depict individual data values."
    )
    fragments = [
        {
            "tokens": [],
            "requirements": [
                {
                    "classification": "L2",
                    "requirement": "Use bar marks for comparisons",
                    "strength": "should",
                    "when": {"intent": "comparison"},
                    "then": {"prefer": "chart.type", "to": "bar"},
                    "evidence": {"lines": "L1", "quote": text.splitlines()[0]},
                },
                {
                    "classification": "L2",
                    "requirement": "Use line marks for trends over time",
                    "strength": "should",
                    "when": {"intent": "trend"},
                    "then": {"prefer": "chart.type", "to": "line"},
                    "evidence": {"lines": "L2", "quote": text.splitlines()[1]},
                },
                {
                    "classification": "L2",
                    "requirement": "Use point marks for individual values",
                    "strength": "should",
                    "when": {"intent": "correlation"},
                    "then": {"prefer": "chart.type", "to": "point"},
                    "evidence": {"lines": "L3", "quote": text.splitlines()[2]},
                },
            ],
        }
    ]
    data, warnings = _assemble_persona("Apple", text, fragments, 1)
    assert not data["parser_provenance"]["quality_errors"]
    assert len(data["L2_adaptations"]) >= 2
    assert any("可无色板" in w for w in warnings)


def test_prefer_counts_for_quality_gate_even_in_suggest_mode(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_PREFER_MODE", "suggest")
    text = (
        "Bar marks work well for comparing categories.\n"
        "Line marks show change over time."
    )
    fragments = [
        {
            "tokens": [],
            "requirements": [
                {
                    "classification": "L2",
                    "requirement": "prefer bar",
                    "strength": "should",
                    "when": {"intent": "comparison"},
                    "then": {"prefer": "chart.type", "to": "bar"},
                    "evidence": {"lines": "L1", "quote": text.splitlines()[0]},
                },
                {
                    "classification": "L2",
                    "requirement": "prefer line",
                    "strength": "should",
                    "when": {"intent": "trend"},
                    "then": {"prefer": "chart.type", "to": "line"},
                    "evidence": {"lines": "L2", "quote": text.splitlines()[1]},
                },
            ],
        }
    ]
    data, _ = _assemble_persona("HIG", text, fragments, 1)
    assert not data["parser_provenance"]["quality_errors"]


def test_llm_organization_pass_merges_chunk_candidates():
    import asyncio

    class OrgLLM:
        mode = "live"

        async def chat_json(self, system: str, user: str, retries: int = 1):
            payload = json.loads(user)
            # 整编调用
            if "candidates" in payload:
                return {
                    "tokens": [],
                    "requirements": [
                        {
                            "classification": "L2",
                            "requirement": "Bar for compare",
                            "strength": "should",
                            "when": {"intent": "comparison"},
                            "then": {"prefer": "chart.type", "to": "bar"},
                            "evidence": {
                                "lines": "L1",
                                "quote": "Bar marks work well for comparing values.",
                            },
                        },
                        {
                            "classification": "L2",
                            "requirement": "Line for trends",
                            "strength": "should",
                            "when": {"intent": "trend"},
                            "then": {"prefer": "chart.type", "to": "line"},
                            "evidence": {
                                "lines": "L2",
                                "quote": "Line marks show change over time.",
                            },
                        },
                    ],
                }
            # 分块抽取：每块回一条
            content = payload["content"]
            line = content.split(":", 1)[1].strip() if ":" in content else content
            if "Bar" in line:
                return {
                    "tokens": [],
                    "requirements": [
                        {
                            "classification": "L2",
                            "requirement": "bar dup",
                            "strength": "should",
                            "when": {"intent": "comparison"},
                            "then": {"prefer": "chart.type", "to": "bar"},
                            "evidence": {"lines": "L1", "quote": line},
                        }
                    ],
                }
            return {
                "tokens": [],
                "requirements": [
                    {
                        "classification": "L2",
                        "requirement": "line dup",
                        "strength": "should",
                        "when": {"intent": "trend"},
                        "then": {"prefer": "chart.type", "to": "line"},
                        "evidence": {"lines": "L2", "quote": line},
                    }
                ],
            }

    text = (
        "Bar marks work well for comparing values.\n"
        "Line marks show change over time.\n"
    )
    data, warnings = asyncio.run(parse_guideline("Apple Org", text, OrgLLM()))
    assert not data["parser_provenance"]["quality_errors"]
    assert data["parser_provenance"].get("organization") == "llm"
    assert any("整编" in w for w in warnings)
    assert len(data["L2_adaptations"]) >= 2


def test_natural_language_requirement_is_preserved():
    text = "Prefer direct labels because they are easier to understand."
    fragments = [
        {
            "tokens": [
                {
                    "path": "color.primary",
                    "value": "#1380A1",
                    "evidence": {"lines": "L1", "quote": "Prefer direct labels"},
                }
            ],
            "requirements": [
                {
                    "classification": "L1",
                    "requirement": "优先使用直接标注",
                    "strength": "should",
                    "when": {},
                    "then": None,
                    "reason": "更容易理解",
                    "evidence": {
                        "lines": "L1",
                        "quote": "Prefer direct labels because they are easier to understand.",
                    },
                },
                {
                    "classification": "L1",
                    "requirement": "避免仅依靠图例",
                    "strength": "should",
                    "when": {},
                    "then": None,
                    "reason": "",
                    "evidence": {
                        "lines": "L1",
                        "quote": "Prefer direct labels because they are easier to understand.",
                    },
                },
            ],
        }
    ]
    data, _ = _assemble_persona("Test", text, fragments, 1)
    assert not data["L1_signature"]["rules"]
    assert len(data["L3_narrative"]["stories"]) == 2
    assert all("then" not in story for story in data["L3_narrative"]["stories"])


async def _parse_with_fake():
    lines = [
        "# Guide",
        'font <- "Helvetica"',
        'legend.position = "top"',
        "it’s better to label data directly",
    ]
    lines.extend(f"filler {i} " + ("x" * 60) for i in range(5, 220))
    lines.append("single series uses blue #1380A1")  # L220
    return await parse_guideline("BBC Cookbook", "\n".join(lines), FakeChunkLLM())


def test_live_parser_maps_three_layers_and_executable_rules():
    import asyncio

    data, warnings = asyncio.run(_parse_with_fake())
    assert data["parser_provenance"]["chunks"] > 1
    assert data["parser_provenance"]["mode"] == "live-chunked"
    assert len(data["L1_signature"]["rules"]) >= 1
    assert len(data["L2_adaptations"]) == 1
    assert len(data["L3_narrative"]["stories"]) >= 1
    assert any(r.get("then", {}).get("set") == "font.family" for r in data["L1_signature"]["rules"])
    assert any(r["strength"] in ("must", "never") for r in data["L1_signature"]["rules"])
    assert all(r["strength"] in ("must", "never", "should", "may") for r in data["L1_signature"]["rules"])
    assert data["L2_adaptations"][0]["when"] == {"series_count": 1}
    assert warnings[0].startswith("分块解析完成")


def test_strict_layer_gate_moves_conditional_l1_to_l2():
    text = "When there is one series, use blue #1380A1."
    fragments = [
        {
            "tokens": [
                {
                    "path": "color.primary",
                    "value": "#1380A1",
                    "evidence": {"lines": "L1", "quote": text},
                }
            ],
            "requirements": [
                {
                    "classification": "L1",
                    "requirement": "单序列使用蓝色",
                    "strength": "must",
                    "when": {"series_count": 1},
                    "then": {"set": "mark.color", "to": "{color.primary}"},
                    "evidence": {"lines": "L1", "quote": text},
                }
            ],
        }
    ]
    data, warnings = _assemble_persona("Test", text, fragments, 1)
    assert not data["L1_signature"]["rules"]
    assert len(data["L2_adaptations"]) == 1
    assert data["L2_adaptations"][0]["when"] == {"series_count": 1}
    assert any("已重分类为 L2" in warning for warning in warnings)


def test_strict_layer_gate_keeps_l3_non_executable():
    text = "Less is more because decoration distracts from the story."
    fragments = [
        {
            "tokens": [],
            "requirements": [
                {
                    "classification": "L3-philosophy",
                    "requirement": "Less is more",
                    "strength": "must",
                    "when": {"chart_type": "bar"},
                    "then": {"set": "mark.color", "to": "#000000"},
                    "evidence": {"lines": "L1", "quote": text},
                }
            ],
        }
    ]
    data, _ = _assemble_persona("Test", text, fragments, 1)
    assert not data["L1_signature"]["rules"]
    assert not data["L2_adaptations"]
    assert data["L3_narrative"]["philosophy"][0]["quote"] == "Less is more"


def test_principle_label_is_reclassified_from_l1_to_l3():
    text = (
        "Accessibility: Charts must work for all audiences, including those with "
        "visual impairments"
    )
    fragments = [
        {
            "tokens": [],
            "requirements": [
                {
                    "classification": "L1",
                    "requirement": "Charts must work for all audiences",
                    "strength": "must",
                    "when": {},
                    "then": None,
                    "evidence": {"lines": "L1", "quote": text},
                }
            ],
        }
    ]

    data, warnings = _assemble_persona("Principles", text, fragments, 1)

    assert not data["L1_signature"]["rules"]
    assert data["L3_narrative"]["philosophy"]
    assert any("抽象原则不属于 L1" in warning for warning in warnings)


def test_named_semantic_token_tree_stays_in_l1():
    text = "color.foreground.accent maps to color.core.blue.500"
    fragments = [
        {
            "tokens": [
                {
                    "path": "color.foreground.accent",
                    "value": "{color.core.blue.500}",
                    "evidence": {"lines": "L1", "quote": text},
                }
            ],
            "requirements": [],
        }
    ]
    data, _ = _assemble_persona("Token System", text, fragments, 1)
    assert (
        data["L1_signature"]["tokens"]["color"]["foreground"]["accent"]
        == "{color.core.blue.500}"
    )
    assert not data["L2_adaptations"]


def test_ibm_scale_prefixed_colors_are_normalized():
    text = (
        "Primary color: Purple 706929c4\n"
        "Categorical palette: Purple 706929c4, Cyan 501192e8"
    )
    fragments = [
        {
            "tokens": [
                {
                    "path": "color.primary",
                    "value": "706929c4",
                    "evidence": {"lines": "L1", "quote": text.splitlines()[0]},
                },
                {
                    "path": "palette.categorical",
                    "value": ["706929c4", "501192e8"],
                    "evidence": {"lines": "L2", "quote": text.splitlines()[1]},
                },
            ],
            "requirements": [],
        }
    ]

    data, _ = _assemble_persona("IBM", text, fragments, 1)

    tokens = data["L1_signature"]["tokens"]
    assert tokens["color"]["primary"] == "#6929C4"
    assert tokens["palette"]["categorical"] == ["#6929C4", "#1192E8"]
    assert data["parser_provenance"]["rejected_items"] == 0


def test_scale_prefixed_hex_rejects_partial_llm_color_hallucination():
    """色阶串的前六位不是颜色值，不能被子串证据校验放行。"""
    text = "Alert palette: Red 60da1e28, Orange 40ff832b"
    fragments = [
        {
            "tokens": [
                {
                    "path": "color.alert.red",
                    "value": "#60DA1E",  # 错误地截取了 ``60da1e28`` 前六位
                    "evidence": {"lines": "L1", "quote": text},
                },
                {
                    "path": "color.alert.orange",
                    "value": "#FF832B",
                    "evidence": {"lines": "L1", "quote": text},
                },
            ],
            "requirements": [],
        }
    ]

    data, _ = _assemble_persona("IBM", text, fragments, 1)

    colors = data["L1_signature"]["tokens"]["color"]["alert"]
    assert "red" not in colors
    assert colors["orange"] == "#FF832B"
    assert data["parser_provenance"]["rejected_items"] == 1


def test_primary_secondary_design_system_table_becomes_derived_executable_palette():
    """无 categorical 标题的设计系统色表也可生成有留痕的 advisor 规则。"""
    text = (
        "Primary\n"
        "Chicago 20  #141F52\n"
        "Chicago 30  #1F2E7A\n"
        "Secondary:\n"
        "Hong Kong 45  #1DC9A4\n"
        "Tokyo 45  #C91D42\n"
        "Greyscale\n"
    )
    data, _ = _assemble_persona(
        "Economist", text, [_deterministic_candidates(text)], 1
    )

    tokens = data["L1_signature"]["tokens"]
    assert tokens["color"]["primary"] == "#141F52"
    assert tokens["color"]["secondary"] == "#1DC9A4"
    assert tokens["palette"]["categorical"][:2] == ["#141F52", "#1F2E7A"]
    assert not data["parser_provenance"]["quality_errors"]
    assert all(item["derived"] for item in data["L2_adaptations"])


def test_bullet_heading_principles_become_l3_philosophy():
    text = (
        "## Principles\n"
        "- Less is more\n"
        "Be concise and focus on the essential through iteration and reduction.\n"
        "- Visual harmony\n"
        "Our grid system supports recognisable patterns through symmetry and proximity.\n"
        "### Color palettes\n"
    )
    data, _ = _assemble_persona(
        "Economist", text, [_deterministic_candidates(text)], 1
    )

    philosophy = data["L3_narrative"]["philosophy"]
    assert [(item["title"], item["quote"]) for item in philosophy] == [
        ("Less is more", "Be concise and focus on the essential through iteration and reduction."),
        ("Visual harmony", "Our grid system supports recognisable patterns through symmetry and proximity."),
    ]


def test_generic_named_palette_and_default_legend_become_executable(example_spec):
    from app.core.beats import beat2_detect, beat4_compile
    from app.core.persona import load_persona_dict
    from app.core.specfacts import extract_facts

    text = (
        "Categorical palettes\n"
        "- Light mode:\n"
        "  1. Azure 70123456\n"
        "  2. Coral 50abcdef\n"
        "Legends are positioned at the bottom by default."
    )
    data, _ = _assemble_persona(
        "Northstar", text, [_deterministic_candidates(text)], 1
    )

    tokens = data["L1_signature"]["tokens"]
    assert tokens["palette"]["categorical"] == ["#123456", "#ABCDEF"]
    assert tokens["color"]["primary"] == "#123456"
    assert not data["parser_provenance"]["quality_errors"]
    assert any(
        rule.get("then") == {"set": "legend.orient", "to": "bottom"}
        for rule in data["L1_signature"]["rules"]
    )
    palette_rule = next(
        item
        for item in data["L2_adaptations"]
        if item.get("then", {}).get("set") == "color.range"
    )
    primary_rule = next(
        item
        for item in data["L2_adaptations"]
        if item.get("then", {}).get("set") == "mark.color"
    )
    assert primary_rule["when"] == {"color_count": {"lte": 1}}

    persona = load_persona_dict(data)
    facts = extract_facts(example_spec)
    candidates, escalations, _, _, _ = beat2_detect(persona, example_spec, facts)
    applied_palette = next(
        (item for item in candidates if item["rule_id"] == palette_rule["id"]),
        None,
    )
    if applied_palette is None:
        # color.range 可能因 coloring_mode 升级慢道，仍须带可执行 compiled ops
        esc = next(item for item in escalations if item["rule_id"] == palette_rule["id"])
        ops = (esc.get("compiled") or {}).get("ops") or []
    else:
        ops = applied_palette["ops"]
    assert ops == [
        {"action": "set_color_range", "colors": ["#123456", "#ABCDEF"]}
    ]

    mono_spec = {
        "mark": "bar",
        "data": {"values": [{"c": "A", "v": 1}, {"c": "B", "v": 2}]},
        "encoding": {
            "x": {"field": "c", "type": "nominal"},
            "y": {"field": "v", "type": "quantitative"},
        },
    }
    mono_facts = extract_facts(mono_spec)
    mono_candidates, _, _, _, _ = beat2_detect(persona, mono_spec, mono_facts)
    assert any(item["rule_id"] == primary_rule["id"] for item in mono_candidates)
    modified, _, _, _ = beat4_compile(
        persona, mono_spec, mono_facts, mono_candidates, [], []
    )
    assert modified["mark"]["color"] == "#123456"


def test_chart_recommend_sections_become_l2_prefer_rules():
    text = (
        "Chart:\n"
        "- Comparisons:\n"
        "  - Charts designed for comparison aim to visualize differences.\n"
        "  - Recommend chart: Simple bar、Grouped bar、Lollipop\n"
        "- Trends:\n"
        "  - Trend charts track change over time.\n"
        "  - Recommend chart: Line、Area\n"
        "Design principle:\n"
        "- Clarity: An institutional visualization should communicate a message "
        "at a glance without gratuitous decoration or ambiguity in the encoding.\n"
    )
    data, _ = _assemble_persona(
        "Atlas", text, [_deterministic_candidates(text)], 1
    )

    intents = {
        str(item["when"].get("intent")): item
        for item in data["L2_adaptations"]
        if isinstance(item.get("when"), dict) and "intent" in item["when"]
    }
    assert "comparison" in intents
    assert intents["comparison"]["then"]["prefer"] == "chart.type"
    assert intents["comparison"]["then"]["to"] == "bar"
    assert "trend" in intents
    assert intents["trend"]["then"]["to"] == "line"
    phil = data["L3_narrative"]["philosophy"]
    assert any(p.get("title") == "Clarity" for p in phil)
    assert all(p.get("title") != "Recommend chart" for p in phil)


def test_unconditional_should_rules_stay_in_l1():
    text = (
        "The title should reflect the main insight the data reveals. "
        "Use concise titles.\n"
        "Gradients should not be used to represent any meaningful progression "
        "or divergence."
    )
    data, _ = _assemble_persona(
        "Guide", text, [_deterministic_candidates(text)], 1
    )
    rules = data["L1_signature"]["rules"]
    assert any(r["strength"] == "should" and "标题" in r["rule"] for r in rules)
    assert any(r["strength"] == "never" and "渐变" in r["rule"] for r in rules)
    assert all(r["check"] == "llm" for r in rules if "标题" in r["rule"] or "渐变" in r["rule"])


def test_heuristic_keywords_use_word_boundaries():
    text = (
        "Landmark labels:Whenever data crosses into a new year, semibold the label.\n"
        "Never truncate labels."
    )
    fragment = _heuristic_fragment(text)

    whenever = next(
        item for item in fragment["requirements"] if item["evidence"]["lines"] == "L1"
    )
    never = next(
        item for item in fragment["requirements"] if item["evidence"]["lines"] == "L2"
    )
    assert whenever["classification"] == "L2"
    assert whenever["strength"] == "should"
    assert never["classification"] == "L1"
    assert never["strength"] == "never"

    data, warnings = _assemble_persona("Boundary", text, [fragment], 1)
    assert not any(
        item["src"] == "L1" for item in data["L2_adaptations"]
    ), "整句回填 context 不得升格为 L2"
    assert any(item["src"] == "L1" for item in data["unmapped_requirements"])
    assert any("条件仅为原文回填" in warning for warning in warnings)


def test_bbc_cookbook_repeated_colors_become_derived_l2_rules(example_spec):
    from app.core.beats import beat2_detect
    from app.core.persona import load_persona_dict
    from app.core.specfacts import extract_facts

    root = Path(__file__).resolve().parents[2]
    text = (root / "guideline" / "bbc-rcookbook.md").read_text(encoding="utf-8")
    fragment = _deterministic_candidates(text)
    data, _ = _assemble_persona("BBC Cookbook", text, [fragment], 1)

    tokens = data["L1_signature"]["tokens"]
    assert tokens["color"]["primary"].lower() == "#1380a1"
    assert tokens["color"]["accent"].lower() == "#faab18"
    assert len(tokens["palette"]["categorical"]) >= 4

    adaptations = data["L2_adaptations"]
    single = next(item for item in adaptations if item["when"] == {"series_count": 1})
    two = next(item for item in adaptations if item["when"] == {"series_count": 2})
    assert single["then"] == {"set": "mark.color", "to": "{color.primary}"}
    assert two["then"] == {"set": "color.range", "to": "{palette.two_series}"}
    assert single["derived"] is True and len(single["pattern_sources"]) >= 2

    persona = load_persona_dict(data)
    candidates, _, _, _, _ = beat2_detect(
        persona,
        example_spec,
        extract_facts(example_spec),
    )
    color_candidate = next(item for item in candidates if item["rule_id"] == single["id"])
    assert color_candidate["ops"][-1] == {"action": "set_mark_color", "color": "#1380A1"}


def test_reference_style_bbc_guide_compiles_executable_persona(example_spec):
    from app.core.beats import beat2_detect, beat4_compile
    from app.core.persona import load_persona_dict
    from app.core.specfacts import extract_facts

    root = Path(__file__).resolve().parents[2]
    text = (root / "data" / "bbc.md").read_text(encoding="utf-8")
    duplicate_llm_fragment = {
        "tokens": [],
        "requirements": [
            {
                "classification": "L2",
                "requirement": "Use BBC Blue for consistency when presenting a single series",
                "strength": "must",
                "when": {"condition": "Single Series"},
                "then": None,
                "evidence": {
                    "lines": "L36",
                    "quote": "1. Single Series: Use BBC Blue for consistency",
                },
            }
        ],
    }
    data, _ = _assemble_persona(
        "BBC Reference",
        text,
        [_deterministic_candidates(text), duplicate_llm_fragment],
        1,
    )

    tokens = data["L1_signature"]["tokens"]
    assert tokens["color"]["primary"] == "#1380A1"
    assert tokens["color"]["secondary"] == "#FAAB18"
    assert tokens["color"]["grid"] == "#cbcbcb"
    assert tokens["font"]["family"] == "Helvetica"
    assert tokens["font"]["size"]["title"] == 28
    assert len(tokens["palette"]["categorical"]) >= 4

    rules = data["L1_signature"]["rules"]
    adaptations = data["L2_adaptations"]
    assert sum(rule["check"] == "programmatic" for rule in rules) >= 6
    assert any(item["when"] == {"series_count": 1} for item in adaptations)
    assert any(item["when"] == {"series_count": 2} for item in adaptations)
    assert any(item["when"] == {"medium": "digital"} for item in adaptations)
    neutral = next(item for item in adaptations if item["when"] == {"data_role": "supporting"})
    assert neutral["check"] == "llm"
    assert all(
        item["src"] != "L36" or item["check"] == "programmatic"
        for item in adaptations
    )
    assert not any(item["src"] == "L36" for item in data["unmapped_requirements"])
    assert not data["parser_provenance"]["quality_errors"]
    assert len(data["L3_narrative"]["philosophy"]) >= 4
    assert {p.get("title") for p in data["L3_narrative"]["philosophy"]} >= {
        "Clarity First",
        "Accessibility",
        "Professional Consistency",
        "Editorial Integrity",
    }
    assert not any(
        "Charts must work for all audiences" in rule["rule"] for rule in rules
    )

    persona = load_persona_dict(data)
    candidates, _, _, _, _ = beat2_detect(
        persona,
        example_spec,
        extract_facts(example_spec),
    )
    actions = [op["action"] for item in candidates for op in item.get("ops", [])]
    assert "set_mark_color" in actions
    assert "set_font" in actions
    assert "merge_config" in actions
    assert "set_subtitle" in actions or "set_source_note" in actions
    assert not any(
        op.get("action") == "set_mark_color" and op.get("color") == "#333333"
        for item in candidates
        for op in item.get("ops", [])
    )

    modified, changes, _, _ = beat4_compile(
        persona,
        example_spec,
        extract_facts(example_spec),
        candidates,
        [],
        [],
    )
    assert modified["width"] == 640 and modified["height"] == 450
    assert modified["mark"]["color"] == "#1380A1"
    assert modified["config"]["axisY"]["gridColor"] == "#cbcbcb"
    assert modified["config"]["axisX"]["grid"] is False
    assert any(change["status"] == "applied" for change in changes)


def test_custom_structured_l1_rule_compiles_without_registered_id(example_spec):
    from app.core.detectors import detect_rule
    from app.core.persona import load_persona_dict
    from app.core.specfacts import extract_facts

    persona = load_persona_dict(
        {
            "institution": {"id": "custom", "name": "Custom"},
            "L1_signature": {
                "tokens": {"font": {"family": "Helvetica"}},
                "rules": [
                    {
                        "id": "s-custom-font",
                        "rule": "使用 Helvetica",
                        "check": "programmatic",
                        "then": {"set": "font.family", "to": "{font.family}"},
                        "src": "L1",
                    }
                ],
            },
        }
    )
    detection = detect_rule(
        persona,
        persona.rules[0],
        example_spec,
        extract_facts(example_spec),
    )
    assert detection is not None and detection.violated
    assert detection.ops == [{"action": "set_font", "family": "Helvetica"}]


def test_persona_document_matches_bbc_economist_shape():
    """落盘主 YAML 仅含范例三层键；审计进 sidecar。"""
    text = (
        "Acme\ntype: journalism\n"
        "Design principle:\n"
        "- Clarity: Keep charts clear and simple.\n"
        "- Primary color #1380A1 must be used for the main series\n"
        "- Never use more than 3 colors\n"
        "- Secondary color #FAAB18 for emphasis\n"
        "Chart:\n"
        "- Comparisons:\n"
        "  - Recommend chart: Simple bar、Grouped bar\n"
    )
    data, _ = _assemble_persona("Acme", text, [_deterministic_candidates(text)], 1)
    assert set(PERSONA_CANONICAL_KEYS).issubset(data.keys())
    assert "exemplars" in data["L3_narrative"]
    persona_doc, audit_doc = split_persona_documents(data)
    assert list(persona_doc.keys()) == list(PERSONA_CANONICAL_KEYS)
    assert set(audit_doc.keys()) <= set(PERSONA_AUDIT_KEYS)
    assert "unmapped_requirements" not in persona_doc
    assert "parser_provenance" not in persona_doc
    assert "evidence_catalog" not in persona_doc


def test_parser_prompts_require_section_coverage_and_keep_l3_institutional():
    """避免 IBM/Carbon 色板指南只抄 token、并把操作性小节泛滥地塞进 L3。"""
    from app.core.parser_agent import EXTRACTION_GUIDE, ORGANIZATION_GUIDE

    assert "Color 章节必须同时抽取 token 与选择策略" in EXTRACTION_GUIDE
    assert "Chart anatomy / Legend / Axes / Time series 建立覆盖清单" in EXTRACTION_GUIDE
    assert "同义 intent 统一为 comparison、trend、" in ORGANIZATION_GUIDE
    assert "part-to-whole、correlation、relationship、map" in ORGANIZATION_GUIDE
    assert "章节标题\n和操作性小节不得进入 L3" in ORGANIZATION_GUIDE


def test_ibm_carbon_rgba_palette_blocks_are_extracted():
    from app.core.parser_agent import _deterministic_candidates

    root = Path(__file__).resolve().parents[2]
    text = (root / "data" / "vizguide" / "IBM.md").read_text(encoding="utf-8")
    paths = {item.get("path") for item in _deterministic_candidates(text).get("tokens", [])}
    assert "palette.sequential" in paths
    assert "palette.diverging" in paths
