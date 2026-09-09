"""POST /api/advisor/discuss 契约与 mock 回复接地测试。"""


def _run_proposals(client, example_spec):
    res = client.post(
        "/api/advisor/run?wait=true",
        json={"spec": example_spec, "persona_ids": ["bbc", "economist"], "context": {}},
    )
    assert res.status_code == 200
    agents = res.json()["agents"]
    return {a["persona_id"]: a["proposal"] for a in agents if a["proposal"]}


def _issue_payload(proposals):
    changes = []
    for prop in proposals.values():
        changes.extend(prop["changes"])
    return {"key": "all", "label": "Institutional norms on this chart", "changes": changes}


def test_discuss_mock_replies_are_grounded(client, example_spec):
    proposals = _run_proposals(client, example_spec)
    assert set(proposals) == {"bbc", "economist"}
    issue = _issue_payload(proposals)

    res = client.post(
        "/api/advisor/discuss",
        json={
            "spec": example_spec,
            "persona_ids": ["bbc", "economist"],
            "issue": issue,
            "question": "Why does this matter for my chart?",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"] == "mock"
    assert body["llm_mode"] == "mock"
    assert {r["persona_id"] for r in body["replies"]} == {"bbc", "economist"}

    # 回复非空；引用必须逐字来自该 persona 的 warrant quote/story
    total_citations = 0
    for reply in body["replies"]:
        assert reply["text"].strip()
        allowed = set()
        for ch in proposals[reply["persona_id"]]["changes"]:
            warrant = ch.get("warrant") or {}
            for key in ("quote", "story"):
                value = " ".join(str(warrant.get(key) or "").split())
                if value:
                    allowed.add(value)
        for cite in reply["citations"]:
            total_citations += 1
            assert any(cite["quote"] in a or a in cite["quote"] for a in allowed)
    assert total_citations >= 1

    # 两机构都有立场 → 主持人 synthesis 存在
    assert body["synthesis"] and body["synthesis"]["text"].strip()


def test_discuss_keep_original_branch(client, example_spec):
    proposals = _run_proposals(client, example_spec)
    issue = _issue_payload(proposals)
    res = client.post(
        "/api/advisor/discuss",
        json={
            "spec": example_spec,
            "persona_ids": ["bbc"],
            "issue": issue,
            "question": "What if I keep the original?",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["replies"]) == 1
    assert "original" in body["replies"][0]["text"].lower()
    # 单机构 → 无主持人合成
    assert body["synthesis"] is None


def test_discuss_validation_errors(client, example_spec):
    res = client.post(
        "/api/advisor/discuss",
        json={"spec": example_spec, "persona_ids": ["bbc"], "issue": {}, "question": "  "},
    )
    assert res.status_code == 400

    res = client.post(
        "/api/advisor/discuss",
        json={"spec": example_spec, "persona_ids": ["nope"], "issue": {}, "question": "Why?"},
    )
    assert res.status_code == 404
    assert "nope" in res.json()["error"]["message"]


def test_discuss_persona_without_changes_gets_neutral_reply(client, example_spec):
    proposals = _run_proposals(client, example_spec)
    # 议题只携带 bbc 的 changes，但同时问 economist → economist 得到中立回复
    issue = {
        "key": "color",
        "label": "Color & emphasis",
        "changes": list(proposals["bbc"]["changes"]),
    }
    res = client.post(
        "/api/advisor/discuss",
        json={
            "spec": example_spec,
            "persona_ids": ["bbc", "economist"],
            "issue": issue,
            "question": "Why does this matter?",
        },
    )
    assert res.status_code == 200
    body = res.json()
    by_id = {r["persona_id"]: r for r in body["replies"]}
    assert by_id["economist"]["citations"] == []
    assert "did not flag" in by_id["economist"]["text"]
    # 只有一家有立场 → 无 synthesis
    assert body["synthesis"] is None
