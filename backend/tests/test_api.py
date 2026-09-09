"""API 契约：health / personas / upload / advisor/run / design/apply / parse。"""
import io
import json


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["llm_mode"] == "mock" and body["personas"] >= 2
    assert body.get("prefer_mode") == "suggest"
    assert body.get("chart_type_prefer_mode") == "suggest"


def test_personas_list(client):
    r = client.get("/api/personas")
    ids = {p["id"] for p in r.json()["personas"]}
    assert {"bbc", "economist"} <= ids
    bbc = next(p for p in r.json()["personas"] if p["id"] == "bbc")
    assert bbc["brand_color"] and bbc["layers"]["l1_rules"] >= 10


def test_upload_spec(client, example_spec):
    buf = io.BytesIO(json.dumps(example_spec).encode("utf-8"))
    r = client.post("/api/upload", files={"file": ("vegalite.json", buf, "application/json")})
    assert r.status_code == 200
    body = r.json()
    assert body["file_id"] and body["facts"]["mark_type"] == "bar"

    bad = io.BytesIO(b"not json")
    r2 = client.post("/api/upload", files={"file": ("bad.json", bad, "application/json")})
    assert r2.status_code == 400 and "error" in r2.json()


def test_advisor_run_and_apply(client, example_spec):
    goal = "I want to visualize this huge gap between reported and solved cases beautifully."
    r = client.post(
        "/api/advisor/run?wait=true",
        json={
            "spec": example_spec,
            "persona_ids": ["bbc", "economist"],
            "context": {"communication_goal": goal},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    execution = body["llm_execution"]
    assert execution["outcome"] == "mock_configured"
    assert execution["configured_mode"] == "mock"
    assert execution["real_llm_succeeded"] is False
    assert execution["api_calls"] == {"total": 0, "successful": 0, "failed": 0}
    agents = {a["persona_id"]: a for a in body["agents"]}
    assert agents["bbc"]["status"] == "done" and agents["bbc"]["proposal"]["changes"]
    assert all(a["proposal"]["facts"]["communication_goal"] == goal for a in agents.values())

    # 轮询接口可查同一 run
    r2 = client.get(f"/api/advisor/run/{body['run_id']}")
    assert r2.status_code == 200 and r2.json()["status"] == "done"

    # 跨机构采纳：BBC 高亮 + Economist 图底 → Composer 确定性重放
    bbc_ch = {c["rule_id"]: c for c in agents["bbc"]["proposal"]["changes"]}
    eco_ch = {c["rule_id"]: c for c in agents["economist"]["proposal"]["changes"]}
    accepted = [bbc_ch["a-color-highlight"], eco_ch["d-canvas-bg"]]
    r3 = client.post(
        "/api/design/apply",
        json={"spec": example_spec, "changes": accepted, "instructions": ""},
    )
    assert r3.status_code == 200
    final = r3.json()["final_spec"]
    assert final["encoding"]["color"]["condition"]["value"] == "#FAAB18"
    assert final["background"] in ("#F5F4EF", "#EFF5F5")
    assert len(r3.json()["applied"]) == 2

    # 未知 persona → 404 稳定错误结构
    r4 = client.post("/api/advisor/run", json={"spec": example_spec, "persona_ids": ["nyt"]})
    assert r4.status_code == 404 and r4.json()["error"]["code"] == 404


def test_parse_custom_persona(client, example_spec):
    md = (
        "Acme Design Standards\n"
        "Clarity above everything.\n"
        "- Primary color #FF5500 must be used for the main series\n"
        "- Never use more than 3 colors\n"
        "- Secondary color #0055FF for comparisons\n"
    )
    r = client.post(
        "/api/personas/parse",
        files={"file": ("acme.md", io.BytesIO(md.encode("utf-8")), "text/markdown")},
        data={"name": "Acme"},
    )
    assert r.status_code == 200
    persona = r.json()["persona"]
    assert persona["kind"] == "custom" and persona["layers"]["l1_rules"] >= 1

    # 落盘主文件对齐 bbc/economist：仅三层正文，无审计大字段
    from pathlib import Path
    import yaml
    from app.config import settings

    path = settings.storage_dir / "personas" / f"{persona['id']}-persona.yaml"
    audit = settings.storage_dir / "personas" / f"{persona['id']}-parser-audit.yaml"
    dumped = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert list(dumped.keys()) == [
        "institution",
        "applicability",
        "L1_signature",
        "L2_adaptations",
        "L3_narrative",
    ]
    assert audit.is_file()
    assert "parser_provenance" in yaml.safe_load(audit.read_text(encoding="utf-8"))

    # 新 persona 立即可参与咨询；显式命名主色直接生成 L1 可执行规则。
    r2 = client.post(
        "/api/advisor/run?wait=true",
        json={"spec": example_spec, "persona_ids": [persona["id"]]},
    )
    agent = r2.json()["agents"][0]
    assert agent["status"] == "done"
    applied = [c for c in agent["proposal"]["changes"] if c["status"] == "applied"]
    assert any(
        op == {"action": "set_mark_color", "color": "#FF5500"}
        for change in applied
        for op in change["ops"]
    )


def test_parse_rejects_non_executable_persona(client):
    md = (
        "Clarity and beauty guide every design decision.\n"
        "Visualizations should help people understand the world."
    )
    r = client.post(
        "/api/personas/parse",
        files={"file": ("inert.md", io.BytesIO(md.encode("utf-8")), "text/markdown")},
        data={"name": "Inert"},
    )

    assert r.status_code == 422
    assert "Persona 质量门未通过" in r.json()["error"]["message"]
    listed_ids = {item["id"] for item in client.get("/api/personas").json()["personas"]}
    assert "inert" not in listed_ids
