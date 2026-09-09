"""扩展机构人格库：8 个内置 persona 的装载、令牌解析与 mock 全流程产出。"""

NEW_IDS = {"cmu", "cfpb", "who", "ibm", "ebay", "shopify"}
ALL_IDS = NEW_IDS | {"bbc", "economist"}


def test_eight_builtin_personas_loaded(registry):
    ids = {p.id for p in registry.list() if p.kind == "builtin"}
    assert ALL_IDS <= ids


def test_new_personas_have_three_layers(registry):
    for pid in sorted(NEW_IDS):
        p = registry.get(pid)
        assert p is not None, pid
        assert len(p.rules) >= 5, pid          # L1 无条件规则
        assert len(p.adaptations) >= 5, pid    # L2 条件规范
        assert len(p.philosophy) >= 3, pid     # L3 哲学（原文引言）
        assert len(p.stories) >= 5, pid        # L3 理由故事
        assert p.applicability.get("suits"), pid
        meta = p.meta()
        assert meta["brand_color"] and meta["palette"], pid
        # 每条 L1/L2 都有出处行号（溯源硬约束）
        assert all(r.src for r in p.rules), pid
        assert all(a.src for a in p.adaptations), pid


def test_new_persona_token_resolution(registry):
    assert registry.get("cmu").resolve_color("{color.cmu-red}") == "#c41230"
    assert len(registry.get("cfpb").resolve_color_list("{palette.categorical}")) == 5
    assert registry.get("who").resolve_color("{color.other}") == "#cccccc"
    assert len(registry.get("ibm").resolve_color_list("{palette.categorical}")) == 14
    assert registry.get("ebay").resolve_color("{color.accent}") == "#3665f3"
    assert registry.get("shopify").resolve_color("{color.viz-purple}") == "#9c6ade"


def test_abbr_and_fullname_hints(client):
    metas = {p["id"]: p for p in client.get("/api/personas").json()["personas"]}
    assert metas["cfpb"]["abbr"] == "CFPB"
    assert metas["economist"]["abbr"] == "ECO"
    assert metas["shopify"]["abbr"] == "SHOP"
    assert metas["who"]["full_name"] == "World Health Organization"


def test_new_personas_mock_run_produces_changes(client, example_spec):
    """六个新机构在 mock 模式下对示例图都要产出可展示的修改（画板效果的底线）。"""
    goal = "Emphasize the huge gap between reported and solved cases."
    r = client.post(
        "/api/advisor/run?wait=true",
        json={
            "spec": example_spec,
            "persona_ids": sorted(NEW_IDS),
            "context": {"communication_goal": goal},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    agents = {a["persona_id"]: a for a in body["agents"]}
    for pid in sorted(NEW_IDS):
        agent = agents[pid]
        assert agent["status"] == "done", pid
        changes = agent["proposal"]["changes"]
        assert changes, f"{pid} 应产出至少一条修改"
        assert any(c.get("reason") for c in changes), pid


def test_persona_signature_effects(client, example_spec):
    """机构签名效果抽查：Shopify 单色柱、eBay accent 蓝、WHO Noto 字族。"""
    r = client.post(
        "/api/advisor/run?wait=true",
        json={"spec": example_spec, "persona_ids": ["shopify", "ebay", "who"]},
    )
    assert r.status_code == 200
    agents = {a["persona_id"]: a for a in r.json()["agents"]}

    def ops_of(pid):
        return [op for c in agents[pid]["proposal"]["changes"] for op in (c.get("ops") or [])]

    shopify_colors = [op.get("color") for op in ops_of("shopify") if op.get("action") == "set_mark_color"]
    assert "#9c6ade" in shopify_colors

    ebay_colors = [op.get("color") for op in ops_of("ebay") if op.get("action") == "set_mark_color"]
    assert "#3665f3" in ebay_colors

    who_fonts = [op for op in ops_of("who") if op.get("action") == "set_font"]
    assert any(op.get("family") == "Noto Sans" for op in who_fonts)
