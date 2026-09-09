"""persona 表示层：三层装载、令牌索引与直注解析。"""


def test_builtin_personas_loaded(registry):
    ids = {p.id for p in registry.list()}
    assert {"bbc", "economist"} <= ids


def test_bbc_layers(registry):
    bbc = registry.get("bbc")
    assert len(bbc.rules) >= 10          # L1 无条件规则
    assert len(bbc.adaptations) >= 6     # L2 条件规范
    assert len(bbc.philosophy) >= 3      # L3 哲学
    assert len(bbc.stories) >= 5         # L3 理由故事
    assert bbc.applicability.get("suits")


def test_token_resolution(registry):
    bbc = registry.get("bbc")
    assert bbc.resolve_color("bbc-blue") == "#1380A1"
    assert bbc.resolve_color("{color.bbc-orange}") == "#FAAB18"
    palette = bbc.resolve_color_list("{palette.categorical}")
    assert palette[0] == "#1380A1" and len(palette) == 6

    eco = registry.get("economist")
    assert eco.resolve_color("chicago-20") == "#141F52"
    assert eco.resolve_color("#123456") == "#123456"
    assert eco.resolve_color("{color.不存在}") is None


def test_story_lookup(registry):
    bbc = registry.get("bbc")
    assert "BBC Blue" in bbc.story_text("n-consistency")
    meta = bbc.meta()
    assert meta["layers"]["l1_rules"] == len(bbc.rules)
    assert meta["brand_color"]


def test_semantic_token_alias_resolves_to_core_color():
    from app.core.persona import load_persona_dict

    persona = load_persona_dict(
        {
            "institution": {"id": "ebay-like", "name": "eBay-like"},
            "L1_signature": {
                "tokens": {
                    "color": {
                        "core": {"blue": {"500": "#3665F3"}},
                        "foreground": {"accent": "{color.core.blue.500}"},
                    }
                }
            },
        }
    )
    assert persona.resolve_color("{color.foreground.accent}") == "#3665F3"
